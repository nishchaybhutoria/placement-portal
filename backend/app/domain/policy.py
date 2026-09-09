"""Pure CYC-2 policy resolution with value provenance."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from app.domain.shared import CycleKind, OfferExpiry

PolicySource = Literal["cycle_policy", "setting", "default"]
_MISSING = object()


@dataclass(frozen=True, slots=True)
class ResolvedValue[T]:
    value: T
    source: PolicySource


@dataclass(frozen=True, slots=True)
class Policy:
    membership_requires_approval: ResolvedValue[bool]
    join_rule: ResolvedValue[object | None]
    max_accepted_offers: ResolvedValue[int | None]
    penalty_blocks_applications: ResolvedValue[bool]
    allow_withdrawal_after_deadline: ResolvedValue[bool]
    allow_edit_after_deadline: ResolvedValue[bool]
    strike_on_absence: ResolvedValue[bool]
    offer_expiry_behavior: ResolvedValue[OfferExpiry]
    deadline_reminder_hours: ResolvedValue[int]
    round_reminder_hours: ResolvedValue[int]
    strikes_per_penalty: ResolvedValue[int | None]


_CYCLE_DEFAULTS: dict[str, object] = {
    "join_rule": None,
    "penalty_blocks_applications": True,
    "allow_withdrawal_after_deadline": False,
    "allow_edit_after_deadline": False,
    "strike_on_absence": True,
    "offer_expiry_behavior": OfferExpiry.AUTO_DECLINE,
    "deadline_reminder_hours": 6,
    "round_reminder_hours": 24,
}


def resolve_policy(
    cycle_kind: CycleKind,
    *,
    cycle_policy: Mapping[str, object] | None = None,
    settings: Mapping[str, object] | None = None,
) -> Policy:
    """Merge persisted values over documented defaults without losing NULL caps."""
    cycle_values = cycle_policy or {}
    setting_values = settings or {}
    kind_defaults = {
        "membership_requires_approval": cycle_kind is not CycleKind.OPEN,
        "max_accepted_offers": None if cycle_kind is CycleKind.OPEN else 1,
    }

    return Policy(
        membership_requires_approval=_cycle_value(
            cycle_values,
            "membership_requires_approval",
            kind_defaults["membership_requires_approval"],
            bool,
        ),
        join_rule=_cycle_object(cycle_values, "join_rule", _CYCLE_DEFAULTS["join_rule"]),
        max_accepted_offers=_nullable_positive_int(
            cycle_values,
            "max_accepted_offers",
            cast(int | None, kind_defaults["max_accepted_offers"]),
            "cycle_policy",
        ),
        penalty_blocks_applications=_cycle_value(
            cycle_values,
            "penalty_blocks_applications",
            _CYCLE_DEFAULTS["penalty_blocks_applications"],
            bool,
        ),
        allow_withdrawal_after_deadline=_cycle_value(
            cycle_values,
            "allow_withdrawal_after_deadline",
            _CYCLE_DEFAULTS["allow_withdrawal_after_deadline"],
            bool,
        ),
        allow_edit_after_deadline=_cycle_value(
            cycle_values,
            "allow_edit_after_deadline",
            _CYCLE_DEFAULTS["allow_edit_after_deadline"],
            bool,
        ),
        strike_on_absence=_cycle_value(
            cycle_values,
            "strike_on_absence",
            _CYCLE_DEFAULTS["strike_on_absence"],
            bool,
        ),
        offer_expiry_behavior=_expiry_value(cycle_values),
        deadline_reminder_hours=_positive_int(
            cycle_values,
            "deadline_reminder_hours",
            cast(int, _CYCLE_DEFAULTS["deadline_reminder_hours"]),
            "cycle_policy",
        ),
        round_reminder_hours=_positive_int(
            cycle_values,
            "round_reminder_hours",
            cast(int, _CYCLE_DEFAULTS["round_reminder_hours"]),
            "cycle_policy",
        ),
        strikes_per_penalty=_nullable_positive_int(
            setting_values,
            "strikes_per_penalty",
            2,
            "setting",
        ),
    )


def _cycle_value[T](
    values: Mapping[str, object], key: str, default: object, expected: type[T]
) -> ResolvedValue[T]:
    raw = values.get(key, _MISSING)
    if raw is _MISSING:
        return ResolvedValue(cast(T, default), "default")
    if expected is bool and not isinstance(raw, bool):
        raise ValueError(f"{key} must be a boolean")
    if not isinstance(raw, expected):
        raise ValueError(f"{key} has an invalid type")
    return ResolvedValue(cast(T, raw), "cycle_policy")


def _cycle_object(
    values: Mapping[str, object], key: str, default: object
) -> ResolvedValue[object | None]:
    if key not in values:
        return ResolvedValue(default, "default")
    return ResolvedValue(values[key], "cycle_policy")


def _positive_int(
    values: Mapping[str, object],
    key: str,
    default: int,
    persisted_source: Literal["cycle_policy", "setting"],
) -> ResolvedValue[int]:
    raw = values.get(key, _MISSING)
    if raw is _MISSING:
        return ResolvedValue(default, "default")
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise ValueError(f"{key} must be a positive integer")
    return ResolvedValue(raw, persisted_source)


def _nullable_positive_int(
    values: Mapping[str, object],
    key: str,
    default: int | None,
    persisted_source: Literal["cycle_policy", "setting"],
) -> ResolvedValue[int | None]:
    raw = values.get(key, _MISSING)
    if raw is _MISSING:
        return ResolvedValue(default, "default")
    if raw is not None and (isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0):
        raise ValueError(f"{key} must be a positive integer or null")
    return ResolvedValue(raw, persisted_source)


def _expiry_value(values: Mapping[str, object]) -> ResolvedValue[OfferExpiry]:
    raw = values.get("offer_expiry_behavior", _MISSING)
    if raw is _MISSING:
        return ResolvedValue(OfferExpiry.AUTO_DECLINE, "default")
    try:
        value = raw if isinstance(raw, OfferExpiry) else OfferExpiry(str(raw))
    except ValueError as error:
        raise ValueError("offer_expiry_behavior is invalid") from error
    return ResolvedValue(value, "cycle_policy")
