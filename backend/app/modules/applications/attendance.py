"""Marking who turned up (Behavior RND-3, RND-2).

Two commands over one pure decision.  ``mark_attendance`` sets one row to a
named value; ``bulk_mark_present`` flips a pasted list from ``pending`` to
``present``, which is the sheet a coordinator carries out of an interview room.

Both are addressed **by round**, not by wherever the application sits now: an
attendance mark is a fact about a round that happened, and the design review section
4.23 requires ``round_id`` on the wire so attendance can never land on a round
the coordinator was not looking at.  Neither command moves a status or a
result; ``finalize_round`` (M11) is what turns absence into a consequence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    APPLICATION_NOT_FOUND,
    CYCLE_ARCHIVED,
    CYCLE_NOT_FOUND,
    DUPLICATE_ROW,
    INVALID_TRANSITION,
    STALE_VIEW,
    UNMATCHED_IDENTIFIER,
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
from app.domain.shared import Attendance, EventType
from app.modules.applications.rounds import (
    RoundStateRow,
    resolve_row,
    round_state_rows,
)
from app.modules.cycles.commands import CycleRow, fetch_cycle
from app.modules.jobs.commands import JobRow, fetch_job, job_not_found

#: The order the board's chip walks, published so the two ends cannot disagree
#: about what "the next state" means even though the chip is what advances it.
ATTENDANCE_CYCLE: tuple[Attendance, ...] = (
    Attendance.PENDING,
    Attendance.PRESENT,
    Attendance.ABSENT,
    Attendance.EXCUSED,
)


def next_attendance(current: Attendance) -> Attendance:
    return ATTENDANCE_CYCLE[(ATTENDANCE_CYCLE.index(current) + 1) % len(ATTENDANCE_CYCLE)]


class MarkAttendanceInput(BaseModel):
    """One row, one named value, and the value the board was displaying."""

    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    job_id: UUID
    #: Required even though it could be defaulted from the application's
    #: current round -- see the design review section 4.23.
    round_id: UUID
    application_id: UUID
    attendance: Attendance
    expected_attendance: Attendance
    reason: str | None = None


class MarkAttendanceSummary(BaseModel):
    application_id: UUID
    round_id: UUID
    attendance: Attendance
    previous: Attendance
    full_name: str


class BulkPresentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    job_id: UUID
    round_id: UUID
    rows: list[dict[str, str]]
    batch_key: str

    @field_validator("rows")
    @classmethod
    def validate_rows(cls, value: list[dict[str, str]]) -> list[dict[str, str]]:
        for row in value:
            keys = set(row)
            if not keys or not keys <= {"application_id", "identifier"}:
                raise ValueError("each row names an application_id or an identifier")
        return value


class BulkPresentSummary(BaseModel):
    #: Only ``rows`` survives ``run_bulk``'s chunk aggregation, so only ``rows``
    #: is promised here: an output model that names a field the response cannot
    #: carry fails response validation and turns a working command into a 500.
    rows: list[dict[str, object]]


@dataclass(frozen=True, slots=True)
class AttendanceState:
    scope_ids: ScopeIds
    cycle_archived: bool
    now: datetime
    cycle: CycleRow | None
    job: JobRow | None
    rows: tuple[RoundStateRow, ...]


@dataclass(frozen=True, slots=True)
class PlannedAttendance:
    """What marking one row would do, before it is done."""

    row: RoundStateRow
    state_id: UUID
    from_attendance: Attendance
    to_attendance: Attendance


def plan_attendance(
    row: RoundStateRow,
    target: Attendance | None,
    *,
    frozen: bool,
    only_from: frozenset[Attendance] | None = None,
) -> PlannedAttendance | Reason:
    """The pure decision for one row: mark it, or why it cannot be marked.

    ``target`` may be ``None``, which asks the target-independent question the
    board needs -- *can this row be marked at all* -- without the screen having
    to know which value the chip will send next.  Everything that can refuse a
    mark other than "it already says that" is independent of the target, which
    is what lets one function answer both (the design review section 4.22).
    """
    if frozen:
        return Reason(code=CYCLE_ARCHIVED, human="This board is read-only")
    if row.state_id is None or row.attendance is None:
        return Reason(code=INVALID_TRANSITION, human="Not sitting in this round")
    if row.status.value in {"withdrawn", "auto_withdrawn"}:
        # Nobody attends a round they withdrew from.  Every other status stays
        # markable, including rejected: RND-3's post-finalize remedy is to fix
        # the attendance sheet and then reinstate.
        return Reason(code=INVALID_TRANSITION, human="Withdrawn from this job")
    if only_from is not None and row.attendance not in only_from:
        return Reason(
            code=INVALID_TRANSITION,
            human=f"Already marked {row.attendance.value}",
        )
    if target is not None and target is row.attendance:
        return Reason(
            code=DUPLICATE_ROW, human=f"Already marked {row.attendance.value}"
        )
    return PlannedAttendance(
        row=row,
        state_id=row.state_id,
        from_attendance=row.attendance,
        to_attendance=target if target is not None else next_attendance(row.attendance),
    )


def attendance_state_op(planned: PlannedAttendance) -> StateOp:
    return StateOp(
        op="update",
        model="application_round_states",
        values={"attendance": planned.to_attendance.value},
        where={"id": planned.state_id},
    )


def attendance_event(
    planned: PlannedAttendance, *, round_id: UUID, job_id: UUID, reason: str | None
) -> Event:
    """No status moves, so the timeline records the fact rather than a change."""
    return Event(
        application_id=planned.row.application_id,
        event_type=EventType.ATTENDANCE_MARKED,
        from_status=planned.row.status.value,
        to_status=planned.row.status.value,
        from_round=round_id,
        to_round=round_id,
        reason=reason,
        payload={
            "attendance": planned.to_attendance.value,
            "previous": planned.from_attendance.value,
            "job_id": str(job_id),
        },
    )


async def _load_state(
    tx: AsyncSession,
    *,
    cycle_id: UUID,
    job_id: UUID,
    round_id: UUID,
    application_id: UUID | None,
    lock: bool,
) -> AttendanceState:
    cycle = await fetch_cycle(tx, cycle_id, lock=lock)
    job = await fetch_job(tx, cycle_id=cycle_id, job_id=job_id, lock=lock)
    if lock:
        # Compare-and-set on `attendance` is only atomic if the row it compares
        # is the row it writes: two coordinators marking the same sheet would
        # otherwise both read `pending` and the second would overwrite the first
        # while its expected_attendance still looked satisfied.
        await tx.execute(
            sa.text(
                "SELECT 1 FROM application_round_states s "
                "JOIN applications a ON a.id = s.application_id "
                "WHERE a.job_id = :job_id AND s.round_id = :round_id"
                + (" AND a.id = :application_id" if application_id else "")
                + " FOR UPDATE OF s"
            ),
            {
                "job_id": job_id,
                "round_id": round_id,
                **({"application_id": application_id} if application_id else {}),
            },
        )
    return AttendanceState(
        scope_ids=ScopeIds(cycle_id=cycle_id, job_id=job_id),
        cycle_archived=cycle is not None and cycle.archived_at is not None,
        now=cast(datetime, await tx.scalar(sa.select(sa.func.now()))),
        cycle=cycle,
        job=job,
        rows=await round_state_rows(
            tx, job_id=job_id, round_id=round_id, application_id=application_id
        ),
    )


async def _load_mark(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> AttendanceState:
    if not isinstance(input_value, MarkAttendanceInput):
        raise TypeError("mark_attendance requires MarkAttendanceInput")
    return await _load_state(
        tx,
        cycle_id=input_value.cycle_id,
        job_id=input_value.job_id,
        round_id=input_value.round_id,
        application_id=input_value.application_id,
        lock=lock,
    )


async def _load_bulk_attendance(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> AttendanceState:
    if not isinstance(input_value, BulkPresentInput):
        raise TypeError("bulk attendance requires BulkPresentInput")
    return await _load_state(
        tx,
        cycle_id=input_value.cycle_id,
        job_id=input_value.job_id,
        round_id=input_value.round_id,
        application_id=None,
        lock=lock,
    )


def _frozen(state: AttendanceState) -> bool:
    return state.job is not None and state.job.cancelled_at is not None


def _decide_mark_attendance(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Set one row's attendance (RND-3).

    Spec IDs: RND-3, RND-1.
    """
    if not isinstance(input_value, MarkAttendanceInput) or not isinstance(
        state, AttendanceState
    ):
        raise TypeError("Invalid mark_attendance decision input")
    if state.cycle is None:
        return Rejection(
            reasons=[Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")]
        )
    if state.job is None:
        return job_not_found()
    row = next(
        (
            item
            for item in state.rows
            if item.application_id == input_value.application_id
        ),
        None,
    )
    if row is None:
        return Rejection(
            reasons=[
                Reason(
                    code=APPLICATION_NOT_FOUND,
                    human="No such application on this job",
                    path="application_id",
                )
            ]
        )
    if row.attendance is not None and row.attendance is not input_value.expected_attendance:
        # The chip was showing something else when this was clicked.
        return Rejection(
            reasons=[
                Reason(
                    code=STALE_VIEW,
                    human=(
                        f"{row.full_name} is marked {row.attendance.value}, "
                        f"not {input_value.expected_attendance.value}"
                    ),
                    path="expected_attendance",
                )
            ]
        )
    planned = plan_attendance(row, input_value.attendance, frozen=_frozen(state))
    if isinstance(planned, Reason):
        return Rejection(reasons=[planned])
    return Plan(
        state_ops=[attendance_state_op(planned)],
        events=[
            attendance_event(
                planned,
                round_id=input_value.round_id,
                job_id=input_value.job_id,
                reason=input_value.reason,
            )
        ],
        deferred=[],
        audit={
            "subject_type": "application",
            "subject_id": row.application_id,
            "details": {
                "attendance": planned.to_attendance.value,
                "previous": planned.from_attendance.value,
                "round_id": str(input_value.round_id),
                "reason": input_value.reason,
            },
        },
        summary={
            "application_id": str(row.application_id),
            "round_id": str(input_value.round_id),
            "attendance": planned.to_attendance.value,
            "previous": planned.from_attendance.value,
            "full_name": row.full_name,
        },
    )


def _decide_bulk_attendance(
    input_value: BaseModel,
    state: object,
    actor: ActorContext,
    *,
    target_attendance: Attendance,
) -> Plan | Rejection:
    """Flip selected pending rows to one explicit attendance value (RND-3, RND-2)."""
    if not isinstance(input_value, BulkPresentInput) or not isinstance(
        state, AttendanceState
    ):
        raise TypeError("Invalid bulk attendance decision input")
    if state.cycle is None:
        return Rejection(
            reasons=[Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")]
        )
    if state.job is None:
        return job_not_found()

    frozen = _frozen(state)
    results: list[dict[str, object]] = []
    unmatched: list[str] = []
    operations: list[StateOp] = []
    events: list[Event] = []
    seen: set[UUID] = set()

    for row in input_value.rows:
        label = row.get("identifier") or row.get("application_id", "")
        target = resolve_row(row, state.rows)
        if target is None:
            unmatched.append(label)
            results.append(
                _row_result(
                    label,
                    None,
                    status="error",
                    reason=UNMATCHED_IDENTIFIER,
                    human="No applicant on this job matched this identifier",
                )
            )
            continue
        if target.application_id in seen:
            results.append(
                _row_result(
                    label,
                    target,
                    status="skipped",
                    reason=DUPLICATE_ROW,
                    human="Named more than once in this batch",
                )
            )
            continue
        planned = plan_attendance(
            target,
            target_attendance,
            frozen=frozen,
            # A bulk mark only fills an unmarked sheet. A row already marked
            # present, absent, or excused is a decision somebody made, and a
            # large batch must not quietly overwrite it.
            only_from=frozenset({Attendance.PENDING}),
        )
        if isinstance(planned, Reason):
            results.append(
                _row_result(
                    label,
                    target,
                    status="skipped",
                    reason=planned.code,
                    human=planned.human,
                )
            )
            continue
        seen.add(target.application_id)
        operations.append(attendance_state_op(planned))
        events.append(
            attendance_event(
                planned,
                round_id=input_value.round_id,
                job_id=input_value.job_id,
                reason=None,
            )
        )
        results.append(
            _row_result(
                label,
                target,
                status="ok",
                attendance=planned.to_attendance.value,
                previous=planned.from_attendance.value,
            )
        )

    return Plan(
        state_ops=operations,
        events=events,
        deferred=[],
        audit={
            "subject_type": "job",
            "subject_id": input_value.job_id,
            "details": {
                "operation": f"mark_{target_attendance.value}",
                "round_id": str(input_value.round_id),
                "matched": len(seen),
                "unmatched": unmatched,
                "actor_user_id": str(actor.user_id) if actor.user_id else None,
            },
        },
        summary={
            "job_id": str(input_value.job_id),
            "round_id": str(input_value.round_id),
            "rows": results,
            "matched": len(seen),
            "unmatched": unmatched,
        },
    )


def _decide_bulk_mark_present(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """Mark selected pending rows present (RND-3, RND-2)."""
    return _decide_bulk_attendance(
        input_value, state, actor, target_attendance=Attendance.PRESENT
    )


def _decide_bulk_mark_absent(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """Mark selected pending rows absent (RND-3, RND-2)."""
    return _decide_bulk_attendance(
        input_value, state, actor, target_attendance=Attendance.ABSENT
    )


def _row_result(
    label: str,
    row: RoundStateRow | None,
    *,
    status: str,
    reason: str | None = None,
    human: str | None = None,
    attendance: str | None = None,
    previous: str | None = None,
) -> dict[str, object]:
    """One line of the per-row report; ``human`` is the sentence, not the code.

    The board renders these rows with the same component it renders the four
    pipeline operations with, so the two report a skip the same way.
    """
    return {
        "identifier": label,
        "application_id": str(row.application_id) if row is not None else None,
        "full_name": row.full_name if row is not None else None,
        "roll_number": row.roll_number if row is not None else None,
        "status": status,
        "reason": reason,
        "human": human,
        "attendance": attendance,
        "previous": previous,
    }


def register_attendance_commands(registry: Registry) -> None:
    registry.command(
        name="mark_attendance",
        input_model=MarkAttendanceInput,
        output_model=MarkAttendanceSummary,
        actor="staff",
        scope="cycle",
        loader=_load_mark,
        rule_domains=(),
        spec_ids=("RND-3", "RND-1"),
        rate_limit="10/min",
    )(_decide_mark_attendance)
    registry.command(
        name="bulk_mark_present",
        input_model=BulkPresentInput,
        output_model=BulkPresentSummary,
        actor="staff",
        scope="cycle",
        loader=_load_bulk_attendance,
        rule_domains=(),
        spec_ids=("RND-3", "RND-2"),
        rate_limit="10/min",
        execution_mode="bulk",
    )(_decide_bulk_mark_present)
    registry.command(
        name="bulk_mark_absent",
        input_model=BulkPresentInput,
        output_model=BulkPresentSummary,
        actor="staff",
        scope="cycle",
        loader=_load_bulk_attendance,
        rule_domains=(),
        spec_ids=("RND-3", "RND-2"),
        rate_limit="10/min",
        execution_mode="bulk",
    )(_decide_bulk_mark_absent)
