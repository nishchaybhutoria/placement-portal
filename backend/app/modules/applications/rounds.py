"""Moving applications through a job's rounds (Behavior RND-1, RND-2, APP-4).

Four staff bulk operations over one shared contract.  Three of them move the
application's *status* through the APP-4 table; ``waitlist`` moves only the
round result, because APP-4 has no waitlisted status and none is to be added
(the design review section 4.21).  A waitlisted application is an ``in_progress``
application whose current round says "not yet", and RND-1's "resolves only by
manual promotion" is why ``promote_waitlisted`` exists and follows advance
semantics exactly.

The RND-2 bulk contract is the reason these share so much: a selection or a
pasted list of rolls or emails, a preview that resolves every target and lists
what could not be matched **individually**, one event per affected row, and
per-row results after commit.  A coordinator pasting fifty rolls with three
typos needs the three, not the number three.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.core.errors import (
    CYCLE_NOT_FOUND,
    DUPLICATE_ROW,
    INVALID_TRANSITION,
    STALE_VIEW,
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
from app.domain.shared import (
    ApplicationStatus,
    Attendance,
    CycleKind,
    EventType,
    RoundResult,
)
from app.domain.transitions import TransitionActor, TransitionContext, decide_transition
from app.modules.cycles.commands import CycleRow, fetch_cycle
from app.modules.jobs.commands import JobRow, fetch_job, job_not_found
from app.modules.notifications.wording import NOT_APPLICABLE, format_time, or_absent

Operation = Literal["advance", "eliminate", "waitlist", "promote"]

#: Each operation's row-level verb, for the preview sentence and the summary.
_VERB: dict[Operation, str] = {
    "advance": "advance",
    "eliminate": "eliminate",
    "waitlist": "waitlist",
    "promote": "promote",
}

_BOARD_ROWS = """
    SELECT
        a.id, a.status, a.current_round_id, a.enrollment_id,
        u.email, e.roll_number, u.full_name,
        s.id AS state_id, s.result, s.attendance,
        s.venue_override, s.scheduled_at_override, s.notified_at,
        r.id AS round_id, r.ord AS round_ord, r.name AS round_name
    FROM applications a
    JOIN enrollments e ON e.id = a.enrollment_id
    JOIN users u ON u.id = e.user_id
    LEFT JOIN job_rounds r ON r.id = a.current_round_id
    LEFT JOIN application_round_states s
        ON s.application_id = a.id AND s.round_id = a.current_round_id
    WHERE a.job_id = :job_id
    ORDER BY u.full_name, a.id
"""

_ROUNDS = """
    SELECT
        r.id, r.ord, r.name, r.venue, r.scheduled_at,
        r.finalized_at, r.finalized_by,
        finalizer.full_name AS finalized_by_name
    FROM job_rounds r
    LEFT JOIN users finalizer ON finalizer.id = r.finalized_by
    WHERE r.job_id = :job_id
    ORDER BY r.ord
