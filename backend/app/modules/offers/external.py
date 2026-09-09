"""External offer lifecycle and dedicated-cycle attachment (EXT-1..4)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    APPLICATION_NOT_FOUND,
    COMPANY_INACTIVE,
    COMPANY_NOT_FOUND,
    CYCLE_NOT_FOUND,
    DUPLICATE_APPLICATION,
    DUPLICATE_ROW,
    FIELD_NOT_EDITABLE,
    INVALID_TRANSITION,
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
from app.domain.gates import (
    evaluate_acceptance_constraints,
    evaluate_offer_cap,
    evaluate_outcome_gate,
)
from app.domain.policy import resolve_policy
from app.domain.shared import (
    ApplicationStatus,
    CycleKind,
    EventType,
    ExternalSource,
    ExternalStatus,
    MembershipStatus,
    Outcome,
    RuleDomain,
)
from app.domain.transitions import EventHistoryItem, compute_restore_candidates
from app.modules.applications.verdict import gate_overrides
from app.modules.cycles.commands import CycleRow, fetch_cycle, fetch_policy
from app.modules.notifications.wording import humanise
from app.modules.offers.commands import _load_offer_applications
from app.modules.offers.derivations import OfferFacts, offer_facts
from app.modules.offers.locking import AcceptanceLockRequest, lock_acceptance_state
from app.modules.offers.planning import (
    OfferApplication,
    plan_acceptance_cascade,
    plan_extension,
)
from app.modules.offers.termination import (
    RestoreSelection,
    _candidate_payload,
    _duplicate_restore_target,
)
from app.modules.overrides.service import ApplicableOverride, applicable_many

_ZERO_CYCLE = UUID(int=0)


@dataclass(frozen=True, slots=True)
class EnrollmentRow:
    id: UUID
    email: str
    full_name: str
    roll_number: str | None


@dataclass(frozen=True, slots=True)
class ExternalOfferRow:
    id: UUID
    enrollment_id: UUID
    email: str
    full_name: str
    roll_number: str | None
    company_id: UUID
    company_name: str
    outcome: Outcome
    source: ExternalSource
    ctc_lpa: Decimal | None
    stipend_month: Decimal | None
    status: ExternalStatus
    offered_on: date | None
    responded_on: date | None
    source_application_id: UUID | None
    attached_cycle_id: UUID | None
    attached_cycle_name: str | None
    attached_cycle_kind: CycleKind | None
    notes: str | None
    created_by: UUID


@dataclass(frozen=True, slots=True)
class ExternalMutationState:
    scope_ids: ScopeIds
    now: datetime
    target: ExternalOfferRow | None
    enrollment: EnrollmentRow | None
    company_exists: bool
    company_active: bool
    company_name: str | None
    source_application_valid: bool
    external_count: int
    applications: tuple[OfferApplication, ...]
    history: tuple[EventHistoryItem, ...]
    facts: OfferFacts | None
    max_accepted_offers: int | None


class ExternalOfferFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: UUID
    outcome: Outcome
    source: ExternalSource
    ctc_lpa: Decimal | None = Field(default=None, ge=0)
    stipend_month: Decimal | None = Field(default=None, ge=0)
    status: ExternalStatus = ExternalStatus.OFFERED
    offered_on: date | None = None
    responded_on: date | None = None
    source_application_id: UUID | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def compensation_matches_outcome(self) -> ExternalOfferFields:
        if self.outcome is Outcome.PLACEMENT and self.stipend_month is not None:
            raise ValueError("placement external offers use ctc_lpa, not stipend_month")
        if self.outcome is Outcome.INTERNSHIP and self.ctc_lpa is not None:
            raise ValueError("internship external offers use stipend_month, not ctc_lpa")
        return self


class CreateExternalOfferInput(ExternalOfferFields):
    enrollment_id: UUID
    reason: str
    notify: bool = True

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("an intervention reason is required")
        return value.strip()


class UpdateExternalOfferInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_offer_id: UUID
    expected_status: ExternalStatus
    company_id: UUID | None = None
    outcome: Outcome | None = None
    source: ExternalSource | None = None
    ctc_lpa: Decimal | None = Field(default=None, ge=0)
    stipend_month: Decimal | None = Field(default=None, ge=0)
    clear_ctc_lpa: bool = False
    clear_stipend_month: bool = False
    status: ExternalStatus | None = None
    offered_on: date | None = None
    responded_on: date | None = None
    clear_offered_on: bool = False
    clear_responded_on: bool = False
    source_application_id: UUID | None = None
    clear_source_application: bool = False
    notes: str | None = None
    clear_notes: bool = False
    restore: list[RestoreSelection] = []
    reason: str
    notify: bool = True

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("an intervention reason is required")
        return value.strip()

    @model_validator(mode="after")
    def choices_are_coherent(self) -> UpdateExternalOfferInput:
        ids = [row.application_id for row in self.restore]
        if len(ids) != len(set(ids)):
            raise ValueError("each restoration application may be selected only once")
        if self.ctc_lpa is not None and self.clear_ctc_lpa:
            raise ValueError("ctc_lpa cannot be set and cleared together")
        if self.stipend_month is not None and self.clear_stipend_month:
            raise ValueError("stipend_month cannot be set and cleared together")
        if self.offered_on is not None and self.clear_offered_on:
            raise ValueError("offered_on cannot be set and cleared together")
        if self.responded_on is not None and self.clear_responded_on:
            raise ValueError("responded_on cannot be set and cleared together")
        if self.source_application_id is not None and self.clear_source_application:
            raise ValueError("source_application_id cannot be set and cleared together")
        if self.notes is not None and self.clear_notes:
            raise ValueError("notes cannot be set and cleared together")
        return self


class DeleteExternalOfferInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_offer_id: UUID
    expected_status: ExternalStatus
    restore: list[RestoreSelection] = []
    reason: str
    notify: bool = True

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("an intervention reason is required")
        return value.strip()

    @model_validator(mode="after")
    def unique_restore_choices(self) -> DeleteExternalOfferInput:
        ids = [row.application_id for row in self.restore]
        if len(ids) != len(set(ids)):
            raise ValueError("each restoration application may be selected only once")
        return self


class ExternalOfferSummary(BaseModel):
    external_offer_id: UUID
    enrollment_id: UUID
    company_id: UUID
    outcome: Outcome
    status: ExternalStatus
    attached_cycle_id: UUID | None
    deleted: bool
    automatic_effects: list[dict[str, object]]
    cascade: list[dict[str, object]]
    restoration_candidates: list[dict[str, object]]
    restored: list[dict[str, object]]
    notify: bool


async def _now(tx: AsyncSession) -> datetime:
    return cast(datetime, await tx.scalar(sa.select(sa.func.now())))


async def _enrollment(tx: AsyncSession, enrollment_id: UUID) -> EnrollmentRow | None:
    row = (
        (
            await tx.execute(
                sa.text(
                    "SELECT e.id, u.email, u.full_name, e.roll_number "
                    "FROM enrollments e JOIN users u ON u.id = e.user_id "
                    "WHERE e.id = :id"
                ),
                {"id": enrollment_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return EnrollmentRow(
        id=cast(UUID, row["id"]),
        email=str(row["email"]),
        full_name=str(row["full_name"]),
        roll_number=str(row["roll_number"]) if row["roll_number"] else None,
    )


async def _external_offer(tx: AsyncSession, external_offer_id: UUID) -> ExternalOfferRow | None:
    row = (
        (
            await tx.execute(
                sa.text(
                    "SELECT eo.*, u.email, u.full_name, e.roll_number, "
                    "company.name AS company_name, c.name AS cycle_name, "
                    "c.kind AS cycle_kind "
                    "FROM external_offers eo "
                    "JOIN enrollments e ON e.id = eo.enrollment_id "
                    "JOIN users u ON u.id = e.user_id "
                    "JOIN companies company ON company.id = eo.company_id "
                    "LEFT JOIN cycles c ON c.id = eo.attached_cycle_id "
                    "WHERE eo.id = :id"
                ),
                {"id": external_offer_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return ExternalOfferRow(
        id=cast(UUID, row["id"]),
        enrollment_id=cast(UUID, row["enrollment_id"]),
        email=str(row["email"]),
        full_name=str(row["full_name"]),
        roll_number=str(row["roll_number"]) if row["roll_number"] else None,
        company_id=cast(UUID, row["company_id"]),
        company_name=str(row["company_name"]),
        outcome=Outcome(row["outcome"]),
        source=ExternalSource(row["source"]),
        ctc_lpa=row["ctc_lpa"],
        stipend_month=row["stipend_month"],
        status=ExternalStatus(row["status"]),
        offered_on=row["offered_on"],
        responded_on=row["responded_on"],
        source_application_id=cast("UUID | None", row["source_application_id"]),
        attached_cycle_id=cast("UUID | None", row["attached_cycle_id"]),
        attached_cycle_name=(str(row["cycle_name"]) if row["cycle_name"] else None),
        attached_cycle_kind=(
            CycleKind(row["cycle_kind"]) if row["cycle_kind"] is not None else None
        ),
        notes=str(row["notes"]) if row["notes"] is not None else None,
        created_by=cast(UUID, row["created_by"]),
    )


async def _history(tx: AsyncSession, enrollment_id: UUID) -> tuple[EventHistoryItem, ...]:
    rows = (
        (
            await tx.execute(
                sa.text(
                    "SELECT ev.event_seq, ev.application_id, ev.event_type, ev.from_status, "
                    "ev.to_status, ev.from_round_id, ev.to_round_id, ev.payload "
                    "FROM application_events ev JOIN applications a ON a.id = ev.application_id "
                    "WHERE a.enrollment_id = :id ORDER BY ev.event_seq"
                ),
                {"id": enrollment_id},
            )
        )
        .mappings()
        .all()
    )
    return tuple(
        EventHistoryItem(
            sequence=int(row["event_seq"]),
            application_id=cast(UUID, row["application_id"]),
            event_type=EventType(row["event_type"]),
            from_status=(
                ApplicationStatus(row["from_status"]) if row["from_status"] is not None else None
            ),
            to_status=(
                ApplicationStatus(row["to_status"]) if row["to_status"] is not None else None
            ),
            from_round_id=cast("UUID | None", row["from_round_id"]),
            to_round_id=cast("UUID | None", row["to_round_id"]),
            payload=dict(row["payload"] or {}),
        )
        for row in rows
    )


async def _company_state(
    tx: AsyncSession, company_id: UUID
) -> tuple[bool, bool, str | None]:
    """Existence, activity, and the name -- which the student is told."""
    row = (
        await tx.execute(
            sa.text("SELECT is_active, name FROM companies WHERE id = :id"),
            {"id": company_id},
        )
    ).mappings().one_or_none()
    if row is None:
        return False, False, None
    return True, bool(row["is_active"]), str(row["name"])


async def _source_valid(
    tx: AsyncSession, source_application_id: UUID | None, enrollment_id: UUID
) -> bool:
    if source_application_id is None:
        return True
    owner = await tx.scalar(
        sa.text("SELECT enrollment_id FROM applications WHERE id = :id"),
        {"id": source_application_id},
    )
    return owner == enrollment_id


def external_offer_id_for(enrollment_id: UUID, prior_count: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"cds:external-offer:{enrollment_id}:{prior_count}")


async def _load_create(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> ExternalMutationState:
    if not isinstance(input_value, CreateExternalOfferInput):
        raise TypeError("create_external_offer requires CreateExternalOfferInput")
    await lock_acceptance_state(
        tx,
        (
            AcceptanceLockRequest(
                enrollment_id=input_value.enrollment_id,
                cycle_id=None,
                application_id=None,
                outcome=input_value.outcome,
                cycle_kind=CycleKind.OPEN,
            ),
        ),
        lock=lock,
    )
    enrollment = await _enrollment(tx, input_value.enrollment_id)
    exists, active, company_name = await _company_state(tx, input_value.company_id)
    source_valid = await _source_valid(
        tx, input_value.source_application_id, input_value.enrollment_id
    )
    # Creation audits outlive deletions, so this sequence never reuses an ID.
    # Counting current rows would recycle the preview-stable UUID after delete
    # and make old cascade evidence appear causal to a later offer.
    count = int(
        await tx.scalar(
            sa.text(
                "SELECT count(*) FROM audit_log "
                "WHERE action = 'create_external_offer' AND subject_type = 'enrollment' "
                "AND subject_id = :id"
            ),
            {"id": input_value.enrollment_id},
        )
        or 0
    )
    applications = await _load_offer_applications(tx, enrollment_ids=(input_value.enrollment_id,))
    facts = await offer_facts(tx, input_value.enrollment_id, _ZERO_CYCLE)
    return ExternalMutationState(
        scope_ids=ScopeIds(
            enrollment_id=input_value.enrollment_id,
            application_id=input_value.source_application_id,
        ),
        now=await _now(tx),
        target=None,
        enrollment=enrollment,
        company_exists=exists,
        company_active=active,
        company_name=company_name,
        source_application_valid=source_valid,
        external_count=count,
        applications=applications,
        history=await _history(tx, input_value.enrollment_id),
        facts=facts,
        max_accepted_offers=None,
    )


async def _load_existing(
    tx: AsyncSession, external_offer_id: UUID, *, lock: bool
) -> ExternalMutationState:
    enrollment_id = cast(
        "UUID | None",
        await tx.scalar(
            sa.text("SELECT enrollment_id FROM external_offers WHERE id = :id"),
            {"id": external_offer_id},
        ),
    )
    if enrollment_id is not None:
        await lock_acceptance_state(
            tx,
            (
                AcceptanceLockRequest(
                    enrollment_id=enrollment_id,
                    cycle_id=None,
                    application_id=None,
                    outcome=None,
                    cycle_kind=None,
                    external_offer_id=external_offer_id,
                ),
            ),
            lock=lock,
        )
    target = await _external_offer(tx, external_offer_id)
    if target is None:
        return ExternalMutationState(
            scope_ids=ScopeIds(),
            now=await _now(tx),
            target=None,
            enrollment=None,
            company_exists=False,
            company_active=False,
            company_name=None,
            source_application_valid=False,
            external_count=0,
            applications=(),
            history=(),
            facts=None,
            max_accepted_offers=None,
        )
    enrollment = await _enrollment(tx, target.enrollment_id)
    exists, active, company_name = await _company_state(tx, target.company_id)
    applications = await _load_offer_applications(tx, enrollment_ids=(target.enrollment_id,))
    fact_cycle = target.attached_cycle_id or _ZERO_CYCLE
    maximum: int | None = None
    if target.attached_cycle_id is not None and target.attached_cycle_kind is not None:
        maximum = resolve_policy(
            target.attached_cycle_kind,
            cycle_policy=await fetch_policy(tx, target.attached_cycle_id),
        ).max_accepted_offers.value
    return ExternalMutationState(
        scope_ids=ScopeIds(
            cycle_id=target.attached_cycle_id,
            enrollment_id=target.enrollment_id,
            application_id=target.source_application_id,
        ),
        now=await _now(tx),
        target=target,
        enrollment=enrollment,
        company_exists=exists,
        company_active=active,
        company_name=company_name,
        source_application_valid=await _source_valid(
            tx, target.source_application_id, target.enrollment_id
        ),
        external_count=0,
        applications=applications,
        history=await _history(tx, target.enrollment_id),
        facts=await offer_facts(tx, target.enrollment_id, fact_cycle),
        max_accepted_offers=maximum,
    )


async def _load_update(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> ExternalMutationState:
    if not isinstance(input_value, UpdateExternalOfferInput):
        raise TypeError("update_external_offer requires UpdateExternalOfferInput")
    state = await _load_existing(tx, input_value.external_offer_id, lock=lock)
    if state.target is None:
        return state
    company_id = input_value.company_id or state.target.company_id
    source_application_id = (
        None
        if input_value.clear_source_application
        else input_value.source_application_id or state.target.source_application_id
    )
    exists, active, company_name = (
        await _company_state(tx, company_id)
        if input_value.company_id is not None
        else (True, True, state.company_name)
    )
    return replace(
        state,
        company_exists=exists,
        company_active=active,
        company_name=company_name,
        source_application_valid=await _source_valid(
            tx, source_application_id, state.target.enrollment_id
        ),
    )


async def _load_delete(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> ExternalMutationState:
    if not isinstance(input_value, DeleteExternalOfferInput):
        raise TypeError("delete_external_offer requires DeleteExternalOfferInput")
    return await _load_existing(tx, input_value.external_offer_id, lock=lock)


def _not_found() -> Rejection:
    return Rejection(
        reasons=[
            Reason(
                code=INVALID_TRANSITION,
                human="The external offer does not exist",
                path="external_offer_id",
            )
        ]
    )


def _base_validation(
    *,
    enrollment: EnrollmentRow | None,
    company_exists: bool,
    company_active: bool,
    source_application_valid: bool,
) -> list[Reason]:
    reasons: list[Reason] = []
    if enrollment is None:
        reasons.append(
            Reason(
                code=APPLICATION_NOT_FOUND,
                human="The enrollment does not exist",
                path="enrollment_id",
            )
        )
    if not company_exists:
        reasons.append(
            Reason(code=COMPANY_NOT_FOUND, human="The company does not exist", path="company_id")
        )
    elif not company_active:
        reasons.append(
            Reason(code=COMPANY_INACTIVE, human="The company is inactive", path="company_id")
        )
    if not source_application_valid:
        reasons.append(
            Reason(
                code=APPLICATION_NOT_FOUND,
                human="The source application does not belong to this enrollment",
                path="source_application_id",
            )
        )
    return reasons


def _acceptance_subject(
    *,
    external_offer_id: UUID,
    enrollment: EnrollmentRow,
    company_name: str,
    outcome: Outcome,
    attached_cycle_id: UUID | None,
    attached_cycle_name: str | None,
    attached_cycle_kind: CycleKind | None,
) -> OfferApplication:
    return OfferApplication(
        application_id=external_offer_id,
        enrollment_id=enrollment.id,
        status=ApplicationStatus.OFFERED,
        current_round_id=None,
        job_id=external_offer_id,
        job_title=f"External {outcome.value} offer",
        company_name=company_name,
        cycle_id=attached_cycle_id or _ZERO_CYCLE,
        cycle_name=attached_cycle_name or "Unattached external offers",
        cycle_kind=attached_cycle_kind or CycleKind.OPEN,
        outcome=outcome,
        email=enrollment.email,
        full_name=enrollment.full_name,
        roll_number=enrollment.roll_number,
        current_offer_id=None,
        current_offer_deadline=None,
        current_offer_response=None,
        current_offer_terminated=False,
        offer_count=0,
    )


def _constraints(
    *,
    outcome: Outcome,
    cycle_kind: CycleKind,
    facts: OfferFacts,
    maximum: int | None,
    overrides: object,
) -> tuple[list[Reason], tuple[UUID, ...]]:
    decision = evaluate_acceptance_constraints(
        outcome=outcome,
        cycle_kind=cycle_kind,
        placement_placed_global=facts.placement_placed_global,
        internship_placed_in_cycle=facts.internship_placed_in_cycle,
        max_accepted_offers=maximum,
        cap_used=facts.cap_used,
        overrides=gate_overrides(cast("tuple[ApplicableOverride, ...]", overrides)),
    )
    return list(decision.failures), decision.applied_override_ids


def _outcome_constraints(
    *,
    outcome: Outcome,
    cycle_kind: CycleKind,
    facts: OfferFacts,
    overrides: object,
) -> tuple[list[Reason], tuple[UUID, ...]]:
    """The global placed-state gate for an offer that has no cycle cap."""
    decision = evaluate_outcome_gate(
        outcome=outcome,
        cycle_kind=cycle_kind,
        placement_placed_global=facts.placement_placed_global,
        internship_placed_in_cycle=facts.internship_placed_in_cycle,
        overrides=gate_overrides(cast("tuple[ApplicableOverride, ...]", overrides)),
    )
    return list(decision.failures), decision.applied_override_ids


def _external_event(
    *,
    application_id: UUID | None,
    event_type: EventType,
    external_offer_id: UUID,
    from_status: ExternalStatus | None,
    to_status: ExternalStatus | None,
    reason: str,
    outcome: Outcome,
    source: ExternalSource,
    applied_override_ids: tuple[UUID, ...],
) -> Event | None:
    if application_id is None:
        return None
    return Event(
        application_id=application_id,
        event_type=event_type,
        from_status=None,
        to_status=None,
        from_round=None,
        to_round=None,
        reason=reason,
        payload={
            "external_offer_id": str(external_offer_id),
            "from_external_status": from_status.value if from_status else None,
            "to_external_status": to_status.value if to_status else None,
            "outcome": outcome.value,
            "source": source.value,
            "applied_override_ids": [str(item) for item in applied_override_ids],
        },
    )


def _notification(
    *,
    event_key: str,
    row: ExternalOfferRow | OfferApplication,
    status: str,
    source: ExternalSource,
    outcome: Outcome,
) -> Deferred:
    return Deferred(
        task="deliver_notification",
        args={
            "event_key": event_key,
            "recipient": row.email,
            "context": {
                "student": row.full_name,
                "company": row.company_name,
                "status": humanise(status),
                # "Source: Off campus" is a label; "an external internship
                # offer" is mid-sentence, and the template decides the case.
                "source": humanise(source.value),
                "outcome": humanise(outcome.value).lower(),
                "cycle_id": (
                    str(row.attached_cycle_id)
                    if isinstance(row, ExternalOfferRow) and row.attached_cycle_id
                    else str(row.cycle_id)
                    if isinstance(row, OfferApplication) and row.cycle_id != _ZERO_CYCLE
                    else None
                ),
            },
        },
    )


def _summary(
    *,
    external_offer_id: UUID,
    enrollment_id: UUID,
    company_id: UUID,
    outcome: Outcome,
    status: ExternalStatus,
    attached_cycle_id: UUID | None,
    deleted: bool,
    automatic_effects: list[dict[str, object]],
    cascade: tuple[dict[str, object], ...] = (),
    candidates: list[dict[str, object]] | None = None,
    restored: list[dict[str, object]] | None = None,
    notify: bool,
) -> dict[str, object]:
    return {
        "external_offer_id": str(external_offer_id),
        "enrollment_id": str(enrollment_id),
        "company_id": str(company_id),
        "outcome": outcome.value,
        "status": status.value,
        "attached_cycle_id": str(attached_cycle_id) if attached_cycle_id else None,
        "deleted": deleted,
        "automatic_effects": automatic_effects,
        "cascade": list(cascade),
        "restoration_candidates": candidates or [],
        "restored": restored or [],
        "notify": notify,
    }


def _decide_create(
    input_value: BaseModel,
    state: object,
    _policy: object,
    overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    if not isinstance(input_value, CreateExternalOfferInput) or not isinstance(
        state, ExternalMutationState
    ):
        raise TypeError("Invalid create_external_offer decision input")
    reasons = _base_validation(
        enrollment=state.enrollment,
        company_exists=state.company_exists,
        company_active=state.company_active,
        source_application_valid=state.source_application_valid,
    )
    if reasons:
        return Rejection(reasons=reasons)
    assert state.enrollment is not None and state.facts is not None
    external_offer_id = external_offer_id_for(input_value.enrollment_id, state.external_count)
    # The student is told which company made the offer. This said "External
    # company" to everyone, in every envelope, because the loader read whether
    # the company existed and never its name.
    company_name = state.company_name or "an external company"
    subject = _acceptance_subject(
        external_offer_id=external_offer_id,
        enrollment=state.enrollment,
        company_name=company_name,
        outcome=input_value.outcome,
        attached_cycle_id=None,
        attached_cycle_name=None,
        attached_cycle_kind=None,
    )
    cascade = ()
    operations: list[StateOp] = [
        StateOp(
            op="insert",
            model="external_offers",
            values={
                "id": external_offer_id,
                "enrollment_id": input_value.enrollment_id,
                "company_id": input_value.company_id,
                "outcome": input_value.outcome.value,
                "source": input_value.source.value,
                "ctc_lpa": input_value.ctc_lpa,
                "stipend_month": input_value.stipend_month,
                "status": input_value.status.value,
                "offered_on": input_value.offered_on,
                "responded_on": input_value.responded_on,
                "source_application_id": input_value.source_application_id,
                "notes": input_value.notes,
                "created_by": actor.user_id,
            },
        )
    ]
    events: list[Event] = []
    deferred: list[Deferred] = []
    applied_override_ids: tuple[UUID, ...] = ()
    if input_value.status is ExternalStatus.ACCEPTED:
        failures, applied_override_ids = _outcome_constraints(
            outcome=input_value.outcome,
            cycle_kind=CycleKind.OPEN,
            facts=state.facts,
            overrides=overrides,
        )
        if failures:
            return Rejection(reasons=failures)
        acceptance = plan_acceptance_cascade(
            subject,
            state.applications,
            acceptance_id=external_offer_id,
            now=state.now,
        )
        operations.extend(acceptance.state_ops)
        events.extend(acceptance.events)
        deferred.extend(acceptance.deferred)
        cascade = acceptance.cascade
    event = _external_event(
        application_id=input_value.source_application_id,
        event_type=EventType.EXTERNAL_RECORDED,
        external_offer_id=external_offer_id,
        from_status=None,
        to_status=input_value.status,
        reason=input_value.reason,
        outcome=input_value.outcome,
        source=input_value.source,
        applied_override_ids=applied_override_ids,
    )
    if event is not None:
        events.insert(0, event)
    if input_value.notify:
        deferred.append(
            _notification(
                event_key="external_recorded",
                row=subject,
                status=input_value.status.value,
                source=input_value.source,
                outcome=input_value.outcome,
            )
        )
    return Plan(
        state_ops=operations,
        events=events,
        deferred=deferred,
        audit={
            "subject_type": "enrollment",
            "subject_id": input_value.enrollment_id,
            "details": {
                "operation": "create_external_offer",
                "external_offer_id": str(external_offer_id),
                "status": input_value.status.value,
                "reason": input_value.reason,
                "applied_override_ids": [
                    str(item) for item in applied_override_ids
                ],
            },
        },
        summary=_summary(
            external_offer_id=external_offer_id,
            enrollment_id=input_value.enrollment_id,
            company_id=input_value.company_id,
            outcome=input_value.outcome,
            status=input_value.status,
            attached_cycle_id=None,
            deleted=False,
            automatic_effects=[
                {"effect": "external_offer_recorded"},
                {
                    "effect": "placed_dimensions_rederived",
                    "applies": input_value.status is ExternalStatus.ACCEPTED,
                },
            ],
            cascade=cascade,
            notify=input_value.notify,
        ),
    )


@dataclass(slots=True)
class RestorationPlan:
    operations: list[StateOp]
    events: list[Event]
    deferred: list[Deferred]
    candidates: list[dict[str, object]]
    restored: list[dict[str, object]]


def _plan_restoration(
    *,
    acceptance_id: UUID,
    history: tuple[EventHistoryItem, ...],
    applications: tuple[OfferApplication, ...],
    selections: list[RestoreSelection],
    now: datetime,
    reason: str,
    notify: bool,
) -> RestorationPlan | Rejection:
    candidates = compute_restore_candidates(
        acceptance_offer_id=acceptance_id,
        history=history,
        current_statuses={row.application_id: row.status for row in applications},
    )
    by_candidate = {row.application_id: row for row in candidates}
    by_application = {row.application_id: row for row in applications}
    selected = {row.application_id: row for row in selections}
    unavailable = sorted(set(selected) - set(by_candidate), key=lambda item: item.int)
    if unavailable:
        return Rejection(
            reasons=[
                Reason(
                    code=STALE_VIEW,
                    human="A selected restoration is stale; refresh the preview",
                    path=f"restore.{application_id}",
                )
                for application_id in unavailable
            ]
        )
    duplicate_by_id = {
        candidate.application_id: _duplicate_restore_target(
            candidate, by_application[candidate.application_id], applications
        )
        for candidate in candidates
    }
    blocked = [item for item in selected if duplicate_by_id[item]]
    if blocked:
        return Rejection(
            reasons=[
                Reason(
                    code=DUPLICATE_APPLICATION,
                    human="Another active application exists for this job",
                    path=f"restore.{application_id}",
                )
                for application_id in blocked
            ]
        )
    open_deadlines = [
        item.application_id
        for item in selections
        if item.deadline_at is not None
        and by_application[item.application_id].cycle_kind is CycleKind.OPEN
    ]
    if open_deadlines:
        return Rejection(
            reasons=[
                Reason(
                    code=INVALID_TRANSITION,
                    human="Open-cycle offers do not carry acceptance deadlines",
                    path=f"restore.{application_id}.deadline_at",
                )
                for application_id in open_deadlines
            ]
        )

    operations: list[StateOp] = []
    events: list[Event] = []
    deferred: list[Deferred] = []
    restored: list[dict[str, object]] = []
    for application_id in sorted(selected, key=lambda item: item.int):
        candidate = by_candidate[application_id]
        application = by_application[application_id]
        selection = selected[application_id]
        if candidate.requires_fresh_offer:
            offer_id, extension = plan_extension(
                application, now=now, deadline=selection.deadline_at, notify=notify
            )
            operations.extend(extension.state_ops)
            events.extend(extension.events)
            deferred.extend(extension.deferred)
            restored.append(
                {
                    "application_id": str(application_id),
                    "status": ApplicationStatus.OFFERED.value,
                    "target_round_id": (
                        str(candidate.restore_round_id) if candidate.restore_round_id else None
                    ),
                    "fresh_offer_id": str(offer_id),
                    "deadline_at": (
                        selection.deadline_at.isoformat() if selection.deadline_at else None
                    ),
                }
            )
        else:
            operations.append(
                StateOp(
                    op="update",
                    model="applications",
                    values={
                        "status": candidate.restore_status.value,
                        "current_round_id": candidate.restore_round_id,
                    },
                    where={"id": application_id},
                )
            )
            events.append(
                Event(
                    application_id=application_id,
                    event_type=EventType.REINSTATED,
                    from_status=candidate.current_status.value,
                    to_status=candidate.restore_status.value,
                    from_round=application.current_round_id,
                    to_round=candidate.restore_round_id,
                    reason=reason,
                    payload={
                        "trigger": "external_offer_restoration",
                        "external_offer_id": str(acceptance_id),
                    },
                )
            )
            restored.append(
                {
                    "application_id": str(application_id),
                    "status": candidate.restore_status.value,
                    "target_round_id": (
                        str(candidate.restore_round_id) if candidate.restore_round_id else None
                    ),
                    "fresh_offer_id": None,
                    "deadline_at": None,
                }
            )
    payloads = [
        _candidate_payload(
            candidate,
            by_application[candidate.application_id],
            selected=selected.get(candidate.application_id),
            duplicate_application=duplicate_by_id[candidate.application_id],
        )
        for candidate in candidates
    ]
    return RestorationPlan(operations, events, deferred, payloads, restored)


def _updated_values(
    input_value: UpdateExternalOfferInput, target: ExternalOfferRow
) -> tuple[dict[str, object], ExternalOfferRow] | Rejection:
    outcome = input_value.outcome or target.outcome
    ctc = (
        None
        if input_value.clear_ctc_lpa
        else (input_value.ctc_lpa if input_value.ctc_lpa is not None else target.ctc_lpa)
    )
    stipend = (
        None
        if input_value.clear_stipend_month
        else (
            input_value.stipend_month
            if input_value.stipend_month is not None
            else target.stipend_month
        )
    )
    if outcome is Outcome.PLACEMENT and stipend is not None:
        return Rejection(
            reasons=[
                Reason(
                    code=INVALID_TRANSITION,
                    human="Placement external offers use ctc_lpa, not stipend_month",
                    path="stipend_month",
                )
            ]
        )
    if outcome is Outcome.INTERNSHIP and ctc is not None:
        return Rejection(
            reasons=[
                Reason(
                    code=INVALID_TRANSITION,
                    human="Internship external offers use stipend_month, not ctc_lpa",
                    path="ctc_lpa",
                )
            ]
        )
    values: dict[str, object] = {
        "company_id": input_value.company_id or target.company_id,
        "outcome": outcome.value,
        "source": (input_value.source or target.source).value,
        "ctc_lpa": ctc,
        "stipend_month": stipend,
        "status": (input_value.status or target.status).value,
        "offered_on": (
            None
            if input_value.clear_offered_on
            else (
                input_value.offered_on if input_value.offered_on is not None else target.offered_on
            )
        ),
        "responded_on": (
            None
            if input_value.clear_responded_on
            else (
                input_value.responded_on
                if input_value.responded_on is not None
                else target.responded_on
            )
        ),
        "source_application_id": (
            None
            if input_value.clear_source_application
            else input_value.source_application_id or target.source_application_id
        ),
        "notes": (
            None
            if input_value.clear_notes
            else input_value.notes
            if input_value.notes is not None
            else target.notes
        ),
    }
    return values, replace(
        target,
        company_id=cast(UUID, values["company_id"]),
        outcome=outcome,
        source=ExternalSource(cast(str, values["source"])),
        ctc_lpa=cast("Decimal | None", values["ctc_lpa"]),
        stipend_month=cast("Decimal | None", values["stipend_month"]),
        status=ExternalStatus(cast(str, values["status"])),
        offered_on=cast("date | None", values["offered_on"]),
        responded_on=cast("date | None", values["responded_on"]),
        source_application_id=cast("UUID | None", values["source_application_id"]),
        notes=cast("str | None", values["notes"]),
    )


def _decide_update(
    input_value: BaseModel,
    state: object,
    _policy: object,
    overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    if not isinstance(input_value, UpdateExternalOfferInput) or not isinstance(
        state, ExternalMutationState
    ):
        raise TypeError("Invalid update_external_offer decision input")
    if state.target is None or state.enrollment is None or state.facts is None:
        return _not_found()
    target = state.target
    if target.status is not input_value.expected_status:
        return Rejection(
            reasons=[
                Reason(
                    code=STALE_VIEW,
                    human="The external offer status changed; refresh the record",
                    path="expected_status",
                )
            ]
        )
    if (
        target.status is ExternalStatus.ACCEPTED
        and input_value.outcome is not None
        and input_value.outcome is not target.outcome
    ):
        return Rejection(
            reasons=[
                Reason(
                    code=FIELD_NOT_EDITABLE,
                    human=(
                        "An accepted external offer's outcome cannot be changed in place. "
                        "Use the safe three-step path: move away from accepted with "
                        "restoration choices, edit outcome, then accept again."
                    ),
                    path="outcome",
                )
            ]
        )
    updated = _updated_values(input_value, target)
    if isinstance(updated, Rejection):
        return updated
    values, after = updated
    reasons = _base_validation(
        enrollment=state.enrollment,
        company_exists=state.company_exists,
        company_active=state.company_active,
        source_application_valid=state.source_application_valid,
    )
    if reasons:
        return Rejection(reasons=reasons)

    changing_outcome = after.outcome is not target.outcome
    moving_to_accepted = (
        target.status is not ExternalStatus.ACCEPTED and after.status is ExternalStatus.ACCEPTED
    )
    if changing_outcome and moving_to_accepted:
        return Rejection(
            reasons=[
                Reason(
                    code=INVALID_TRANSITION,
                    human=(
                        "Edit the outcome first, then accept it in a separate preview "
                        "so the acceptance cascade uses the reviewed outcome"
                    ),
                    path="outcome",
                )
            ]
        )
    if (
        changing_outcome
        and target.attached_cycle_kind is not None
        and after.outcome.value != target.attached_cycle_kind.value
    ):
        return Rejection(
            reasons=[
                Reason(
                    code=INVALID_TRANSITION,
                    human=("Detach the external offer before changing it to a different outcome"),
                    path="outcome",
                )
            ]
        )
    moving_from_accepted = (
        target.status is ExternalStatus.ACCEPTED and after.status is not ExternalStatus.ACCEPTED
    )
    operations: list[StateOp] = [
        StateOp(
            op="update",
            model="external_offers",
            values=values,
            where={"id": target.id},
        )
    ]
    events: list[Event] = []
    deferred: list[Deferred] = []
    cascade: tuple[dict[str, object], ...] = ()
    applied_override_ids: tuple[UUID, ...] = ()
    restoration = RestorationPlan([], [], [], [], [])
    if moving_to_accepted:
        if after.attached_cycle_id is None:
            failures, applied_override_ids = _outcome_constraints(
                outcome=after.outcome,
                cycle_kind=CycleKind.OPEN,
                facts=state.facts,
                overrides=overrides,
            )
        else:
            failures, applied_override_ids = _constraints(
                outcome=after.outcome,
                cycle_kind=after.attached_cycle_kind or CycleKind.OPEN,
                facts=state.facts,
                maximum=state.max_accepted_offers,
                overrides=overrides,
            )
        if failures:
            return Rejection(reasons=failures)
        acceptance = plan_acceptance_cascade(
            _acceptance_subject(
                external_offer_id=after.id,
                enrollment=state.enrollment,
                company_name=after.company_name,
                outcome=after.outcome,
                attached_cycle_id=after.attached_cycle_id,
                attached_cycle_name=after.attached_cycle_name,
                attached_cycle_kind=after.attached_cycle_kind,
            ),
            state.applications,
            acceptance_id=after.id,
            now=state.now,
        )
        operations.extend(acceptance.state_ops)
        events.extend(acceptance.events)
        deferred.extend(acceptance.deferred)
        cascade = acceptance.cascade
    elif moving_from_accepted:
        planned = _plan_restoration(
            acceptance_id=target.id,
            history=state.history,
            applications=state.applications,
            selections=input_value.restore,
            now=state.now,
            reason=input_value.reason,
            notify=input_value.notify,
        )
        if isinstance(planned, Rejection):
            return planned
        restoration = planned
        operations.extend(planned.operations)
        events.extend(planned.events)
        deferred.extend(planned.deferred)
    elif input_value.restore:
        return Rejection(
            reasons=[
                Reason(
                    code=INVALID_TRANSITION,
                    human="Restoration choices apply only when moving away from accepted",
                    path="restore",
                )
            ]
        )

    own_event = _external_event(
        application_id=after.source_application_id,
        event_type=EventType.EXTERNAL_UPDATED,
        external_offer_id=target.id,
        from_status=target.status,
        to_status=after.status,
        reason=input_value.reason,
        outcome=after.outcome,
        source=after.source,
        applied_override_ids=applied_override_ids,
    )
    if own_event is not None:
        events.insert(0, own_event)
    if input_value.notify:
        deferred.append(
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": "external_updated",
                    "recipient": target.email,
                    "context": {
                        "student": target.full_name,
                        "company": target.company_name,
                        "status": humanise(after.status.value),
                        "cycle_id": (
                            str(after.attached_cycle_id) if after.attached_cycle_id else None
                        ),
                    },
                },
            )
        )
    return Plan(
        state_ops=operations,
        events=events,
        deferred=deferred,
        audit={
            "subject_type": "enrollment",
            "subject_id": target.enrollment_id,
            "details": {
                "operation": "update_external_offer",
                "external_offer_id": str(target.id),
                "from_status": target.status.value,
                "to_status": after.status.value,
                "reason": input_value.reason,
                "applied_override_ids": [
                    str(item) for item in applied_override_ids
                ],
                "restored_application_ids": [
                    str(row.application_id) for row in input_value.restore
                ],
            },
        },
        summary=_summary(
            external_offer_id=target.id,
            enrollment_id=target.enrollment_id,
            company_id=after.company_id,
            outcome=after.outcome,
            status=after.status,
            attached_cycle_id=after.attached_cycle_id,
            deleted=False,
            automatic_effects=[
                {"effect": "external_offer_updated"},
                {
                    "effect": "placed_dimensions_rederived",
                    "applies": moving_to_accepted or moving_from_accepted,
                },
                {
                    "effect": "cycle_cap_recomputed",
                    "cycle_id": (str(after.attached_cycle_id) if after.attached_cycle_id else None),
                    "applies": moving_to_accepted or moving_from_accepted,
                },
            ],
            cascade=cascade,
            candidates=restoration.candidates,
            restored=restoration.restored,
            notify=input_value.notify,
        ),
    )


def _decide_delete(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    if not isinstance(input_value, DeleteExternalOfferInput) or not isinstance(
        state, ExternalMutationState
    ):
        raise TypeError("Invalid delete_external_offer decision input")
    if state.target is None:
        return _not_found()
    target = state.target
    if target.status is not input_value.expected_status:
        return Rejection(
            reasons=[
                Reason(
                    code=STALE_VIEW,
                    human="The external offer status changed",
                    path="expected_status",
                )
            ]
        )
    restoration = RestorationPlan([], [], [], [], [])
    if target.status is ExternalStatus.ACCEPTED:
        planned = _plan_restoration(
            acceptance_id=target.id,
            history=state.history,
            applications=state.applications,
            selections=input_value.restore,
            now=state.now,
            reason=input_value.reason,
            notify=input_value.notify,
        )
        if isinstance(planned, Rejection):
            return planned
        restoration = planned
    elif input_value.restore:
        return Rejection(
            reasons=[
                Reason(
                    code=INVALID_TRANSITION,
                    human="Only accepted offers have restoration choices",
                    path="restore",
                )
            ]
        )
    deferred = list(restoration.deferred)
    if input_value.notify:
        deferred.append(
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": "external_updated",
                    "recipient": target.email,
                    "context": {
                        "student": target.full_name,
                        "company": target.company_name,
                        "status": humanise("deleted"),
                        "cycle_id": (
                            str(target.attached_cycle_id) if target.attached_cycle_id else None
                        ),
                    },
                },
            )
        )
    return Plan(
        state_ops=[
            StateOp(op="delete", model="external_offers", values={}, where={"id": target.id}),
            *restoration.operations,
        ],
        events=restoration.events,
        deferred=deferred,
        audit={
            "subject_type": "enrollment",
            "subject_id": target.enrollment_id,
            "details": {
                "operation": "delete_external_offer",
                "external_offer_id": str(target.id),
                "status": target.status.value,
                "reason": input_value.reason,
                "restored_application_ids": [
                    str(row.application_id) for row in input_value.restore
                ],
            },
        },
        summary=_summary(
            external_offer_id=target.id,
            enrollment_id=target.enrollment_id,
            company_id=target.company_id,
            outcome=target.outcome,
            status=target.status,
            attached_cycle_id=target.attached_cycle_id,
            deleted=True,
            automatic_effects=[
                {"effect": "external_offer_deleted"},
                {
                    "effect": "placed_dimensions_rederived",
                    "applies": target.status is ExternalStatus.ACCEPTED,
                },
                {
                    "effect": "cycle_cap_released",
                    "cycle_id": str(target.attached_cycle_id) if target.attached_cycle_id else None,
                    "applies": target.status is ExternalStatus.ACCEPTED,
                },
            ],
            candidates=restoration.candidates,
            restored=restoration.restored,
            notify=input_value.notify,
        ),
    )


class AttachExternalOfferInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    external_offer_id: UUID
    expected_attached_cycle_id: UUID | None = None
    reason: str

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("an attachment reason is required")
        return value.strip()


class AttachRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_offer_id: UUID
    expected_attached_cycle_id: UUID | None = None


class AttachExternalOffersInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    rows: list[AttachRow]
    batch_key: str
    reason: str

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("an attachment reason is required")
        return value.strip()


class DetachExternalOfferInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    external_offer_id: UUID
    expected_attached_cycle_id: UUID
    reason: str

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a detachment reason is required")
        return value.strip()


class AttachmentSummary(BaseModel):
    external_offer_id: UUID
    enrollment_id: UUID
    attached_cycle_id: UUID | None
    status: ExternalStatus
    membership_auto_created: bool
    membership_left_in_place: bool
    applied_override_ids: list[UUID]


class BulkAttachmentSummary(BaseModel):
    rows: list[dict[str, object]]


@dataclass(frozen=True, slots=True)
class AttachmentState:
    scope_ids: ScopeIds
    cycle_archived: bool
    now: datetime
    cycle: CycleRow | None
    rows: dict[UUID, ExternalOfferRow]
    facts: dict[UUID, OfferFacts]
    memberships: dict[UUID, UUID]
    max_accepted_offers: int | None
    row_overrides: dict[UUID, tuple[ApplicableOverride, ...]]


async def _load_attachment_rows(
    tx: AsyncSession,
    *,
    cycle_id: UUID,
    external_offer_ids: tuple[UUID, ...],
    lock: bool,
    resolve_current_cycle: bool = False,
) -> AttachmentState:
    cycle = await fetch_cycle(tx, cycle_id, lock=False)
    prelim = (
        (
            await tx.execute(
                sa.text(
                    "SELECT id, enrollment_id, outcome FROM external_offers "
                    "WHERE id = ANY(:ids) ORDER BY id"
                ),
                {"ids": list(external_offer_ids)},
            )
        )
        .mappings()
        .all()
    )
    requests: list[AcceptanceLockRequest] = []
    for row in prelim:
        requests.append(
            AcceptanceLockRequest(
                enrollment_id=cast(UUID, row["enrollment_id"]),
                cycle_id=None if resolve_current_cycle else cycle_id,
                application_id=None,
                outcome=None if resolve_current_cycle else Outcome(row["outcome"]),
                cycle_kind=None
                if resolve_current_cycle
                else (CycleKind(cycle.kind) if cycle is not None else CycleKind.OPEN),
                external_offer_id=cast(UUID, row["id"]),
            )
        )
    await lock_acceptance_state(tx, tuple(requests), lock=lock)
    cycle = await fetch_cycle(tx, cycle_id, lock=False)
    rows: dict[UUID, ExternalOfferRow] = {}
    for external_offer_id in external_offer_ids:
        row = await _external_offer(tx, external_offer_id)
        if row is not None:
            rows[external_offer_id] = row
    enrollment_ids = tuple(
        sorted({row.enrollment_id for row in rows.values()}, key=lambda item: item.int)
    )
    facts = {
        enrollment_id: await offer_facts(tx, enrollment_id, cycle_id)
        for enrollment_id in enrollment_ids
    }
    membership_rows = (
        (
            await tx.execute(
                sa.text(
                    "SELECT id, enrollment_id FROM cycle_memberships "
                    "WHERE cycle_id = :cycle_id AND enrollment_id = ANY(:ids)"
                ),
                {"cycle_id": cycle_id, "ids": list(enrollment_ids)},
            )
        )
        .mappings()
        .all()
        if enrollment_ids
        else []
    )
    memberships = {
        cast(UUID, row["enrollment_id"]): cast(UUID, row["id"]) for row in membership_rows
    }
    maximum: int | None = None
    if cycle is not None:
        maximum = resolve_policy(
            CycleKind(cycle.kind),
            cycle_policy=await fetch_policy(tx, cycle_id),
        ).max_accepted_offers.value
    return AttachmentState(
        scope_ids=ScopeIds(cycle_id=cycle_id),
        cycle_archived=cycle is not None and cycle.archived_at is not None,
        now=await _now(tx),
        cycle=cycle,
        rows=rows,
        facts=facts,
        memberships=memberships,
        max_accepted_offers=maximum,
        row_overrides={},
    )


async def _with_attachment_overrides(
    tx: AsyncSession, state: AttachmentState, *, cycle_id: UUID
) -> AttachmentState:
    """Resolve cap grants only for operations that can add to the cycle cap."""
    row_overrides = await applicable_many(
        tx,
        (RuleDomain.OFFER_CAP,),
        {
            row.id: ScopeIds(
                cycle_id=cycle_id,
                enrollment_id=row.enrollment_id,
                application_id=row.source_application_id,
            )
            for row in state.rows.values()
        },
    )
    return replace(state, row_overrides=row_overrides)


async def _load_attach(tx: AsyncSession, input_value: BaseModel, *, lock: bool) -> AttachmentState:
    if not isinstance(input_value, AttachExternalOfferInput):
        raise TypeError("attach_external_offer requires AttachExternalOfferInput")
    state = await _load_attachment_rows(
        tx,
        cycle_id=input_value.cycle_id,
        external_offer_ids=(input_value.external_offer_id,),
        lock=lock,
    )
    return await _with_attachment_overrides(
        tx, state, cycle_id=input_value.cycle_id
    )


async def _load_attach_bulk(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> AttachmentState:
    if not isinstance(input_value, AttachExternalOffersInput):
        raise TypeError("attach_external_offers requires AttachExternalOffersInput")
    state = await _load_attachment_rows(
        tx,
        cycle_id=input_value.cycle_id,
        external_offer_ids=tuple(row.external_offer_id for row in input_value.rows),
        lock=lock,
    )
    return await _with_attachment_overrides(
        tx, state, cycle_id=input_value.cycle_id
    )


async def _load_detach(tx: AsyncSession, input_value: BaseModel, *, lock: bool) -> AttachmentState:
    if not isinstance(input_value, DetachExternalOfferInput):
        raise TypeError("detach_external_offer requires DetachExternalOfferInput")
    return await _load_attachment_rows(
        tx,
        cycle_id=input_value.cycle_id,
        external_offer_ids=(input_value.external_offer_id,),
        lock=lock,
        resolve_current_cycle=True,
    )


def _membership_id(enrollment_id: UUID, cycle_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"cds:external-membership:{enrollment_id}:{cycle_id}")


def _attach_plan(
    *,
    state: AttachmentState,
    cycle_id: UUID,
    requested: tuple[AttachRow, ...],
    reason: str,
    actor: ActorContext,
    bulk: bool,
) -> Plan | Rejection:
    if state.cycle is None:
        return Rejection(reasons=[Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")])
    cycle_kind = CycleKind(state.cycle.kind)
    if cycle_kind is CycleKind.OPEN:
        return Rejection(
            reasons=[
                Reason(
                    code=INVALID_TRANSITION,
                    human="External offers attach only to dedicated cycles",
                    path="cycle_id",
                )
            ]
        )
    operations: list[StateOp] = []
    deferred: list[Deferred] = []
    results: list[dict[str, object]] = []
    seen: set[UUID] = set()
    memberships = set(state.memberships)
    virtual_cap = {enrollment_id: facts.cap_used for enrollment_id, facts in state.facts.items()}
    successful: list[ExternalOfferRow] = []
    for selection in requested:
        row = state.rows.get(selection.external_offer_id)
        if row is None:
            results.append(
                {
                    "external_offer_id": str(selection.external_offer_id),
                    "status": "error",
                    "reason": "external_offer_not_found",
                }
            )
            continue
        if row.id in seen:
            results.append(
                {"external_offer_id": str(row.id), "status": "skipped", "reason": DUPLICATE_ROW}
            )
            continue
        seen.add(row.id)
        if row.attached_cycle_id != selection.expected_attached_cycle_id:
            results.append(
                {"external_offer_id": str(row.id), "status": "error", "reason": STALE_VIEW}
            )
            continue
        if row.attached_cycle_id is not None:
            results.append(
                {
                    "external_offer_id": str(row.id),
                    "status": "skipped",
                    "reason": INVALID_TRANSITION,
                }
            )
            continue
        if row.outcome.value != cycle_kind.value:
            results.append(
                {
                    "external_offer_id": str(row.id),
                    "status": "skipped",
                    "reason": "attachment_kind_mismatch",
                }
            )
            continue
        applied_override_ids: tuple[UUID, ...] = ()
        if row.status is ExternalStatus.ACCEPTED:
            used = virtual_cap[row.enrollment_id]
            cap = evaluate_offer_cap(
                max_accepted_offers=state.max_accepted_offers,
                cap_used=used,
                overrides=gate_overrides(state.row_overrides.get(row.id, ())),
            )
            if cap.failures:
                results.append(
                    {
                        "external_offer_id": str(row.id),
                        "status": "skipped",
                        "reason": cap.failures[0].code,
                    }
                )
                continue
            applied_override_ids = cap.applied_override_ids
            virtual_cap[row.enrollment_id] = used + 1
        auto_membership = row.enrollment_id not in memberships
        if auto_membership:
            memberships.add(row.enrollment_id)
            membership_id = _membership_id(row.enrollment_id, cycle_id)
            operations.append(
                StateOp(
                    op="insert",
                    model="cycle_memberships",
                    values={
                        "id": membership_id,
                        "cycle_id": cycle_id,
                        "enrollment_id": row.enrollment_id,
                        "status": MembershipStatus.ACTIVE.value,
                        "auto_created": True,
                    },
                )
            )
            deferred.append(
                Deferred(
                    task="deliver_notification",
                    args={
                        "event_key": "membership_approved",
                        "recipient": row.email,
                        "context": {"student": row.full_name, "cycle": state.cycle.name},
                    },
                )
            )
        operations.append(
            StateOp(
                op="update",
                model="external_offers",
                values={"attached_cycle_id": cycle_id},
                where={"id": row.id},
            )
        )
        if bulk:
            operations.append(
                StateOp(
                    op="insert",
                    model="audit_log",
                    values={
                        "actor_user_id": actor.user_id,
                        "action": "attach_external_offers",
                        "subject_type": "enrollment",
                        "subject_id": row.enrollment_id,
                        "details": {
                            "external_offer_id": str(row.id),
                            "cycle_id": str(cycle_id),
                            "reason": reason,
                            "membership_auto_created": auto_membership,
                            "applied_override_ids": [
                                str(item) for item in applied_override_ids
                            ],
                        },
                    },
                )
            )
        successful.append(row)
        results.append(
            {
                "external_offer_id": str(row.id),
                "enrollment_id": str(row.enrollment_id),
                "attached_cycle_id": str(cycle_id),
                "status": "ok",
                "offer_status": row.status.value,
                "reason": None,
                "membership_auto_created": auto_membership,
                "membership_left_in_place": False,
                "applied_override_ids": [
                    str(item) for item in applied_override_ids
                ],
            }
        )
    if not bulk:
        if not successful:
            failure_code = cast(str, results[0]["reason"]) if results else INVALID_TRANSITION
            return Rejection(
                reasons=[
                    Reason(
                        code=failure_code,
                        human="The external offer cannot be attached",
                    )
                ]
            )
        row = successful[0]
        result = results[-1]
        summary: dict[str, object] = {
            "external_offer_id": str(row.id),
            "enrollment_id": str(row.enrollment_id),
            "attached_cycle_id": str(cycle_id),
            "status": row.status.value,
            "membership_auto_created": result["membership_auto_created"],
            "membership_left_in_place": False,
            "applied_override_ids": result["applied_override_ids"],
        }
        audit = {
            "subject_type": "enrollment",
            "subject_id": row.enrollment_id,
            "details": {
                "operation": "attach_external_offer",
                "external_offer_id": str(row.id),
                "cycle_id": str(cycle_id),
                "reason": reason,
                "membership_auto_created": result["membership_auto_created"],
                "applied_override_ids": result["applied_override_ids"],
            },
        }
    else:
        summary = {"rows": results}
        audit = None
    return Plan(state_ops=operations, events=[], deferred=deferred, audit=audit, summary=summary)


def _decide_attach(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    if not isinstance(input_value, AttachExternalOfferInput) or not isinstance(
        state, AttachmentState
    ):
        raise TypeError("Invalid attach_external_offer decision input")
    return _attach_plan(
        state=state,
        cycle_id=input_value.cycle_id,
        requested=(
            AttachRow(
                external_offer_id=input_value.external_offer_id,
                expected_attached_cycle_id=input_value.expected_attached_cycle_id,
            ),
        ),
        reason=input_value.reason,
        actor=actor,
        bulk=False,
    )


def _decide_attach_bulk(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    if not isinstance(input_value, AttachExternalOffersInput) or not isinstance(
        state, AttachmentState
    ):
        raise TypeError("Invalid attach_external_offers decision input")
    return _attach_plan(
        state=state,
        cycle_id=input_value.cycle_id,
        requested=tuple(input_value.rows),
        reason=input_value.reason,
        actor=actor,
        bulk=True,
    )


def _decide_detach(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    if not isinstance(input_value, DetachExternalOfferInput) or not isinstance(
        state, AttachmentState
    ):
        raise TypeError("Invalid detach_external_offer decision input")
    if state.cycle is None:
        return Rejection(reasons=[Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")])
    row = state.rows.get(input_value.external_offer_id)
    if row is None:
        return _not_found()
    if (
        row.attached_cycle_id != input_value.expected_attached_cycle_id
        or row.attached_cycle_id != input_value.cycle_id
    ):
        return Rejection(
            reasons=[
                Reason(
                    code=STALE_VIEW,
                    human="The external offer attachment changed",
                    path="expected_attached_cycle_id",
                )
            ]
        )
    membership_id = state.memberships.get(row.enrollment_id)
    return Plan(
        state_ops=[
            StateOp(
                op="update",
                model="external_offers",
                values={"attached_cycle_id": None},
                where={"id": row.id},
            )
        ],
        events=[],
        deferred=[],
        audit={
            "subject_type": "enrollment",
            "subject_id": row.enrollment_id,
            "details": {
                "operation": "detach_external_offer",
                "external_offer_id": str(row.id),
                "cycle_id": str(input_value.cycle_id),
                "reason": input_value.reason,
                "membership_left_in_place": membership_id is not None,
            },
        },
        summary={
            "external_offer_id": str(row.id),
            "enrollment_id": str(row.enrollment_id),
            "attached_cycle_id": None,
            "status": row.status.value,
            "membership_auto_created": False,
            "membership_left_in_place": membership_id is not None,
            "applied_override_ids": [],
        },
    )


def register_external_offer_commands(registry: Registry) -> None:
    registry.command(
        name="create_external_offer",
        input_model=CreateExternalOfferInput,
        output_model=ExternalOfferSummary,
        actor="staff",
        scope="none",
        loader=_load_create,
        rule_domains=(RuleDomain.OUTCOME_GATE,),
        spec_ids=("EXT-1", "EXT-2", "EXT-4", "DER-1", "OFR-3"),
        rate_limit="10/min",
    )(_decide_create)
    registry.command(
        name="update_external_offer",
        input_model=UpdateExternalOfferInput,
        output_model=ExternalOfferSummary,
        actor="staff",
        scope="none",
        loader=_load_update,
        rule_domains=(RuleDomain.OUTCOME_GATE, RuleDomain.OFFER_CAP),
        spec_ids=("EXT-1", "EXT-2", "EXT-4", "DER-1", "OFR-3", "OFR-5"),
        rate_limit="10/min",
    )(_decide_update)
    registry.command(
        name="delete_external_offer",
        input_model=DeleteExternalOfferInput,
        output_model=ExternalOfferSummary,
        actor="staff",
        scope="none",
        loader=_load_delete,
        rule_domains=(),
        spec_ids=("EXT-1", "EXT-2", "EXT-4", "DER-1", "OFR-5"),
        rate_limit="10/min",
    )(_decide_delete)
    registry.command(
        name="attach_external_offer",
        input_model=AttachExternalOfferInput,
        output_model=AttachmentSummary,
        actor="staff",
        scope="cycle",
        loader=_load_attach,
        rule_domains=(RuleDomain.OFFER_CAP,),
        spec_ids=("EXT-3", "DER-1", "INT-2"),
        rate_limit="10/min",
    )(_decide_attach)
    registry.command(
        name="attach_external_offers",
        input_model=AttachExternalOffersInput,
        output_model=BulkAttachmentSummary,
        actor="staff",
        scope="cycle",
        loader=_load_attach_bulk,
        rule_domains=(RuleDomain.OFFER_CAP,),
        spec_ids=("EXT-3", "DER-1", "INT-2"),
        rate_limit="10/min",
        execution_mode="bulk",
    )(_decide_attach_bulk)
    registry.command(
        name="detach_external_offer",
        input_model=DetachExternalOfferInput,
        output_model=AttachmentSummary,
        actor="staff",
        scope="cycle",
        loader=_load_detach,
        rule_domains=(),
        spec_ids=("EXT-3", "DER-1"),
        rate_limit="10/min",
    )(_decide_detach)
