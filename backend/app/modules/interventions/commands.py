"""Staff interventions on a single application (Behavior INT-1, APP-4.14/17).

Two commands, deliberately unlike each other.

``reinstate_application`` is a *specified* repair: APP-4.14 names its legal
source statuses and CYC-4 promises the position underneath a withdrawal is
preserved precisely so it can be restored.  It therefore has real semantics --
which round the application returns to, and what happens to the round-state
ledger on either side of it -- and it notifies, because a student who was
rejected and is now sitting in round 3 must be told rather than discovering it
by chance.

``force_transition`` is the *unspecified* catch-all: APP-4.17 exists so that a
state nobody anticipated can still be corrected, and by construction there is
nothing it can promise about consequences.  It writes one status and one event
and does nothing else -- no cascade, no offer row, no round state, no email.
Its preview says so in words, naming what a sanctioned command would have done
in its place, because that sentence is the only thing standing between a
coordinator and a half-applied intervention.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    APPLICATION_NOT_FOUND,
    CYCLE_NOT_FOUND,
    DUPLICATE_APPLICATION,
    INVALID_TRANSITION,
    JOB_CANCELLED,
    MEMBERSHIP_NOT_ACTIVE,
    ROUND_NOT_FOUND,
    STALE_VIEW,
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
from app.domain.shared import (
    ApplicationStatus,
    Attendance,
    CycleKind,
    EventType,
    MembershipStatus,
    RoundResult,
)
from app.domain.transitions import (
    TransitionActor,
    TransitionContext,
    decide_transition,
)
from app.modules.notifications.wording import NOT_APPLICABLE

REINSTATABLE: frozenset[ApplicationStatus] = frozenset(
    {
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
        ApplicationStatus.AUTO_WITHDRAWN,
    }
)

#: What each destination status would have carried if it had been reached the
#: sanctioned way.  ``force_transition`` performs none of it, and the preview
#: prints the matching line so staff know which compensating command to run
#: themselves (Behavior section 16, rule 3).
UNPERFORMED_CONSEQUENCES: dict[ApplicationStatus, str] = {
    ApplicationStatus.IN_PROGRESS: (
        "No round state is created or cleared. Use reinstate_application to "
        "return an application to a chosen round with its ledger repaired."
    ),
    ApplicationStatus.PENDING_OFFER: (
        "No round is advanced or closed. Use the round operations on the board "
        "to move an application through its pipeline."
    ),
    ApplicationStatus.OFFERED: (
        "No offer row is created, no response deadline is set and no expiry is "
        "scheduled, so nothing can be accepted or declined. Use extend_offers "
        "or re_extend_offer to make a real offer."
    ),
    ApplicationStatus.ACCEPTED: (
        "The OFR-3 acceptance cascade does not run: no other application is "
        "auto-withdrawn, no other offer is auto-declined, and no acceptance "
        "email is sent. Use accept_offer or record_open_outcome for a real "
        "acceptance."
    ),
    ApplicationStatus.DECLINED: (
        "No offer response is recorded, so the offer stays open and its expiry "
        "task still fires. Use decline_offer or record_open_outcome instead."
    ),
    ApplicationStatus.REJECTED: (
        "No round result is written, no strike is awarded and no rejection "
        "email is sent. Use eliminate_applications or finalize_round instead."
    ),
    ApplicationStatus.WITHDRAWN: (
        "Nothing is released on the student's behalf and no email is sent; the "
        "student's own withdrawal is withdraw_application."
    ),
    ApplicationStatus.AUTO_WITHDRAWN: (
        "No trigger is recorded, so the timeline will not say what withdrew "
        "this. The system writes this status itself during an acceptance "
        "cascade, a membership exit or an archival."
    ),
    ApplicationStatus.OFFER_TERMINATED: (
        "No offer is terminated, no restoration candidates are offered and no "
        "discipline is chained. Use terminate_offer, which previews all three."
    ),
}

_APPLICATION = """
    SELECT a.id, a.job_id, a.enrollment_id, a.status, a.current_round_id,
           j.cycle_id, j.title, j.cancelled_at, j.company_id,
           co.name AS company_name,
           u.full_name AS student_name, u.email AS student_email,
           m.status AS membership_status,
           c.kind AS cycle_kind, c.archived_at
    FROM applications a
    JOIN jobs j ON j.id = a.job_id
    JOIN companies co ON co.id = j.company_id
    JOIN enrollments e ON e.id = a.enrollment_id
    JOIN users u ON u.id = e.user_id
    JOIN cycles c ON c.id = j.cycle_id
    LEFT JOIN cycle_memberships m
        ON m.cycle_id = j.cycle_id AND m.enrollment_id = a.enrollment_id
    WHERE a.id = :application_id AND j.cycle_id = :cycle_id
