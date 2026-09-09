"""The admin override register screen (Behavior INT-2, LLD section 11.3)."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.plan import ActorContext
from app.core.registry import Registry
from app.modules.overrides.queries import admin_overrides


async def _admin_overrides_screen(
    request: Request,
    actor: ActorContext,
    rule_domain: str | None = None,
    scope: str | None = None,
    cycle_id: UUID | None = None,
    state: str | None = None,
) -> dict[str, object]:
    engine = cast(AsyncEngine, request.app.state.database_engine)
    return await admin_overrides(
        engine,
        rule_domain=rule_domain,
        scope=scope,
        cycle_id=cycle_id,
        state=state,
        visible_cycle_ids=(
            None if actor.role == "admin" else actor.coordinated_cycle_ids
        ),
    )


def register_override_screens(registry: Registry) -> None:
    # `create_override` is `actor="staff"` (INT-2 grants it to staff of the
    # cycle), so the register has to be readable by the coordinator who granted
    # one; `admin_overrides` scopes their view to the cycles they coordinate.
    # The id keeps its name: renaming it churns the generated client and the
    # screen-dependency map for no change in behaviour.
    registry.screen(id="admin/overrides", roles=("staff",))(_admin_overrides_screen)
