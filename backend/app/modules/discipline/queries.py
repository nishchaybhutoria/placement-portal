"""The admin discipline surface (Behavior DIS, LLD section 11.3).

A searchable roster of enrollments, including clean students so an admin can
award the first strike or penalty, and — when one is named — the full history
behind them. Every control the screen offers reports the answer its own command
would give, computed by the same predicate rather than re-derived here
(the design review section 4.22).
"""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.plan import Reason
from app.domain.policy import resolve_policy
from app.domain.shared import CycleKind
from app.modules.discipline.awards import (
    PenaltyRow,
    StrikeRow,
    load_discipline,
    penalty_revocable,
    strike_revocable,
)

_ROSTER = """
    WITH strike_counts AS (
        SELECT enrollment_id, count(*) FILTER (WHERE is_active) AS active
        FROM strikes GROUP BY enrollment_id
    ), penalty_counts AS (
        SELECT enrollment_id, count(*) FILTER (WHERE is_active) AS active
        FROM penalties GROUP BY enrollment_id
    )
    SELECT
        e.id AS enrollment_id, u.full_name, u.email, e.roll_number, e.is_current,
        COALESCE(s.active, 0) AS active_strikes,
        COALESCE(p.active, 0) AS active_penalties
    FROM enrollments e
    JOIN users u ON u.id = e.user_id
    LEFT JOIN strike_counts s ON s.enrollment_id = e.id
    LEFT JOIN penalty_counts p ON p.enrollment_id = e.id
    WHERE e.is_current OR s.enrollment_id IS NOT NULL OR p.enrollment_id IS NOT NULL
    ORDER BY
        (COALESCE(s.active, 0) > 0 OR COALESCE(p.active, 0) > 0) DESC,
        u.full_name, e.id
"""


async def admin_discipline(
    engine: AsyncEngine, *, enrollment_id: UUID | None = None
) -> dict[str, object]:
    """The roster, plus one student's panel when the caller names one."""
    async with engine.connect() as connection:
        roster = (await connection.execute(sa.text(_ROSTER))).mappings().all()
        settings_rows = (
            (await connection.execute(sa.text("SELECT key, value FROM settings"))).mappings().all()
        )
        panel: dict[str, object] | None = None
        if enrollment_id is not None:
            records = await load_discipline(connection, [enrollment_id])
            record = records.get(enrollment_id)
            if record is not None:
                panel = _panel(record)

    settings = {str(row["key"]): row["value"] for row in settings_rows}
    resolved = resolve_policy(
        # The knob is global; the kind is irrelevant to it.
        CycleKind.PLACEMENT,
        settings=settings,
    ).strikes_per_penalty
    if panel is not None:
        panel["strikes_to_next_penalty"] = _to_next(
            cast(int, panel["unconsumed_strikes"]), resolved.value
        )
    return {
        "threshold": {"value": resolved.value, "source": resolved.source},
        "roster": [
            {
                "enrollment_id": str(cast(UUID, row["enrollment_id"])),
                "full_name": str(row["full_name"]),
                "email": str(row["email"]),
                "roll_number": str(row["roll_number"]) if row["roll_number"] else None,
                "is_current": bool(row["is_current"]),
                "active_strikes": int(row["active_strikes"]),
                "active_penalties": int(row["active_penalties"]),
                # What the gate will actually do, where a cycle turns it on.
                "blocked": int(row["active_penalties"]) > 0,
            }
            for row in roster
        ],
        "student": panel,
    }


def _panel(record: object) -> dict[str, object]:
    from app.modules.discipline.awards import EnrollmentDiscipline

    assert isinstance(record, EnrollmentDiscipline)
    unconsumed = sum(
        1 for strike in record.strikes if strike.is_active and strike.consumed_by_penalty_id is None
    )
    return {
        "enrollment_id": str(record.enrollment_id),
        "full_name": record.full_name,
        "email": record.email,
        "roll_number": record.roll_number,
        "active_strikes": record.active_strikes(),
        "active_penalties": record.active_penalties(),
        "unconsumed_strikes": unconsumed,
        "strikes": [_strike(strike) for strike in record.strikes],
        "penalties": [_penalty(penalty) for penalty in record.penalties],
    }


def _to_next(unconsumed: int, threshold: int | None) -> int | None:
    """How many more strikes convert, or None when conversion is disabled."""
    if threshold is None:
        return None
    return threshold - (unconsumed % threshold)


def _strike(strike: StrikeRow) -> dict[str, object]:
    return {
        "id": str(strike.id),
        "reason": strike.reason,
        "source": strike.source.value,
        "created_at": _iso(strike.created_at),
        "updated_at": _iso(strike.updated_at),
        "awarded_by": (
            {"id": str(strike.awarded_by), "name": strike.awarded_by_name}
            if strike.awarded_by is not None
            else None
        ),
        "is_active": strike.is_active,
        "consumed_by_penalty_id": (
            str(strike.consumed_by_penalty_id)
            if strike.consumed_by_penalty_id is not None
            else None
        ),
        "actions": {"revoke": _permission(strike_revocable(strike))},
    }


def _penalty(penalty: PenaltyRow) -> dict[str, object]:
    return {
        "id": str(penalty.id),
        "reasons": penalty.reasons,
        "from_strikes": penalty.from_strikes,
        "created_at": _iso(penalty.created_at),
        "created_by": (
            {"id": str(penalty.created_by), "name": penalty.created_by_name}
            if penalty.created_by is not None
            else None
        ),
        "is_active": penalty.is_active,
        "revoked_at": _iso(penalty.revoked_at),
        "revoked_by": (
            {"id": str(penalty.revoked_by), "name": penalty.revoked_by_name}
            if penalty.revoked_by is not None
            else None
        ),
        "actions": {"revoke": _permission(penalty_revocable(penalty))},
    }


def _permission(reason: Reason | None) -> dict[str, object]:
    return {
        "allowed": reason is None,
        "reason": reason.code if reason is not None else None,
        "human": reason.human if reason is not None else None,
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