"""


@dataclass(frozen=True, slots=True)
class RoundStateRow:
    """One application as seen *from a named round*, not from where it sits now.

    ``board_rows`` reports each application against its current round, which is
    the right frame for advancing one.  Attendance and venue are the other
    frame: they are facts about a round that happened, so they are addressed by
    round and a row with no state in that round is one this operation cannot
    touch (the design review section 4.23).
    """

    application_id: UUID
    enrollment_id: UUID
    status: ApplicationStatus
    current_round_id: UUID | None
    state_id: UUID | None
    result: RoundResult | None
    attendance: Attendance | None
    venue_override: str | None
    scheduled_at_override: datetime | None
    notified_at: datetime | None
    email: str
    roll_number: str | None
    full_name: str


@dataclass(frozen=True, slots=True)
class BoardRow(RoundStateRow):
    """A round-state row seen from the round the application is *sitting* in.

    It is a ``RoundStateRow`` and not merely like one, so the attendance and
    venue decisions -- which are written against a named round -- run over the
    board's rows unchanged.  What it adds is the position: which round this is,
    which is what advancing needs and marking attendance does not.
    """

    round_ord: int | None
    round_name: str | None


@dataclass(frozen=True, slots=True)
class JobRound:
    id: UUID
    ord: int
    name: str
    #: The round's defaults, which a per-student override replaces (RND-1).
    venue: str | None = None
    scheduled_at: datetime | None = None
    finalized_at: datetime | None = None
    finalized_by: UUID | None = None
    finalized_by_name: str | None = None


def job_round(row: sa.RowMapping) -> JobRound:
    return JobRound(
        id=cast(UUID, row["id"]),
        ord=int(row["ord"]),
        name=str(row["name"]),
        venue=str(row["venue"]) if row["venue"] is not None else None,
        scheduled_at=cast("datetime | None", row["scheduled_at"]),
        finalized_at=cast("datetime | None", row.get("finalized_at")),
        finalized_by=cast("UUID | None", row.get("finalized_by")),
        finalized_by_name=(
            str(row["finalized_by_name"])
            if row.get("finalized_by_name") is not None
            else None
        ),
    )


def _board_row(row: sa.RowMapping) -> BoardRow:
    return BoardRow(
        application_id=cast(UUID, row["id"]),
        enrollment_id=cast(UUID, row["enrollment_id"]),
        status=ApplicationStatus(row["status"]),
        current_round_id=cast("UUID | None", row["current_round_id"]),
        state_id=cast("UUID | None", row["state_id"]),
        result=RoundResult(row["result"]) if row["result"] is not None else None,
        attendance=(
            Attendance(row["attendance"]) if row["attendance"] is not None else None
        ),
        venue_override=(
            str(row["venue_override"]) if row["venue_override"] is not None else None
        ),
        scheduled_at_override=cast("datetime | None", row["scheduled_at_override"]),
        notified_at=cast("datetime | None", row["notified_at"]),
        email=str(row["email"]),
        roll_number=str(row["roll_number"]) if row["roll_number"] else None,
        full_name=str(row["full_name"]),
        round_ord=int(row["round_ord"]) if row["round_ord"] is not None else None,
        round_name=str(row["round_name"]) if row["round_name"] is not None else None,
    )


async def board_rows(
    executor: AsyncConnection | AsyncSession, job_id: UUID
) -> tuple[tuple[BoardRow, ...], tuple[JobRound, ...]]:
    """Every application on a job, plus the job's rounds in order.

    Shared by the board screen and the bulk loaders on purpose: the screen's
    "can this row advance" and the command's answer must be one computation
    (the design review section 4.22).
    """
    rows = (
        await executor.execute(sa.text(_BOARD_ROWS), {"job_id": job_id})
    ).mappings().all()
    rounds = (
        await executor.execute(sa.text(_ROUNDS), {"job_id": job_id})
    ).mappings().all()
    return (
        tuple(_board_row(row) for row in rows),
        tuple(job_round(item) for item in rounds),
    )


_ROUND_STATE_ROWS = """
    SELECT
        a.id, a.status, a.enrollment_id, a.current_round_id,
        u.email, e.roll_number, u.full_name,
        s.id AS state_id, s.result, s.attendance,
        s.venue_override, s.scheduled_at_override, s.notified_at
    FROM applications a
    JOIN enrollments e ON e.id = a.enrollment_id
    JOIN users u ON u.id = e.user_id
    LEFT JOIN application_round_states s
        ON s.application_id = a.id AND s.round_id = :round_id
    WHERE a.job_id = :job_id
