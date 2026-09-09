"""Publishing where and when a round happens (Behavior RND-4, RND-2).

Staff-assigned only: there is no student-facing write path here.  A row sets
the per-student overrides on the round state it names, and publishing is what
fires the venue-timing notification -- flagged as an update when this student
has already been told once, which is the whole content of RND-4's "flagged as
update on repeat".

Rows arrive two ways, from a CSV/XLSX upload and typed on the board, and both
are validated by the same pure ``parse_slot_time`` (the design review section 4.5): a
check that lived only in the upload route is one a typed row walks past.
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
    CYCLE_ARCHIVED,
    CYCLE_NOT_FOUND,
    DUPLICATE_ROW,
    INVALID_FIELD_VALUE,
    INVALID_TRANSITION,
    UNMATCHED_IDENTIFIER,
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
from app.domain.shared import EventType
from app.modules.applications.rounds import (
    JobRound,
    RoundStateRow,
    job_round,
    resolve_row,
    round_state_rows,
)
from app.modules.applications.slots import parse_slot_time
from app.modules.cycles.commands import CycleRow, fetch_cycle
from app.modules.jobs.commands import JobRow, fetch_job, job_not_found
from app.modules.notifications.wording import format_time, or_absent, schedule_note

_ROUND = """
    SELECT id, ord, name, venue, scheduled_at
    FROM job_rounds WHERE id = :round_id AND job_id = :job_id
