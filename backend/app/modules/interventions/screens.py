"""The staff drill-down on one enrollment (LLD section 11.3)."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.plan import ActorContext
from app.core.registry import Registry
from app.modules.interventions.queries import staff_student_record


async def _staff_student_screen(
    # ``actor`` is bound to a dependency by the route generator, so it must come
    # after every parameter that has no default of its own.
    request: Request,
    enrollment_id: UUID,
    actor: ActorContext,
) -> dict[str, object]:
    engine = cast(AsyncEngine, request.app.state.database_engine)
    return await staff_student_record(engine, actor, enrollment_id)


def register_intervention_screens(registry: Registry) -> None:
    registry.screen(id="staff/student/{enrollment_id}", roles=("staff",))(
        _staff_student_screen
    )
