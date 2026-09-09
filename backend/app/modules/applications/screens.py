"""Registry-backed screens for the student's own applications (APP-3)."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.authz import require_staff_cycle
from app.core.errors import AuthorizationDenied
from app.core.plan import ActorContext
from app.core.registry import Registry
from app.modules.applications.queries import me_applications, staff_job_board


async def _me_applications_screen(
    request: Request, actor: ActorContext
) -> dict[str, object]:
    engine = cast(AsyncEngine, request.app.state.database_engine)
    if actor.current_enrollment_id is None:
        raise AuthorizationDenied(authenticated=actor.user_id is not None)
    return await me_applications(engine, actor.current_enrollment_id)


async def _staff_job_board_screen(
    request: Request, id: UUID, actor: ActorContext
) -> dict[str, object]:
    engine = cast(AsyncEngine, request.app.state.database_engine)
    board = await staff_job_board(engine, id)
    if board is None:
        raise HTTPException(status_code=404, detail="Job not found")
    # The board is addressed by job alone, so its cycle is only known once the
    # payload is built; the scope check is against that, not against anything
    # the caller supplied.
    require_staff_cycle(actor, UUID(str(cast(dict[str, object], board["cycle"])["id"])))
    return board


def register_application_screens(registry: Registry) -> None:
    registry.screen(id="me/applications", roles=("student",))(_me_applications_screen)
    registry.screen(id="staff/job/{id}/board", roles=("staff",))(_staff_job_board_screen)
