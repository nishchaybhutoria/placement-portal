"""Read-only screen queries for taxonomy administration."""

from __future__ import annotations

from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from app.modules.taxonomies.commands import TaxonomyKind


async def admin_taxonomies(engine: AsyncEngine) -> dict[str, object]:
    result: dict[str, object] = {}
    async with engine.connect() as connection:
        for kind in TaxonomyKind:
            rows = (
                await connection.execute(
                    sa.text(
                        f"SELECT id, name, is_active FROM {kind.value} "  # noqa: S608
                        "ORDER BY name, id"
                    )
                )
            ).mappings().all()
            result[kind.value] = [
                {
                    "id": str(row["id"]),
                    "name": str(row["name"]),
                    "is_active": bool(row["is_active"]),
                }
                for row in rows
            ]
        mappings = (
            await connection.execute(
                sa.text(
                    "SELECT program_id, branch_id FROM program_branches "
                    "ORDER BY program_id, branch_id"
                )
            )
        ).mappings().all()
    result["program_branches"] = [
        {
            "program_id": str(cast(UUID, row["program_id"])),
            "branch_id": str(cast(UUID, row["branch_id"])),
        }
        for row in mappings
    ]
    return result


async def admin_settings(engine: AsyncEngine) -> dict[str, object]:
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                sa.text(
                    "SELECT key, value, updated_by, updated_at FROM settings ORDER BY key"
                )
            )
        ).mappings().all()
    return {
        "settings": [
            {
                "key": str(row["key"]),
                "value": row["value"],
                "updated_by": str(row["updated_by"])
                if row["updated_by"] is not None
                else None,
                "updated_at": row["updated_at"].isoformat(),
            }
            for row in rows
        ]
    }
