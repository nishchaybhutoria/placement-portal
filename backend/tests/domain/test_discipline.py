"""Pure DIS strike conversion and revoke-recompute contracts."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.domain.discipline import (
    PenaltyState,
    StrikeState,
    maybe_convert,
    recompute_after_revoke,
)

BASE = datetime(2027, 3, 1, tzinfo=UTC)
PENALTY = UUID(int=601)


def _strike(
    number: int,
    *,
    consumed_by: UUID | None = None,
    active: bool = True,
    age: int | None = None,
) -> StrikeState:
    return StrikeState(
        id=UUID(int=number),
        reason=f"reason-{number}",
        created_at=BASE + timedelta(minutes=number if age is None else age),
        is_active=active,
        consumed_by_penalty_id=consumed_by,
    )


@pytest.mark.parametrize(("count", "expected_groups"), [(1, 0), (2, 1), (5, 2)])
def test_DIS_conversion_below_at_and_above_threshold(count: int, expected_groups: int) -> None:
    groups = maybe_convert(tuple(_strike(index + 1) for index in range(count)), 2)
    assert len(groups) == expected_groups
    assert all(len(group.strike_ids) == 2 for group in groups)


def test_DIS_conversion_is_oldest_first_and_ignores_inactive_or_consumed() -> None:
    strikes = (
        _strike(1, age=30),
        _strike(2, age=10),
        _strike(3, active=False, age=1),
        _strike(4, consumed_by=PENALTY, age=2),
        _strike(5, age=20),
    )
    groups = maybe_convert(strikes, 2)
    assert [strike_id.int for strike_id in groups[0].strike_ids] == [2, 5]
    assert groups[0].reasons == "reason-2; reason-5"


def test_DIS_null_threshold_disables_conversion() -> None:
    assert maybe_convert(tuple(_strike(index) for index in range(1, 5)), None) == ()


def test_DIS_revoke_dissolves_unsupported_penalty_and_unconsumes_support() -> None:
    strikes = tuple(_strike(index, consumed_by=PENALTY) for index in range(1, 4))
    result = recompute_after_revoke(
        strikes=strikes,
        penalties=(PenaltyState(PENALTY, from_strikes=True),),
        revoked_strike_id=UUID(int=1),
        threshold=3,
    )
    assert len(result.dissolutions) == 1
    assert result.dissolutions[0].penalty_id == PENALTY
    assert [item.int for item in result.dissolutions[0].unconsume_strike_ids] == [1, 2, 3]
    assert result.conversions == ()


def test_DIS_revoke_with_null_threshold_dissolves_only_zero_support_penalty() -> None:
    only_support = (_strike(1, consumed_by=PENALTY),)
    zero_support = recompute_after_revoke(
        strikes=only_support,
        penalties=(PenaltyState(PENALTY, from_strikes=True),),
        revoked_strike_id=UUID(int=1),
        threshold=None,
    )
    remaining_support = recompute_after_revoke(
        strikes=(
            _strike(1, consumed_by=PENALTY),
            _strike(2, consumed_by=PENALTY),
        ),
        penalties=(PenaltyState(PENALTY, from_strikes=True),),
        revoked_strike_id=UUID(int=1),
        threshold=None,
    )
    assert [item.penalty_id for item in zero_support.dissolutions] == [PENALTY]
    assert zero_support.conversions == ()
    assert remaining_support.dissolutions == ()
    assert remaining_support.conversions == ()


def test_DIS_revoke_does_not_dissolve_direct_or_still_supported_penalty() -> None:
    strikes = tuple(_strike(index, consumed_by=PENALTY) for index in range(1, 4))
    direct = recompute_after_revoke(
        strikes=strikes,
        penalties=(PenaltyState(PENALTY, from_strikes=False),),
        revoked_strike_id=UUID(int=1),
        threshold=3,
    )
    supported = recompute_after_revoke(
        strikes=strikes,
        penalties=(PenaltyState(PENALTY, from_strikes=True),),
        revoked_strike_id=UUID(int=1),
        threshold=2,
    )
    assert direct.dissolutions == ()
    assert supported.dissolutions == ()


def test_DIS_invalid_threshold_fails_closed() -> None:
    with pytest.raises(ValueError):
        maybe_convert((_strike(1),), 0)
