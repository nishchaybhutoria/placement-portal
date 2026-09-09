"""Pure strike conversion and revoke recomputation for Behavior DIS."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class StrikeState:
    id: UUID
    reason: str
    created_at: datetime
    is_active: bool = True
    consumed_by_penalty_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class PenaltyState:
    id: UUID
    from_strikes: bool
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class StrikeConversionGroup:
    strike_ids: tuple[UUID, ...]
    reasons: str


@dataclass(frozen=True, slots=True)
class DissolvePenalty:
    penalty_id: UUID
    unconsume_strike_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class RecomputeResult:
    dissolutions: tuple[DissolvePenalty, ...]
    conversions: tuple[StrikeConversionGroup, ...]


def maybe_convert(
    strikes: tuple[StrikeState, ...], threshold: int | None
) -> tuple[StrikeConversionGroup, ...]:
    """Group every complete active/unconsumed threshold, oldest first."""
    if threshold is None:
        return ()
    if threshold <= 0:
        raise ValueError("strike conversion threshold must be positive or null")
    available = sorted(
        (
            strike
            for strike in strikes
            if strike.is_active and strike.consumed_by_penalty_id is None
        ),
        key=lambda strike: (strike.created_at, strike.id.int),
    )
    complete_count = len(available) // threshold
    return tuple(
        StrikeConversionGroup(
            strike_ids=tuple(
                strike.id for strike in available[index * threshold : (index + 1) * threshold]
            ),
            reasons="; ".join(
                strike.reason for strike in available[index * threshold : (index + 1) * threshold]
            ),
        )
        for index in range(complete_count)
    )


def recompute_after_revoke(
    *,
    strikes: tuple[StrikeState, ...],
    penalties: tuple[PenaltyState, ...],
    revoked_strike_id: UUID,
    threshold: int | None,
) -> RecomputeResult:
    """Dissolve unsupported automatic penalties, unconsume, then regroup strikes."""
    if threshold is not None and threshold <= 0:
        raise ValueError("strike conversion threshold must be positive or null")

    revoked = next((strike for strike in strikes if strike.id == revoked_strike_id), None)
    if revoked is None:
        raise ValueError("revoked strike is not present in the snapshot")

    penalty_by_id = {penalty.id: penalty for penalty in penalties}
    linked_penalty_id = revoked.consumed_by_penalty_id
    dissolution_ids: set[UUID] = set()
    if linked_penalty_id is not None:
        penalty = penalty_by_id.get(linked_penalty_id)
        if penalty is not None and penalty.is_active and penalty.from_strikes:
            support_count = sum(
                1
                for strike in strikes
                if strike.id != revoked_strike_id
                and strike.is_active
                and strike.consumed_by_penalty_id == linked_penalty_id
            )
            if support_count == 0 or (threshold is not None and support_count < threshold):
                dissolution_ids.add(linked_penalty_id)

    dissolutions = tuple(
        DissolvePenalty(
            penalty_id=penalty_id,
            unconsume_strike_ids=tuple(
                strike.id
                for strike in sorted(strikes, key=lambda item: (item.created_at, item.id.int))
                if strike.consumed_by_penalty_id == penalty_id
            ),
        )
        for penalty_id in sorted(dissolution_ids, key=lambda item: item.int)
    )

    recomputed: list[StrikeState] = []
    for strike in strikes:
        consumed = strike.consumed_by_penalty_id
        if consumed in dissolution_ids:
            consumed = None
        recomputed.append(
            StrikeState(
                id=strike.id,
                reason=strike.reason,
                created_at=strike.created_at,
                is_active=strike.is_active and strike.id != revoked_strike_id,
                consumed_by_penalty_id=consumed,
            )
        )
    return RecomputeResult(
        dissolutions=dissolutions,
        conversions=maybe_convert(tuple(recomputed), threshold),
    )
