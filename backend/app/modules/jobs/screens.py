"""Job screens for the builder, the cycle list, and students (LLD section 11.3)."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.authz import require_staff_cycle
from app.core.errors import AuthorizationDenied
from app.core.plan import ActorContext
from app.core.registry import Registry
from app.modules.jobs.queries import (
    staff_cycle_jobs,
    staff_job_builder,
    student_cycle_jobs,
    student_job_detail,
)


def _engine(request: Request) -> AsyncEngine:
    return cast(AsyncEngine, request.app.state.database_engine)


def _enrollment(actor: ActorContext) -> UUID:
    if actor.current_enrollment_id is None:
        raise AuthorizationDenied(authenticated=actor.user_id is not None)
    return actor.current_enrollment_id


async def _cycle_jobs_screen(
    request: Request, id: UUID, actor: ActorContext, include_cancelled: bool = True
) -> dict[str, object]:
    require_staff_cycle(actor, id)
    jobs = await staff_cycle_jobs(
        _engine(request), id, include_cancelled=include_cancelled
    )
    if jobs is None:
        raise HTTPException(status_code=404, detail="Cycle not found")
    return jobs


async def _builder_screen(
    request: Request, id: UUID, cycle_id: UUID, actor: ActorContext
) -> dict[str, object]:
    # The builder is addressed by job and cycle together, and `staff_job_builder`
    # returns None unless the pair really matches -- so guarding the stated
    # cycle guards the job it is asked for.
    require_staff_cycle(actor, cycle_id)
    builder = await staff_job_builder(_engine(request), cycle_id=cycle_id, job_id=id)
    if builder is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return builder


async def _student_jobs_screen(
    request: Request, id: UUID, actor: ActorContext
) -> dict[str, object]:
    jobs = await student_cycle_jobs(
        _engine(request), cycle_id=id, enrollment_id=_enrollment(actor)
    )
    if jobs is None:
        raise HTTPException(status_code=404, detail="Cycle not found")
    return jobs


async def _student_job_screen(
    request: Request, id: UUID, actor: ActorContext
) -> dict[str, object]:
    detail = await student_job_detail(
        _engine(request), job_id=id, enrollment_id=_enrollment(actor)
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return detail


def register_job_screens(registry: Registry) -> None:
    registry.screen(id="staff/cycle/{id}/jobs", roles=("staff",))(_cycle_jobs_screen)
    registry.screen(id="staff/job/{id}/builder", roles=("staff",))(_builder_screen)
    registry.screen(id="cycle/{id}/jobs", roles=("student",))(_student_jobs_screen)
    registry.screen(id="job/{id}", roles=("student",))(_student_job_screen)
