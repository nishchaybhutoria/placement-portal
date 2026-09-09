"""Registry-backed screen for the admin discipline surface (Behavior DIS)."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.registry import Registry
from app.modules.discipline.queries import admin_discipline


async def _admin_discipline_screen(
    request: Request, enrollment_id: UUID | None = None
) -> dict[str, object]:
    engine = cast(AsyncEngine, request.app.state.database_engine)
    return await admin_discipline(engine, enrollment_id=enrollment_id)


def register_discipline_screens(registry: Registry) -> None:
    registry.screen(id="admin/discipline", roles=("admin",))(_admin_discipline_screen)
