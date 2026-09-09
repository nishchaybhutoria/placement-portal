"""Resolve the taxonomy ids a rule names to their display names (ELG-2).

A stored rule addresses programs, branches, and minors by id.  Every place a
rule is shown to a person -- the builder's summary, a student's ineligibility
reasons, a staff impact preview -- needs those ids as names, so all of them
resolve through here rather than each inventing a join.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

# Every taxonomy a RuleField can point at, plus the two a job itself names.
_LABEL_TABLES = ("programs", "branches", "minors", "sectors", "round_types")
_LABEL_QUERY = " UNION ALL ".join(
    f"SELECT id, name FROM {table} WHERE id = ANY(:ids)"  # noqa: S608
    for table in _LABEL_TABLES
)


async def resolve_labels(
    connection: AsyncConnection | AsyncSession, ids: Iterable[UUID]
) -> dict[UUID, str]:
    """Name every id that exists; a missing id is simply absent from the map.

    Callers fall back to rendering the raw UUID, so a rule naming a deleted
    program still renders instead of failing.
    """
    wanted = list(dict.fromkeys(ids))
    if not wanted:
        return {}
    rows = (
        await connection.execute(sa.text(_LABEL_QUERY), {"ids": wanted})
    ).mappings().all()
    return {row["id"]: str(row["name"]) for row in rows}
