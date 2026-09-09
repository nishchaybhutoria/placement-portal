"""Job cancellation and the export preset (Behavior JOB-5, ANA).

Cancelling reaches every application still in flight, so it runs through the
RND-2 bulk contract: chunked, replayable under one batch key, one result row
per application.  The rows here are the applications themselves rather than a
staff-supplied list -- a cancellation is "everyone", and asking staff to paste
the roster would let one be missed.

Two things it deliberately does not touch.  An ``accepted`` application is left
alone (JOB-5): a student holding an accepted offer has made plans, and unwinding
that is ``terminate_offer``'s job with its own restore choices, so the preview
names them with that pointer instead.  And the job's rounds, questions, and
eligibility rule stay exactly as they were, because a cancelled job is still a
record of what happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.core.errors import (
    CYCLE_NOT_FOUND,
    DUPLICATE_ROW,
    INVALID_TRANSITION,
    UNKNOWN_EXPORT_COLUMN,
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
from app.domain.shared import ApplicationStatus, EventType
from app.domain.transitions import TransitionActor, TransitionContext, decide_transition
from app.modules.analytics.columns import application_registry, unknown_columns
from app.modules.cycles.commands import CycleRow, fetch_cycle
from app.modules.jobs.commands import JobRow, fetch_job, job_not_found

CANCELLATION_REASON = "job_cancelled"
# JOB-5 moves every non-terminal application to rejected; accepted is excluded
# by APP-4's cancel_job row and reported separately.
CANCELLABLE_STATUSES = (
    ApplicationStatus.IN_PROGRESS,
    ApplicationStatus.PENDING_OFFER,
    ApplicationStatus.OFFERED,
)


class CancelJobInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    job_id: UUID
    rows: list[dict[str, str]]
    batch_key: str
    reason: str = "The job was cancelled"

    @field_validator("rows")
    @classmethod
    def validate_rows(cls, value: list[dict[str, str]]) -> list[dict[str, str]]:
        for row in value:
            if set(row) != {"application_id"}:
                raise ValueError("each row names one application_id")
        return value

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("a cancellation reason is required")
        return stripped


class CancelJobSummary(BaseModel):
    rows: list[dict[str, object]]


class SaveExportPresetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    job_id: UUID
    columns: list[str]

    @field_validator("columns")
    @classmethod
    def validate_columns(cls, value: list[str]) -> list[str]:
        cleaned = [" ".join(column.split()) for column in value]
        cleaned = [column for column in cleaned if column]
        if not cleaned:
            raise ValueError("an export preset needs at least one column")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("an export preset's columns must be distinct")
        return cleaned


class ExportPresetSummary(BaseModel):
    cycle_id: UUID
    job_id: UUID
    columns: list[str]
    changed: bool


@dataclass(frozen=True, slots=True)
class CancelApplicationRow:
    application_id: UUID
    enrollment_id: UUID
    status: ApplicationStatus
    current_round_id: UUID | None
    email: str
    full_name: str
    open_offer_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class CancelJobState:
    scope_ids: ScopeIds
    cycle_archived: bool
    now: datetime
    cycle: CycleRow | None
    job: JobRow | None
    applications: tuple[CancelApplicationRow, ...]


@dataclass(frozen=True, slots=True)
class ExportPresetState:
    scope_ids: ScopeIds
    cycle_archived: bool
    cycle_exists: bool
    job: JobRow | None
    preset_id: UUID
    existing_columns: list[str] | None
    #: The job's questions, so the preset can be checked against the ANA-4
    #: column registry at save time rather than at download time.
    questions: tuple[tuple[UUID, str], ...] = ()


_APPLICATION_SELECT = """
    SELECT
        a.id, a.enrollment_id, a.status, a.current_round_id,
        u.email, u.full_name,
        coalesce(
            (
                SELECT array_agg(o.id)
                FROM offers o
                WHERE o.application_id = a.id
                  AND o.responded_at IS NULL
                  AND o.terminated_at IS NULL
            ),
            '{}'
        ) AS open_offer_ids
    FROM applications a
    JOIN enrollments e ON e.id = a.enrollment_id
    JOIN users u ON u.id = e.user_id
    WHERE a.job_id = :job_id