"""

_ONE_APPLICATION = " AND a.id = :application_id"
_ROUND_STATE_ORDER = " ORDER BY u.full_name, a.id"


async def round_state_rows(
    executor: AsyncConnection | AsyncSession,
    *,
    job_id: UUID,
    round_id: UUID,
    application_id: UUID | None = None,
) -> tuple[RoundStateRow, ...]:
    """Every application on the job, carrying its state in one named round."""
    parameters: dict[str, object] = {"job_id": job_id, "round_id": round_id}
    statement = _ROUND_STATE_ROWS
    if application_id is not None:
        statement += _ONE_APPLICATION
        parameters["application_id"] = application_id
    rows = (
        await executor.execute(sa.text(statement + _ROUND_STATE_ORDER), parameters)
    ).mappings().all()
    return tuple(
        RoundStateRow(
            application_id=cast(UUID, row["id"]),
            enrollment_id=cast(UUID, row["enrollment_id"]),
            status=ApplicationStatus(row["status"]),
            current_round_id=cast("UUID | None", row["current_round_id"]),
            state_id=cast("UUID | None", row["state_id"]),
            result=RoundResult(row["result"]) if row["result"] is not None else None,
            attendance=(
                Attendance(row["attendance"]) if row["attendance"] is not None else None
            ),
            venue_override=(
                str(row["venue_override"]) if row["venue_override"] is not None else None
            ),
            scheduled_at_override=cast("datetime | None", row["scheduled_at_override"]),
            notified_at=cast("datetime | None", row["notified_at"]),
            email=str(row["email"]),
            roll_number=str(row["roll_number"]) if row["roll_number"] else None,
            full_name=str(row["full_name"]),
        )
        for row in rows
    )


class BulkRoundInput(BaseModel):
    """The RND-2 contract: a selection, or pasted identifiers, never both."""

    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    job_id: UUID
    rows: list[dict[str, str]]
    batch_key: str
    reason: str | None = None

    @field_validator("rows")
    @classmethod
    def validate_rows(cls, value: list[dict[str, str]]) -> list[dict[str, str]]:
        for row in value:
            keys = set(row)
            if not keys or not keys <= {"application_id", "identifier", "expected_status"}:
                raise ValueError(
                    "each row names an application_id or an identifier, "
                    "optionally with the expected_status the board displayed"
                )
            if not keys & {"application_id", "identifier"}:
                raise ValueError("each row names an application_id or an identifier")
        return value


class BulkRoundSummary(BaseModel):
    #: Per-row outcome, in the order submitted.  A preview carries the same
    #: rows with the same planned effects; that is what makes the confirm
    #: dialog's promise checkable (LLD section 5, "previews never lie").
    #: Only ``rows`` survives ``run_bulk``'s chunk aggregation, so only ``rows``
    #: is promised here: an output model that names a field the response cannot
    #: carry fails response validation and turns a working command into a 500.
    rows: list[dict[str, object]]


@dataclass(frozen=True, slots=True)
class BulkRoundState:
    scope_ids: ScopeIds
    cycle_archived: bool
    now: datetime
    cycle: CycleRow | None
    job: JobRow | None
    applications: tuple[BoardRow, ...]
    rounds: tuple[JobRound, ...]


async def _load_bulk(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> BulkRoundState:
    if not isinstance(input_value, BulkRoundInput):
        raise TypeError("A round operation requires BulkRoundInput")
    cycle = await fetch_cycle(tx, input_value.cycle_id, lock=lock)
    job = await fetch_job(
        tx, cycle_id=input_value.cycle_id, job_id=input_value.job_id, lock=lock
    )
    if lock:
        # The rows this decide is about to move, locked before it judges them
        # (CONTRIBUTING.md invariant 9): two coordinators advancing the same board
        # would otherwise both read in_progress and both write round two.
        await tx.execute(
            sa.text(
                "SELECT 1 FROM applications WHERE job_id = :job_id FOR UPDATE"
            ),
            {"job_id": input_value.job_id},
        )
    applications, rounds = await board_rows(tx, input_value.job_id)
    return BulkRoundState(
        scope_ids=ScopeIds(cycle_id=input_value.cycle_id, job_id=input_value.job_id),
        cycle_archived=cycle is not None and cycle.archived_at is not None,
        now=cast(datetime, await tx.scalar(sa.select(sa.func.now()))),
        cycle=cycle,
        job=job,
        applications=applications,
        rounds=rounds,
    )


class Resolvable(Protocol):
    """What an identifier can be resolved against: an id, an email, a roll."""

    @property
    def application_id(self) -> UUID: ...
    @property
    def email(self) -> str: ...
    @property
    def roll_number(self) -> str | None: ...


def resolve_row[RowT: Resolvable](
    row: dict[str, str], applications: Sequence[RowT]
) -> RowT | None:
    """Selection by id, or a pasted roll number or email (RND-2).

    Matching is case-insensitive and never fuzzy: an identifier that does not
    match exactly is reported back rather than guessed at, because the cost of
    a wrong guess here is eliminating the wrong student.
    """
    if "application_id" in row:
        target = UUID(row["application_id"])
        return next(
            (item for item in applications if item.application_id == target), None
        )
    identifier = row["identifier"].strip().casefold()
    if not identifier:
        return None
    return next(
        (
            item
            for item in applications
            if item.email.casefold() == identifier
            or (item.roll_number or "").casefold() == identifier
        ),
        None,
    )


def _next_round(
    current: BoardRow, rounds: tuple[JobRound, ...]
) -> JobRound | None:
    if current.round_ord is None:
        return None
    return next((item for item in rounds if item.ord > current.round_ord), None)


@dataclass(frozen=True, slots=True)
class PlannedRow:
    """What one operation would do to one application, before it does it."""

    row: BoardRow
    transition: str
    to_status: ApplicationStatus
    to_round: JobRound | None
    result: RoundResult


def plan_row(
    operation: Operation, row: BoardRow, rounds: tuple[JobRound, ...]
) -> PlannedRow | Reason:
    """The pure decision for one row: what happens, or why nothing does.

    Shared by the board screen (to decide whether to offer the control) and by
    every one of the four commands (to carry it out), so a row the board shows
    as advanceable is one the command advances -- the design review section 4.22.
    """
    if operation == "eliminate":
        if row.status is not ApplicationStatus.IN_PROGRESS:
            return Reason(code=INVALID_TRANSITION, human="Not in progress")
        return PlannedRow(
            row=row,
            transition="eliminate",
            to_status=ApplicationStatus.REJECTED,
            to_round=None,
            result=RoundResult.ELIMINATED,
        )

    if operation == "waitlist":
        # A round result, not a status: the application stays in_progress and
        # keeps its position while the coordinator decides (RND-1).
        if row.status is not ApplicationStatus.IN_PROGRESS or row.state_id is None:
            return Reason(code=INVALID_TRANSITION, human="Not sitting in a round")
        if row.result is RoundResult.WAITLISTED:
            return Reason(code=DUPLICATE_ROW, human="Already waitlisted")
        return PlannedRow(
            row=row,
            transition="waitlist",
            to_status=ApplicationStatus.IN_PROGRESS,
            to_round=None,
            result=RoundResult.WAITLISTED,
        )

    # advance and promote share their mechanics; they differ only in what they
    # are legal from, which is the whole content of "resolves only by manual
    # promotion".
    if row.status is not ApplicationStatus.IN_PROGRESS or row.state_id is None:
        return Reason(code=INVALID_TRANSITION, human="Not sitting in a round")
    if operation == "promote" and row.result is not RoundResult.WAITLISTED:
        return Reason(code=INVALID_TRANSITION, human="Not waitlisted")
    if operation == "advance" and row.result is RoundResult.WAITLISTED:
        return Reason(
            code=INVALID_TRANSITION,
            human="Waitlisted: promote it rather than advancing it",
        )
    following = _next_round(row, rounds)
    return PlannedRow(
        row=row,
        transition="advance" if following is not None else "advance_final",
        to_status=(
            ApplicationStatus.IN_PROGRESS
            if following is not None
            else ApplicationStatus.PENDING_OFFER
        ),
        to_round=following,
        result=RoundResult.ADVANCED,
    )


def _first_human(rejection: Rejection) -> str | None:
    """The sentence a rejection leads with, for the per-row report."""
    return rejection.reasons[0].human if rejection.reasons else None


def _result_row(
    label: str,
    row: BoardRow | None,
    *,
    status: str,
    reason: str | None = None,
    human: str | None = None,
    planned: PlannedRow | None = None,
) -> dict[str, object]:
    """One line of the per-row report, identical in preview and execution.

    ``human`` carries the sentence the decision already produced -- "Not sitting
    in a round" rather than the bare ``invalid_transition`` code.  A coordinator
    reading a skip needs to know *which* of a code's several causes they hit,
    and the screen must not re-derive that from the code (which is how a board
    comes to explain a refusal differently from the command that made it).
    ``assign_venue_timing`` has reported rows this way since M10c; these four
    now match it.
    """
    entry: dict[str, object] = {
        "identifier": label,
        "application_id": str(row.application_id) if row is not None else None,
        "full_name": row.full_name if row is not None else None,
        "roll_number": row.roll_number if row is not None else None,
        "status": status,
        "reason": reason,
        "human": human,
    }
    if planned is not None:
        entry |= {
            "to_status": planned.to_status.value,
            "to_round": planned.to_round.name if planned.to_round is not None else None,
            "round_result": planned.result.value,
        }
    return entry


def _decide(operation: Operation) -> object:
    def decide(
        input_value: BaseModel,
        state: object,
        _policy: object,
        _overrides: object,
        actor: ActorContext,
    ) -> Plan | Rejection:
        if not isinstance(input_value, BulkRoundInput) or not isinstance(
            state, BulkRoundState
        ):
            raise TypeError("Invalid round operation decision input")
        if state.cycle is None:
            return Rejection(
                reasons=[Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")]
            )
        if state.job is None:
            return job_not_found()
        if operation == "eliminate" and not (input_value.reason or "").strip():
            return Rejection(
                reasons=[
                    Reason(
                        code=INVALID_TRANSITION,
                        human="Eliminating requires a reason",
                        path="reason",
                    )
                ]
            )

        results: list[dict[str, object]] = []
        unmatched: list[str] = []
        operations: list[StateOp] = []
        events: list[Event] = []
        deferred: list[Deferred] = []
        seen: set[UUID] = set()

        for row in input_value.rows:
            label = row.get("identifier") or row.get("application_id", "")
            target = resolve_row(row, state.applications)
            if target is None:
                # Listed, never counted: three typos in fifty rolls are three
                # names the coordinator has to go and check.
                unmatched.append(label)
                results.append(
                    _result_row(
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
                    _result_row(
                        label,
                        target,
                        status="skipped",
                        reason=DUPLICATE_ROW,
                        human="Named more than once in this batch",
                    )
                )
                continue
            expected = row.get("expected_status")
            if expected is not None and expected != target.status.value:
                # The board was showing something else when this was submitted.
                results.append(
                    _result_row(
                        label,
                        target,
                        status="error",
                        reason=STALE_VIEW,
                        human="The board was showing a different status when this was submitted",
                    )
                )
                continue

            planned = plan_row(operation, target, state.rounds)
            if isinstance(planned, Reason):
                results.append(
                    _result_row(
                        label,
                        target,
                        status="skipped",
                        reason=planned.code,
                        human=planned.human,
                    )
                )
                continue

            # Waitlisting moves no status, so there is no APP-4 row to consult;
            # everything else is checked against the table before it is written.
            if planned.to_status is not target.status:
                transition = decide_transition(
                    planned.transition,
                    from_status=target.status,
                    to_status=planned.to_status,
                    actor=TransitionActor.STAFF,
                    context=TransitionContext(cycle_kind=CycleKind(state.cycle.kind)),
                    reason=input_value.reason,
                )
                if isinstance(transition, Rejection):
                    results.append(
                        _result_row(
                            label,
                            target,
                            status="skipped",
                            reason=INVALID_TRANSITION,
                            human=_first_human(transition),
                        )
                    )
                    continue

            seen.add(target.application_id)
            # 1. The round the application is sitting in records the decision.
            if target.state_id is not None:
                operations.append(
                    StateOp(
                        op="update",
                        model="application_round_states",
                        values={"result": planned.result.value},
                        where={"id": target.state_id},
                    )
                )
            # 2. The status moves only when the plan says it does.
            if planned.to_status is not target.status:
                operations.append(
                    StateOp(
                        op="update",
                        model="applications",
                        values={"status": planned.to_status.value},
                        where={"id": target.application_id},
                    )
                )
            # 3. Advancing creates the next round's pending state and moves the
            #    position onto it (RND-1).  From the final round there is no
            #    next state, and the position stays where it was so the
            #    timeline still says which round produced the offer.
            if planned.to_round is not None:
                operations.append(
                    StateOp(
                        op="update",
                        model="applications",
                        values={"current_round_id": planned.to_round.id},
                        where={"id": target.application_id},
                    )
                )
                operations.append(
                    StateOp(
                        op="insert",
                        model="application_round_states",
                        values={
                            "id": uuid4(),
                            "application_id": target.application_id,
                            "round_id": planned.to_round.id,
                            "result": RoundResult.PENDING.value,
                            "attendance": "pending",
                        },
                    )
                )
            events.append(
                Event(
                    application_id=target.application_id,
                    event_type=_EVENT[operation],
                    from_status=target.status.value,
                    to_status=planned.to_status.value,
                    from_round=target.current_round_id,
                    to_round=(
                        planned.to_round.id
                        if planned.to_round is not None
                        else target.current_round_id
                    ),
                    reason=input_value.reason,
                    payload={
                        "operation": operation,
                        "round_result": planned.result.value,
                        "job_id": str(input_value.job_id),
                    },
                )
            )
            if operation in {"advance", "promote"} and planned.to_round is not None:
                deferred.append(
                    Deferred(
                        task="deliver_notification",
                        args={
                            "event_key": "advanced",
                            "recipient": target.email,
                            "context": {
                                "student": target.full_name,
                                "next_round": planned.to_round.name,
                                # The round's own defaults, which are usually
                                # empty here: the schedule is published later,
                                # by assign_venue_timing. "to be announced" is
                                # the honest reading of that, and a blank line
                                # promising a venue is not.
                                "venue": or_absent(planned.to_round.venue),
                                "time": format_time(planned.to_round.scheduled_at),
                                "job": state.job.title,
                                "cycle_id": str(input_value.cycle_id),
                            },
                        },
                    )
                )
            elif operation == "eliminate":
                deferred.append(
                    Deferred(
                        task="deliver_notification",
                        args={
                            "event_key": "rejected",
                            "recipient": target.email,
                            "context": {
                                "student": target.full_name,
                                "round": or_absent(target.round_name, NOT_APPLICABLE),
                                "job": state.job.title,
                                "reason": input_value.reason,
                                "cycle_id": str(input_value.cycle_id),
                            },
                        },
                    )
                )
            results.append(
                _result_row(label, target, status="ok", planned=planned)
            )

        return Plan(
            state_ops=operations,
            events=events,
            deferred=deferred,
            audit={
                "subject_type": "job",
                "subject_id": input_value.job_id,
                "details": {
                    "operation": operation,
                    "matched": len(seen),
                    "unmatched": unmatched,
                    "reason": input_value.reason,
                    "actor_user_id": str(actor.user_id) if actor.user_id else None,
                },
            },
            summary={
                "job_id": str(input_value.job_id),
                "operation": _VERB[operation],
                "rows": results,
                "matched": len(seen),
                "unmatched": unmatched,
            },
        )

    return decide


_EVENT: dict[Operation, EventType] = {
    "advance": EventType.ADVANCED,
    "promote": EventType.ADVANCED,
    "eliminate": EventType.ELIMINATED,
    "waitlist": EventType.WAITLISTED,
}


def register_round_commands(registry: Registry) -> None:
    for name, operation, spec_ids in (
        ("advance_applications", "advance", ("RND-1", "RND-2", "APP-4")),
        ("eliminate_applications", "eliminate", ("RND-1", "RND-2", "APP-4")),
        ("waitlist_applications", "waitlist", ("RND-1", "RND-2")),
        ("promote_waitlisted", "promote", ("RND-1", "RND-2", "APP-4")),
    ):
        registry.command(
            name=name,
            input_model=BulkRoundInput,
            output_model=BulkRoundSummary,
            actor="staff",
            scope="cycle",
            loader=_load_bulk,
            rule_domains=(),
            spec_ids=spec_ids,
            rate_limit="10/min",
            execution_mode="bulk",
        )(_decide(cast(Operation, operation)))  # type: ignore[arg-type]
