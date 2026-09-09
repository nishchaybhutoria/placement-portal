"""Applying to a job (Behavior APP-1, APP-2; LLD sections 7 and 10).

The whole of ELG-3 and the job's ELG-2 rule bind here, through the same module
the student's card renders from (``verdict.py``) -- that identity is the point,
and ``tests/applications/test_verdict_equivalence.py`` holds it.

Two races matter and are handled differently.  A duplicate application is
serialised by a transaction-scoped advisory lock on the (job, enrollment) pair,
so ``decide`` judges a state nobody can change under it, with the partial-unique
index as the DB-level backstop that CONTRIBUTING.md invariant 9 requires.  A profile
edited after applying is not a race at all: ELG-4 says the application keeps the
snapshot it was created with, so nothing re-reads it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    CYCLE_NOT_FOUND,
    JOB_NOT_FOUND,
    RESUME_NOT_FOUND,
    RESUME_REQUIRED,
)
from app.core.plan import (
    ActorContext,
    Deferred,
    Event,
    Plan,
    Reason,
    Rejection,
    ScopeIds,
    StateOp,
)
from app.core.registry import Registry
from app.domain.rules import Labels
from app.domain.shared import (
    ApplicationStatus,
    Attendance,
    CycleKind,
    EventType,
    QuestionType,
    RoundResult,
)
from app.domain.transitions import (
    TransitionActor,
    TransitionContext,
    decide_transition,
)
from app.modules.applications.answers import QuestionSpec, validate_answers
from app.modules.applications.verdict import (
    APPLY_RULE_DOMAINS,
    StudentContext,
    compute_verdict,
    gate_overrides,
    load_cycle_header,
    load_rule_labels,
    load_student_context,
    student_job_query,
)
from app.modules.overrides.service import ApplicableOverride
from app.modules.profiles.commands import is_drive_file_url

_APPLY_JOB = student_job_query("j.id = :job_id AND j.cycle_id = :cycle_id", published_only=False)

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

_FIRST_ROUND = """
    SELECT id FROM job_rounds WHERE job_id = :job_id ORDER BY ord LIMIT 1
"""

_PRIOR_APPLICATIONS = """
    SELECT count(*) FROM applications
    WHERE job_id = :job_id AND enrollment_id = :enrollment_id
