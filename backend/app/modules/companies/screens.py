"""Company directory screens for Behavior section 4 (LLD section 11.3)."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.plan import ActorContext
from app.core.registry import Registry
from app.modules.analytics.queries import company_analytics
from app.modules.companies.queries import staff_companies, staff_company


async def _companies_screen(
    request: Request,
    q: str | None = None,
    sector_id: UUID | None = None,
    include_inactive: bool = False,
) -> dict[str, object]:
    engine = cast(AsyncEngine, request.app.state.database_engine)
    return await staff_companies(
        engine, query=q, sector_id=sector_id, include_inactive=include_inactive
    )


async def _company_screen(
    request: Request, id: UUID, actor: ActorContext
) -> dict[str, object]:
    """The directory record plus ANA-2's cross-cycle view of the same company.

    One screen rather than two, because LLD section 11.3 lists one and because
    the two halves answer the same question: a coordinator looking at a company
    wants its contacts and its hiring history on the same page.  The analytics
    half comes from the ANA-1 metrics like every other figure in the system.
    """
    engine = cast(AsyncEngine, request.app.state.database_engine)
    detail = await staff_company(engine, id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Company not found")
    analytics = await company_analytics(engine, id)
    if analytics is None:
        raise HTTPException(status_code=404, detail="Company not found")
    admin = actor.role == "admin"
    permission = {
        "allowed": admin,
        "reason": None,
        "human": None if admin else "Only an administrator can merge or change company activity.",
    }
    return {
        **detail,
        "analytics": analytics,
        "actions": {"manage_activity": permission, "merge": permission},
    }


def register_company_screens(registry: Registry) -> None:
    registry.screen(id="staff/companies", roles=("staff",))(_companies_screen)
    registry.screen(id="staff/company/{id}", roles=("staff",))(_company_screen)
