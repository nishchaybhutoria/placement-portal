"""Pure CYC-2 policy resolution and provenance contracts."""

import pytest

from app.domain.policy import resolve_policy
from app.domain.shared import CycleKind, OfferExpiry


@pytest.mark.parametrize(
    ("kind", "approval", "cap"),
    [
        (CycleKind.PLACEMENT, True, 1),
        (CycleKind.INTERNSHIP, True, 1),
        (CycleKind.OPEN, False, None),
    ],
)
def test_CYC2_kind_defaults_and_global_strike_default(
    kind: CycleKind, approval: bool, cap: int | None
) -> None:
    policy = resolve_policy(kind)
    assert policy.membership_requires_approval.value is approval
    assert policy.max_accepted_offers.value == cap
    assert policy.penalty_blocks_applications.value is True
    assert policy.allow_withdrawal_after_deadline.value is False
    assert policy.allow_edit_after_deadline.value is False
    assert policy.strike_on_absence.value is True
    assert policy.offer_expiry_behavior.value is OfferExpiry.AUTO_DECLINE
    assert policy.deadline_reminder_hours.value == 6
    assert policy.round_reminder_hours.value == 24
    assert policy.strikes_per_penalty.value == 2
    assert policy.membership_requires_approval.source == "default"
    assert policy.strikes_per_penalty.source == "default"


def test_CYC2_persisted_policy_and_setting_values_carry_provenance() -> None:
    policy = resolve_policy(
        CycleKind.PLACEMENT,
        cycle_policy={
            "membership_requires_approval": False,
            "join_rule": {"field": "cpi", "op": "gte", "value": 8},
            "max_accepted_offers": None,
            "penalty_blocks_applications": False,
            "allow_withdrawal_after_deadline": True,
            "allow_edit_after_deadline": True,
            "strike_on_absence": False,
            "offer_expiry_behavior": "auto_accept",
            "deadline_reminder_hours": 12,
            "round_reminder_hours": 48,
        },
        settings={"strikes_per_penalty": None},
    )
    assert policy.max_accepted_offers.value is None
    assert policy.max_accepted_offers.source == "cycle_policy"
    assert policy.offer_expiry_behavior.value is OfferExpiry.AUTO_ACCEPT
    assert policy.offer_expiry_behavior.source == "cycle_policy"
    assert policy.strikes_per_penalty.value is None
    assert policy.strikes_per_penalty.source == "setting"
    assert policy.join_rule.source == "cycle_policy"


@pytest.mark.parametrize(
    ("cycle_policy", "settings"),
    [
        ({"max_accepted_offers": 0}, {}),
        ({"deadline_reminder_hours": 0}, {}),
        ({"penalty_blocks_applications": "yes"}, {}),
        ({"offer_expiry_behavior": "invalid"}, {}),
        ({}, {"strikes_per_penalty": 0}),
    ],
)
def test_CYC2_policy_resolution_fails_closed_on_invalid_values(
    cycle_policy: dict[str, object], settings: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        resolve_policy(
            CycleKind.PLACEMENT,
            cycle_policy=cycle_policy,
            settings=settings,
        )
