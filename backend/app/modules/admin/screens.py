"""The admin consistency-findings screen (LLD sections 11.3 and 12)."""

from __future__ import annotations

from typing import cast

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.registry import Registry
from app.modules.admin.queries import admin_findings


async def _admin_findings_screen(
    request: Request, status: str | None = None, invariant: str | None = None
) -> dict[str, object]:
    engine = cast(AsyncEngine, request.app.state.database_engine)
    return await admin_findings(engine, status=status, invariant=invariant)


def register_admin_screens(registry: Registry) -> None:
    registry.screen(id="admin/findings", roles=("admin",))(_admin_findings_screen)