"""


def application_id_for(*, job_id: UUID, enrollment_id: UUID, prior: int) -> UUID:
    """The id this application will get, known before it is written.

    The preview-parity contract is strict event equality, and an event carries
    the id of the row it describes -- so a ``uuid4`` here would make every
    ``apply`` preview differ from its own execution, which is exactly the class
    of lie the harness exists to catch.  Deriving it from the pair and the
    number of prior attempts keeps the preview honest and, as a bonus, makes a
    replayed submission reproduce the same row rather than a second one.
    """
    return uuid5(NAMESPACE_URL, f"cds:application:{job_id}:{enrollment_id}:{prior}")


class AnswerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: UUID
    value: object = None


class ApplyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    job_id: UUID
    enrollment_id: UUID
    # APP-1: the cycle default is preselected, so omitting both means "the one
    # I already chose for this cycle" rather than an error.
    resume_id: UUID | None = None
    resume_url: str | None = None
    answers: list[AnswerInput] = []


class ApplicationSummary(BaseModel):
    application_id: UUID
    job_id: UUID
    enrollment_id: UUID
    status: ApplicationStatus
    current_round_id: UUID | None
    resume_url: str
    answer_count: int


@dataclass(frozen=True, slots=True)
class ApplyState:
    scope_ids: ScopeIds
    cycle_archived: bool
    cycle_exists: bool
    cycle_kind: CycleKind | None
    job: sa.RowMapping | None
    context: StudentContext | None
    labels: Labels
    questions: tuple[QuestionSpec, ...]
    first_round_id: UUID | None
    application_id: UUID
    resume_url: str | None
    resume_chosen: bool
    email: str | None
    company_name: str | None


async def resolve_resume(
    tx: AsyncSession,
    *,
    cycle_id: UUID,
    enrollment_id: UUID,
    resume_id: UUID | None,
    resume_url: str | None,
) -> tuple[str | None, bool]:
    """The URL an application is filed with (APP-1, APP-3, PRO-3).

    Returns the URL and whether the student named a choice at all, so a decider
    can tell "you picked someone else's resume" -- which is an error worth a
    sentence -- from "you named nothing", where apply falls back to the cycle
    default and an edit keeps what the application already carries.

    One resolution for both commands: a pasted link accepted at apply time and
    refused at edit time would be a rule nobody could state.
    """
    if resume_url is not None:
        url = resume_url.strip()
        return (url if is_drive_file_url(url) else None), True
    if resume_id is not None:
        owned = (
            await tx.execute(
                sa.text(
                    "SELECT drive_url FROM resumes "
                    "WHERE id = :resume_id AND enrollment_id = :enrollment_id"
                ),
                {"resume_id": resume_id, "enrollment_id": enrollment_id},
            )
        ).scalar_one_or_none()
        return (str(owned) if owned is not None else None), True
    default = (
        await tx.execute(
            sa.text(
                "SELECT r.drive_url FROM cycle_memberships m "
                "JOIN resumes r ON r.id = m.default_resume_id "
                "WHERE m.cycle_id = :cycle_id AND m.enrollment_id = :enrollment_id"
            ),
            {"cycle_id": cycle_id, "enrollment_id": enrollment_id},
        )
    ).scalar_one_or_none()
    return (str(default) if default is not None else None), False


async def _load_apply(tx: AsyncSession, input_value: BaseModel, *, lock: bool) -> ApplyState:
    if not isinstance(input_value, ApplyInput):
        raise TypeError("apply requires ApplyInput")

    if lock:
        # Serialise concurrent applies for this exact pair.  Two students, or
        # the same student on two jobs, never contend; the same pair does, and
        # that is the only race the duplicate gate can lose.
        await tx.execute(
            sa.text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended(:key, 0))"
            ),
            {"key": f"apply:{input_value.job_id}:{input_value.enrollment_id}"},
        )

    cycle = await load_cycle_header(tx, input_value.cycle_id)
    job = (
        await tx.execute(
            sa.text(_APPLY_JOB),
            {
                "job_id": input_value.job_id,
                "cycle_id": input_value.cycle_id,
                "enrollment_id": input_value.enrollment_id,
            },
        )
    ).mappings().one_or_none()

    context: StudentContext | None = None
    labels: Labels = {}
    if cycle is not None:
        context = await load_student_context(
            tx, cycle=cycle, enrollment_id=input_value.enrollment_id, lock=lock
        )
        labels = await load_rule_labels(
            tx,
            context,
            [cast("dict[str, object] | None", job["eligibility_rule"])] if job else [],
        )

    question_rows = (
        await tx.execute(sa.text(_QUESTIONS), {"job_id": input_value.job_id})
    ).mappings().all()
    first_round = (
        await tx.execute(sa.text(_FIRST_ROUND), {"job_id": input_value.job_id})
    ).scalar_one_or_none()
    prior_applications = int(
        await tx.scalar(
            sa.text(_PRIOR_APPLICATIONS),
            {
                "job_id": input_value.job_id,
                "enrollment_id": input_value.enrollment_id,
            },
        )
        or 0
    )
    resume_url, resume_chosen = await resolve_resume(
        tx,
        cycle_id=input_value.cycle_id,
        enrollment_id=input_value.enrollment_id,
        resume_id=input_value.resume_id,
        resume_url=input_value.resume_url,
    )
    email = (
        await tx.execute(
            sa.text(
                "SELECT u.email FROM enrollments e JOIN users u ON u.id = e.user_id "
                "WHERE e.id = :enrollment_id"
            ),
            {"enrollment_id": input_value.enrollment_id},
        )
    ).scalar_one_or_none()

    return ApplyState(
        scope_ids=ScopeIds(
            cycle_id=input_value.cycle_id,
            job_id=input_value.job_id,
            enrollment_id=input_value.enrollment_id,
        ),
        cycle_archived=cycle is not None and cycle["archived_at"] is not None,
        cycle_exists=cycle is not None,
        cycle_kind=CycleKind(cycle["kind"]) if cycle is not None else None,
        job=job,
        context=context,
        labels=labels,
        questions=tuple(
            QuestionSpec(
                id=cast(UUID, row["id"]),
                text=str(row["text"]),
                qtype=QuestionType(row["qtype"]),
                required=bool(row["required"]),
                options=tuple(str(option) for option in (row["options"] or ())),
            )
            for row in question_rows
        ),
        first_round_id=cast("UUID | None", first_round),
        application_id=application_id_for(
            job_id=input_value.job_id,
            enrollment_id=input_value.enrollment_id,
            prior=prior_applications,
        ),
        resume_url=resume_url,
        resume_chosen=resume_chosen,
        email=str(email) if email is not None else None,
        company_name=str(job["company_name"]) if job is not None else None,
    )


def _jsonable(value: object) -> object:
    """JSONB-safe rendering that keeps decimals exact."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def snapshot_profile(profile: dict[str, object]) -> dict[str, object]:
    """The profile as it stood when the application was filed (ELG-4).

    A later profile edit must not move an existing application, so what the
    rule saw is stored rather than referenced.
    """
    return {key: _jsonable(value) for key, value in sorted(profile.items())}


