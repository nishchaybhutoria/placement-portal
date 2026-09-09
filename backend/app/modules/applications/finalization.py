"""Closing a round and living with the consequences (Behavior RND-3).

Finalization is the one operation that reaches out of the pipeline and into a
student's disciplinary record, which is why it is explicit and previewed: an
absent applicant is rejected *and* earns a strike where the cycle says so, and
two strikes become a penalty that blocks them from applying anywhere the policy
is on.  The preview therefore has to say "will earn a strike" per row before
anybody commits it (RND-2).

What happens to each row is M5's ``decide_round_finalization`` and nothing
else; the strike that follows is ``discipline/awards``, shared with the
manual award so the two cannot convert differently (the design review section 4.25).
One transaction, never chunked: half a finalized round is a worse state than a
slow one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    CYCLE_ARCHIVED,
    CYCLE_NOT_FOUND,
    INVALID_TRANSITION,
    JOB_CANCELLED,
    ROUND_ALREADY_FINALIZED,
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
from app.domain.policy import resolve_policy
from app.domain.shared import (
    ApplicationStatus,
    Attendance,
    CycleKind,
    EventType,
    RoundResult,
    StrikeSource,
)
from app.domain.transitions import (
    RoundFinalizationAction,
    RoundFinalizationState,
    decide_round_finalization,
)
from app.modules.applications.rounds import (
    JobRound,
    RoundStateRow,
    job_round,
    round_state_rows,
)
from app.modules.cycles.commands import CycleRow, fetch_cycle
from app.modules.discipline.awards import (
    EnrollmentDiscipline,
    StrikeIntent,
    award_strikes,
    load_discipline,
    lock_enrollments,
    resolve_threshold,
)
from app.modules.jobs.commands import JobRow, fetch_job, job_not_found

_ROUND = """
    SELECT id, ord, name, venue, scheduled_at, finalized_at, finalized_by
    FROM job_rounds WHERE id = :round_id AND job_id = :job_id
"""

_POLICY = """
    SELECT * FROM cycle_policies WHERE cycle_id = :cycle_id