"""

_ROUNDS = """
    SELECT id, name, ord FROM job_rounds WHERE job_id = :job_id ORDER BY ord
"""

_ROUND_STATES = """
    SELECT s.id, s.round_id, s.result, s.attendance, r.name, r.ord
    FROM application_round_states s
    JOIN job_rounds r ON r.id = s.round_id
    WHERE s.application_id = :application_id
    ORDER BY r.ord
"""

_ACTIVE_DUPLICATE = """
    SELECT id FROM applications
    WHERE job_id = :job_id AND enrollment_id = :enrollment_id AND id <> :application_id
      AND status NOT IN ('withdrawn', 'auto_withdrawn')
"""


def _required_text(value: str) -> str:
    if not value.strip():
        raise ValueError("a reason is required")
    return value.strip()


class ReinstateApplicationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    application_id: UUID
    #: The round the application returns to.  Null for an open-cycle job, which
    #: has no rounds at all (JOB-6).
    target_round_id: UUID | None = None
    reason: str
    #: The status the screen was showing, per the section 16 stale-view rule for
    #: single-row staff actions.
    expected_status: ApplicationStatus | None = None
    notify: bool = True

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return _required_text(value)


class ForceTransitionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    application_id: UUID
    to_status: ApplicationStatus
    reason: str
    expected_status: ApplicationStatus | None = None

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return _required_text(value)


class ReinstateSummary(BaseModel):
    application_id: UUID
    job_id: UUID
    from_status: ApplicationStatus
    status: ApplicationStatus
    target_round_id: UUID | None
    target_round_name: str | None
    #: Per-row, never counted: a coordinator repairing a pipeline position needs
    #: to see which rounds lose their history and which keep it.
    cleared_round_states: list[dict[str, object]]
    kept_round_states: list[dict[str, object]]
    notify: bool


class ForceTransitionSummary(BaseModel):
    application_id: UUID
    job_id: UUID
    from_status: ApplicationStatus
    to_status: ApplicationStatus
    #: The sentence that makes this command safe to offer at all.
    consequences: str
    unperformed: str


@dataclass(frozen=True, slots=True)
class RoundStateRow:
    id: UUID
    round_id: UUID
    name: str
    ord: int
    result: RoundResult
    attendance: Attendance


@dataclass(frozen=True, slots=True)
class RoundRow:
    id: UUID
    name: str
    ord: int


@dataclass(frozen=True, slots=True)
class InterventionState:
    scope_ids: ScopeIds
    cycle_archived: bool
    cycle_exists: bool
    cycle_kind: CycleKind | None
    application: sa.RowMapping | None
    rounds: tuple[RoundRow, ...]
    round_states: tuple[RoundStateRow, ...]
    duplicate_application_id: UUID | None
    now: datetime


async def _load_intervention(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> InterventionState:
    if not isinstance(
        input_value, (ReinstateApplicationInput, ForceTransitionInput)
    ):
        raise TypeError("An intervention requires a reinstate or force input")

    cycle = (
        await tx.execute(
            sa.text("SELECT id, kind, archived_at FROM cycles WHERE id = :id"),
            {"id": input_value.cycle_id},
        )
    ).mappings().one_or_none()
    application = (
        await tx.execute(
            sa.text(_APPLICATION + (" FOR UPDATE OF a" if lock else "")),
            {
                "application_id": input_value.application_id,
                "cycle_id": input_value.cycle_id,
            },
        )
    ).mappings().one_or_none()

    rounds: tuple[RoundRow, ...] = ()
    states: tuple[RoundStateRow, ...] = ()
    duplicate: UUID | None = None
    if application is not None:
        round_rows = (
            await tx.execute(sa.text(_ROUNDS), {"job_id": application["job_id"]})
        ).mappings().all()
        rounds = tuple(
            RoundRow(
                id=cast(UUID, row["id"]), name=str(row["name"]), ord=int(row["ord"])
            )
            for row in round_rows
        )
        state_rows = (
            await tx.execute(
                sa.text(_ROUND_STATES),
                {"application_id": input_value.application_id},
            )
        ).mappings().all()
        states = tuple(
            RoundStateRow(
                id=cast(UUID, row["id"]),
                round_id=cast(UUID, row["round_id"]),
                name=str(row["name"]),
                ord=int(row["ord"]),
                result=RoundResult(row["result"]),
                attendance=Attendance(row["attendance"]),
            )
            for row in state_rows
        )
        # Locked with the application, because "is there another live
        # application for this pair" is an existence invariant the partial-unique
        # index backstops (CONTRIBUTING.md invariant 9).
        duplicate = cast(
            "UUID | None",
            await tx.scalar(
                sa.text(_ACTIVE_DUPLICATE + (" FOR UPDATE" if lock else "")),
                {
                    "job_id": application["job_id"],
                    "enrollment_id": application["enrollment_id"],
                    "application_id": input_value.application_id,
                },
            ),
        )

    return InterventionState(
        scope_ids=ScopeIds(
            cycle_id=input_value.cycle_id,
            job_id=(
                cast(UUID, application["job_id"]) if application is not None else None
            ),
            enrollment_id=(
                cast(UUID, application["enrollment_id"])
                if application is not None
                else None
            ),
            application_id=input_value.application_id,
        ),
        cycle_archived=cycle is not None and cycle["archived_at"] is not None,
        cycle_exists=cycle is not None,
        cycle_kind=CycleKind(cycle["kind"]) if cycle is not None else None,
        application=application,
        rounds=rounds,
        round_states=states,
        duplicate_application_id=duplicate,
        now=cast(datetime, await tx.scalar(sa.select(sa.func.now()))),
    )


def _cycle_missing() -> Rejection:
    return Rejection(
        reasons=[
            Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist", path="cycle_id")
        ]
    )


def _application_missing() -> Rejection:
    return Rejection(
        reasons=[
            Reason(
                code=APPLICATION_NOT_FOUND,
                human="No such application in this cycle",
                path="application_id",
            )
        ]
    )


def _stale(expected: ApplicationStatus, actual: ApplicationStatus) -> Rejection:
    return Rejection(
        reasons=[
            Reason(
                code=STALE_VIEW,
                human=(
                    f"This application is {actual.value.replace('_', ' ')}, not "
                    f"{expected.value.replace('_', ' ')}. Refresh and try again."
                ),
                path="expected_status",
            )
        ]
    )


def _state_row(row: RoundStateRow) -> dict[str, object]:
    return {
        "round_id": str(row.round_id),
        "round_name": row.name,
        "ord": row.ord,
        "result": row.result.value,
        "attendance": row.attendance.value,
    }


def _decide_reinstate(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """Return a closed application to a chosen round (INT-1, APP-4.14)."""
    if not isinstance(input_value, ReinstateApplicationInput) or not isinstance(
        state, InterventionState
    ):
        raise TypeError("Invalid reinstate_application decision input")
    if not state.cycle_exists:
        return _cycle_missing()
    if state.application is None:
        return _application_missing()

    application = state.application
    status = ApplicationStatus(application["status"])
    if (
        input_value.expected_status is not None
        and input_value.expected_status is not status
    ):
        return _stale(input_value.expected_status, status)
    if status not in REINSTATABLE:
        return Rejection(
            reasons=[
                Reason(
                    code=INVALID_TRANSITION,
                    human=(
                        f"An application that is {status.value.replace('_', ' ')} "
                        "cannot be reinstated"
                    ),
                    path="application_id",
                )
            ]
        )

    reasons: list[Reason] = []
    if state.duplicate_application_id is not None:
        # The student withdrew and applied again.  Reinstating would put two
        # live applications on one (enrollment, job) pair, which the partial
        # unique index refuses -- so this is a reasoned rejection rather than a
        # constraint violation surfacing as a 500 (the design review section 4.21).
        reasons.append(
            Reason(
                code=DUPLICATE_APPLICATION,
                human=(
                    "This student already has another active application to this "
                    "job. Resolve that one first."
                ),
                path="application_id",
            )
        )
    membership = application["membership_status"]
    if membership is None or MembershipStatus(membership) is not MembershipStatus.ACTIVE:
        # Reinstating here would manufacture exactly the state the consistency
        # checker reports as corruption: an in_progress application on a
        # non-active membership.  Restore the membership first.
        reasons.append(
            Reason(
                code=MEMBERSHIP_NOT_ACTIVE,
                human=(
                    "This student's membership in the cycle is not active, so "
                    "the application cannot be live. Restore the membership first."
                ),
                path="membership_status",
            )
        )
    if application["cancelled_at"] is not None:
        reasons.append(
            Reason(
                code=JOB_CANCELLED,
                human="This job has been cancelled, so nothing can return to its pipeline",
                path="job_id",
            )
        )

    target: RoundRow | None = None
    if state.rounds:
        if input_value.target_round_id is None:
            reasons.append(
                Reason(
                    code=ROUND_NOT_FOUND,
                    human="Choose the round this application returns to",
                    path="target_round_id",
                )
            )
        else:
            target = next(
                (item for item in state.rounds if item.id == input_value.target_round_id),
                None,
            )
            if target is None:
                reasons.append(
                    Reason(
                        code=ROUND_NOT_FOUND,
                        human="That round does not belong to this job",
                        path="target_round_id",
                    )
                )
    elif input_value.target_round_id is not None:
        reasons.append(
            Reason(
                code=ROUND_NOT_FOUND,
                human="This job has no rounds, so there is no round to return to",
                path="target_round_id",
            )
        )
    if reasons:
        return Rejection(reasons=reasons)

    transition = decide_transition(
        "reinstate",
        from_status=status,
        to_status=ApplicationStatus.IN_PROGRESS,
        actor=TransitionActor.STAFF,
        context=TransitionContext(cycle_kind=cast(CycleKind, state.cycle_kind)),
        reason=input_value.reason,
    )
    if isinstance(transition, Rejection):
        return transition

    target_ord = target.ord if target is not None else None
    cleared = [row for row in state.round_states if target_ord is not None and row.ord > target_ord]
    kept = [row for row in state.round_states if target_ord is None or row.ord < target_ord]
    at_target = next(
        (row for row in state.round_states if target is not None and row.ord == target_ord),
        None,
    )

    operations: list[StateOp] = [
        StateOp(
            op="update",
            model="applications",
            values={
                "status": ApplicationStatus.IN_PROGRESS.value,
                "current_round_id": target.id if target is not None else None,
            },
            where={"id": input_value.application_id},
        )
    ]
    operations.extend(
        StateOp(
            op="delete",
            model="application_round_states",
            values={},
            where={"id": row.id},
        )
        for row in cleared
    )
    if target is not None:
        if at_target is None:
            operations.append(
                StateOp(
                    op="insert",
                    model="application_round_states",
                    values={
                        "id": uuid4(),
                        "application_id": input_value.application_id,
                        "round_id": target.id,
                        "result": RoundResult.PENDING.value,
                        "attendance": Attendance.PENDING.value,
                    },
                )
            )
        elif at_target.result is not RoundResult.PENDING:
            # The result reopens; the attendance mark does not.  RND-3's own
            # remedy is "edit the attendance sheet *then* reinstate", so wiping
            # what the sheet recorded would undo the correction staff just made.
            operations.append(
                StateOp(
                    op="update",
                    model="application_round_states",
                    values={"result": RoundResult.PENDING.value},
                    where={"id": at_target.id},
                )
            )

    deferred: list[Deferred] = []
    if input_value.notify:
        deferred.append(
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": "reinstated",
                    "recipient": str(application["student_email"]),
                    "context": {
                        "student": str(application["student_name"]),
                        "job": str(application["title"]),
                        "company": str(application["company_name"]),
                        "round": target.name if target is not None else NOT_APPLICABLE,
                        "reason": input_value.reason,
                    },
                },
            )
        )

    return Plan(
        state_ops=operations,
        events=[
            Event(
                application_id=input_value.application_id,
                event_type=EventType.REINSTATED,
                from_status=status.value,
                to_status=ApplicationStatus.IN_PROGRESS.value,
                from_round=cast("UUID | None", application["current_round_id"]),
                to_round=target.id if target is not None else None,
                reason=input_value.reason,
                payload={
                    "cleared_round_states": [_state_row(row) for row in cleared],
                    "kept_round_states": [_state_row(row) for row in kept],
                    "notified": input_value.notify,
                },
            )
        ],
        deferred=deferred,
        audit={
            "subject_type": "application",
            "subject_id": input_value.application_id,
            "details": {
                "action": "reinstate_application",
                "from_status": status.value,
                "target_round_id": str(target.id) if target is not None else None,
                "cleared_round_states": len(cleared),
                "reason": input_value.reason,
            },
        },
        summary={
            "application_id": str(input_value.application_id),
            "job_id": str(application["job_id"]),
            "from_status": status.value,
            "status": ApplicationStatus.IN_PROGRESS.value,
            "target_round_id": str(target.id) if target is not None else None,
            "target_round_name": target.name if target is not None else None,
            "cleared_round_states": [_state_row(row) for row in cleared],
            "kept_round_states": [_state_row(row) for row in kept],
            "notify": input_value.notify,
        },
    )


def _decide_force_transition(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Move one status with no implicit consequences at all (INT-1, APP-4.17)."""
    if not isinstance(input_value, ForceTransitionInput) or not isinstance(
        state, InterventionState
    ):
        raise TypeError("Invalid force_transition decision input")
    if not state.cycle_exists:
        return _cycle_missing()
    if state.application is None:
        return _application_missing()

    status = ApplicationStatus(state.application["status"])
    if (
        input_value.expected_status is not None
        and input_value.expected_status is not status
    ):
        return _stale(input_value.expected_status, status)
    if input_value.to_status is status:
        # APP-4.17 is "anything *else*": a self-transition writes nothing and
        # would leave a forced_transition event claiming a move that never
        # happened.
        return Rejection(
            reasons=[
                Reason(
                    code=INVALID_TRANSITION,
                    human=(
                        "This application is already "
                        f"{status.value.replace('_', ' ')}"
                    ),
                    path="to_status",
                )
            ]
        )

    transition = decide_transition(
        "force",
        from_status=status,
        to_status=input_value.to_status,
        actor=TransitionActor.STAFF,
        context=TransitionContext(cycle_kind=cast(CycleKind, state.cycle_kind)),
        reason=input_value.reason,
    )
    if isinstance(transition, Rejection):
        return transition

    consequences = (
        "This writes the status and its event, and nothing else. No cascade, "
        "no offer row, no round state, no notification. Anything the ordinary "
        "path would have done must be run yourself as a separate command."
    )
    unperformed = UNPERFORMED_CONSEQUENCES[input_value.to_status]
    return Plan(
        state_ops=[
            StateOp(
                op="update",
                model="applications",
                # current_round_id is left exactly where it is: moving it would
                # be an implicit consequence, and this command has none.
                values={"status": input_value.to_status.value},
                where={"id": input_value.application_id},
            )
        ],
        events=[
            Event(
                application_id=input_value.application_id,
                event_type=EventType.FORCED_TRANSITION,
                from_status=status.value,
                to_status=input_value.to_status.value,
                from_round=cast("UUID | None", state.application["current_round_id"]),
                to_round=cast("UUID | None", state.application["current_round_id"]),
                reason=input_value.reason,
                payload={"implicit_consequences": "none", "unperformed": unperformed},
            )
        ],
        deferred=[],
        audit={
            "subject_type": "application",
            "subject_id": input_value.application_id,
            "details": {
                "action": "force_transition",
                "from_status": status.value,
                "to_status": input_value.to_status.value,
                "reason": input_value.reason,
            },
        },
        summary={
            "application_id": str(input_value.application_id),
            "job_id": str(state.application["job_id"]),
            "from_status": status.value,
            "to_status": input_value.to_status.value,
            "consequences": consequences,
            "unperformed": unperformed,
        },
    )


def register_intervention_commands(registry: Registry) -> None:
    registry.command(
        name="reinstate_application",
        input_model=ReinstateApplicationInput,
        output_model=ReinstateSummary,
        actor="staff",
        scope="cycle",
        loader=_load_intervention,
        rule_domains=(),
        spec_ids=("INT-1", "APP-4"),
        rate_limit="10/min",
    )(_decide_reinstate)
    registry.command(
        name="force_transition",
        input_model=ForceTransitionInput,
        output_model=ForceTransitionSummary,
        actor="staff",
        scope="cycle",
        loader=_load_intervention,
        rule_domains=(),
        spec_ids=("INT-1", "APP-4"),
        rate_limit="10/min",
    )(_decide_force_transition)
