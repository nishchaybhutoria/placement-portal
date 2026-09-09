"""Editing and withdrawing one's own application (Behavior APP-3).

Both are the student's own writes on a live application and both use the same
closed-boundary calculation, but their policy flags and override domains are
separate.  Reopening an answer edit does not also authorize a late exit from the
pipeline (the design review section 4.53).

Neither notifies: APP-3 says an edit is silent, and a self-withdrawal tells the
student nothing they do not already know.  Neither touches ``current_round_id``
either -- a withdrawn application keeps the position it held, so a later
reinstatement (INT-1) has something to restore to.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    APPLICATION_NOT_EDITABLE,
    APPLICATION_NOT_FOUND,
    CYCLE_NOT_FOUND,
    RESUME_NOT_FOUND,
    RESUME_REQUIRED,
)
from app.core.plan import (
    ActorContext,
    Event,
    Plan,
    Reason,
    Rejection,
    ScopeIds,
    StateOp,
)
from app.core.registry import Registry
from app.domain.gates import evaluate_edit_window, evaluate_withdraw_window
from app.domain.policy import resolve_policy
from app.domain.shared import ApplicationStatus, CycleKind, EventType, QuestionType, RuleDomain
from app.domain.transitions import TransitionActor, TransitionContext, decide_transition
from app.modules.applications.answers import QuestionSpec, validate_answers
from app.modules.applications.commands import AnswerInput, resolve_resume
from app.modules.applications.verdict import gate_overrides, load_cycle_header
from app.modules.cycles.commands import POLICY_COLUMNS
from app.modules.overrides.service import ApplicableOverride

EDIT_RULE_DOMAINS: tuple[RuleDomain, ...] = (RuleDomain.EDIT_WINDOW,)
WITHDRAW_RULE_DOMAINS: tuple[RuleDomain, ...] = (RuleDomain.WITHDRAW_WINDOW,)

_APPLICATION = """
    SELECT a.id, a.job_id, a.enrollment_id, a.status, a.current_round_id,
           a.resume_url, j.cycle_id, j.title, j.application_deadline
    FROM applications a
    JOIN jobs j ON j.id = a.job_id
    WHERE a.id = :application_id AND a.enrollment_id = :enrollment_id
      AND j.cycle_id = :cycle_id
"""

_QUESTIONS = """
    SELECT q.id, q.text, q.qtype, q.required,
           coalesce(
               (SELECT array_agg(o.text ORDER BY o.ord)
                FROM job_question_options o WHERE o.question_id = q.id),
               ARRAY[]::text[]
           ) AS options
    FROM job_questions q
    WHERE q.job_id = :job_id
    ORDER BY q.ord
