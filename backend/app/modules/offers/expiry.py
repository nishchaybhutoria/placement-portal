"""OFR-4 fire-time expiry enforcement through the command executor."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plan import (
    ActorContext,
    Deferred,
    Plan,
    Rejection,
    ScopeIds,
    StateOp,
)
from app.core.registry import Registry
from app.domain.gates import evaluate_expiry_acceptance_constraints
from app.domain.policy import resolve_policy
from app.domain.shared import (
    ApplicationStatus,
    CycleKind,
    MembershipStatus,
    OfferExpiry,
    OfferResponse,
    Outcome,
    RuleDomain,
)
from app.domain.transitions import ExpiryAction, ExpiryState, decide_expiry
from app.modules.admin.checker import suggested_fix_for
from app.modules.applications.verdict import gate_overrides
from app.modules.cycles.commands import fetch_policy
from app.modules.notifications.wording import expiry_outcome
from app.modules.offers.commands import _load_offer_applications
from app.modules.offers.derivations import OfferFacts, offer_facts
from app.modules.offers.locking import AcceptanceLockRequest, lock_acceptance_state
from app.modules.offers.planning import OfferApplication, plan_acceptance, plan_decline
from app.modules.overrides.service import ApplicableOverride

_EXPIRY_OFFER = """
    SELECT o.id AS offer_id, o.application_id, o.deadline_at, o.response,
           o.terminated_at, a.enrollment_id, a.status AS application_status,
           j.id AS job_id, j.cycle_id, j.outcome,
           c.kind AS cycle_kind, c.archived_at
    FROM offers o
    JOIN applications a ON a.id = o.application_id
    JOIN jobs j ON j.id = a.job_id
    JOIN cycles c ON c.id = j.cycle_id
    WHERE o.id = :offer_id