def _decide_apply(
    input_value: BaseModel,
    state: object,
    _policy: object,
    overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """Apply to a job, gates and rule bound at this instant (APP-1, ELG-3)."""
    if not isinstance(input_value, ApplyInput) or not isinstance(state, ApplyState):
        raise TypeError("Invalid apply decision input")
    if not state.cycle_exists:
        return Rejection(
            reasons=[Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")]
        )
    if state.job is None or state.context is None:
        return Rejection(
            reasons=[
                Reason(
                    code=JOB_NOT_FOUND,
                    human="The job does not exist in this cycle",
                    path="job_id",
                )
            ]
        )

    resolved = gate_overrides(cast("tuple[ApplicableOverride, ...]", overrides))
    verdict = compute_verdict(
        state.context, state.job, labels=state.labels, overrides=resolved
    )
    # Neither half is re-coded here: the gates carry their own codes and the
    # rule evaluator carries NOT_ELIGIBLE, so the student reads at apply time
    # the same sentences the card showed them.
    reasons = list(verdict.reasons)

    if state.resume_url is None:
        reasons.append(
            Reason(
                code=RESUME_NOT_FOUND if state.resume_chosen else RESUME_REQUIRED,
                human=(
                    "Choose a resume from your own library, or paste a Drive link"
                    if state.resume_chosen
                    else "Choose a resume to apply with"
                ),
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

    transition = decide_transition(
        "apply",
        from_status=None,
        to_status=ApplicationStatus.IN_PROGRESS,
        actor=TransitionActor.STUDENT,
        context=TransitionContext(cycle_kind=state.context.cycle_kind),
    )
    if isinstance(transition, Rejection):
        return transition

    resume_url = state.resume_url
    state_ops: list[StateOp] = [
        StateOp(
            op="insert",
            model="applications",
            values={
                "id": state.application_id,
                "job_id": input_value.job_id,
                "enrollment_id": input_value.enrollment_id,
                "status": ApplicationStatus.IN_PROGRESS.value,
                # JOB-6: an open-cycle job carries no rounds, so an application
                # to one holds no round position at all.
                "current_round_id": state.first_round_id,
                "resume_url": resume_url,
                "profile_snapshot": snapshot_profile(state.context.profile),
                "applied_at": state.context.now,
            },
        )
    ]
    state_ops.extend(
        StateOp(
            op="insert",
            model="application_answers",
            values={
                "id": uuid4(),
                "application_id": state.application_id,
                "question_id": question_id,
                "value": value,
            },
        )
        for question_id, value in answers.values.items()
    )
    if state.first_round_id is not None:
        state_ops.append(
            StateOp(
                op="insert",
                model="application_round_states",
                values={
                    "id": uuid4(),
                    "application_id": state.application_id,
                    "round_id": state.first_round_id,
                    "result": RoundResult.PENDING.value,
                    "attendance": Attendance.PENDING.value,
                },
            )
        )

    deferred: list[Deferred] = []
    if state.email is not None:
        deferred.append(
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": "application_submitted",
                    "recipient": state.email,
                    "context": {
                        "student": state.context.profile.get("full_name"),
                        "job": str(state.job["title"]),
                        "company": state.company_name,
                        "cycle_id": str(input_value.cycle_id),
                    },
                },
            )
        )

    return Plan(
        state_ops=state_ops,
        events=[
            Event(
                application_id=state.application_id,
                event_type=EventType.CREATED,
                from_status=None,
                to_status=ApplicationStatus.IN_PROGRESS.value,
                from_round=None,
                to_round=state.first_round_id,
                reason=None,
                payload={
                    "job_id": str(input_value.job_id),
                    "cycle_id": str(input_value.cycle_id),
                    "resume_url": resume_url,
                    "answer_count": len(answers.values),
                    # INT-2: which overrides let this through, stamped on the
                    # event, so a later reader can see the application was not
                    # ordinary.
                    "applied_override_ids": [
                        str(override_id) for override_id in verdict.applied_override_ids
                    ],
                },
            )
        ],
        deferred=deferred,
        audit={
            "subject_type": "application",
            "subject_id": state.application_id,
            "details": {
                "job_id": str(input_value.job_id),
                "cycle_id": str(input_value.cycle_id),
                "enrollment_id": str(input_value.enrollment_id),
                "actor_user_id": str(actor.user_id) if actor.user_id else None,
            },
        },
        summary={
            "application_id": str(state.application_id),
            "job_id": str(input_value.job_id),
            "enrollment_id": str(input_value.enrollment_id),
            "status": ApplicationStatus.IN_PROGRESS.value,
            "current_round_id": (
                str(state.first_round_id) if state.first_round_id is not None else None
            ),
            "resume_url": resume_url,
            "answer_count": len(answers.values),
        },
    )


def register_application_commands(registry: Registry) -> None:
    registry.command(
        name="apply",
        input_model=ApplyInput,
        output_model=ApplicationSummary,
        actor="student",
        scope="cycle",
        loader=_load_apply,
        rule_domains=APPLY_RULE_DOMAINS,
        spec_ids=("APP-1", "APP-2", "ELG-1", "ELG-3"),
    )(_decide_apply)
