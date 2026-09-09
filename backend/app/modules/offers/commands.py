"""Portal offer extension, response, and open-cycle outcomes (OFR-1..3, JOB-6)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal, cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    APPLICATION_NOT_FOUND,
    CYCLE_NOT_FOUND,
    DUPLICATE_ROW,
    INVALID_TRANSITION,
    JOB_NOT_FOUND,
    NOT_OFFERED,
    OFFER_TERMINATED,
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
from app.domain.gates import (
    evaluate_acceptance_constraints,
    evaluate_offer_deadline,
)
from app.domain.policy import resolve_policy
from app.domain.shared import (
    ApplicationStatus,
    CycleKind,
    EventType,
    OfferResponse,
    Outcome,
    RuleDomain,
)
from app.domain.transitions import TransitionActor, TransitionContext, decide_transition
from app.modules.applications.verdict import gate_overrides
from app.modules.cycles.commands import CycleRow, fetch_cycle, fetch_policy
from app.modules.jobs.commands import JobRow, fetch_job, job_cancelled_reason
from app.modules.notifications.wording import NOT_APPLICABLE
from app.modules.offers.derivations import OfferFacts, offer_facts
from app.modules.offers.locking import AcceptanceLockRequest, lock_acceptance_state
from app.modules.offers.planning import (
    OfferApplication,
    PlannedMutation,
    plan_acceptance,
    plan_decline,
    plan_extension,
)
from app.modules.overrides.service import ApplicableOverride, applicable_many

_OFFER_APPLICATIONS = """
    SELECT
        a.id AS application_id, a.enrollment_id, a.status,
        a.current_round_id, j.id AS job_id, j.title AS job_title,
        j.outcome, j.offer_acceptance_deadline,
        c.id AS cycle_id, c.name AS cycle_name, c.kind AS cycle_kind,
        company.name AS company_name, u.email, u.full_name, e.roll_number,
        current_offer.id AS current_offer_id,
        current_offer.deadline_at AS current_offer_deadline,
        current_offer.response AS current_offer_response,
        current_offer.terminated_at AS current_offer_terminated_at,
        (SELECT count(*) FROM offers counted WHERE counted.application_id = a.id)
            AS offer_count
    FROM applications a
    JOIN jobs j ON j.id = a.job_id
    JOIN cycles c ON c.id = j.cycle_id
    JOIN companies company ON company.id = j.company_id
    JOIN enrollments e ON e.id = a.enrollment_id
    JOIN users u ON u.id = e.user_id
    LEFT JOIN LATERAL (
        SELECT o.id, o.deadline_at, o.response, o.terminated_at
        FROM offers o
        WHERE o.application_id = a.id
        ORDER BY o.extended_at DESC, o.id DESC
        LIMIT 1
    ) current_offer ON true
"""

_RESOLUTION_ROWS = """
    SELECT a.id AS application_id, a.enrollment_id, a.status,
           u.email, e.roll_number
    FROM applications a
    JOIN enrollments e ON e.id = a.enrollment_id
    JOIN users u ON u.id = e.user_id
    WHERE a.job_id = :job_id
    ORDER BY a.id