"""


class EnforceOfferExpiryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_id: UUID
    scheduled_deadline: datetime


class EnforceOfferExpirySummary(BaseModel):
    offer_id: UUID
    application_id: UUID | None
    action: ExpiryAction
    reschedule_at: datetime | None = None
    failed_gate_codes: list[str] = []
    applied_override_ids: list[UUID] = []
    cascade: list[dict[str, object]] = []


@dataclass(frozen=True, slots=True)
class ExpiryOfferRow:
    offer_id: UUID
    application_id: UUID
    deadline_at: datetime | None
    response: OfferResponse | None
    terminated: bool
    enrollment_id: UUID
    application_status: ApplicationStatus
    job_id: UUID
    cycle_id: UUID
    outcome: Outcome
    cycle_kind: CycleKind
    cycle_archived: bool


@dataclass(frozen=True, slots=True)
class ExpiryCommandState:
    scope_ids: ScopeIds
    cycle_archived: bool
    now: datetime
    offer: ExpiryOfferRow | None
    target: OfferApplication | None
    applications: tuple[OfferApplication, ...]
    facts: OfferFacts | None
    membership_active: bool
    behavior: OfferExpiry
    max_accepted_offers: int | None


def _expiry_offer(row: sa.RowMapping | None) -> ExpiryOfferRow | None:
    if row is None:
        return None
    return ExpiryOfferRow(
        offer_id=cast(UUID, row["offer_id"]),
        application_id=cast(UUID, row["application_id"]),
        deadline_at=cast("datetime | None", row["deadline_at"]),
        response=(
            OfferResponse(row["response"]) if row["response"] is not None else None
        ),
        terminated=row["terminated_at"] is not None,
        enrollment_id=cast(UUID, row["enrollment_id"]),
        application_status=ApplicationStatus(row["application_status"]),
        job_id=cast(UUID, row["job_id"]),
        cycle_id=cast(UUID, row["cycle_id"]),
        outcome=Outcome(row["outcome"]),
        cycle_kind=CycleKind(row["cycle_kind"]),
        cycle_archived=row["archived_at"] is not None,
    )


async def _fetch_expiry_offer(
    tx: AsyncSession, offer_id: UUID
) -> ExpiryOfferRow | None:
    row = (
        await tx.execute(sa.text(_EXPIRY_OFFER), {"offer_id": offer_id})
    ).mappings().one_or_none()
    return _expiry_offer(row)


async def _load_expiry(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> ExpiryCommandState:
    if not isinstance(input_value, EnforceOfferExpiryInput):
        raise TypeError("enforce_offer_expiry requires EnforceOfferExpiryInput")

    # The task knows only the Offer ID. This first lookup discovers immutable
    # relationship IDs; all row locks and every authoritative re-read happen
    # through the shared enrollment → offers → targets order below.
    identity = await _fetch_expiry_offer(tx, input_value.offer_id)
    if identity is not None:
        await lock_acceptance_state(
            tx,
            (
                AcceptanceLockRequest(
                    enrollment_id=identity.enrollment_id,
                    cycle_id=identity.cycle_id,
                    application_id=identity.application_id,
                    outcome=identity.outcome,
                    cycle_kind=identity.cycle_kind,
                ),
            ),
            lock=lock,
        )
    offer = await _fetch_expiry_offer(tx, input_value.offer_id)
    now = cast(datetime, await tx.scalar(sa.select(sa.func.now())))
    if offer is None:
        return ExpiryCommandState(
            scope_ids=ScopeIds(),
            cycle_archived=False,
            now=now,
            offer=None,
            target=None,
            applications=(),
            facts=None,
            membership_active=False,
            behavior=OfferExpiry.AUTO_DECLINE,
            max_accepted_offers=None,
        )

    applications = await _load_offer_applications(
        tx, enrollment_ids=(offer.enrollment_id,)
    )
    target = next(
        (
            application
            for application in applications
            if application.application_id == offer.application_id
        ),
        None,
    )
    facts = await offer_facts(tx, offer.enrollment_id, offer.cycle_id)
    membership_status = await tx.scalar(
        sa.text(
            "SELECT status FROM cycle_memberships "
            "WHERE cycle_id = :cycle_id AND enrollment_id = :enrollment_id"
        ),
        {"cycle_id": offer.cycle_id, "enrollment_id": offer.enrollment_id},
    )
    policy = resolve_policy(
        offer.cycle_kind,
        cycle_policy=await fetch_policy(tx, offer.cycle_id),
    )
    return ExpiryCommandState(
        scope_ids=ScopeIds(
            cycle_id=offer.cycle_id,
            job_id=offer.job_id,
            enrollment_id=offer.enrollment_id,
            application_id=offer.application_id,
        ),
        cycle_archived=offer.cycle_archived,
        now=now,
        offer=offer,
        target=target,
        applications=applications,
        facts=facts,
        membership_active=membership_status == MembershipStatus.ACTIVE.value,
        behavior=policy.offer_expiry_behavior.value,
        max_accepted_offers=policy.max_accepted_offers.value,
    )


def _summary(
    input_value: EnforceOfferExpiryInput,
    state: ExpiryCommandState,
    *,
    action: ExpiryAction,
    reschedule_at: datetime | None = None,
    failed_gate_codes: tuple[str, ...] = (),
    applied_override_ids: tuple[UUID, ...] = (),
    cascade: tuple[dict[str, object], ...] = (),
) -> dict[str, object]:
    return {
        "offer_id": str(input_value.offer_id),
        "application_id": (
            str(state.offer.application_id) if state.offer is not None else None
        ),
        "action": action.value,
        "reschedule_at": reschedule_at.isoformat() if reschedule_at else None,
        "failed_gate_codes": list(failed_gate_codes),
        "applied_override_ids": [str(item) for item in applied_override_ids],
        "cascade": list(cascade),
    }


def _audit(
    input_value: EnforceOfferExpiryInput,
    action: ExpiryAction,
    failed_gate_codes: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "subject_type": "offer",
        "subject_id": input_value.offer_id,
        "details": {
            "operation": "enforce_offer_expiry",
            "action": action.value,
            "scheduled_deadline": input_value.scheduled_deadline.isoformat(),
            "failed_gate_codes": list(failed_gate_codes),
        },
    }


def _decide_expiry(
    input_value: BaseModel,
    state: object,
    _policy: object,
    overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    if not isinstance(input_value, EnforceOfferExpiryInput) or not isinstance(
        state, ExpiryCommandState
    ):
        raise TypeError("Invalid enforce_offer_expiry decision input")
    if state.offer is None or state.target is None or state.cycle_archived:
        return Plan(
            state_ops=[],
            events=[],
            deferred=[],
            audit=_audit(input_value, ExpiryAction.NOOP),
            summary=_summary(input_value, state, action=ExpiryAction.NOOP),
        )
    assert state.facts is not None

    resolved_overrides = gate_overrides(
        cast("tuple[ApplicableOverride, ...]", overrides)
    )
    standing = evaluate_expiry_acceptance_constraints(
        membership_active=state.membership_active,
        outcome=state.offer.outcome,
        cycle_kind=state.offer.cycle_kind,
        placement_placed_global=state.facts.placement_placed_global,
        internship_placed_in_cycle=state.facts.internship_placed_in_cycle,
        max_accepted_offers=state.max_accepted_offers,
        cap_used=state.facts.cap_used,
        overrides=resolved_overrides,
    )
    pure = decide_expiry(
        ExpiryState(
            offer_id=state.offer.offer_id,
            application_id=state.offer.application_id,
            application_status=state.offer.application_status,
            is_latest_offer=state.target.current_offer_id == state.offer.offer_id,
            response=state.offer.response,
            terminated=state.offer.terminated,
            deadline_at=state.offer.deadline_at,
            scheduled_deadline=input_value.scheduled_deadline,
            now=state.now,
            cycle_kind=state.offer.cycle_kind,
            behavior=state.behavior,
            gate_failures=(
                standing.failures
                if state.behavior is OfferExpiry.AUTO_ACCEPT
                else ()
            ),
        )
    )
    if pure.action is ExpiryAction.NOOP:
        return Plan(
            state_ops=[],
            events=[],
            deferred=[],
            audit=_audit(input_value, pure.action),
            summary=_summary(input_value, state, action=pure.action),
        )
    if pure.action is ExpiryAction.RESCHEDULE:
        assert pure.reschedule_at is not None
        deferred = Deferred(
            task="enforce_offer_expiry",
            args={
                "offer_id": str(state.offer.offer_id),
                "scheduled_deadline": pure.reschedule_at.isoformat(),
            },
            schedule_at=pure.reschedule_at,
        )
        return Plan(
            state_ops=[],
            events=[],
            deferred=[deferred],
            audit=_audit(input_value, pure.action),
            summary=_summary(
                input_value,
                state,
                action=pure.action,
                reschedule_at=pure.reschedule_at,
            ),
        )

    gate_codes = tuple(reason.code for reason in standing.failures)
    if pure.action in {
        ExpiryAction.AUTO_DECLINE,
        ExpiryAction.AUTO_DECLINE_GATE_FALLBACK,
    }:
        fallback = pure.action is ExpiryAction.AUTO_DECLINE_GATE_FALLBACK
        planned = plan_decline(
            state.target,
            offer_id=state.offer.offer_id,
            now=state.now,
            event_key="offer_expired",
            reason="Offer expired",
            system_initiated=True,
            payload_extra={"failed_gate_codes": list(gate_codes)} if fallback else None,
            notification_context_extra={"behavior": expiry_outcome(state.behavior.value)},
        )
        operations = list(planned.state_ops)
        if fallback:
            assert pure.finding is not None
            finding_id = uuid5(
                NAMESPACE_URL,
                "cds:expiry-finding:"
                f"{state.offer.offer_id}:{input_value.scheduled_deadline.isoformat()}",
            )
            # The subject carries what the compensating command needs, and the
            # command name comes from the one catalog `admin/findings` reads, so
            # this finding gets the same working one-click fix as every finding
            # the nightly checker raises (the design review section 4.29).
            subject = {
                **pure.finding.subject,
                "cycle_id": str(state.offer.cycle_id),
                "job_id": str(state.offer.job_id),
                "expected_status": ApplicationStatus.DECLINED.value,
            }
            fix = suggested_fix_for(pure.finding.invariant)
            operations.append(
                StateOp(
                    op="insert",
                    model="consistency_findings",
                    values={
                        "id": finding_id,
                        "invariant": pure.finding.invariant,
                        "subject": subject,
                        "detail": pure.finding.detail,
                        "suggested_fix": fix.command if fix is not None else None,
                    },
                )
            )
        return Plan(
            state_ops=operations,
            events=list(planned.events),
            deferred=list(planned.deferred),
            audit=_audit(input_value, pure.action, gate_codes),
            summary=_summary(
                input_value,
                state,
                action=pure.action,
                failed_gate_codes=gate_codes if fallback else (),
                applied_override_ids=standing.applied_override_ids,
            ),
        )

    assert pure.action is ExpiryAction.AUTO_ACCEPT
    planned_acceptance = plan_acceptance(
        state.target,
        state.applications,
        offer_id=state.offer.offer_id,
        now=state.now,
        applied_override_ids=standing.applied_override_ids,
        system_initiated=True,
    )
    return Plan(
        state_ops=list(planned_acceptance.state_ops),
        events=list(planned_acceptance.events),
        deferred=list(planned_acceptance.deferred),
        audit=_audit(input_value, pure.action),
        summary=_summary(
            input_value,
            state,
            action=pure.action,
            applied_override_ids=standing.applied_override_ids,
            cascade=planned_acceptance.cascade,
        ),
    )


def register_expiry_commands(registry: Registry) -> None:
    registry.command(
        name="enforce_offer_expiry",
        input_model=EnforceOfferExpiryInput,
        output_model=EnforceOfferExpirySummary,
        actor="system",
        scope="none",
        loader=_load_expiry,
        rule_domains=(RuleDomain.OUTCOME_GATE, RuleDomain.OFFER_CAP),
        spec_ids=("OFR-3", "OFR-4", "DER-1"),
        expose_http=False,
    )(_decide_expiry)