"""


class AssignVenueTimingInput(BaseModel):
    """A venue, a time, or both, for each named applicant."""

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
            if not keys <= {"application_id", "identifier", "venue", "time"}:
                raise ValueError(
                    "each row names an application_id or an identifier, "
                    "with a venue, a time, or both"
                )
            if not keys & {"application_id", "identifier"}:
                raise ValueError("each row names an application_id or an identifier")
        return value


class AssignVenueTimingSummary(BaseModel):
    #: Only ``rows`` survives ``run_bulk``'s chunk aggregation, so only ``rows``
    #: is promised here: an output model that names a field the response cannot
    #: carry fails response validation and turns a working command into a 500.
    rows: list[dict[str, object]]


@dataclass(frozen=True, slots=True)
class VenueState:
    scope_ids: ScopeIds
    cycle_archived: bool
    now: datetime
    cycle: CycleRow | None
    job: JobRow | None
    round: JobRound | None
    rows: tuple[RoundStateRow, ...]


@dataclass(frozen=True, slots=True)
class PlannedSlot:
    """What one row would publish, before it publishes it."""

    row: RoundStateRow
    state_id: UUID
    venue: str | None
    scheduled_at: datetime | None
    is_update: bool
    #: The venue and time this student will actually see afterwards: the
    #: override where there is one, the round's default otherwise (RND-1).
    #: These are what the notification states and what change is measured
    #: against -- the notification used to read the override alone, so a
    #: time-only row told a student "Venue: to be announced" while the
    #: dashboard, the round reminder and the analytics export all showed the
    #: round's real venue.
    effective_venue: str | None
    effective_scheduled_at: datetime | None
    #: Whether this row moves either effective value. A row that moves neither
    #: publishes nothing and mails nobody (the design review section 4.46): re-uploading
    #: a corrected sheet used to re-mail every unchanged student, each one told
    #: that this "replaces the schedule sent to you earlier".
    changed: bool

    @property
    def should_publish(self) -> bool:
        """A first telling is a publish even when it moves nothing.

        A round carrying its own default venue and time is published by naming
        the same values per student; suppressing that because nothing moved
        would mean nobody was ever told.
        """
        return self.changed or self.row.notified_at is None


def slot_blocker(row: RoundStateRow, *, frozen: bool) -> Reason | None:
    """Why this row can take no slot at all, independent of what the slot says.

    Split out because it is the question the board asks -- *can this row be
    given a venue* -- long before anyone has typed one, and asking it through a
    second copy of these rules is how a board comes to offer a control the
    command refuses (the design review section 4.22).
    """
    if frozen:
        return Reason(code=CYCLE_ARCHIVED, human="This board is read-only")
    if row.state_id is None:
        return Reason(code=INVALID_TRANSITION, human="Not sitting in this round")
    if row.status.value in {"withdrawn", "auto_withdrawn"}:
        return Reason(code=INVALID_TRANSITION, human="Withdrawn from this job")
    return None


def plan_slot(
    row: RoundStateRow,
    *,
    venue: str,
    time_text: str,
    frozen: bool,
    round_venue: str | None = None,
    round_scheduled_at: datetime | None = None,
) -> PlannedSlot | Reason:
    """The pure decision for one row: what it would publish, or why it cannot.

    An empty cell leaves that override alone (the design review section 4.23), so the
    plan carries ``None`` for "unchanged" rather than for "cleared" -- a
    truncated spreadsheet column must not wipe every venue on the board.

    The round's own defaults are arguments because change is measured against
    what the student can actually see, which is the override where there is one
    and the round's default everywhere else (RND-1).
    """
    blocked = slot_blocker(row, frozen=frozen)
    if blocked is not None:
        return blocked
    if row.state_id is None:  # pragma: no cover - narrowed by slot_blocker
        return Reason(code=INVALID_TRANSITION, human="Not sitting in this round")
    if not venue and not time_text:
        return Reason(
            code=INVALID_FIELD_VALUE,
            human="Give a venue, a time, or both",
            path="venue",
        )
    scheduled_at: datetime | None = None
    if time_text:
        parsed = parse_slot_time(time_text)
        if isinstance(parsed, Reason):
            return parsed
        scheduled_at = parsed

    current_venue = row.venue_override if row.venue_override is not None else round_venue
    current_scheduled_at = (
        row.scheduled_at_override
        if row.scheduled_at_override is not None
        else round_scheduled_at
    )
    effective_venue = venue or current_venue
    effective_scheduled_at = (
        scheduled_at if scheduled_at is not None else current_scheduled_at
    )
    return PlannedSlot(
        row=row,
        state_id=row.state_id,
        venue=venue or None,
        scheduled_at=scheduled_at,
        # Told once already: RND-4 wants the second mail to say so, because a
        # student who reads "your interview is at 09:30" twice cannot tell which
        # one is current.
        is_update=row.notified_at is not None,
        effective_venue=effective_venue,
        effective_scheduled_at=effective_scheduled_at,
        changed=(
            effective_venue != current_venue
            or effective_scheduled_at != current_scheduled_at
        ),
    )


async def _load(tx: AsyncSession, input_value: BaseModel, *, lock: bool) -> VenueState:
    if not isinstance(input_value, AssignVenueTimingInput):
        raise TypeError("assign_venue_timing requires AssignVenueTimingInput")
    cycle = await fetch_cycle(tx, input_value.cycle_id, lock=lock)
    job = await fetch_job(
        tx, cycle_id=input_value.cycle_id, job_id=input_value.job_id, lock=lock
    )
    if lock:
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
    return VenueState(
        scope_ids=ScopeIds(cycle_id=input_value.cycle_id, job_id=input_value.job_id),
        cycle_archived=cycle is not None and cycle.archived_at is not None,
        now=cast(datetime, await tx.scalar(sa.select(sa.func.now()))),
        cycle=cycle,
        job=job,
        round=(job_round(round_row) if round_row is not None else None),
        rows=await round_state_rows(
            tx, job_id=input_value.job_id, round_id=input_value.round_id
        ),
    )


def _decide(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """Publish a venue and a time per applicant (RND-4).

    Spec IDs: RND-4, RND-2.
    """
    if not isinstance(input_value, AssignVenueTimingInput) or not isinstance(
        state, VenueState
    ):
        raise TypeError("Invalid assign_venue_timing decision input")
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

    frozen = state.job.cancelled_at is not None
    results: list[dict[str, object]] = []
    unmatched: list[str] = []
    operations: list[StateOp] = []
    events: list[Event] = []
    deferred: list[Deferred] = []
    seen: set[UUID] = set()

    for row in input_value.rows:
        label = row.get("identifier") or row.get("application_id", "")
        target = resolve_row(row, state.rows)
        if target is None:
            unmatched.append(label)
            results.append(
                _result(label, None, status="error", reason=UNMATCHED_IDENTIFIER)
            )
            continue
        if target.application_id in seen:
            results.append(
                _result(label, target, status="skipped", reason=DUPLICATE_ROW)
            )
            continue
        planned = plan_slot(
            target,
            venue=row.get("venue", "").strip(),
            time_text=row.get("time", "").strip(),
            frozen=frozen,
            round_venue=state.round.venue,
            round_scheduled_at=state.round.scheduled_at,
        )
        if isinstance(planned, Reason):
            results.append(
                _result(
                    label,
                    target,
                    status="error" if planned.code == INVALID_FIELD_VALUE else "skipped",
                    reason=planned.code,
                    human=planned.human,
                )
            )
            continue

        seen.add(target.application_id)
        if not planned.should_publish:
            # Nothing about this student's slot moves, and they have already
            # been told what it is. Writing the same values back would stamp a
            # fresh notified_at, append an event recording no change, and mail
            # them that the schedule they already have replaces itself.
            results.append(
                _result(
                    label,
                    target,
                    status="unchanged",
                    venue=planned.effective_venue,
                    scheduled_at=_iso(planned.effective_scheduled_at),
                    is_update=planned.is_update,
                )
            )
            continue
        values: dict[str, object] = {"notified_at": state.now}
        if planned.venue is not None:
            values["venue_override"] = planned.venue
        if planned.scheduled_at is not None:
            values["scheduled_at_override"] = planned.scheduled_at
        operations.append(
            StateOp(
                op="update",
                model="application_round_states",
                values=values,
                where={"id": planned.state_id},
            )
        )
        venue = planned.effective_venue
        scheduled_at = planned.effective_scheduled_at
        events.append(
            Event(
                application_id=target.application_id,
                event_type=EventType.VENUE_ASSIGNED,
                from_status=target.status.value,
                to_status=target.status.value,
                from_round=input_value.round_id,
                to_round=input_value.round_id,
                reason=None,
                payload={
                    "venue": venue,
                    "scheduled_at": _iso(scheduled_at),
                    "is_update": planned.is_update,
                    "round": state.round.name,
                    "job_id": str(input_value.job_id),
                },
            )
        )
        deferred.append(
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": "venue_timing",
                    "recipient": target.email,
                    "context": {
                        "student": target.full_name,
                        "round": state.round.name,
                        "venue": or_absent(venue),
                        "time": format_time(scheduled_at),
                        "is_update": schedule_note(planned.is_update),
                        "job": state.job.title,
                        "cycle_id": str(input_value.cycle_id),
                    },
                },
            )
        )
        results.append(
            _result(
                label,
                target,
                status="ok",
                venue=venue,
                scheduled_at=_iso(scheduled_at),
                is_update=planned.is_update,
            )
        )

    return Plan(
        state_ops=operations,
        events=events,
        deferred=deferred,
        audit={
            "subject_type": "job",
            "subject_id": input_value.job_id,
            "details": {
                "operation": "assign_venue_timing",
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


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _result(
    label: str,
    row: RoundStateRow | None,
    *,
    status: str,
    reason: str | None = None,
    human: str | None = None,
    venue: str | None = None,
    scheduled_at: str | None = None,
    is_update: bool | None = None,
) -> dict[str, object]:
    """One line of the per-row report, identical in preview and execution."""
    return {
        "identifier": label,
        "application_id": str(row.application_id) if row is not None else None,
        "full_name": row.full_name if row is not None else None,
        "roll_number": row.roll_number if row is not None else None,
        "status": status,
        "reason": reason,
        "human": human,
        "venue": venue,
        "scheduled_at": scheduled_at,
        "is_update": is_update,
    }


def register_venue_commands(registry: Registry) -> None:
    registry.command(
        name="assign_venue_timing",
        input_model=AssignVenueTimingInput,
        output_model=AssignVenueTimingSummary,
        actor="staff",
        scope="cycle",
        loader=_load,
        rule_domains=(),
        spec_ids=("RND-4", "RND-2"),
        rate_limit="10/min",
        execution_mode="bulk",
    )(_decide)
