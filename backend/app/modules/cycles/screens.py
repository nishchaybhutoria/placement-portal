"""Cycle and membership screens for Behavior CYC-1 and CYC-3."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.authz import require_staff_cycle
from app.core.errors import AuthorizationDenied
from app.core.plan import ActorContext
from app.core.registry import Registry
from app.modules.cycles.queries import (
    cycles_joinable,
    staff_cycle,
    staff_cycle_approvals,
    staff_cycles,
)


def _admin_control(actor: ActorContext) -> dict[str, object]:
    allowed = actor.role == "admin"
    return {
        "allowed": allowed,
        "reason": None,
        "human": None if allowed else "Only an administrator can manage cycle settings.",
    }


async def _cycles_screen(
    request: Request,
    actor: ActorContext,
    kind: str | None = None,
    include_archived: bool = False,
) -> dict[str, object]:
    engine = cast(AsyncEngine, request.app.state.database_engine)
    result = await staff_cycles(
        engine,
        kind=kind,
        include_archived=include_archived,
        # A coordinator's list is their cycles; an administrator's is every one.
        cycle_ids=None if actor.role == "admin" else actor.coordinated_cycle_ids,
    )
    result["actions"] = {"create": _admin_control(actor)}
    return result


async def _cycle_screen(
    request: Request, id: UUID, actor: ActorContext
) -> dict[str, object]:
    require_staff_cycle(actor, id)
    engine = cast(AsyncEngine, request.app.state.database_engine)
    detail = await staff_cycle(engine, id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Cycle not found")
    detail["actions"] = {"manage": _admin_control(actor)}
    return detail


async def _approvals_screen(
    request: Request, id: UUID, actor: ActorContext, status: str = "pending"
) -> dict[str, object]:
    require_staff_cycle(actor, id)
    engine = cast(AsyncEngine, request.app.state.database_engine)
    queue = await staff_cycle_approvals(engine, actor, id, status=status)
    if queue is None:
        raise HTTPException(status_code=404, detail="Cycle not found")
    return queue


async def _joinable_screen(request: Request, actor: ActorContext) -> dict[str, object]:
    engine = cast(AsyncEngine, request.app.state.database_engine)
    if actor.current_enrollment_id is None:
        raise AuthorizationDenied(authenticated=actor.user_id is not None)
    return await cycles_joinable(engine, actor.current_enrollment_id)


def register_cycle_screens(registry: Registry) -> None:
    registry.screen(id="staff/cycles", roles=("staff",))(_cycles_screen)
    registry.screen(id="staff/cycle/{id}", roles=("staff",))(_cycle_screen)
    registry.screen(id="staff/cycle/{id}/approvals", roles=("staff",))(_approvals_screen)
    registry.screen(id="cycles/joinable", roles=("student",))(_joinable_screen)
