"""Job creation, basics, and publishing (Behavior JOB-1, JOB-2, JOB-3, JOB-6).

A job's ``outcome`` is the one field that can never move: gates and cascades
are scoped by it, so editing it mid-flight would silently re-target every
application already in the pipeline (JOB-1).  Everything else about a job is
freely editable, including after publication -- JOB-3's rule is that existing
applications are never affected, not that the job is frozen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    COMPANY_INACTIVE,
    COMPANY_NOT_FOUND,
    CYCLE_NOT_FOUND,
    FIELD_NOT_EDITABLE,
    INVALID_FIELD_VALUE,
    JOB_CANCELLED,
    JOB_NOT_FOUND,
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
from app.domain.shared import CycleKind, Outcome
from app.modules.cycles.commands import CycleRow, fetch_cycle
from app.modules.notifications.wording import format_deadline

# The descriptive and compensation columns update_job_basics owns.  Deliberately
# excludes outcome (JOB-1 immutable), the publish flags, and the eligibility
# tree, each of which has its own command with its own rules.
BASICS_COLUMNS: tuple[str, ...] = (
    "company_id",
    "title",
    "description",
    "location",
    "sector_id",
    "ctc_lpa",
    "ctc_breakdown",
    "stipend_month",
    "application_deadline",
    "offer_acceptance_deadline",
)
JOB_COLUMNS = (
    "id, cycle_id, company_id, outcome, title, description, location, sector_id, "
    "ctc_lpa, ctc_breakdown, stipend_month, application_deadline, "
    "offer_acceptance_deadline, is_published, published_at, cancelled_at, "
    "eligibility_rule, eligibility_summary"
)


def _validated_title(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("title must not be blank")
    if len(normalized) > 200:
        raise ValueError("title must be at most 200 characters")
    return normalized


def _validated_money(value: Decimal | None) -> Decimal | None:
    if value is not None and value < 0:
        raise ValueError("compensation must not be negative")
    return value


class ProgramCtcRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program_id: UUID
    ctc_lpa: Decimal

    @field_validator("ctc_lpa")
    @classmethod
    def validate_ctc(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("per-program CTC must not be negative")
        return value


class CreateJobInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    company_id: UUID
    title: str
    description: str
    # Required only in an open cycle; in a dedicated cycle the cycle's kind
    # supplies it and a mismatching value is rejected rather than ignored.
    outcome: Outcome | None = None
    location: str | None = None
    sector_id: UUID | None = None
    ctc_lpa: Decimal | None = None
    ctc_breakdown: str | None = None
    stipend_month: Decimal | None = None
    application_deadline: datetime | None = None
    offer_acceptance_deadline: datetime | None = None
    program_ctc: list[ProgramCtcRow] = []

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _validated_title(value)

    @field_validator("ctc_lpa", "stipend_month")
    @classmethod
    def validate_money(cls, value: Decimal | None) -> Decimal | None:
        return _validated_money(value)

    @model_validator(mode="after")
    def validate_program_ctc(self) -> CreateJobInput:
        seen = {row.program_id for row in self.program_ctc}
        if len(seen) != len(self.program_ctc):
            raise ValueError("each program may carry at most one CTC row")
        return self


class UpdateJobBasicsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    job_id: UUID
    # Accepted so a client may echo the whole job back; decide rejects only an
    # actual change, matching update_cycle's treatment of kind (JOB-1).
    outcome: Outcome | None = None
    company_id: UUID | None = None
    title: str | None = None
    description: str | None = None
    location: str | None = None
    sector_id: UUID | None = None
    ctc_lpa: Decimal | None = None
    ctc_breakdown: str | None = None
    stipend_month: Decimal | None = None
    application_deadline: datetime | None = None
    offer_acceptance_deadline: datetime | None = None
    program_ctc: list[ProgramCtcRow] | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        return None if value is None else _validated_title(value)

    @field_validator("ctc_lpa", "stipend_month")
    @classmethod
    def validate_money(cls, value: Decimal | None) -> Decimal | None:
        return _validated_money(value)

    @model_validator(mode="after")
    def validate_program_ctc(self) -> UpdateJobBasicsInput:
        if self.program_ctc is None:
            return self
        seen = {row.program_id for row in self.program_ctc}
        if len(seen) != len(self.program_ctc):
            raise ValueError("each program may carry at most one CTC row")
        return self


class PublishJobInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    job_id: UUID


class JobSummary(BaseModel):
    cycle_id: UUID
    job_id: UUID
    outcome: Outcome
    title: str
    is_published: bool
    changed: bool
    notified_applicants: int = 0
    updated_offer_deadlines: int = 0
    scheduled_offer_expiries: int = 0


@dataclass(frozen=True, slots=True)
class JobRow:
    id: UUID
    cycle_id: UUID
    company_id: UUID
    outcome: Outcome
    title: str
    description: str
    location: str | None
    sector_id: UUID | None
    ctc_lpa: Decimal | None
    ctc_breakdown: str | None
    stipend_month: Decimal | None
    application_deadline: datetime | None
    offer_acceptance_deadline: datetime | None
    is_published: bool
    published_at: datetime | None
    cancelled_at: datetime | None
    eligibility_rule: dict[str, object] | None
    eligibility_summary: str | None

    def snapshot(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "cycle_id": str(self.cycle_id),
            "company_id": str(self.company_id),
            "outcome": self.outcome.value,
            "title": self.title,
            "description": self.description,
            "location": self.location,
            "sector_id": str(self.sector_id) if self.sector_id else None,
            "ctc_lpa": str(self.ctc_lpa) if self.ctc_lpa is not None else None,
            "ctc_breakdown": self.ctc_breakdown,
            "stipend_month": (
                str(self.stipend_month) if self.stipend_month is not None else None
            ),
            "application_deadline": _iso(self.application_deadline),
            "offer_acceptance_deadline": _iso(self.offer_acceptance_deadline),
            "is_published": self.is_published,
            "published_at": _iso(self.published_at),
            "cancelled_at": _iso(self.cancelled_at),
            "eligibility_summary": self.eligibility_summary,
        }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def job_row(row: sa.RowMapping) -> JobRow:
    return JobRow(
        id=row["id"],
        cycle_id=row["cycle_id"],
        company_id=row["company_id"],
        outcome=Outcome(row["outcome"]),
        title=str(row["title"]),
        description=str(row["description"]),
        location=row["location"],
        sector_id=row["sector_id"],
        ctc_lpa=row["ctc_lpa"],
        ctc_breakdown=row["ctc_breakdown"],
        stipend_month=row["stipend_month"],
        application_deadline=row["application_deadline"],
        offer_acceptance_deadline=row["offer_acceptance_deadline"],
        is_published=bool(row["is_published"]),
        published_at=row["published_at"],
        cancelled_at=row["cancelled_at"],
        eligibility_rule=row["eligibility_rule"],
        eligibility_summary=row["eligibility_summary"],
    )


async def fetch_job(
    tx: AsyncSession, *, cycle_id: UUID, job_id: UUID, lock: bool
) -> JobRow | None:
    """Look a job up inside its cycle.

    Scoping by cycle is what makes the two-stage authorization meaningful: the
    route stage authorized the caller for ``cycle_id``, so a job living in a
    different cycle must not be reachable by naming it here.
    """
    row = (
        await tx.execute(
            sa.text(
                f"SELECT {JOB_COLUMNS} FROM jobs "  # noqa: S608
                "WHERE id = :job_id AND cycle_id = :cycle_id"
                + (" FOR UPDATE" if lock else "")
            ),
            {"job_id": job_id, "cycle_id": cycle_id},
        )
    ).mappings().one_or_none()
    return job_row(row) if row is not None else None


async def now(tx: AsyncSession) -> datetime:
    return await tx.scalar(sa.select(sa.func.now()))  # type: ignore[return-value]


async def fetch_program_ctc(tx: AsyncSession, job_id: UUID) -> dict[UUID, Decimal]:
    rows = (
        await tx.execute(
            sa.text(
                "SELECT program_id, ctc_lpa FROM job_program_ctc WHERE job_id = :job_id"
            ),
            {"job_id": job_id},
        )
    ).mappings().all()
    return {row["program_id"]: row["ctc_lpa"] for row in rows}


async def unknown_taxonomy_ids(
    tx: AsyncSession, *, table: str, ids: list[UUID]
) -> list[UUID]:
    """Which of these ids do not name an active row of that taxonomy."""
    if not ids:
        return []
    found = (
        await tx.execute(
            sa.text(
                f"SELECT id FROM {table} WHERE id = ANY(:ids) AND is_active"  # noqa: S608
            ),
            {"ids": ids},
        )
    ).scalars().all()
    return [item for item in ids if item not in set(found)]


@dataclass(frozen=True, slots=True)
class JobCreateState:
    scope_ids: ScopeIds
    cycle_archived: bool
    now: datetime
    cycle: CycleRow | None
    job_id: UUID
    company_is_active: bool | None
    unknown_sector: bool
    unknown_programs: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class OpenOfferDeadline:
    offer_id: UUID
    deadline_at: datetime | None


@dataclass(frozen=True, slots=True)
class ApplicantRecipient:
    email: str
    full_name: str


@dataclass(frozen=True, slots=True)
class JobState:
    scope_ids: ScopeIds
    cycle_archived: bool
    now: datetime
    cycle: CycleRow | None
    job: JobRow | None
    program_ctc: dict[UUID, Decimal]
    company_is_active: bool | None
    unknown_sector: bool
    unknown_programs: tuple[UUID, ...]
    applicants: tuple[ApplicantRecipient, ...]
    open_offers: tuple[OpenOfferDeadline, ...]


async def _company_is_active(tx: AsyncSession, company_id: UUID | None) -> bool | None:
    if company_id is None:
        return None
    return await tx.scalar(
        sa.text("SELECT is_active FROM companies WHERE id = :id"), {"id": company_id}
    )


async def _in_flight_applicants(
    tx: AsyncSession, job_id: UUID
) -> tuple[ApplicantRecipient, ...]:
    """Everyone whose application a deadline move or process change reaches (JOB-3)."""
    rows = (
        await tx.execute(
            sa.text(
                "SELECT u.email, u.full_name FROM applications a "
                "JOIN enrollments e ON e.id = a.enrollment_id "
                "JOIN users u ON u.id = e.user_id "
                "WHERE a.job_id = :job_id AND a.status NOT IN "
                "('withdrawn', 'auto_withdrawn', 'rejected', 'declined', "
                "'offer_terminated') ORDER BY u.email"
            ),
            {"job_id": job_id},
        )
    ).mappings().all()
    return tuple(
        ApplicantRecipient(email=str(row["email"]), full_name=str(row["full_name"]))
        for row in rows
    )


async def _open_offers(
    tx: AsyncSession, job_id: UUID, *, lock: bool
) -> tuple[OpenOfferDeadline, ...]:
    rows = (
        await tx.execute(
            sa.text(
                "SELECT o.id, o.deadline_at FROM offers o "
                "JOIN applications a ON a.id = o.application_id "
                "WHERE a.job_id = :job_id AND o.response IS NULL "
                "AND o.terminated_at IS NULL ORDER BY o.id"
                + (" FOR UPDATE OF o" if lock else "")
            ),
            {"job_id": job_id},
        )
    ).mappings().all()
    return tuple(
        OpenOfferDeadline(
            offer_id=cast(UUID, row["id"]),
            deadline_at=cast("datetime | None", row["deadline_at"]),
        )
        for row in rows
    )


async def _load_create(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> JobCreateState:
    if not isinstance(input_value, CreateJobInput):
        raise TypeError("create_job requires CreateJobInput")
    cycle = await fetch_cycle(tx, input_value.cycle_id, lock=lock)
    return JobCreateState(
        scope_ids=ScopeIds(cycle_id=input_value.cycle_id),
        cycle_archived=cycle is not None and cycle.archived_at is not None,
        now=await now(tx),
        cycle=cycle,
        job_id=uuid4(),
        company_is_active=await _company_is_active(tx, input_value.company_id),
        unknown_sector=bool(
            await unknown_taxonomy_ids(
                tx,
                table="sectors",
                ids=[input_value.sector_id] if input_value.sector_id else [],
            )
        ),
        unknown_programs=tuple(
            await unknown_taxonomy_ids(
                tx,
                table="programs",
                ids=[row.program_id for row in input_value.program_ctc],
            )
        ),
    )


async def _load_basics(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> JobState:
    if not isinstance(input_value, UpdateJobBasicsInput):
        raise TypeError("update_job_basics requires UpdateJobBasicsInput")
    return await _load_job_state(
        tx,
        cycle_id=input_value.cycle_id,
        job_id=input_value.job_id,
        lock=lock,
        company_id=input_value.company_id,
        sector_ids=[input_value.sector_id] if input_value.sector_id else [],
        program_ids=[row.program_id for row in (input_value.program_ctc or [])],
        load_open_offers=True,
    )


async def _load_publish(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> JobState:
    if not isinstance(input_value, PublishJobInput):
        raise TypeError("Publishing commands require PublishJobInput")
    return await _load_job_state(
        tx, cycle_id=input_value.cycle_id, job_id=input_value.job_id, lock=lock
    )


async def _load_job_state(
    tx: AsyncSession,
    *,
    cycle_id: UUID,
    job_id: UUID,
    lock: bool,
    company_id: UUID | None = None,
    sector_ids: list[UUID] | None = None,
    program_ids: list[UUID] | None = None,
    load_open_offers: bool = False,
) -> JobState:
    cycle = await fetch_cycle(tx, cycle_id, lock=lock)
    job = await fetch_job(tx, cycle_id=cycle_id, job_id=job_id, lock=lock)
    return JobState(
        scope_ids=ScopeIds(cycle_id=cycle_id, job_id=job_id),
        cycle_archived=cycle is not None and cycle.archived_at is not None,
        now=await now(tx),
        cycle=cycle,
        job=job,
        program_ctc=await fetch_program_ctc(tx, job_id) if job else {},
        company_is_active=await _company_is_active(tx, company_id),
        unknown_sector=bool(
            await unknown_taxonomy_ids(tx, table="sectors", ids=sector_ids or [])
        ),
        unknown_programs=tuple(
            await unknown_taxonomy_ids(tx, table="programs", ids=program_ids or [])
        ),
        applicants=await _in_flight_applicants(tx, job_id) if job else (),
        open_offers=(
            await _open_offers(tx, job_id, lock=lock)
            if job is not None and load_open_offers
            else ()
        ),
    )


def job_not_found() -> Rejection:
    return Rejection(
        reasons=[
            Reason(
                code=JOB_NOT_FOUND,
                human="The job does not exist in this cycle",
                path="job_id",
            )
        ]
    )


def job_cancelled_reason() -> Reason:
    return Reason(
        code=JOB_CANCELLED,
        human="A cancelled job can no longer be edited",
        path="job_id",
    )


def resolve_outcome(
    cycle: CycleRow, requested: Outcome | None
) -> Outcome | Reason:
    """JOB-1: a dedicated cycle dictates the outcome, an open cycle demands one."""
    if cycle.kind is CycleKind.OPEN:
        if requested is None:
            return Reason(
                code=INVALID_FIELD_VALUE,
                human=(
                    "An open cycle carries both kinds of role, so this job's "
                    "outcome must be chosen explicitly"
                ),
                path="outcome",
            )
        return requested
    forced = (
        Outcome.PLACEMENT if cycle.kind is CycleKind.PLACEMENT else Outcome.INTERNSHIP
    )
    if requested is not None and requested is not forced:
        return Reason(
            code=INVALID_FIELD_VALUE,
            human=(
                f"A {cycle.kind.value} cycle only carries {forced.value} roles, "
                f"so this job cannot be a {requested.value}"
            ),
            path="outcome",
        )
    return forced


def deadline_reasons(
    cycle: CycleRow,
    *,
    application_deadline: datetime | None,
    offer_acceptance_deadline: datetime | None,
) -> list[Reason]:
    """JOB-6: the two deadlines exist only where the cycle kind allows them."""
    reasons: list[Reason] = []
    if cycle.kind is CycleKind.OPEN:
        if offer_acceptance_deadline is not None:
            reasons.append(
                Reason(
                    code=FIELD_NOT_EDITABLE,
                    human=(
                        "An open cycle records outcomes directly and has no "
                        "offer-acceptance deadline"
                    ),
                    path="offer_acceptance_deadline",
                )
            )
    elif application_deadline is None:
        reasons.append(
            Reason(
                code=INVALID_FIELD_VALUE,
                human="A job in this cycle must carry an application deadline",
                path="application_deadline",
            )
        )
    if (
        application_deadline is not None
        and offer_acceptance_deadline is not None
        and offer_acceptance_deadline <= application_deadline
    ):
        reasons.append(
            Reason(
                code=INVALID_FIELD_VALUE,
                human=(
                    "The offer-acceptance deadline must fall after the "
                    "application deadline"
                ),
                path="offer_acceptance_deadline",
            )
        )
    return reasons


def _company_reasons(is_active: bool | None) -> list[Reason]:
    if is_active is None:
        return [
            Reason(
                code=COMPANY_NOT_FOUND,
                human="The company does not exist",
                path="company_id",
            )
        ]
    if not is_active:
        return [
            Reason(
                code=COMPANY_INACTIVE,
                human="A deactivated company cannot carry new jobs",
                path="company_id",
            )
        ]
    return []


def _taxonomy_reasons(
    *, unknown_sector: bool, unknown_programs: tuple[UUID, ...]
) -> list[Reason]:
    reasons: list[Reason] = []
    if unknown_sector:
        reasons.append(
            Reason(
                code=UNKNOWN_TAXONOMY_VALUE,
                human="The sector is not an active taxonomy entry",
                path="sector_id",
            )
        )
    reasons.extend(
        Reason(
            code=UNKNOWN_TAXONOMY_VALUE,
            human=f"Program {program_id} is not an active taxonomy entry",
            path="program_ctc",
        )
        for program_id in unknown_programs
    )
    return reasons


def _program_ctc_ops(
    job_id: UUID, rows: list[ProgramCtcRow], existing: dict[UUID, Decimal]
) -> list[StateOp]:
    """Replace the per-program CTC set wholesale; it is a small edited table."""
    operations: list[StateOp] = []
    wanted = {row.program_id: row.ctc_lpa for row in rows}
    for program_id in existing:
        if program_id not in wanted:
            operations.append(
                StateOp(
                    op="delete",
                    model="job_program_ctc",
                    values={},
                    where={"job_id": job_id, "program_id": program_id},
                )
            )
    for program_id, ctc in wanted.items():
        if program_id not in existing:
            operations.append(
                StateOp(
                    op="insert",
                    model="job_program_ctc",
                    values={
                        "id": uuid4(),
                        "job_id": job_id,
                        "program_id": program_id,
                        "ctc_lpa": ctc,
                    },
                )
            )
        elif existing[program_id] != ctc:
            operations.append(
                StateOp(
                    op="update",
                    model="job_program_ctc",
                    values={"ctc_lpa": ctc},
                    where={"job_id": job_id, "program_id": program_id},
                )
            )
    return operations


def _decide_create_job(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Create a job with its outcome fixed for life (Behavior JOB-1, JOB-2)."""
    if not isinstance(input_value, CreateJobInput) or not isinstance(
        state, JobCreateState
    ):
        raise TypeError("Invalid create_job decision input")
    if state.cycle is None:
        return Rejection(
            reasons=[Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")]
        )

    reasons = _company_reasons(state.company_is_active)
    reasons.extend(
        _taxonomy_reasons(
            unknown_sector=state.unknown_sector,
            unknown_programs=state.unknown_programs,
        )
    )
    outcome = resolve_outcome(state.cycle, input_value.outcome)
    if isinstance(outcome, Reason):
        reasons.append(outcome)
    reasons.extend(
        deadline_reasons(
            state.cycle,
            application_deadline=input_value.application_deadline,
            offer_acceptance_deadline=input_value.offer_acceptance_deadline,
        )
    )
    if reasons:
        return Rejection(reasons=reasons)
    assert isinstance(outcome, Outcome)

    job = JobRow(
        id=state.job_id,
        cycle_id=input_value.cycle_id,
        company_id=input_value.company_id,
        outcome=outcome,
        title=input_value.title,
        description=input_value.description,
        location=input_value.location,
        sector_id=input_value.sector_id,
        ctc_lpa=input_value.ctc_lpa,
        ctc_breakdown=input_value.ctc_breakdown,
        stipend_month=input_value.stipend_month,
        application_deadline=input_value.application_deadline,
        offer_acceptance_deadline=input_value.offer_acceptance_deadline,
        is_published=False,
        published_at=None,
        cancelled_at=None,
        eligibility_rule=None,
        eligibility_summary=None,
    )
    return Plan(
        state_ops=[
            StateOp(
                op="insert",
                model="jobs",
                values={
                    "id": job.id,
                    "cycle_id": job.cycle_id,
                    "company_id": job.company_id,
                    "outcome": job.outcome.value,
                    "title": job.title,
                    "description": job.description,
                    "location": job.location,
                    "sector_id": job.sector_id,
                    "ctc_lpa": job.ctc_lpa,
                    "ctc_breakdown": job.ctc_breakdown,
                    "stipend_month": job.stipend_month,
                    "application_deadline": job.application_deadline,
                    "offer_acceptance_deadline": job.offer_acceptance_deadline,
                    "is_published": False,
                },
            ),
            *_program_ctc_ops(job.id, input_value.program_ctc, {}),
        ],
        events=[],
        deferred=[],
        audit={
            "subject_type": "job",
            "subject_id": job.id,
            "details": {"before": None, "after": job.snapshot()},
        },
        summary={
            "cycle_id": str(job.cycle_id),
            "job_id": str(job.id),
            "outcome": job.outcome.value,
            "title": job.title,
            "is_published": False,
            "changed": True,
            "notified_applicants": 0,
        },
    )


def _decide_update_job_basics(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Edit copy, compensation, and deadlines (Behavior JOB-2, JOB-3).

    A deadline move notifies whoever is still in flight, including a move into
    the past: JOB-3 permits shortening and expects it to close applying at
    once, so the notification is the warning students get.
    """
    if not isinstance(input_value, UpdateJobBasicsInput) or not isinstance(
        state, JobState
    ):
        raise TypeError("Invalid update_job_basics decision input")
    if state.cycle is None:
        return Rejection(
            reasons=[Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")]
        )
    if state.job is None:
        return job_not_found()
    before = state.job
    provided = input_value.model_fields_set

    reasons: list[Reason] = []
    if before.cancelled_at is not None:
        reasons.append(job_cancelled_reason())
    if (
        "outcome" in provided
        and input_value.outcome is not None
        and input_value.outcome is not before.outcome
    ):
        reasons.append(
            Reason(
                code=FIELD_NOT_EDITABLE,
                human=(
                    "A job's outcome decides which gates and cascades apply to "
                    "it and cannot be changed after creation"
                ),
                path="outcome",
            )
        )
    if "company_id" in provided and input_value.company_id is not None:
        reasons.extend(_company_reasons(state.company_is_active))
    reasons.extend(
        _taxonomy_reasons(
            unknown_sector=state.unknown_sector,
            unknown_programs=state.unknown_programs,
        )
    )

    def field[T](key: str, current: T) -> T:
        return getattr(input_value, key) if key in provided else current

    after = JobRow(
        id=before.id,
        cycle_id=before.cycle_id,
        company_id=field("company_id", before.company_id) or before.company_id,
        outcome=before.outcome,
        title=input_value.title if "title" in provided and input_value.title else before.title,
        description=(
            input_value.description
            if "description" in provided and input_value.description is not None
            else before.description
        ),
        location=field("location", before.location),
        sector_id=field("sector_id", before.sector_id),
        ctc_lpa=field("ctc_lpa", before.ctc_lpa),
        ctc_breakdown=field("ctc_breakdown", before.ctc_breakdown),
        stipend_month=field("stipend_month", before.stipend_month),
        application_deadline=field("application_deadline", before.application_deadline),
        offer_acceptance_deadline=field(
            "offer_acceptance_deadline", before.offer_acceptance_deadline
        ),
        is_published=before.is_published,
        published_at=before.published_at,
        cancelled_at=before.cancelled_at,
        eligibility_rule=before.eligibility_rule,
        eligibility_summary=before.eligibility_summary,
    )
    reasons.extend(
        deadline_reasons(
            state.cycle,
            application_deadline=after.application_deadline,
            offer_acceptance_deadline=after.offer_acceptance_deadline,
        )
    )
    if reasons:
        return Rejection(reasons=reasons)

    ctc_ops = (
        _program_ctc_ops(before.id, input_value.program_ctc, state.program_ctc)
        if input_value.program_ctc is not None
        else []
    )
    changed = after != before or bool(ctc_ops)
    deadline_moved = (
        after.application_deadline != before.application_deadline
        or after.offer_acceptance_deadline != before.offer_acceptance_deadline
    )
    acceptance_deadline_moved = (
        after.offer_acceptance_deadline != before.offer_acceptance_deadline
    )
    notifications: list[Deferred] = []
    if deadline_moved:
        notifications = [
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": "deadline_changed",
                    "recipient": applicant.email,
                    "context": {
                        "student": applicant.full_name,
                        "job": after.title,
                        "job_id": str(after.id),
                        "cycle_id": str(after.cycle_id),
                        "application_deadline": format_deadline(
                            after.application_deadline
                        ),
                        "offer_acceptance_deadline": format_deadline(
                            after.offer_acceptance_deadline
                        ),
                        "shortened": (
                            before.application_deadline is not None
                            and after.application_deadline is not None
                            and after.application_deadline < before.application_deadline
                        ),
                    },
                },
            )
            for applicant in state.applicants
        ]

    offer_operations: list[StateOp] = []
    expiry_tasks: list[Deferred] = []
    if acceptance_deadline_moved:
        for offer in state.open_offers:
            offer_operations.append(
                StateOp(
                    op="update",
                    model="offers",
                    values={"deadline_at": after.offer_acceptance_deadline},
                    where={"id": offer.offer_id},
                )
            )
            if after.offer_acceptance_deadline is not None:
                expiry_tasks.append(
                    Deferred(
                        task="enforce_offer_expiry",
                        args={
                            "offer_id": str(offer.offer_id),
                            "scheduled_deadline": (
                                after.offer_acceptance_deadline.isoformat()
                            ),
                        },
                        schedule_at=after.offer_acceptance_deadline,
                    )
                )

    return Plan(
        state_ops=(
            [
                StateOp(
                    op="update",
                    model="jobs",
                    values={column: getattr(after, column) for column in BASICS_COLUMNS},
                    where={"id": before.id},
                )
            ]
            if after != before
            else []
        )
        + ctc_ops
        + offer_operations,
        events=[],
        deferred=notifications + expiry_tasks,
        audit={
            "subject_type": "job",
            "subject_id": before.id,
            "details": {
                "before": before.snapshot(),
                "after": after.snapshot(),
                "notified_applicants": len(notifications),
                "updated_offer_deadlines": len(offer_operations),
                "scheduled_offer_expiries": len(expiry_tasks),
            },
        },
        summary={
            "cycle_id": str(before.cycle_id),
            "job_id": str(before.id),
            "outcome": before.outcome.value,
            "title": after.title,
            "is_published": after.is_published,
            "changed": changed,
            "notified_applicants": len(notifications),
            "updated_offer_deadlines": len(offer_operations),
            "scheduled_offer_expiries": len(expiry_tasks),
        },
    )


def _decide_set_published(*, published: bool):  # noqa: ANN202 - closure factory
    def decide(
        input_value: BaseModel,
        state: object,
        _policy: object,
        _overrides: object,
        _actor: ActorContext,
    ) -> Plan | Rejection:
        """Toggle student visibility (Behavior JOB-2.5, JOB-4)."""
        if not isinstance(input_value, PublishJobInput) or not isinstance(
            state, JobState
        ):
            raise TypeError("Invalid publish decision input")
        if state.cycle is None:
            return Rejection(
                reasons=[Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")]
            )
        if state.job is None:
            return job_not_found()
        before = state.job
        if published and before.cancelled_at is not None:
            return Rejection(reasons=[job_cancelled_reason()])

        changed = before.is_published != published
        # published_at is the timestamp of the first publication (JOB-2.5); an
        # unpublish/republish cycle keeps it, so "when did students first see
        # this" survives a staff correction.
        published_at = before.published_at or (state.now if published else None)
        return Plan(
            state_ops=(
                [
                    StateOp(
                        op="update",
                        model="jobs",
                        values={
                            "is_published": published,
                            "published_at": published_at,
                        },
                        where={"id": before.id},
                    )
                ]
                if changed
                else []
            ),
            events=[],
            deferred=[],
            audit={
                "subject_type": "job",
                "subject_id": before.id,
                "details": {
                    "is_published": published,
                    "published_at": _iso(published_at),
                    "changed": changed,
                },
            },
            summary={
                "cycle_id": str(before.cycle_id),
                "job_id": str(before.id),
                "outcome": before.outcome.value,
                "title": before.title,
                "is_published": published,
                "changed": changed,
                "notified_applicants": 0,
            },
        )

    return decide


def register_job_commands(registry: Registry) -> None:
    registry.command(
        name="create_job",
        input_model=CreateJobInput,
        output_model=JobSummary,
        actor="staff",
        scope="cycle",
        loader=_load_create,
        rule_domains=(),
        spec_ids=("JOB-1", "JOB-2", "JOB-6"),
    )(_decide_create_job)
    registry.command(
        name="update_job_basics",
        input_model=UpdateJobBasicsInput,
        output_model=JobSummary,
        actor="staff",
        scope="cycle",
        loader=_load_basics,
        rule_domains=(),
        spec_ids=("JOB-2", "JOB-3", "JOB-6"),
    )(_decide_update_job_basics)
    registry.command(
        name="publish_job",
        input_model=PublishJobInput,
        output_model=JobSummary,
        actor="staff",
        scope="cycle",
        loader=_load_publish,
        rule_domains=(),
        spec_ids=("JOB-2", "JOB-4"),
    )(_decide_set_published(published=True))
    registry.command(
        name="unpublish_job",
        input_model=PublishJobInput,
        output_model=JobSummary,
        actor="staff",
        scope="cycle",
        loader=_load_publish,
        rule_domains=(),
        spec_ids=("JOB-2", "JOB-4", "JOB-6"),
    )(_decide_set_published(published=False))