"""


class EditApplicationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    enrollment_id: UUID
    application_id: UUID
    # APP-3 replaces the answer set wholesale rather than patching it: a form
    # posted with a question omitted means that question is now unanswered, and
    # a partial edit would leave the student unable to clear one.
    answers: list[AnswerInput] = []
    resume_id: UUID | None = None
    resume_url: str | None = None


class WithdrawApplicationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    enrollment_id: UUID
    application_id: UUID


class EditApplicationSummary(BaseModel):
    application_id: UUID
    answer_count: int
    resume_url: str
    resume_changed: bool


class WithdrawApplicationSummary(BaseModel):
    application_id: UUID
    job_id: UUID
    status: ApplicationStatus


@dataclass(frozen=True, slots=True)
class ApplicationLifecycleState:
    scope_ids: ScopeIds
    cycle_archived: bool
    cycle_exists: bool
    cycle_kind: CycleKind | None
    application: sa.RowMapping | None
    questions: tuple[QuestionSpec, ...]
    allow_edit_after_deadline: bool
    allow_withdrawal_after_deadline: bool
    now: datetime
    resume_url: str | None
    resume_chosen: bool


async def _load_lifecycle(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> ApplicationLifecycleState:
    if not isinstance(input_value, (EditApplicationInput, WithdrawApplicationInput)):
        raise TypeError("Application lifecycle requires an edit or withdraw input")

    cycle = await load_cycle_header(tx, input_value.cycle_id)
    application = (
        await tx.execute(
            sa.text(_APPLICATION + (" FOR UPDATE OF a" if lock else "")),
            {
                "application_id": input_value.application_id,
                "enrollment_id": input_value.enrollment_id,
                "cycle_id": input_value.cycle_id,
            },
        )
    ).mappings().one_or_none()

    questions: tuple[QuestionSpec, ...] = ()
    resume_url: str | None = None
    resume_chosen = False
    if application is not None and isinstance(input_value, EditApplicationInput):
        rows = (
            await tx.execute(
                sa.text(_QUESTIONS), {"job_id": application["job_id"]}
            )
        ).mappings().all()
        questions = tuple(
            QuestionSpec(
                id=cast(UUID, row["id"]),
                text=str(row["text"]),
                qtype=QuestionType(row["qtype"]),
                required=bool(row["required"]),
                options=tuple(cast("list[str]", row["options"] or [])),
            )
            for row in rows
        )
        resume_url, resume_chosen = await resolve_resume(
            tx,
            cycle_id=input_value.cycle_id,
            enrollment_id=input_value.enrollment_id,
            resume_id=input_value.resume_id,
            resume_url=input_value.resume_url,
        )
        if not resume_chosen and resume_url is None:
            # An edit that names no resume keeps the one the application was
            # filed with; only apply falls back to the cycle default.
            resume_url = str(application["resume_url"])

    policy = (
        resolve_policy(
            CycleKind(cycle["kind"]),
            cycle_policy={column: cycle[column] for column in POLICY_COLUMNS},
        )
        if cycle is not None
        else None
    )
    return ApplicationLifecycleState(
        scope_ids=ScopeIds(
            cycle_id=input_value.cycle_id,
            enrollment_id=input_value.enrollment_id,
            application_id=input_value.application_id,
            job_id=cast(UUID, application["job_id"]) if application is not None else None,
        ),
        cycle_archived=cycle is not None and cycle["archived_at"] is not None,
        cycle_exists=cycle is not None,
        cycle_kind=CycleKind(cycle["kind"]) if cycle is not None else None,
        application=application,
        questions=questions,
        allow_edit_after_deadline=(
            policy.allow_edit_after_deadline.value if policy is not None else False
        ),
        allow_withdrawal_after_deadline=(
            policy.allow_withdrawal_after_deadline.value if policy is not None else False
        ),
        now=cast(datetime, await tx.scalar(sa.select(sa.func.now()))),
        resume_url=resume_url,
        resume_chosen=resume_chosen,
    )


def _not_found() -> Rejection:
    return Rejection(
        reasons=[
            Reason(
                code=APPLICATION_NOT_FOUND,
                human="You have no application to this job",
                path="application_id",
            )
        ]
    )


def _not_in_progress(status: ApplicationStatus, action: str) -> Rejection:
    return Rejection(
        reasons=[
            Reason(
                code=APPLICATION_NOT_EDITABLE,
                human=(
                    f"This application is {status.value.replace('_', ' ')}, "
                    f"so it can no longer be {action}"
                ),
                path="application_id",
            )
        ]
    )


def _edit_window_reasons(
    state: ApplicationLifecycleState, overrides: object
) -> tuple[list[Reason], list[UUID]]:
    application = cast(sa.RowMapping, state.application)
    window = evaluate_edit_window(
        now=state.now,
        deadline=application["application_deadline"],
        allowed_after_deadline=state.allow_edit_after_deadline,
        overrides=gate_overrides(cast("tuple[ApplicableOverride, ...]", overrides)),
    )
    return list(window.failures), list(window.applied_override_ids)


def _withdraw_window_reasons(
    state: ApplicationLifecycleState, overrides: object
) -> tuple[list[Reason], list[UUID]]:
    application = cast(sa.RowMapping, state.application)
    window = evaluate_withdraw_window(
        now=state.now,
        deadline=application["application_deadline"],
        allowed_after_deadline=state.allow_withdrawal_after_deadline,
        overrides=gate_overrides(cast("tuple[ApplicableOverride, ...]", overrides)),
    )
    return list(window.failures), list(window.applied_override_ids)


def _decide_edit_application(
    input_value: BaseModel,
    state: object,
    _policy: object,
    overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """Replace an application's answers and resume, in window (APP-3)."""
    if not isinstance(input_value, EditApplicationInput) or not isinstance(
        state, ApplicationLifecycleState
    ):
        raise TypeError("Invalid edit_application decision input")
    if not state.cycle_exists:
        return Rejection(
            reasons=[Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")]
        )
    if state.application is None:
        return _not_found()

    status = ApplicationStatus(state.application["status"])
    if status is not ApplicationStatus.IN_PROGRESS:
        return _not_in_progress(status, "edited")

    reasons, applied = _edit_window_reasons(state, overrides)
    if state.resume_url is None:
        reasons.append(
            Reason(
                code=RESUME_NOT_FOUND if state.resume_chosen else RESUME_REQUIRED,
                human="Choose a resume from your own library, or paste a Drive link",
                path="resume_id",
            )
        )
    answers = validate_answers(
        state.questions,
        {answer.question_id: answer.value for answer in input_value.answers},
    )
    reasons.extend(answers.failures)
    if reasons:
        return Rejection(reasons=reasons)

    resume_url = cast(str, state.resume_url)
    previous_resume = str(state.application["resume_url"])
    state_ops: list[StateOp] = [
        StateOp(
            op="delete",
            model="application_answers",
            values={},
            where={"application_id": input_value.application_id},
        )
    ]
    state_ops.extend(
        StateOp(
            op="insert",
            model="application_answers",
            values={
                "id": uuid4(),
                "application_id": input_value.application_id,
                "question_id": question_id,
                "value": value,
            },
        )
        for question_id, value in answers.values.items()
    )
    if resume_url != previous_resume:
        state_ops.append(
            StateOp(
                op="update",
                model="applications",
                values={"resume_url": resume_url},
                where={"id": input_value.application_id},
            )
        )

    return Plan(
        state_ops=state_ops,
        events=[
            Event(
                application_id=input_value.application_id,
                event_type=EventType.EDITED,
                # An edit is not a transition: APP-4 has no row for it and the
                # status does not move, so the event records what changed rather
                # than claiming a status change that did not happen.
                from_status=None,
                to_status=None,
                from_round=None,
                to_round=None,
                reason=None,
                payload={
                    "answer_count": len(answers.values),
                    "resume_changed": resume_url != previous_resume,
                    "applied_override_ids": [str(item) for item in applied],
                },
            )
        ],
        deferred=[],
        audit={
            "subject_type": "application",
            "subject_id": input_value.application_id,
            "details": {
                "job_id": str(state.application["job_id"]),
                "answer_count": len(answers.values),
                "resume_changed": resume_url != previous_resume,
                "actor_user_id": str(actor.user_id) if actor.user_id else None,
            },
        },
        summary={
            "application_id": str(input_value.application_id),
            "answer_count": len(answers.values),
            "resume_url": resume_url,
            "resume_changed": resume_url != previous_resume,
        },
    )


def _decide_withdraw_application(
    input_value: BaseModel,
    state: object,
    _policy: object,
    overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """Withdraw one's own application, freeing the slot (APP-3, APP-4.12)."""
    if not isinstance(input_value, WithdrawApplicationInput) or not isinstance(
        state, ApplicationLifecycleState
    ):
        raise TypeError("Invalid withdraw_application decision input")
    if not state.cycle_exists:
        return Rejection(
            reasons=[Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")]
        )
    if state.application is None:
        return _not_found()

    status = ApplicationStatus(state.application["status"])
    if status is not ApplicationStatus.IN_PROGRESS:
        return _not_in_progress(status, "withdrawn")

    reasons, applied = _withdraw_window_reasons(state, overrides)
    if reasons:
        return Rejection(reasons=reasons)

    transition = decide_transition(
        "withdraw",
        from_status=status,
        to_status=ApplicationStatus.WITHDRAWN,
        actor=TransitionActor.STUDENT,
        context=TransitionContext(cycle_kind=cast(CycleKind, state.cycle_kind)),
    )
    if isinstance(transition, Rejection):
        return transition

    return Plan(
        state_ops=[
            StateOp(
                op="update",
                model="applications",
                # current_round_id is deliberately left where it is: the
                # position is what a reinstatement restores to (INT-1), and
                # APP-4.13 preserves it for the system's own withdrawals too.
                values={"status": ApplicationStatus.WITHDRAWN.value},
                where={"id": input_value.application_id},
            )
        ],
        events=[
            Event(
                application_id=input_value.application_id,
                event_type=EventType.WITHDRAWN,
                from_status=status.value,
                to_status=ApplicationStatus.WITHDRAWN.value,
                from_round=cast("UUID | None", state.application["current_round_id"]),
                to_round=cast("UUID | None", state.application["current_round_id"]),
                reason=None,
                payload={
                    "job_id": str(state.application["job_id"]),
                    "applied_override_ids": [str(item) for item in applied],
                },
            )
        ],
        deferred=[],
        audit={
            "subject_type": "application",
            "subject_id": input_value.application_id,
            "details": {
                "job_id": str(state.application["job_id"]),
                "from_status": status.value,
                "actor_user_id": str(actor.user_id) if actor.user_id else None,
            },
        },
        summary={
            "application_id": str(input_value.application_id),
            "job_id": str(state.application["job_id"]),
            "status": ApplicationStatus.WITHDRAWN.value,
        },
    )


def register_application_lifecycle_commands(registry: Registry) -> None:
    registry.command(
        name="edit_application",
        input_model=EditApplicationInput,
        output_model=EditApplicationSummary,
        actor="student",
        scope="cycle",
        loader=_load_lifecycle,
        rule_domains=EDIT_RULE_DOMAINS,
        spec_ids=("APP-3",),
    )(_decide_edit_application)
    registry.command(
        name="withdraw_application",
        input_model=WithdrawApplicationInput,
        output_model=WithdrawApplicationSummary,
        actor="student",
        scope="cycle",
        loader=_load_lifecycle,
        rule_domains=WITHDRAW_RULE_DOMAINS,
        spec_ids=("APP-3", "APP-4"),
    )(_decide_withdraw_application)
