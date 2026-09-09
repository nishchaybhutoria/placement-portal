"""Registry-backed screens for Behavior PRO-1, PRO-2, and PRO-3."""

from __future__ import annotations

from typing import cast

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.errors import AuthorizationDenied
from app.core.plan import ActorContext
from app.core.registry import Registry
from app.modules.profiles.queries import admin_bulk_upsert, me_profile


async def _me_profile_screen(request: Request, actor: ActorContext) -> dict[str, object]:
    engine = cast(AsyncEngine, request.app.state.database_engine)
    if actor.current_enrollment_id is None:
        raise AuthorizationDenied(authenticated=actor.user_id is not None)
    return await me_profile(engine, actor.current_enrollment_id)


async def _admin_bulk_upsert_screen(request: Request) -> dict[str, object]:
    engine = cast(AsyncEngine, request.app.state.database_engine)
    return await admin_bulk_upsert(engine)


def register_profile_screens(registry: Registry) -> None:
    registry.screen(id="me/profile", roles=("student",))(_me_profile_screen)
    registry.screen(id="admin/bulk-upsert", roles=("admin",))(_admin_bulk_upsert_screen)
