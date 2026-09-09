"""Pure OFR-4 offer-expiry decisions."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.core.errors import OFFER_CAP_REACHED, OUTCOME_GATE_PLACEMENT
from app.core.plan import Reason
from app.domain.shared import ApplicationStatus, CycleKind, OfferExpiry, OfferResponse
from app.domain.transitions import ExpiryAction, ExpiryState, decide_expiry

NOW = datetime(2027, 2, 1, tzinfo=UTC)


def _due() -> ExpiryState:
    deadline = NOW - timedelta(minutes=1)
    return ExpiryState(
        offer_id=UUID(int=401),
        application_id=UUID(int=402),
        application_status=ApplicationStatus.OFFERED,
        is_latest_offer=True,
        response=None,
        terminated=False,
        deadline_at=deadline,
        scheduled_deadline=deadline,
        now=NOW,
        cycle_kind=CycleKind.PLACEMENT,
        behavior=OfferExpiry.AUTO_DECLINE,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"application_status": ApplicationStatus.ACCEPTED},
        {"is_latest_offer": False},
        {"response": OfferResponse.DECLINED},
        {"terminated": True},
        {"deadline_at": None},
        {"cycle_kind": CycleKind.OPEN},
    ],
)
def test_OFR4_expiry_revalidation_noops_when_offer_is_no_longer_actionable(
    changes: dict[str, object],
) -> None:
    assert decide_expiry(replace(_due(), **changes)).action is ExpiryAction.NOOP


def test_OFR4_deadline_move_or_early_execution_reschedules() -> None:
    moved = NOW + timedelta(hours=2)
    moved_result = decide_expiry(replace(_due(), deadline_at=moved))
    early_result = decide_expiry(replace(_due(), deadline_at=moved, scheduled_deadline=moved))
    assert moved_result.action is ExpiryAction.RESCHEDULE
    assert moved_result.reschedule_at == moved
    assert early_result.action is ExpiryAction.RESCHEDULE
    assert early_result.reschedule_at == moved


def test_OFR4_policy_honors_auto_decline_and_auto_accept() -> None:
    assert decide_expiry(_due()).action is ExpiryAction.AUTO_DECLINE
    accepted = decide_expiry(replace(_due(), behavior=OfferExpiry.AUTO_ACCEPT))
    assert accepted.action is ExpiryAction.AUTO_ACCEPT
    assert accepted.finding is None


@pytest.mark.parametrize("code", [OFFER_CAP_REACHED, OUTCOME_GATE_PLACEMENT])
def test_OFR4_any_auto_accept_gate_failure_declines_and_creates_finding(
    code: str,
) -> None:
    decision = decide_expiry(
        replace(
            _due(),
            behavior=OfferExpiry.AUTO_ACCEPT,
            gate_failures=(Reason(code, "gate failed", "gate"),),
        )
    )
    assert decision.action is ExpiryAction.AUTO_DECLINE_GATE_FALLBACK
    assert decision.finding is not None
    assert decision.finding.invariant == "offer_expiry_auto_accept_gate_failed"
    assert code in decision.finding.detail