"""


async def _now(tx: AsyncSession) -> datetime:
    return cast(datetime, await tx.scalar(sa.select(sa.func.now())))


def _offer_application(row: sa.RowMapping) -> OfferApplication:
    return OfferApplication(
        application_id=cast(UUID, row["application_id"]),
        enrollment_id=cast(UUID, row["enrollment_id"]),
        status=ApplicationStatus(row["status"]),
        current_round_id=cast("UUID | None", row["current_round_id"]),
        job_id=cast(UUID, row["job_id"]),
        job_title=str(row["job_title"]),
        company_name=str(row["company_name"]),
        cycle_id=cast(UUID, row["cycle_id"]),
        cycle_name=str(row["cycle_name"]),
        cycle_kind=CycleKind(row["cycle_kind"]),
        outcome=Outcome(row["outcome"]),
        email=str(row["email"]),
        full_name=str(row["full_name"]),
        roll_number=str(row["roll_number"]) if row["roll_number"] else None,
        current_offer_id=cast("UUID | None", row["current_offer_id"]),
        current_offer_deadline=cast("datetime | None", row["current_offer_deadline"]),
        current_offer_response=(
            OfferResponse(row["current_offer_response"])
            if row["current_offer_response"] is not None
            else None
        ),
        current_offer_terminated=row["current_offer_terminated_at"] is not None,
        offer_count=int(row["offer_count"]),
    )


async def _load_offer_applications(
    tx: AsyncSession,
    *,
    job_id: UUID | None = None,
    enrollment_ids: tuple[UUID, ...] = (),
) -> tuple[OfferApplication, ...]:
    conditions: list[str] = []
    parameters: dict[str, object] = {}
    if job_id is not None:
        conditions.append("a.job_id = :job_id")
        parameters["job_id"] = job_id
    if enrollment_ids:
        conditions.append("a.enrollment_id = ANY(:enrollment_ids)")
        parameters["enrollment_ids"] = list(enrollment_ids)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    rows = (
        await tx.execute(
            sa.text(_OFFER_APPLICATIONS + where + " ORDER BY a.id"), parameters
        )
    ).mappings().all()
    return tuple(_offer_application(row) for row in rows)


@dataclass(frozen=True, slots=True)
class ResolutionRow:
    application_id: UUID
    enrollment_id: UUID
    status: ApplicationStatus
    email: str
    roll_number: str | None


async def _resolution_rows(
    tx: AsyncSession, job_id: UUID
) -> tuple[ResolutionRow, ...]:
    rows = (
        await tx.execute(sa.text(_RESOLUTION_ROWS), {"job_id": job_id})
    ).mappings().all()
    return tuple(
        ResolutionRow(
            application_id=cast(UUID, row["application_id"]),
            enrollment_id=cast(UUID, row["enrollment_id"]),
            status=ApplicationStatus(row["status"]),
            email=str(row["email"]),
            roll_number=str(row["roll_number"]) if row["roll_number"] else None,
        )
        for row in rows
    )


def _validate_selection_rows(value: list[dict[str, str]]) -> list[dict[str, str]]:
    allowed = {"application_id", "identifier", "expected_status"}
    for row in value:
        keys = set(row)
        if not keys or not keys <= allowed or not keys & {"application_id", "identifier"}:
            raise ValueError(
                "each row names an application_id or identifier and may include expected_status"
            )
    return value


def _resolve[RowT: ResolutionRow | OfferApplication](
    requested: dict[str, str], rows: tuple[RowT, ...]
) -> RowT | None:
    raw_id = requested.get("application_id")
    if raw_id is not None:
        try:
            application_id = UUID(raw_id)
        except ValueError:
            return None
        return next((row for row in rows if row.application_id == application_id), None)
    identifier = requested["identifier"].strip().casefold()
    if not identifier:
        return None
    return next(
        (
            row
            for row in rows
            if row.email.casefold() == identifier
            or (row.roll_number or "").casefold() == identifier
        ),
        None,
    )


def _row_result(
    label: str,
    application: OfferApplication | ResolutionRow | None,
    *,
    status: str,
    reason: str | None = None,
    to_status: ApplicationStatus | None = None,
    offer_id: UUID | None = None,
    cascade: tuple[dict[str, object], ...] = (),
) -> dict[str, object]:
    return {
        "identifier": label,
        "application_id": (
            str(application.application_id) if application is not None else None
        ),
        "status": status,
        "reason": reason,
        "to_status": to_status.value if to_status is not None else None,
        "offer_id": str(offer_id) if offer_id is not None else None,
        "cascade": list(cascade),
    }


class ExtendOffersInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    job_id: UUID
    rows: list[dict[str, str]]
    batch_key: str

    _rows = field_validator("rows")(_validate_selection_rows)


class BulkOfferSummary(BaseModel):
    rows: list[dict[str, object]]


@dataclass(frozen=True, slots=True)
class ExtendState:
    scope_ids: ScopeIds
    cycle_archived: bool
    now: datetime
    cycle: CycleRow | None
    job: JobRow | None
    applications: tuple[OfferApplication, ...]


async def _load_extend(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> ExtendState:
    if not isinstance(input_value, ExtendOffersInput):
        raise TypeError("extend_offers requires ExtendOffersInput")
    cycle = await fetch_cycle(tx, input_value.cycle_id, lock=lock)
    job = await fetch_job(
        tx, cycle_id=input_value.cycle_id, job_id=input_value.job_id, lock=lock
    )
    if lock:
        # Align non-accepting writers with locking.py's offer → application
        # phases.  They do not need the enrollment mutex, but reversing these
        # two rows would deadlock against an acceptance of the same offer.
        await tx.execute(
            sa.text(
                "SELECT o.id FROM offers o JOIN applications a "
                "ON a.id = o.application_id WHERE a.job_id = :job_id "
                "ORDER BY o.id FOR UPDATE OF o"
            ),
            {"job_id": input_value.job_id},
        )
        await tx.execute(
            sa.text(
                "SELECT id FROM applications WHERE job_id = :job_id "
                "ORDER BY id FOR UPDATE"
            ),
            {"job_id": input_value.job_id},
        )
    return ExtendState(
        scope_ids=ScopeIds(cycle_id=input_value.cycle_id, job_id=input_value.job_id),
        cycle_archived=cycle is not None and cycle.archived_at is not None,
        now=await _now(tx),
        cycle=cycle,
        job=job,
        applications=await _load_offer_applications(tx, job_id=input_value.job_id),
    )


def _decide_extend(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """OFR-2: rollout/direct extension creates history, event, notice and expiry."""
    if not isinstance(input_value, ExtendOffersInput) or not isinstance(
        state, ExtendState
    ):
        raise TypeError("Invalid extend_offers decision input")
    if state.cycle is None:
        return Rejection(reasons=[Reason(code=CYCLE_NOT_FOUND, human="Cycle not found")])
    if state.job is None:
        return Rejection(reasons=[Reason(code=JOB_NOT_FOUND, human="Job not found")])
    if state.job.cancelled_at is not None:
        return Rejection(reasons=[job_cancelled_reason()])

    results: list[dict[str, object]] = []
    operations: list[StateOp] = []
    events: list[Event] = []
    deferred: list[Deferred] = []
    seen: set[UUID] = set()
    for requested in input_value.rows:
        label = requested.get("identifier") or requested.get("application_id", "")
        target = _resolve(requested, state.applications)
        if target is None:
            results.append(
                _row_result(label, None, status="error", reason=UNMATCHED_IDENTIFIER)
            )
            continue
        if target.application_id in seen:
            results.append(
                _row_result(label, target, status="skipped", reason=DUPLICATE_ROW)
            )
            continue
        expected = requested.get("expected_status")
        if expected is not None and expected != target.status.value:
            results.append(_row_result(label, target, status="error", reason=STALE_VIEW))
            continue
        transition = decide_transition(
            "extend_offer",
            from_status=target.status,
            to_status=ApplicationStatus.OFFERED,
            actor=TransitionActor.STAFF,
            context=TransitionContext(cycle_kind=CycleKind(state.cycle.kind)),
        )
        if isinstance(transition, Rejection):
            results.append(
                _row_result(label, target, status="skipped", reason=INVALID_TRANSITION)
            )
            continue
        seen.add(target.application_id)
        offer_id, planned = plan_extension(
            target,
            now=state.now,
            deadline=state.job.offer_acceptance_deadline,
            notify=True,
        )
        operations.extend(planned.state_ops)
        events.extend(planned.events)
        deferred.extend(planned.deferred)
        results.append(
            _row_result(
                label,
                target,
                status="ok",
                to_status=ApplicationStatus.OFFERED,
                offer_id=offer_id,
            )
        )

    return Plan(
        state_ops=operations,
        events=events,
        deferred=deferred,
        audit={
            "subject_type": "job",
            "subject_id": input_value.job_id,
            "details": {"operation": "extend_offers", "count": len(seen)},
        },
        summary={"rows": results},
    )


class OfferResponseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    job_id: UUID
    application_id: UUID
    offer_id: UUID
    enrollment_id: UUID
    expected_status: ApplicationStatus


class OfferActionSummary(BaseModel):
    cycle_id: UUID
    job_id: UUID
    application_id: UUID
    offer_id: UUID
    enrollment_id: UUID
    status: ApplicationStatus
    cascade: list[dict[str, object]]
    applied_override_ids: list[UUID]


@dataclass(frozen=True, slots=True)
class ResponseState:
    scope_ids: ScopeIds
    cycle_archived: bool
    now: datetime
    cycle: CycleRow | None
    job: JobRow | None
    target: OfferApplication | None
    applications: tuple[OfferApplication, ...]
    facts: OfferFacts | None
    max_accepted_offers: int | None


async def _load_response(
    tx: AsyncSession,
    input_value: BaseModel,
    *,
    lock: bool,
    accepting: bool,
) -> ResponseState:
    if not isinstance(input_value, OfferResponseInput):
        raise TypeError("Offer responses require OfferResponseInput")
    # Outcome and cycle kind are immutable, so they may safely describe the
    # central lock request before the mutable offer/application rows are read.
    cycle = await fetch_cycle(tx, input_value.cycle_id, lock=False)
    job = await fetch_job(
        tx, cycle_id=input_value.cycle_id, job_id=input_value.job_id, lock=False
    )
    if accepting and cycle is not None and job is not None:
        await lock_acceptance_state(
            tx,
            (
                AcceptanceLockRequest(
                    enrollment_id=input_value.enrollment_id,
                    cycle_id=input_value.cycle_id,
                    application_id=input_value.application_id,
                    outcome=job.outcome,
                    cycle_kind=CycleKind(cycle.kind),
                ),
            ),
            lock=lock,
        )
    elif lock:
        await tx.execute(
            sa.text(
                "SELECT id FROM offers WHERE application_id = :application_id "
                "ORDER BY id FOR UPDATE"
            ),
            {"application_id": input_value.application_id},
        )
        await tx.execute(
            sa.text("SELECT id FROM applications WHERE id = :id FOR UPDATE"),
            {"id": input_value.application_id},
        )

    # Re-read archival status and all mutable offer rows after locks.
    cycle = await fetch_cycle(tx, input_value.cycle_id, lock=False)
    job = await fetch_job(
        tx, cycle_id=input_value.cycle_id, job_id=input_value.job_id, lock=False
    )
    applications = await _load_offer_applications(
        tx, enrollment_ids=(input_value.enrollment_id,)
    )
    target = next(
        (
            row
            for row in applications
            if row.application_id == input_value.application_id
            and row.job_id == input_value.job_id
            and row.enrollment_id == input_value.enrollment_id
        ),
        None,
    )
    facts: OfferFacts | None = None
    maximum: int | None = None
    if accepting and cycle is not None:
        facts = await offer_facts(
            tx, input_value.enrollment_id, input_value.cycle_id
        )
        policy = resolve_policy(
            CycleKind(cycle.kind),
            cycle_policy=await fetch_policy(tx, input_value.cycle_id),
        )
        maximum = policy.max_accepted_offers.value
    return ResponseState(
        scope_ids=ScopeIds(
            cycle_id=input_value.cycle_id,
            job_id=input_value.job_id,
            enrollment_id=input_value.enrollment_id,
            application_id=input_value.application_id,
        ),
        cycle_archived=cycle is not None and cycle.archived_at is not None,
        now=await _now(tx),
        cycle=cycle,
        job=job,
        target=target,
        applications=applications,
        facts=facts,
        max_accepted_offers=maximum,
    )


async def _load_accept(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> ResponseState:
    return await _load_response(tx, input_value, lock=lock, accepting=True)


async def _load_decline(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> ResponseState:
    return await _load_response(tx, input_value, lock=lock, accepting=False)


def _response_reasons(
    input_value: OfferResponseInput, state: ResponseState
) -> list[Reason]:
    if state.cycle is None:
        return [Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")]
    if state.job is None:
        return [Reason(code=JOB_NOT_FOUND, human="The job does not exist")]
    target = state.target
    if target is None:
        return [
            Reason(
                code=APPLICATION_NOT_FOUND,
                human="The application does not exist for this student and job",
                path="application_id",
            )
        ]
    reasons: list[Reason] = []
    if target.status is not input_value.expected_status:
        reasons.append(
            Reason(
                code=STALE_VIEW,
                human="The application status changed since this offer was displayed",
                path="expected_status",
            )
        )
    if target.status is not ApplicationStatus.OFFERED:
        reasons.append(
            Reason(code=NOT_OFFERED, human="This application is not currently offered")
        )
    if target.current_offer_id != input_value.offer_id:
        reasons.append(
            Reason(
                code=STALE_VIEW,
                human="A newer offer row is now current for this application",
                path="offer_id",
            )
        )
    if target.current_offer_terminated:
        reasons.append(
            Reason(code=OFFER_TERMINATED, human="This offer has been terminated")
        )
    if target.current_offer_response is not None:
        reasons.append(
            Reason(code=NOT_OFFERED, human="This offer has already been answered")
        )
    return reasons


def _decide_accept(
    input_value: BaseModel,
    state: object,
    _policy: object,
    overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """OFR-3: dedicated-cycle student acceptance and its invariant cascade."""
    if not isinstance(input_value, OfferResponseInput) or not isinstance(
        state, ResponseState
    ):
        raise TypeError("Invalid accept_offer decision input")
    reasons = _response_reasons(input_value, state)
    if reasons:
        return Rejection(reasons=reasons)
    assert state.cycle is not None and state.job is not None
    assert state.target is not None and state.facts is not None
    transition = decide_transition(
        "accept",
        from_status=state.target.status,
        to_status=ApplicationStatus.ACCEPTED,
        actor=TransitionActor.STUDENT,
        context=TransitionContext(cycle_kind=CycleKind(state.cycle.kind)),
    )
    if isinstance(transition, Rejection):
        return transition
    resolved = gate_overrides(cast("tuple[ApplicableOverride, ...]", overrides))
    deadline = evaluate_offer_deadline(
        now=state.now,
        deadline=state.target.current_offer_deadline,
        overrides=resolved,
    )
    constraints = evaluate_acceptance_constraints(
        outcome=state.target.outcome,
        cycle_kind=state.target.cycle_kind,
        placement_placed_global=state.facts.placement_placed_global,
        internship_placed_in_cycle=state.facts.internship_placed_in_cycle,
        max_accepted_offers=state.max_accepted_offers,
        cap_used=state.facts.cap_used,
        overrides=resolved,
    )
    failures = [*deadline.failures, *constraints.failures]
    if failures:
        return Rejection(reasons=failures)
    applied = tuple(
        dict.fromkeys(
            (*deadline.applied_override_ids, *constraints.applied_override_ids)
        )
    )
    planned = plan_acceptance(
        state.target,
        state.applications,
        offer_id=input_value.offer_id,
        now=state.now,
        applied_override_ids=applied,
    )
    return Plan(
        state_ops=list(planned.state_ops),
        events=list(planned.events),
        deferred=list(planned.deferred),
        audit={
            "subject_type": "application",
            "subject_id": input_value.application_id,
            "details": {
                "operation": "accept_offer",
                "offer_id": str(input_value.offer_id),
                "cascade_count": len(planned.cascade),
                "actor_user_id": str(actor.user_id) if actor.user_id else None,
            },
        },
        summary={
            "cycle_id": str(input_value.cycle_id),
            "job_id": str(input_value.job_id),
            "application_id": str(input_value.application_id),
            "offer_id": str(input_value.offer_id),
            "enrollment_id": str(input_value.enrollment_id),
            "status": ApplicationStatus.ACCEPTED.value,
            "cascade": list(planned.cascade),
            "applied_override_ids": [str(item) for item in applied],
        },
    )


def _decide_decline(
    input_value: BaseModel,
    state: object,
    _policy: object,
    overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """OFR-3: a guarded decline updates the current Offer and cascades nothing."""
    if not isinstance(input_value, OfferResponseInput) or not isinstance(
        state, ResponseState
    ):
        raise TypeError("Invalid decline_offer decision input")
    reasons = _response_reasons(input_value, state)
    if reasons:
        return Rejection(reasons=reasons)
    assert state.cycle is not None and state.target is not None
    transition = decide_transition(
        "decline",
        from_status=state.target.status,
        to_status=ApplicationStatus.DECLINED,
        actor=TransitionActor.STUDENT,
        context=TransitionContext(cycle_kind=CycleKind(state.cycle.kind)),
    )
    if isinstance(transition, Rejection):
        return transition
    resolved = gate_overrides(cast("tuple[ApplicableOverride, ...]", overrides))
    deadline = evaluate_offer_deadline(
        now=state.now,
        deadline=state.target.current_offer_deadline,
        overrides=resolved,
    )
    if deadline.failures:
        return Rejection(reasons=list(deadline.failures))
    planned = plan_decline(state.target, offer_id=input_value.offer_id, now=state.now)
    return Plan(
        state_ops=list(planned.state_ops),
        events=list(planned.events),
        deferred=list(planned.deferred),
        audit={
            "subject_type": "application",
            "subject_id": input_value.application_id,
            "details": {
                "operation": "decline_offer",
                "offer_id": str(input_value.offer_id),
                "actor_user_id": str(actor.user_id) if actor.user_id else None,
            },
        },
        summary={
            "cycle_id": str(input_value.cycle_id),
            "job_id": str(input_value.job_id),
            "application_id": str(input_value.application_id),
            "offer_id": str(input_value.offer_id),
            "enrollment_id": str(input_value.enrollment_id),
            "status": ApplicationStatus.DECLINED.value,
            "cascade": [],
            "applied_override_ids": [
                str(item) for item in deadline.applied_override_ids
            ],
        },
    )


OpenOutcome = Literal["offered", "accepted", "declined", "rejected"]


class RecordOpenOutcomeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    job_id: UUID
    target_status: OpenOutcome
    rows: list[dict[str, str]]
    batch_key: str
    reason: str | None = None

    _rows = field_validator("rows")(_validate_selection_rows)


@dataclass(frozen=True, slots=True)
class OpenOutcomeState:
    scope_ids: ScopeIds
    cycle_archived: bool
    now: datetime
    cycle: CycleRow | None
    job: JobRow | None
    applications: tuple[OfferApplication, ...]
    facts: dict[UUID, OfferFacts]
    max_accepted_offers: int | None
    row_overrides: dict[UUID, tuple[ApplicableOverride, ...]]


async def _load_open_outcome(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> OpenOutcomeState:
    if not isinstance(input_value, RecordOpenOutcomeInput):
        raise TypeError("record_open_outcome requires RecordOpenOutcomeInput")
    cycle = await fetch_cycle(tx, input_value.cycle_id, lock=False)
    job = await fetch_job(
        tx, cycle_id=input_value.cycle_id, job_id=input_value.job_id, lock=False
    )
    preliminary = await _resolution_rows(tx, input_value.job_id)
    targets = tuple(
        target
        for requested in input_value.rows
        if (target := _resolve(requested, preliminary)) is not None
    )
    if (
        input_value.target_status == ApplicationStatus.ACCEPTED.value
        and cycle is not None
        and job is not None
    ):
        await lock_acceptance_state(
            tx,
            tuple(
                AcceptanceLockRequest(
                    enrollment_id=target.enrollment_id,
                    cycle_id=input_value.cycle_id,
                    application_id=target.application_id,
                    outcome=job.outcome,
                    cycle_kind=CycleKind(cycle.kind),
                )
                for target in targets
            ),
            lock=lock,
        )
    elif lock:
        await tx.execute(
            sa.text(
                "SELECT o.id FROM offers o JOIN applications a "
                "ON a.id = o.application_id WHERE a.job_id = :job_id "
                "ORDER BY o.id FOR UPDATE OF o"
            ),
            {"job_id": input_value.job_id},
        )
        await tx.execute(
            sa.text(
                "SELECT id FROM applications WHERE job_id = :job_id "
                "ORDER BY id FOR UPDATE"
            ),
            {"job_id": input_value.job_id},
        )
    cycle = await fetch_cycle(tx, input_value.cycle_id, lock=False)
    job = await fetch_job(
        tx, cycle_id=input_value.cycle_id, job_id=input_value.job_id, lock=False
    )
    enrollment_ids = tuple(
        sorted({row.enrollment_id for row in targets}, key=lambda item: item.int)
    )
    applications = await _load_offer_applications(
        tx,
        enrollment_ids=enrollment_ids,
        job_id=None if enrollment_ids else input_value.job_id,
    )
    facts: dict[UUID, OfferFacts] = {}
    maximum: int | None = None
    row_overrides: dict[UUID, tuple[ApplicableOverride, ...]] = {}
    if input_value.target_status == ApplicationStatus.ACCEPTED.value and cycle is not None:
        for enrollment_id in enrollment_ids:
            facts[enrollment_id] = await offer_facts(
                tx, enrollment_id, input_value.cycle_id
            )
        maximum = resolve_policy(
            CycleKind(cycle.kind),
            cycle_policy=await fetch_policy(tx, input_value.cycle_id),
        ).max_accepted_offers.value
        row_overrides = await applicable_many(
            tx,
            (RuleDomain.OUTCOME_GATE, RuleDomain.OFFER_CAP),
            {
                row.application_id: ScopeIds(
                    cycle_id=input_value.cycle_id,
                    job_id=input_value.job_id,
                    enrollment_id=row.enrollment_id,
                    application_id=row.application_id,
                )
                for row in applications
                if row.job_id == input_value.job_id
            },
        )
    return OpenOutcomeState(
        scope_ids=ScopeIds(cycle_id=input_value.cycle_id, job_id=input_value.job_id),
        cycle_archived=cycle is not None and cycle.archived_at is not None,
        now=await _now(tx),
        cycle=cycle,
        job=job,
        applications=applications,
        facts=facts,
        max_accepted_offers=maximum,
        row_overrides=row_overrides,
    )


def _append_mutation(
    planned: PlannedMutation,
    operations: list[StateOp],
    events: list[Event],
    deferred: list[Deferred],
) -> None:
    operations.extend(planned.state_ops)
    events.extend(planned.events)
    deferred.extend(planned.deferred)


def _decide_open_outcome(
    input_value: BaseModel,
    state: object,
    _policy: object,
    overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """JOB-6: staff-recorded outcomes compose only legal APP-4 transitions."""
    if not isinstance(input_value, RecordOpenOutcomeInput) or not isinstance(
        state, OpenOutcomeState
    ):
        raise TypeError("Invalid record_open_outcome decision input")
    if state.cycle is None:
        return Rejection(reasons=[Reason(code=CYCLE_NOT_FOUND, human="Cycle not found")])
    if state.job is None:
        return Rejection(reasons=[Reason(code=JOB_NOT_FOUND, human="Job not found")])
    if state.job.cancelled_at is not None:
        return Rejection(reasons=[job_cancelled_reason()])
    if CycleKind(state.cycle.kind) is not CycleKind.OPEN:
        return Rejection(
            reasons=[
                Reason(
                    code=INVALID_TRANSITION,
                    human="Staff-recorded final outcomes are only available for open-cycle jobs",
                    path="cycle_id",
                )
            ]
        )
    if input_value.target_status == ApplicationStatus.REJECTED.value and not (
        input_value.reason or ""
    ).strip():
        return Rejection(
            reasons=[
                Reason(
                    code=INVALID_TRANSITION,
                    human="Rejecting applications requires a reason",
                    path="reason",
                )
            ]
        )

    del overrides
    job_rows = tuple(row for row in state.applications if row.job_id == input_value.job_id)
    results: list[dict[str, object]] = []
    operations: list[StateOp] = []
    events: list[Event] = []
    deferred: list[Deferred] = []
    seen: set[UUID] = set()
    virtually_changed: set[UUID] = set()
    accepted_placement: set[UUID] = set()
    virtual_cap = {
        enrollment_id: facts.cap_used for enrollment_id, facts in state.facts.items()
    }

    for requested in input_value.rows:
        label = requested.get("identifier") or requested.get("application_id", "")
        target = _resolve(requested, job_rows)
        if target is None:
            results.append(
                _row_result(label, None, status="error", reason=UNMATCHED_IDENTIFIER)
            )
            continue
        if target.application_id in seen:
            results.append(
                _row_result(label, target, status="skipped", reason=DUPLICATE_ROW)
            )
            continue
        if target.application_id in virtually_changed:
            results.append(
                _row_result(label, target, status="skipped", reason=STALE_VIEW)
            )
            continue
        expected = requested.get("expected_status")
        if expected is not None and expected != target.status.value:
            results.append(_row_result(label, target, status="error", reason=STALE_VIEW))
            continue
        seen.add(target.application_id)
        desired = ApplicationStatus(input_value.target_status)

        if desired is ApplicationStatus.REJECTED:
            transition = decide_transition(
                "bulk_reject",
                from_status=target.status,
                to_status=desired,
                actor=TransitionActor.STAFF,
                context=TransitionContext(cycle_kind=CycleKind.OPEN),
                reason=input_value.reason,
            )
            if isinstance(transition, Rejection):
                results.append(
                    _row_result(label, target, status="skipped", reason=INVALID_TRANSITION)
                )
                continue
            operations.append(
                StateOp(
                    op="update",
                    model="applications",
                    values={"status": desired.value},
                    where={"id": target.application_id},
                )
            )
            events.append(
                Event(
                    application_id=target.application_id,
                    event_type=EventType.ELIMINATED,
                    from_status=target.status.value,
                    to_status=desired.value,
                    from_round=target.current_round_id,
                    to_round=target.current_round_id,
                    reason=input_value.reason,
                    payload={"operation": "record_open_outcome"},
                )
            )
            deferred.append(
                Deferred(
                    task="deliver_notification",
                    args={
                        "event_key": "rejected",
                        "recipient": target.email,
                        "context": {
                            "student": target.full_name,
                            # An open-cycle outcome is recorded against the
                            # application, not against a round; the template's
                            # round line has to say so rather than sit blank.
                            "round": NOT_APPLICABLE,
                            "job": target.job_title,
                            "reason": input_value.reason,
                        },
                    },
                )
            )
            results.append(
                _row_result(label, target, status="ok", to_status=desired)
            )
            continue

        working = target
        extension: PlannedMutation | None = None
        offer_id = target.current_offer_id
        if target.status is ApplicationStatus.IN_PROGRESS:
            transition = decide_transition(
                "extend_offer",
                from_status=target.status,
                to_status=ApplicationStatus.OFFERED,
                actor=TransitionActor.STAFF,
                context=TransitionContext(cycle_kind=CycleKind.OPEN),
            )
            if isinstance(transition, Rejection):
                results.append(
                    _row_result(label, target, status="skipped", reason=INVALID_TRANSITION)
                )
                continue
            offer_id, extension = plan_extension(
                target,
                now=state.now,
                deadline=None,
                notify=desired is ApplicationStatus.OFFERED,
            )
            working = replace(
                target,
                status=ApplicationStatus.OFFERED,
                current_offer_id=offer_id,
                current_offer_deadline=None,
                current_offer_response=None,
                current_offer_terminated=False,
                offer_count=target.offer_count + 1,
            )
        elif target.status is not ApplicationStatus.OFFERED:
            results.append(
                _row_result(label, target, status="skipped", reason=INVALID_TRANSITION)
            )
            continue
        if offer_id is None or working.current_offer_terminated or working.current_offer_response:
            results.append(_row_result(label, target, status="skipped", reason=NOT_OFFERED))
            continue

        if desired is ApplicationStatus.OFFERED:
            if extension is None:
                results.append(
                    _row_result(label, target, status="skipped", reason=DUPLICATE_ROW)
                )
                continue
            _append_mutation(extension, operations, events, deferred)
            results.append(
                _row_result(
                    label,
                    target,
                    status="ok",
                    to_status=desired,
                    offer_id=offer_id,
                )
            )
            continue

        if desired is ApplicationStatus.ACCEPTED:
            facts = state.facts[working.enrollment_id]
            constraints = evaluate_acceptance_constraints(
                outcome=working.outcome,
                cycle_kind=CycleKind.OPEN,
                placement_placed_global=(
                    facts.placement_placed_global
                    or working.enrollment_id in accepted_placement
                ),
                internship_placed_in_cycle=facts.internship_placed_in_cycle,
                max_accepted_offers=state.max_accepted_offers,
                cap_used=virtual_cap[working.enrollment_id],
                overrides=gate_overrides(
                    state.row_overrides.get(working.application_id, ())
                ),
            )
            if constraints.failures:
                results.append(
                    _row_result(
                        label,
                        target,
                        status="skipped",
                        reason=constraints.failures[0].code,
                    )
                )
                continue
            transition = decide_transition(
                "accept",
                from_status=working.status,
                to_status=desired,
                actor=TransitionActor.STAFF,
                context=TransitionContext(cycle_kind=CycleKind.OPEN),
            )
            if isinstance(transition, Rejection):
                results.append(
                    _row_result(label, target, status="skipped", reason=INVALID_TRANSITION)
                )
                continue
            if extension is not None:
                _append_mutation(extension, operations, events, deferred)
            all_for_enrollment = tuple(
                working if row.application_id == working.application_id else row
                for row in state.applications
                if row.enrollment_id == working.enrollment_id
            )
            acceptance = plan_acceptance(
                working,
                all_for_enrollment,
                offer_id=offer_id,
                now=state.now,
                applied_override_ids=constraints.applied_override_ids,
            )
            _append_mutation(acceptance, operations, events, deferred)
            virtually_changed.update(
                UUID(cast(str, item["application_id"])) for item in acceptance.cascade
            )
            if working.outcome is Outcome.PLACEMENT:
                accepted_placement.add(working.enrollment_id)
            virtual_cap[working.enrollment_id] += 1
            results.append(
                _row_result(
                    label,
                    target,
                    status="ok",
                    to_status=desired,
                    offer_id=offer_id,
                    cascade=acceptance.cascade,
                )
            )
            continue

        transition = decide_transition(
            "decline",
            from_status=working.status,
            to_status=ApplicationStatus.DECLINED,
            actor=TransitionActor.STAFF,
            context=TransitionContext(cycle_kind=CycleKind.OPEN),
        )
        if isinstance(transition, Rejection):
            results.append(
                _row_result(label, target, status="skipped", reason=INVALID_TRANSITION)
            )
            continue
        if extension is not None:
            _append_mutation(extension, operations, events, deferred)
        decline = plan_decline(working, offer_id=offer_id, now=state.now)
        _append_mutation(decline, operations, events, deferred)
        results.append(
            _row_result(
                label,
                target,
                status="ok",
                to_status=ApplicationStatus.DECLINED,
                offer_id=offer_id,
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
                "operation": "record_open_outcome",
                "target_status": input_value.target_status,
            },
        },
        summary={"rows": results},
    )


def register_offer_commands(registry: Registry) -> None:
    registry.command(
        name="extend_offers",
        input_model=ExtendOffersInput,
        output_model=BulkOfferSummary,
        actor="staff",
        scope="cycle",
        loader=_load_extend,
        rule_domains=(),
        spec_ids=("OFR-1", "OFR-2", "RND-2", "APP-4"),
        rate_limit="10/min",
        execution_mode="bulk",
    )(_decide_extend)
    registry.command(
        name="accept_offer",
        input_model=OfferResponseInput,
        output_model=OfferActionSummary,
        actor="student",
        scope="cycle",
        loader=_load_accept,
        rule_domains=(
            RuleDomain.OFFER_DEADLINE,
            RuleDomain.OUTCOME_GATE,
            RuleDomain.OFFER_CAP,
        ),
        spec_ids=("OFR-1", "OFR-3", "APP-4", "DER-1"),
    )(_decide_accept)
    registry.command(
        name="decline_offer",
        input_model=OfferResponseInput,
        output_model=OfferActionSummary,
        actor="student",
        scope="cycle",
        loader=_load_decline,
        rule_domains=(RuleDomain.OFFER_DEADLINE,),
        spec_ids=("OFR-1", "OFR-3", "APP-4"),
    )(_decide_decline)
    registry.command(
        name="record_open_outcome",
        input_model=RecordOpenOutcomeInput,
        output_model=BulkOfferSummary,
        actor="staff",
        scope="cycle",
        loader=_load_open_outcome,
        rule_domains=(RuleDomain.OUTCOME_GATE, RuleDomain.OFFER_CAP),
        spec_ids=("JOB-6", "OFR-1", "OFR-2", "OFR-3", "RND-2", "APP-4"),
        rate_limit="10/min",
        execution_mode="bulk",
    )(_decide_open_outcome)