"""


async def _load_cancel(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> CancelJobState:
    if not isinstance(input_value, CancelJobInput):
        raise TypeError("cancel_job requires CancelJobInput")
    cycle = await fetch_cycle(tx, input_value.cycle_id, lock=lock)
    job = await fetch_job(
        tx, cycle_id=input_value.cycle_id, job_id=input_value.job_id, lock=lock
    )
    application_ids = [UUID(row["application_id"]) for row in input_value.rows]
    if lock:
        # Offer acceptance takes in-cycle offer rows before cascade-target
        # applications.  Cancellation touches the same pair, so it follows the
        # same offer → application order rather than creating an AB/BA deadlock.
        await tx.execute(
            sa.text(
                "SELECT o.id FROM offers o JOIN applications a "
                "ON a.id = o.application_id "
                "WHERE a.job_id = :job_id AND a.id = ANY(:ids) "
                "ORDER BY o.id FOR UPDATE OF o"
            ),
            {"job_id": input_value.job_id, "ids": application_ids},
        )
    rows = (
        await tx.execute(
            sa.text(
                _APPLICATION_SELECT
                + " AND a.id = ANY(:ids)"
                + (" FOR UPDATE OF a" if lock else "")
            ),
            {
                "job_id": input_value.job_id,
                "ids": application_ids,
            },
        )
    ).mappings().all()
    return CancelJobState(
        scope_ids=ScopeIds(cycle_id=input_value.cycle_id, job_id=input_value.job_id),
        cycle_archived=cycle is not None and cycle.archived_at is not None,
        now=await tx.scalar(sa.select(sa.func.now())),  # type: ignore[arg-type]
        cycle=cycle,
        job=job,
        applications=tuple(
            CancelApplicationRow(
                application_id=row["id"],
                enrollment_id=row["enrollment_id"],
                status=ApplicationStatus(row["status"]),
                current_round_id=row["current_round_id"],
                email=str(row["email"]),
                full_name=str(row["full_name"]),
                open_offer_ids=tuple(row["open_offer_ids"]),
            )
            for row in rows
        ),
    )


async def cancellation_targets(
    connection: AsyncConnection | AsyncSession, job_id: UUID
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """The JOB-5 preview: what cancelling moves, and what it leaves behind."""
    rows = (
        await connection.execute(sa.text(_APPLICATION_SELECT), {"job_id": job_id})
    ).mappings().all()
    targets: list[dict[str, object]] = []
    untouched: list[dict[str, object]] = []
    for row in rows:
        status = ApplicationStatus(row["status"])
        entry: dict[str, object] = {
            "application_id": str(row["id"]),
            "full_name": str(row["full_name"]),
            "status": status.value,
            "open_offers": len(row["open_offer_ids"]),
        }
        if status in CANCELLABLE_STATUSES:
            targets.append(entry)
        elif status is ApplicationStatus.ACCEPTED:
            untouched.append(entry | {"suggested_command": "terminate_offer"})
    return targets, untouched


def _decide_cancel_job(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """Reject every in-flight application and revoke its open offer (JOB-5)."""
    if not isinstance(input_value, CancelJobInput) or not isinstance(
        state, CancelJobState
    ):
        raise TypeError("Invalid cancel_job decision input")
    if state.cycle is None:
        return Rejection(
            reasons=[Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")]
        )
    if state.job is None:
        return job_not_found()

    by_id = {row.application_id: row for row in state.applications}
    context = TransitionContext(cycle_kind=state.cycle.kind)
    results: list[dict[str, object]] = []
    operations: list[StateOp] = []
    events: list[Event] = []
    deferred: list[Deferred] = []
    seen: set[UUID] = set()

    for row in input_value.rows:
        application_id = UUID(row["application_id"])
        application = by_id.get(application_id)
        if application is None:
            results.append(
                {
                    "application_id": str(application_id),
                    "status": "error",
                    "reason": UNMATCHED_IDENTIFIER,
                }
            )
            continue
        if application_id in seen:
            results.append(
                {
                    "application_id": str(application_id),
                    "status": "skipped",
                    "reason": DUPLICATE_ROW,
                }
            )
            continue
        transition = decide_transition(
            "cancel_job",
            from_status=application.status,
            to_status=ApplicationStatus.REJECTED,
            actor=TransitionActor.STAFF,
            context=context,
            reason=input_value.reason,
        )
        if isinstance(transition, Rejection):
            # An accepted application lands here, which is exactly JOB-5's rule
            # that cancellation must not touch it.
            results.append(
                {
                    "application_id": str(application_id),
                    "status": "skipped",
                    "reason": INVALID_TRANSITION,
                    "suggested_command": (
                        "terminate_offer"
                        if application.status is ApplicationStatus.ACCEPTED
                        else None
                    ),
                }
            )
            continue

        seen.add(application_id)
        operations.append(
            StateOp(
                op="update",
                model="applications",
                values={"status": ApplicationStatus.REJECTED.value},
                where={"id": application_id},
            )
        )
        # An unresponded offer on a rejected application would sit there for
        # the expiry job to trip over, so cancelling revokes it (JOB-5).
        operations.extend(
            StateOp(
                op="update",
                model="offers",
                values={
                    "terminated_at": state.now,
                    "termination_kind": "company_revoked",
                    "termination_reason": CANCELLATION_REASON,
                },
                where={"id": offer_id},
            )
            for offer_id in application.open_offer_ids
        )
        events.append(
            Event(
                application_id=application_id,
                event_type=EventType.ELIMINATED,
                from_status=application.status.value,
                to_status=ApplicationStatus.REJECTED.value,
                from_round=application.current_round_id,
                to_round=None,
                reason=CANCELLATION_REASON,
                payload={
                    "job_id": str(state.job.id),
                    "detail": input_value.reason,
                    "terminated_offers": [
                        str(offer_id) for offer_id in application.open_offer_ids
                    ],
                },
            )
        )
        deferred.append(
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": "job_cancelled",
                    "recipient": application.email,
                    "context": {
                        "student": application.full_name,
                        "job": state.job.title,
                        "job_id": str(state.job.id),
                        "cycle": state.cycle.name,
                        "reason": input_value.reason,
                        "cycle_id": str(input_value.cycle_id),
                    },
                },
            )
        )
        results.append(
            {
                "application_id": str(application_id),
                "status": "applied",
                "reason": None,
                "from_status": application.status.value,
                "terminated_offers": len(application.open_offer_ids),
            }
        )

    # The job is flagged and hidden once, on the chunk that carries the flag;
    # replaying a later chunk must not resurrect a published job.
    if state.job.cancelled_at is None:
        operations.append(
            StateOp(
                op="update",
                model="jobs",
                values={
                    "cancelled_at": state.now,
                    "is_published": False,
                },
                where={"id": state.job.id},
            )
        )

    return Plan(
        state_ops=operations,
        events=events,
        deferred=deferred,
        audit=None,
        summary={"rows": results},
    )


async def _load_export_preset(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> ExportPresetState:
    if not isinstance(input_value, SaveExportPresetInput):
        raise TypeError("save_export_preset requires SaveExportPresetInput")
    cycle = (
        await tx.execute(
            sa.text("SELECT archived_at FROM cycles WHERE id = :id"),
            {"id": input_value.cycle_id},
        )
    ).mappings().one_or_none()
    existing = (
        await tx.execute(
            sa.text(
                "SELECT id, columns FROM export_presets WHERE job_id = :job_id"
                + (" FOR UPDATE" if lock else "")
            ),
            {"job_id": input_value.job_id},
        )
    ).mappings().one_or_none()
    question_rows = (
        await tx.execute(
            sa.text(
                "SELECT id, text FROM job_questions WHERE job_id = :job_id ORDER BY ord"
            ),
            {"job_id": input_value.job_id},
        )
    ).mappings().all()
    return ExportPresetState(
        scope_ids=ScopeIds(cycle_id=input_value.cycle_id, job_id=input_value.job_id),
        cycle_archived=cycle is not None and cycle["archived_at"] is not None,
        cycle_exists=cycle is not None,
        job=await fetch_job(
            tx, cycle_id=input_value.cycle_id, job_id=input_value.job_id, lock=lock
        ),
        preset_id=existing["id"] if existing is not None else uuid4(),
        existing_columns=(
            [str(column) for column in existing["columns"]]
            if existing is not None
            else None
        ),
        questions=tuple(
            (UUID(str(row["id"])), str(row["text"])) for row in question_rows
        ),
    )


def _decide_save_export_preset(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Remember which columns this job's board exports (LLD section 10)."""
    if not isinstance(input_value, SaveExportPresetInput) or not isinstance(
        state, ExportPresetState
    ):
        raise TypeError("Invalid save_export_preset decision input")
    if not state.cycle_exists:
        return Rejection(
            reasons=[Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")]
        )
    if state.job is None:
        return job_not_found()

    # M15: a preset is validated against the ANA-4 column registry here, where
    # the person choosing can be told which name is wrong. Before the registry
    # existed this command accepted any string, so a preset naming a deleted
    # question failed at download time instead -- on a screen with no way to
    # explain it (the design review 4.30n).
    unknown = unknown_columns(
        tuple(input_value.columns), application_registry(state.questions)
    )
    if unknown:
        return Rejection(
            reasons=[
                Reason(
                    code=UNKNOWN_EXPORT_COLUMN,
                    human=f"{name} is not a column of this job's export",
                    path=f"columns.{index}",
                )
                for index, name in enumerate(unknown)
            ]
        )

    columns: list[object] = list(input_value.columns)
    changed = state.existing_columns != input_value.columns
    operation = (
        StateOp(
            op="insert",
            model="export_presets",
            values={
                "id": state.preset_id,
                "job_id": state.job.id,
                "columns": columns,
            },
        )
        if state.existing_columns is None
        else StateOp(
            op="update",
            model="export_presets",
            values={"columns": columns},
            where={"id": state.preset_id},
        )
    )
    return Plan(
        state_ops=[operation] if changed else [],
        events=[],
        deferred=[],
        audit={
            "subject_type": "job",
            "subject_id": state.job.id,
            "details": {
                "before": state.existing_columns,
                "after": input_value.columns,
            },
        },
        summary={
            "cycle_id": str(state.job.cycle_id),
            "job_id": str(state.job.id),
            "columns": input_value.columns,
            "changed": changed,
        },
    )


def register_job_cancellation_commands(registry: Registry) -> None:
    registry.command(
        name="cancel_job",
        input_model=CancelJobInput,
        output_model=CancelJobSummary,
        actor="staff",
        scope="cycle",
        loader=_load_cancel,
        rule_domains=(),
        spec_ids=("JOB-5", "APP-4"),
        execution_mode="bulk",
    )(_decide_cancel_job)
    registry.command(
        name="save_export_preset",
        input_model=SaveExportPresetInput,
        output_model=ExportPresetSummary,
        actor="staff",
        scope="cycle",
        loader=_load_export_preset,
        rule_domains=(),
        spec_ids=("ANA-3",),
    )(_decide_save_export_preset)
