"""The rounds and questions tabs of the job builder (Behavior JOB-2, JOB-3).

Both are edited as a whole ordered list rather than row by row, because that is
how the builder presents them and it makes reordering expressible: a partial
patch cannot say "these five, in this order".

What each may *not* do is drop history.  JOB-3 blocks deleting a round any
application has entered and blocks removing or re-typing a question that
already has answers -- in both cases the stored data would be orphaned or
silently reinterpreted.  Renaming and reordering stay free, and inserting is
free, because neither invalidates what is already recorded.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    CYCLE_NOT_FOUND,
    FIELD_NOT_EDITABLE,
    INVALID_FIELD_VALUE,
    UNKNOWN_TAXONOMY_VALUE,
)
from app.core.plan import (
    ActorContext,
    Deferred,
    Plan,
    Reason,
    Rejection,
    ScopeIds,
    StateOp,
)
from app.core.registry import Registry
from app.domain.shared import CycleKind, QuestionType
from app.modules.cycles.commands import CycleRow, fetch_cycle
from app.modules.jobs.commands import (
    JobRow,
    fetch_job,
    job_cancelled_reason,
    job_not_found,
)
from app.modules.notifications.wording import format_time, or_absent, schedule_note

# A question type whose answers are a set of chosen options, so the option list
# is required for it and forbidden for everything else.
OPTION_TYPES = frozenset({QuestionType.SINGLE, QuestionType.MULTI})


def _validated_label(value: str, *, field: str, maximum: int = 200) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{field} must not be blank")
    if len(normalized) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters")
    return normalized


class JobRoundRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Absent for a round being added; present to keep an existing one, which is
    # what lets a reorder be expressed as the same ids in a new order.
    round_id: UUID | None = None
    round_type_id: UUID
    name: str
    venue: str | None = None
    scheduled_at: object | None = None
    duration_min: int | None = None
    instructions: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _validated_label(value, field="round name")

    @field_validator("duration_min")
    @classmethod
    def validate_duration(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("a round's duration must be at least one minute")
        return value


class UpsertJobRoundsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    job_id: UUID
    rounds: list[JobRoundRow]

    @model_validator(mode="after")
    def validate_rounds(self) -> UpsertJobRoundsInput:
        named = [row.round_id for row in self.rounds if row.round_id is not None]
        if len(set(named)) != len(named):
            raise ValueError("a round may appear at most once in the order")
        return self


class JobQuestionRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: UUID | None = None
    text: str
    qtype: QuestionType
    required: bool = False
    options: list[str] = []

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _validated_label(value, field="question text", maximum=500)

    @model_validator(mode="after")
    def validate_options(self) -> JobQuestionRow:
        if self.qtype in OPTION_TYPES:
            cleaned = [" ".join(option.split()) for option in self.options]
            cleaned = [option for option in cleaned if option]
            if len(cleaned) < 2:
                raise ValueError(f"a {self.qtype.value}-select question needs two options")
            if len(set(cleaned)) != len(cleaned):
                raise ValueError("a question's options must be distinct")
            self.options = cleaned
        elif self.options:
            raise ValueError(f"a {self.qtype.value} question does not take options")
        return self


class UpsertJobQuestionsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    job_id: UUID
    questions: list[JobQuestionRow]

    @model_validator(mode="after")
    def validate_questions(self) -> UpsertJobQuestionsInput:
        named = [row.question_id for row in self.questions if row.question_id is not None]
        if len(set(named)) != len(named):
            raise ValueError("a question may appear at most once in the order")
        return self


class JobRoundsSummary(BaseModel):
    cycle_id: UUID
    job_id: UUID
    round_count: int
    added: int
    removed: int
    reordered: bool
    notified_applicants: int
    #: Students told their slot moved because a round's own default did
    #: (the design review 4.46). Separate from notified_applicants, which counts the
    #: JOB-3 process-change notice: the two answer different questions.
    rescheduled_applicants: int
    changed: bool


class JobQuestionsSummary(BaseModel):
    cycle_id: UUID
    job_id: UUID
    question_count: int
    added: int
    removed: int
    changed: bool


@dataclass(frozen=True, slots=True)
class ExistingRound:
    id: UUID
    round_type_id: UUID
    name: str
    ord: int
    venue: str | None
    scheduled_at: object | None
    duration_min: int | None
    instructions: str | None
    has_round_state: bool


@dataclass(frozen=True, slots=True)
class ExistingQuestion:
    id: UUID
    text: str
    qtype: QuestionType
    required: bool
    ord: int
    options: tuple[str, ...]
    answer_count: int


@dataclass(frozen=True, slots=True)
class Applicant:
    """Who hears about a process change, by name as well as by address."""

    email: str
    full_name: str


@dataclass(frozen=True, slots=True)
class RescheduledRound:
    """A round whose own default venue or time this edit moves."""

    round_id: UUID
    name: str
    venue: str | None
    scheduled_at: datetime | None


#: A student who has left the job hears nothing about its schedule.
_LIVE_STATUSES = frozenset({"in_progress", "pending_offer", "offered"})


def _reschedule_notices(
    state: JobRoundsState,
    rescheduled: dict[UUID, RescheduledRound],
    *,
    cycle_id: UUID,
) -> tuple[list[Deferred], list[StateOp]]:
    """Tell the students whose effective slot a round-default edit moved.

    Pure: it reads the loaded occupants and returns what to do about them.
    Nobody with their own override is told, because nothing they can see
    changed; nobody who has left the job is told at all.
    """
    if not rescheduled or state.job is None:
        return [], []
    notices: list[Deferred] = []
    stamps: list[StateOp] = []
    for occupant in state.occupants:
        moved = rescheduled.get(occupant.round_id)
        if moved is None or occupant.status not in _LIVE_STATUSES:
            continue
        before = state.round_by_id.get(occupant.round_id)
        was_venue = (
            occupant.venue_override
            if occupant.venue_override is not None
            else (before.venue if before is not None else None)
        )
        was_time = (
            occupant.scheduled_at_override
            if occupant.scheduled_at_override is not None
            else (before.scheduled_at if before is not None else None)
        )
        now_venue = (
            occupant.venue_override
            if occupant.venue_override is not None
            else moved.venue
        )
        now_time = (
            occupant.scheduled_at_override
            if occupant.scheduled_at_override is not None
            else moved.scheduled_at
        )
        if was_venue == now_venue and was_time == now_time:
            continue
        stamps.append(
            StateOp(
                op="update",
                model="application_round_states",
                values={"notified_at": state.now},
                where={"id": occupant.state_id},
            )
        )
        notices.append(
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": "venue_timing",
                    "recipient": occupant.email,
                    "context": {
                        "student": occupant.full_name,
                        "round": moved.name,
                        "venue": or_absent(now_venue),
                        "time": format_time(now_time),
                        "is_update": schedule_note(occupant.notified_at is not None),
                        "job": state.job.title,
                        "cycle_id": str(cycle_id),
                    },
                },
            )
        )
    return notices, stamps


@dataclass(frozen=True, slots=True)
class RoundOccupant:
    """One student sitting in one round, and what they can see of its slot.

    A round's default venue and time are what a student sees unless they have
    a per-student override (RND-1), so editing those defaults moves the slot
    of everyone without one -- and used to move it silently (the design review 4.46).
    """

    application_id: UUID
    state_id: UUID
    round_id: UUID
    email: str
    full_name: str
    venue_override: str | None
    scheduled_at_override: datetime | None
    notified_at: datetime | None
    status: str


@dataclass(frozen=True, slots=True)
class JobRoundsState:
    scope_ids: ScopeIds
    cycle_archived: bool
    cycle: CycleRow | None
    job: JobRow | None
    rounds: tuple[ExistingRound, ...]
    unknown_round_types: tuple[UUID, ...]
    applicants: tuple[Applicant, ...]
    occupants: tuple[RoundOccupant, ...]
    now: datetime

    @property
    def round_by_id(self) -> dict[UUID, ExistingRound]:
        return {round_.id: round_ for round_ in self.rounds}


@dataclass(frozen=True, slots=True)
class JobQuestionsState:
    scope_ids: ScopeIds
    cycle_archived: bool
    cycle: CycleRow | None
    job: JobRow | None
    questions: tuple[ExistingQuestion, ...]


async def _load_rounds(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> JobRoundsState:
    if not isinstance(input_value, UpsertJobRoundsInput):
        raise TypeError("upsert_job_rounds requires UpsertJobRoundsInput")
    cycle = await fetch_cycle(tx, input_value.cycle_id, lock=lock)
    job = await fetch_job(
        tx, cycle_id=input_value.cycle_id, job_id=input_value.job_id, lock=lock
    )
    rows = (
        await tx.execute(
            sa.text(
                "SELECT r.id, r.round_type_id, r.name, r.ord, r.venue, "
                "r.scheduled_at, r.duration_min, r.instructions, "
                "EXISTS (SELECT 1 FROM application_round_states s "
                "WHERE s.round_id = r.id) AS has_round_state "
                "FROM job_rounds r WHERE r.job_id = :job_id ORDER BY r.ord"
                + (" FOR UPDATE OF r" if lock else "")
            ),
            {"job_id": input_value.job_id},
        )
    ).mappings().all()
    wanted = [row.round_type_id for row in input_value.rounds]
    known = set(
        (
            await tx.execute(
                sa.text("SELECT id FROM round_types WHERE id = ANY(:ids) AND is_active"),
                {"ids": wanted},
            )
        ).scalars().all()
    )
    applicants = (
        await tx.execute(
            sa.text(
                "SELECT u.email, u.full_name FROM applications a "
                "JOIN enrollments e ON e.id = a.enrollment_id "
                "JOIN users u ON u.id = e.user_id "
                "WHERE a.job_id = :job_id AND a.status IN "
                "('in_progress', 'pending_offer', 'offered') ORDER BY u.email"
            ),
            {"job_id": input_value.job_id},
        )
    ).mappings().all()
    # Who is sitting in each round, and whether their own override already
    # masks the round's default. A student who has one hears nothing when the
    # default moves, because nothing they can see moved.
    occupants = (
        await tx.execute(
            sa.text(
                "SELECT s.id AS state_id, s.round_id, s.application_id, "
                "s.venue_override, s.scheduled_at_override, s.notified_at, "
                "a.status, u.email, u.full_name "
                "FROM application_round_states s "
                "JOIN applications a ON a.id = s.application_id "
                "JOIN enrollments e ON e.id = a.enrollment_id "
                "JOIN users u ON u.id = e.user_id "
                "WHERE a.job_id = :job_id ORDER BY u.full_name, s.id"
                + (" FOR UPDATE OF s" if lock else "")
            ),
            {"job_id": input_value.job_id},
        )
    ).mappings().all()
    return JobRoundsState(
        scope_ids=ScopeIds(cycle_id=input_value.cycle_id, job_id=input_value.job_id),
        cycle_archived=cycle is not None and cycle.archived_at is not None,
        cycle=cycle,
        job=job,
        now=cast(datetime, await tx.scalar(sa.select(sa.func.now()))),
        occupants=tuple(
            RoundOccupant(
                application_id=cast(UUID, row["application_id"]),
                state_id=cast(UUID, row["state_id"]),
                round_id=cast(UUID, row["round_id"]),
                email=str(row["email"]),
                full_name=str(row["full_name"]),
                venue_override=(
                    str(row["venue_override"]) if row["venue_override"] is not None else None
                ),
                scheduled_at_override=cast(
                    "datetime | None", row["scheduled_at_override"]
                ),
                notified_at=cast("datetime | None", row["notified_at"]),
                status=str(row["status"]),
            )
            for row in occupants
        ),
        rounds=tuple(
            ExistingRound(
                id=row["id"],
                round_type_id=row["round_type_id"],
                name=str(row["name"]),
                ord=int(row["ord"]),
                venue=row["venue"],
                scheduled_at=row["scheduled_at"],
                duration_min=row["duration_min"],
                instructions=row["instructions"],
                has_round_state=bool(row["has_round_state"]),
            )
            for row in rows
        ),
        unknown_round_types=tuple(
            dict.fromkeys(item for item in wanted if item not in known)
        ),
        applicants=tuple(
            Applicant(email=str(row["email"]), full_name=str(row["full_name"]))
            for row in applicants
        ),
    )


async def _load_questions(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> JobQuestionsState:
    if not isinstance(input_value, UpsertJobQuestionsInput):
        raise TypeError("upsert_job_questions requires UpsertJobQuestionsInput")
    cycle = await fetch_cycle(tx, input_value.cycle_id, lock=lock)
    job = await fetch_job(
        tx, cycle_id=input_value.cycle_id, job_id=input_value.job_id, lock=lock
    )
    rows = (
        await tx.execute(
            sa.text(
                "SELECT q.id, q.text, q.qtype, q.required, q.ord, "
                "(SELECT count(*) FROM application_answers a "
                "WHERE a.question_id = q.id) AS answer_count, "
                "coalesce((SELECT array_agg(o.text ORDER BY o.ord) "
                "FROM job_question_options o WHERE o.question_id = q.id), "
                "'{}') AS options "
                "FROM job_questions q WHERE q.job_id = :job_id ORDER BY q.ord"
                + (" FOR UPDATE OF q" if lock else "")
            ),
            {"job_id": input_value.job_id},
        )
    ).mappings().all()
    return JobQuestionsState(
        scope_ids=ScopeIds(cycle_id=input_value.cycle_id, job_id=input_value.job_id),
        cycle_archived=cycle is not None and cycle.archived_at is not None,
        cycle=cycle,
        job=job,
        questions=tuple(
            ExistingQuestion(
                id=row["id"],
                text=str(row["text"]),
                qtype=QuestionType(row["qtype"]),
                required=bool(row["required"]),
                ord=int(row["ord"]),
                options=tuple(str(option) for option in row["options"]),
                answer_count=int(row["answer_count"]),
            )
            for row in rows
        ),
    )


def _answered(count: int) -> str:
    verb = "application has" if count == 1 else "applications have"
    return f"{count} {verb} already answered it"


def _guard(cycle: CycleRow | None, job: JobRow | None) -> Rejection | None:
    if cycle is None:
        return Rejection(
            reasons=[Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")]
        )
    if job is None:
        return job_not_found()
    if job.cancelled_at is not None:
        return Rejection(reasons=[job_cancelled_reason()])
    return None


def _decide_upsert_job_rounds(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Rewrite the round order (Behavior JOB-2.3, JOB-3, JOB-6)."""
    if not isinstance(input_value, UpsertJobRoundsInput) or not isinstance(
        state, JobRoundsState
    ):
        raise TypeError("Invalid upsert_job_rounds decision input")
    guard = _guard(state.cycle, state.job)
    if guard is not None:
        return guard
    assert state.cycle is not None and state.job is not None

    reasons: list[Reason] = []
    if state.cycle.kind is CycleKind.OPEN:
        reasons.append(
            Reason(
                code=FIELD_NOT_EDITABLE,
                human=(
                    "An open cycle's jobs are lightweight: they carry no rounds, "
                    "attendance, or venue scheduling"
                ),
                path="rounds",
            )
        )
    reasons.extend(
        Reason(
            code=UNKNOWN_TAXONOMY_VALUE,
            human=f"Round type {round_type_id} is not an active taxonomy entry",
            path="rounds",
        )
        for round_type_id in state.unknown_round_types
    )

    existing = {round_.id: round_ for round_ in state.rounds}
    kept = {row.round_id for row in input_value.rounds if row.round_id is not None}
    unknown_rounds = sorted(kept - set(existing), key=str)
    reasons.extend(
        Reason(
            code=INVALID_FIELD_VALUE,
            human=f"Round {round_id} does not belong to this job",
            path="rounds",
        )
        for round_id in unknown_rounds
    )
    # JOB-3: a round anyone has entered holds attendance and results; deleting
    # it would orphan them, so renaming and rescheduling are the way to fix it.
    for round_ in state.rounds:
        if round_.id not in kept and round_.has_round_state:
            reasons.append(
                Reason(
                    code=FIELD_NOT_EDITABLE,
                    human=(
                        f"'{round_.name}' cannot be removed because applications "
                        "have already reached it; rename or reschedule it instead"
                    ),
                    path="rounds",
                )
            )
    if reasons:
        return Rejection(reasons=reasons)

    operations: list[StateOp] = []
    added = 0
    removed = 0
    reordered = False
    changed_process = False
    rescheduled: dict[UUID, RescheduledRound] = {}
    for round_ in state.rounds:
        if round_.id not in kept:
            removed += 1
            operations.append(
                StateOp(
                    op="delete",
                    model="job_rounds",
                    values={},
                    where={"id": round_.id},
                )
            )
    for position, row in enumerate(input_value.rounds, start=1):
        # An omitted schedule leaves the round's default alone; only an
        # explicit null clears it. Same doctrine as an empty cell on a venue
        # sheet (the design review section 4.23), and for the same reason: the builder
        # screen sends the rounds tab's five editable fields and no schedule,
        # so writing `scheduled_at` unconditionally silently nulled every
        # round's default time on the next save -- and, once a moved default
        # notifies, would have mailed the whole round "Time: to be announced".
        before = existing.get(row.round_id) if row.round_id is not None else None
        scheduled_at = (
            row.scheduled_at
            if "scheduled_at" in row.model_fields_set or before is None
            else before.scheduled_at
        )
        values: dict[str, object] = {
            "round_type_id": row.round_type_id,
            "name": row.name,
            "ord": position,
            "venue": row.venue,
            "scheduled_at": scheduled_at,
            "duration_min": row.duration_min,
            "instructions": row.instructions,
        }
        if row.round_id is None:
            added += 1
            operations.append(
                StateOp(
                    op="insert",
                    model="job_rounds",
                    values={"id": uuid4(), "job_id": state.job.id, **values},
                )
            )
            continue
        assert before is not None
        if before.ord != position:
            reordered = True
        if before.round_type_id != row.round_type_id:
            changed_process = True
        if before.venue != row.venue or before.scheduled_at != scheduled_at:
            rescheduled[row.round_id] = RescheduledRound(
                round_id=row.round_id,
                name=row.name,
                venue=row.venue,
                scheduled_at=cast("datetime | None", scheduled_at),
            )
        if (
            before.name != row.name
            or before.ord != position
            or before.venue != row.venue
            or before.scheduled_at != scheduled_at
            or before.duration_min != row.duration_min
            or before.instructions != row.instructions
            or before.round_type_id != row.round_type_id
        ):
            operations.append(
                StateOp(
                    op="update",
                    model="job_rounds",
                    values=values,
                    where={"id": row.round_id},
                )
            )

    # JOB-3: inserting, removing, or reordering changes the process someone is
    # already in the middle of, so they hear about it.  A rename does not,
    # which is why the flags above are tracked separately.
    process_changed = added > 0 or removed > 0 or reordered or changed_process
    deferred: list[Deferred] = (
        [
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": "process_changed",
                    "recipient": applicant.email,
                    "context": {
                        "student": applicant.full_name,
                        "job": state.job.title,
                        "job_id": str(state.job.id),
                        "round_count": len(input_value.rounds),
                        "cycle_id": str(input_value.cycle_id),
                    },
                },
            )
            for applicant in state.applicants
        ]
        if process_changed
        else []
    )

    # RND-4 through the design review 4.46: a round's default venue and time are what a
    # student without an override sees, so moving them moves that student's
    # slot -- and used to move it with no notification at all, on the grounds
    # that "a venue fix" is not a process change. It is not a process change;
    # it is a schedule change, which is a different notification.
    rescheduled_notices, rescheduled_stamps = _reschedule_notices(
        state, rescheduled, cycle_id=input_value.cycle_id
    )
    # Counted apart from the process-change notices: they answer different
    # questions, and one number covering both tells an operator neither.
    notified_applicants = len(deferred)
    deferred.extend(rescheduled_notices)
    operations.extend(rescheduled_stamps)

    return Plan(
        state_ops=operations,
        events=[],
        deferred=deferred,
        audit={
            "subject_type": "job",
            "subject_id": state.job.id,
            "details": {
                "before": [
                    {"id": str(round_.id), "name": round_.name, "ord": round_.ord}
                    for round_ in state.rounds
                ],
                "after": [
                    {"name": row.name, "ord": position}
                    for position, row in enumerate(input_value.rounds, start=1)
                ],
                "notified_applicants": notified_applicants,
                "rescheduled_applicants": len(rescheduled_notices),
                "rescheduled_rounds": [
                    {"id": str(moved.round_id), "name": moved.name}
                    for moved in rescheduled.values()
                ],
            },
        },
        summary={
            "cycle_id": str(state.cycle.id),
            "job_id": str(state.job.id),
            "round_count": len(input_value.rounds),
            "added": added,
            "removed": removed,
            "reordered": reordered,
            "notified_applicants": notified_applicants,
            "rescheduled_applicants": len(rescheduled_notices),
            "changed": bool(operations),
        },
    )


