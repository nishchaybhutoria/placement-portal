"""Registry-backed taxonomy and settings screens for Behavior TAX."""

from __future__ import annotations

from typing import cast

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.registry import Registry
from app.modules.taxonomies.queries import admin_settings, admin_taxonomies


async def _taxonomies_screen(request: Request) -> dict[str, object]:
    engine = cast(AsyncEngine, request.app.state.database_engine)
    return await admin_taxonomies(engine)


async def _settings_screen(request: Request) -> dict[str, object]:
    engine = cast(AsyncEngine, request.app.state.database_engine)
    return await admin_settings(engine)


def register_taxonomy_screens(registry: Registry) -> None:
    registry.screen(id="admin/taxonomies", roles=("admin",))(_taxonomies_screen)
    # The same lists, readable by a coordinator.  Building a job means picking a
    # sector, naming round types and writing an ELG-2 rule over programs and
    # branches, so the job builder cannot function without them -- and it was
    # reading the admin id, which 403s for the coordinators JOB-1 gives the
    # builder to.  Editing a taxonomy stays admin-only: that is `upsert_taxonomy_item`,
    # not this screen.
    registry.screen(id="staff/taxonomies", roles=("staff",))(_taxonomies_screen)
    registry.screen(id="admin/settings", roles=("admin",))(_settings_screen)
