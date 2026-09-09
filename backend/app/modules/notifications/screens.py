"""Admin notification-template screen registration (Behavior NTF)."""

from __future__ import annotations

from typing import cast

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.errors import AuthorizationDenied
from app.core.plan import ActorContext
from app.core.registry import Registry
from app.modules.notifications.queries import admin_templates, me_notifications


async def _templates_screen(request: Request) -> dict[str, object]:
    engine = cast(AsyncEngine, request.app.state.database_engine)
    return await admin_templates(engine)


async def _my_notifications_screen(
    request: Request, actor: ActorContext
) -> dict[str, object]:
    engine = cast(AsyncEngine, request.app.state.database_engine)
    # Addressed by the email the notification was sent to, which is the only
    # thing notification_log records about a recipient. A session without one
    # cannot be shown somebody else's record by default.
    if actor.email is None:
        raise AuthorizationDenied(authenticated=actor.user_id is not None)
    return await me_notifications(engine, actor.email)


def register_notification_screens(registry: Registry) -> None:
    registry.screen(id="admin/templates", roles=("admin",))(_templates_screen)
    registry.screen(id="me/notifications", roles=("student",))(_my_notifications_screen)
