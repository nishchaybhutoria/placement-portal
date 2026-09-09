"""Analytics screens (LLD section 11.3, Behavior ANA-2)."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.authz import require_staff_cycle
from app.core.plan import ActorContext
from app.core.registry import Registry
from app.modules.analytics.queries import (
    cycle_analytics,
    job_analytics,
    portal_analytics,
)


def _engine(request: Request) -> AsyncEngine:
    return cast(AsyncEngine, request.app.state.database_engine)



async def _cycle_analytics_screen(
    request: Request, id: UUID, actor: ActorContext
) -> dict[str, object]:
    require_staff_cycle(actor, id)
    body = await cycle_analytics(_engine(request), id)
    if body is None:
        raise HTTPException(status_code=404, detail="Cycle not found")
    return body


async def _portal_analytics_screen(request: Request) -> dict[str, object]:
    return await portal_analytics(_engine(request))


async def _job_analytics_screen(
    request: Request, id: UUID, actor: ActorContext
) -> dict[str, object]:
    body = await job_analytics(_engine(request), id)
    if body is None:
        raise HTTPException(status_code=404, detail="Job not found")
    # The cycle check happens after the load because the job is what names the
    # cycle: refusing before knowing which cycle it belongs to would deny a
    # coordinator their own job.  A missing job is a 404 either way.
    job = cast("dict[str, object]", body["job"])
    cycle = cast("dict[str, object]", job["cycle"])
    require_staff_cycle(actor, UUID(str(cycle["id"])))
    return body


def register_analytics_screens(registry: Registry) -> None:
    registry.screen(id="staff/cycle/{id}/analytics", roles=("staff",))(
        _cycle_analytics_screen
    )
    registry.screen(id="admin/analytics/portal", roles=("admin",))(
        _portal_analytics_screen
    )
    registry.screen(id="staff/job/{id}/analytics", roles=("staff",))(
        _job_analytics_screen
    )