"""


class FinalizeRoundInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    job_id: UUID
    round_id: UUID


class FinalizeRoundSummary(BaseModel):
    job_id: UUID
    round_id: UUID
    round_name: str
    strike_on_absence: bool
    #: Per-row planned effect, identical in preview and execution.
    rows: list[dict[str, object]]
    finalized: int
    strikes: int
    penalties: int


@dataclass(frozen=True, slots=True)
class FinalizationState:
    scope_ids: ScopeIds
    cycle_archived: bool
    now: datetime
    cycle: CycleRow | None
    job: JobRow | None
    round: JobRound | None
    finalized_at: datetime | None
    strike_on_absence: bool
    rows: tuple[RoundStateRow, ...]
    discipline: dict[UUID, EnrollmentDiscipline]
    threshold: int | None


def round_finalization_blocker(
    job_round: JobRound,
    *,
    cycle_archived: bool,
    job_cancelled: bool,
) -> Reason | None:
    """Why this round cannot be finalized, shared by command and board.

    The command's archive rejection is normally raised by ``Authorizer`` before
    its decider runs. The board still needs the same answer in its payload, so
    the predicate includes that scope-level guard rather than teaching the
    client to infer it (the design review section 4.22).
    """
    if cycle_archived:
        return Reason(
            code=CYCLE_ARCHIVED,
            human="The cycle is archived and is now read-only",
            path="cycle_id",
        )
    if job_cancelled:
        return Reason(
            code=JOB_CANCELLED,
            human="The job is cancelled",
            path="job_id",
        )
    if job_round.finalized_at is not None:
        return Reason(
            code=ROUND_ALREADY_FINALIZED,
            human=f"{job_round.name} was finalized already",
            path="round_id",
        )
    return None


async def _load(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> FinalizationState:
    if not isinstance(input_value, FinalizeRoundInput):
        raise TypeError("finalize_round requires FinalizeRoundInput")
    cycle = await fetch_cycle(tx, input_value.cycle_id, lock=lock)
    job = await fetch_job(
        tx, cycle_id=input_value.cycle_id, job_id=input_value.job_id, lock=lock
    )
    if lock:
        # The whole round moves at once, so the whole round is locked -- and
        # the round row itself, because "already finalized" is the guard that
        # stops a second run awarding a second set of strikes.
        await tx.execute(
            sa.text("SELECT 1 FROM job_rounds WHERE id = :round_id FOR UPDATE"),
            {"round_id": input_value.round_id},
        )
        await tx.execute(
            sa.text(
                "SELECT 1 FROM application_round_states s "
                "JOIN applications a ON a.id = s.application_id "
                "WHERE a.job_id = :job_id AND s.round_id = :round_id FOR UPDATE OF s"
            ),
            {"job_id": input_value.job_id, "round_id": input_value.round_id},
        )
    round_row = (
        await tx.execute(
            sa.text(_ROUND),
            {"round_id": input_value.round_id, "job_id": input_value.job_id},
        )
    ).mappings().one_or_none()
    policy_row = (
        await tx.execute(sa.text(_POLICY), {"cycle_id": input_value.cycle_id})
    ).mappings().one_or_none()
    policy = resolve_policy(
        CycleKind(cycle.kind) if cycle is not None else CycleKind.PLACEMENT,
        cycle_policy=dict(policy_row) if policy_row is not None else None,
    )
    rows = await round_state_rows(
        tx, job_id=input_value.job_id, round_id=input_value.round_id
    )
    enrollment_ids = [row.enrollment_id for row in rows]
    if lock:
        await lock_enrollments(tx, enrollment_ids)
    return FinalizationState(
        scope_ids=ScopeIds(cycle_id=input_value.cycle_id, job_id=input_value.job_id),
        cycle_archived=cycle is not None and cycle.archived_at is not None,
        now=cast(datetime, await tx.scalar(sa.select(sa.func.now()))),
        cycle=cycle,
        job=job,
        round=job_round(round_row) if round_row is not None else None,
        finalized_at=round_row["finalized_at"] if round_row is not None else None,
        strike_on_absence=policy.strike_on_absence.value,
        rows=rows,
        discipline=await load_discipline(tx, enrollment_ids),
        threshold=await resolve_threshold(tx),
    )


def _skip_reason(row: RoundStateRow) -> str | None:
    """Why a row in this round is not one finalization touches.

    RND-1's waitlist "resolves only by manual promotion", so a waitlisted row
    survives finalization whatever its attendance says.  Naming it here is the
    point: a coordinator closing a round has to see that the waitlisted
    applicant is still live rather than find out later (the design review 4.25).
    """
    if row.state_id is None:
        return "not_in_round"
    if row.result is RoundResult.WAITLISTED:
        return "waitlisted"
    if row.result is not RoundResult.PENDING:
        return "already_decided"
    if row.status is not ApplicationStatus.IN_PROGRESS:
        return "not_in_progress"
    if row.attendance is Attendance.PRESENT:
        return "present"
    return None


def _decide(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """Close a round: absent and pending are rejected, excused too (RND-3).

    Spec IDs: RND-3, RND-1, DIS.
    """
    if not isinstance(input_value, FinalizeRoundInput) or not isinstance(
        state, FinalizationState
    ):
        raise TypeError("Invalid finalize_round decision input")
    if state.cycle is None:
        return Rejection(
            reasons=[Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")]
        )
    if state.job is None:
        return job_not_found()
    if state.round is None:
        return Rejection(
            reasons=[
                Reason(
                    code=INVALID_TRANSITION,
                    human="The round does not belong to this job",
                    path="round_id",
                )
            ]
        )
    blocked = round_finalization_blocker(
        state.round,
        cycle_archived=state.cycle_archived,
        job_cancelled=state.job.cancelled_at is not None,
    )
    if blocked is not None:
        # Recorded rather than derived, so a second run is refused instead of
        # silently awarding a second round of strikes (the design review 4.25).
        return Rejection(reasons=[blocked])

    by_application = {row.application_id: row for row in state.rows}
    actions = decide_round_finalization(
        tuple(
            RoundFinalizationState(
                application_id=row.application_id,
                status=row.status,
                round_result=row.result or RoundResult.PENDING,
                attendance=row.attendance or Attendance.PENDING,
            )
            for row in state.rows
            if row.state_id is not None
        ),
        strike_on_absence=state.strike_on_absence,
    )
    acted_on = {action.application_id for action in actions}

    operations: list[StateOp] = []
    events: list[Event] = []
    deferred: list[Deferred] = []
    reported: list[dict[str, object]] = []
    intents: list[StrikeIntent] = []

    for action in actions:
        row = by_application[action.application_id]
        operations.append(
            StateOp(
                op="update",
                model="application_round_states",
                values={
                    "attendance": action.attendance_after.value,
                    "result": action.result_after.value,
                },
                where={"id": row.state_id},
            )
        )
        operations.append(
            StateOp(
                op="update",
                model="applications",
                values={"status": action.status_after.value},
                where={"id": action.application_id},
            )
        )
        events.append(
            Event(
                application_id=action.application_id,
                event_type=EventType.ROUND_FINALIZED,
                from_status=row.status.value,
                to_status=action.status_after.value,
                from_round=input_value.round_id,
                to_round=input_value.round_id,
                reason=action.reason,
                payload={
                    "round": state.round.name,
                    "attendance": action.attendance_after.value,
                    "strike_awarded": action.award_strike,
                    "job_id": str(input_value.job_id),
                },
            )
        )
        if action.award_strike:
            intents.append(
                StrikeIntent(
                    enrollment_id=row.enrollment_id,
                    reason=f"Absent from {state.round.name} ({state.job.title})",
                    source=StrikeSource.AUTO_ABSENCE,
                )
            )
        reported.append(_planned(row, action))

    # Strikes are awarded together so one enrollment absent from two rounds of
    # the same finalization converts once, on the pair, rather than twice.
    outcome = award_strikes(
        intents,
        state.discipline,
        threshold=state.threshold,
        now=state.now,
        actor_user_id=actor.user_id,
    )
    operations.extend(outcome.state_ops)
    totals = {
        str(entry["enrollment_id"]): entry["strike_total"] for entry in outcome.rows
    }

    for action in actions:
        row = by_application[action.application_id]
        if action.reason == "absence":
            deferred.append(
                Deferred(
                    task="deliver_notification",
                    args={
                        "event_key": "absent_marked",
                        "recipient": row.email,
                        "context": {
                            "student": row.full_name,
                            "round": state.round.name,
                            "job": state.job.title,
                            # Absent when the cycle's strike_on_absence is off:
                            # the student is told they were marked absent, and
                            # nothing about a strike they did not earn.
                            "strike_total": totals.get(str(row.enrollment_id)),
                            "cycle_id": str(input_value.cycle_id),
                        },
                    },
                )
            )
        else:
            deferred.append(
                Deferred(
                    task="deliver_notification",
                    args={
                        "event_key": "rejected",
                        "recipient": row.email,
                        "context": {
                            "student": row.full_name,
                            "job": state.job.title,
                            "round": state.round.name,
                            "reason": "Excused from this round",
                            "cycle_id": str(input_value.cycle_id),
                        },
                    },
                )
            )
    deferred.extend(outcome.deferred)

    for row in state.rows:
        if row.application_id in acted_on:
            continue
        skipped = _skip_reason(row)
        if skipped is None or skipped == "not_in_round":
            continue
        reported.append(_untouched(row, skipped))

    operations.append(
        StateOp(
            op="update",
            model="job_rounds",
            values={"finalized_at": state.now, "finalized_by": actor.user_id},
            where={"id": input_value.round_id},
        )
    )

    return Plan(
        state_ops=operations,
        events=events,
        deferred=deferred,
        audit={
            "subject_type": "job_round",
            "subject_id": input_value.round_id,
            "details": {
                "action": "finalize_round",
                "job_id": str(input_value.job_id),
                "strike_on_absence": state.strike_on_absence,
                "finalized": len(actions),
                "strikes": len(intents),
                "penalties": sum(
                    int(cast(int, entry["penalties_created"])) for entry in outcome.rows
                ),
                "actor_user_id": str(actor.user_id) if actor.user_id else None,
            },
        },
        summary={
            "job_id": str(input_value.job_id),
            "round_id": str(input_value.round_id),
            "round_name": state.round.name,
            "strike_on_absence": state.strike_on_absence,
            "rows": reported,
            "finalized": len(actions),
            "strikes": len(intents),
            "penalties": sum(
                int(cast(int, entry["penalties_created"])) for entry in outcome.rows
            ),
        },
    )


def _planned(row: RoundStateRow, action: RoundFinalizationAction) -> dict[str, object]:
    return {
        "application_id": str(row.application_id),
        "full_name": row.full_name,
        "roll_number": row.roll_number,
        "attendance_before": row.attendance.value if row.attendance else None,
        "attendance_after": action.attendance_after.value,
        "to_status": action.status_after.value,
        "reason": action.reason,
        # RND-2 names this one specifically: staff see "will earn a strike"
        # before they commit, not after.
        "earns_strike": action.award_strike,
        "outcome": "finalized",
    }


def _untouched(row: RoundStateRow, skipped: str) -> dict[str, object]:
    return {
        "application_id": str(row.application_id),
        "full_name": row.full_name,
        "roll_number": row.roll_number,
        "attendance_before": row.attendance.value if row.attendance else None,
        "attendance_after": row.attendance.value if row.attendance else None,
        "to_status": row.status.value,
        "reason": skipped,
        "earns_strike": False,
        "outcome": "untouched",
    }


def register_finalization_commands(registry: Registry) -> None:
    registry.command(
        name="finalize_round",
        input_model=FinalizeRoundInput,
        output_model=FinalizeRoundSummary,
        actor="staff",
        scope="cycle",
        loader=_load,
        rule_domains=(),
        spec_ids=("RND-3", "RND-1", "DIS"),
        rate_limit="10/min",
    )(_decide)