def _decide_upsert_job_questions(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Rewrite the application form (Behavior JOB-2.4, JOB-3, JOB-6)."""
    if not isinstance(input_value, UpsertJobQuestionsInput) or not isinstance(
        state, JobQuestionsState
    ):
        raise TypeError("Invalid upsert_job_questions decision input")
    guard = _guard(state.cycle, state.job)
    if guard is not None:
        return guard
    assert state.cycle is not None and state.job is not None

    existing = {question.id: question for question in state.questions}
    kept = {row.question_id for row in input_value.questions if row.question_id is not None}
    reasons: list[Reason] = [
        Reason(
            code=INVALID_FIELD_VALUE,
            human=f"Question {question_id} does not belong to this job",
            path="questions",
        )
        for question_id in sorted(kept - set(existing), key=str)
    ]
    # JOB-3: an answered question cannot be removed (the answers would be
    # orphaned) or re-typed (they would be silently reinterpreted).  Rename and
    # reorder stay free because neither changes what an answer means.
    for question in state.questions:
        if question.id not in kept and question.answer_count:
            reasons.append(
                Reason(
                    code=FIELD_NOT_EDITABLE,
                    human=(
                        f"'{question.text}' cannot be removed because "
                        f"{_answered(question.answer_count)}; rename or "
                        "reorder it instead"
                    ),
                    path="questions",
                )
            )
    for row in input_value.questions:
        if row.question_id is None:
            continue
        before = existing.get(row.question_id)
        if before is None or not before.answer_count:
            continue
        if before.qtype is not row.qtype:
            reasons.append(
                Reason(
                    code=FIELD_NOT_EDITABLE,
                    human=(
                        f"'{before.text}' cannot change type because "
                        f"{_answered(before.answer_count)}"
                    ),
                    path="questions",
                )
            )
        elif before.qtype in OPTION_TYPES and set(row.options) < set(before.options):
            # Adding an option is fine; withdrawing one that an answer already
            # selected would leave that answer pointing at nothing.
            reasons.append(
                Reason(
                    code=FIELD_NOT_EDITABLE,
                    human=(
                        f"'{before.text}' cannot drop options because "
                        f"{_answered(before.answer_count)}"
                    ),
                    path="questions",
                )
            )
    if reasons:
        return Rejection(reasons=reasons)

    operations: list[StateOp] = []
    added = 0
    removed = 0
    for question in state.questions:
        if question.id not in kept:
            removed += 1
            operations.append(
                StateOp(
                    op="delete",
                    model="job_question_options",
                    values={},
                    where={"question_id": question.id},
                )
            )
            operations.append(
                StateOp(
                    op="delete",
                    model="job_questions",
                    values={},
                    where={"id": question.id},
                )
            )
    for position, row in enumerate(input_value.questions, start=1):
        question_id = row.question_id or uuid4()
        values: dict[str, object] = {
            "ord": position,
            "text": row.text,
            "qtype": row.qtype.value,
            "required": row.required,
        }
        if row.question_id is None:
            added += 1
            operations.append(
                StateOp(
                    op="insert",
                    model="job_questions",
                    values={"id": question_id, "job_id": state.job.id, **values},
                )
            )
        else:
            before = existing[row.question_id]
            if (
                before.text != row.text
                or before.ord != position
                or before.qtype is not row.qtype
                or before.required != row.required
            ):
                operations.append(
                    StateOp(
                        op="update",
                        model="job_questions",
                        values=values,
                        where={"id": question_id},
                    )
                )
            if before.options == tuple(row.options):
                continue
            operations.append(
                StateOp(
                    op="delete",
                    model="job_question_options",
                    values={},
                    where={"question_id": question_id},
                )
            )
        operations.extend(
            StateOp(
                op="insert",
                model="job_question_options",
                values={
                    "id": uuid4(),
                    "question_id": question_id,
                    "ord": index,
                    "text": option,
                },
            )
            for index, option in enumerate(row.options, start=1)
        )

    return Plan(
        state_ops=operations,
        events=[],
        deferred=[],
        audit={
            "subject_type": "job",
            "subject_id": state.job.id,
            "details": {
                "before": [
                    {
                        "id": str(question.id),
                        "text": question.text,
                        "qtype": question.qtype.value,
                        "ord": question.ord,
                    }
                    for question in state.questions
                ],
                "after": [
                    {"text": row.text, "qtype": row.qtype.value, "ord": position}
                    for position, row in enumerate(input_value.questions, start=1)
                ],
            },
        },
        summary={
            "cycle_id": str(state.cycle.id),
            "job_id": str(state.job.id),
            "question_count": len(input_value.questions),
            "added": added,
            "removed": removed,
            "changed": bool(operations),
        },
    )


def register_job_builder_commands(registry: Registry) -> None:
    registry.command(
        name="upsert_job_rounds",
        input_model=UpsertJobRoundsInput,
        output_model=JobRoundsSummary,
        actor="staff",
        scope="cycle",
        loader=_load_rounds,
        rule_domains=(),
        spec_ids=("JOB-2", "JOB-3", "JOB-6"),
    )(_decide_upsert_job_rounds)
    registry.command(
        name="upsert_job_questions",
        input_model=UpsertJobQuestionsInput,
        output_model=JobQuestionsSummary,
        actor="staff",
        scope="cycle",
        loader=_load_questions,
        rule_domains=(),
        spec_ids=("JOB-2", "JOB-3", "JOB-6"),
    )(_decide_upsert_job_questions)
