"""Read-only screen queries for the company directory (Behavior section 4)."""

from __future__ import annotations

from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

_LIST_SQL = """
    SELECT
        c.id,
        c.name,
        c.description,
        c.website_url,
        c.is_active,
        c.sector_id,
        s.name AS sector_name,
        (SELECT count(*) FROM company_contacts cc WHERE cc.company_id = c.id) AS contact_count,
        (SELECT count(*) FROM jobs j WHERE j.company_id = c.id) AS job_count,
        (
            SELECT cc.name FROM company_contacts cc
            WHERE cc.company_id = c.id AND cc.is_primary
        ) AS primary_contact_name,
        (
            SELECT cc.email FROM company_contacts cc
            WHERE cc.company_id = c.id AND cc.is_primary
        ) AS primary_contact_email
    FROM companies c
    LEFT JOIN sectors s ON s.id = c.sector_id
    WHERE (:include_inactive OR c.is_active)
      AND (CAST(:sector_id AS uuid) IS NULL OR c.sector_id = CAST(:sector_id AS uuid))
      AND (CAST(:query AS text) IS NULL OR c.name ILIKE '%' || CAST(:query AS text) || '%')
    ORDER BY c.name, c.id
"""


async def staff_companies(
    engine: AsyncEngine,
    *,
    query: str | None = None,
    sector_id: UUID | None = None,
    include_inactive: bool = False,
) -> dict[str, object]:
    """The directory list; the default response is the picker (inactive hidden)."""
    normalized = query.strip() if query and query.strip() else None
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                sa.text(_LIST_SQL),
                {
                    "include_inactive": include_inactive,
                    "sector_id": sector_id,
                    "query": normalized,
                },
            )
        ).mappings().all()
        sectors = (
            await connection.execute(
                sa.text("SELECT id, name FROM sectors WHERE is_active ORDER BY name, id")
            )
        ).mappings().all()
    return {
        "filters": {
            "q": normalized,
            "sector_id": str(sector_id) if sector_id else None,
            "include_inactive": include_inactive,
        },
        "sectors": [
            {"id": str(cast(UUID, row["id"])), "name": str(row["name"])} for row in sectors
        ],
        "companies": [
            {
                "id": str(cast(UUID, row["id"])),
                "name": str(row["name"]),
                "description": row["description"],
                "website_url": row["website_url"],
                "is_active": bool(row["is_active"]),
                "sector": (
                    {"id": str(cast(UUID, row["sector_id"])), "name": str(row["sector_name"])}
                    if row["sector_id"] is not None
                    else None
                ),
                "contact_count": int(row["contact_count"]),
                "job_count": int(row["job_count"]),
                "primary_contact": (
                    {
                        "name": str(row["primary_contact_name"]),
                        "email": str(row["primary_contact_email"]),
                    }
                    if row["primary_contact_name"] is not None
                    else None
                ),
            }
            for row in rows
        ],
    }


async def staff_company(engine: AsyncEngine, company_id: UUID) -> dict[str, object] | None:
    async with engine.connect() as connection:
        company = (
            await connection.execute(
                sa.text(
                    "SELECT c.id, c.name, c.description, c.website_url, c.is_active, "
                    "c.sector_id, s.name AS sector_name, c.created_at, c.updated_at "
                    "FROM companies c LEFT JOIN sectors s ON s.id = c.sector_id "
                    "WHERE c.id = :id"
                ),
                {"id": company_id},
            )
        ).mappings().one_or_none()
        if company is None:
            return None
        contacts = (
            await connection.execute(
                sa.text(
                    "SELECT id, name, email, phone, designation, is_primary "
                    "FROM company_contacts WHERE company_id = :id "
                    "ORDER BY is_primary DESC, name, id"
                ),
                {"id": company_id},
            )
        ).mappings().all()
        jobs = (
            await connection.execute(
                sa.text(
                    "SELECT j.id, j.title, j.outcome, j.is_published, j.cancelled_at, "
                    "cy.id AS cycle_id, cy.name AS cycle_name "
                    "FROM jobs j JOIN cycles cy ON cy.id = j.cycle_id "
                    "WHERE j.company_id = :id ORDER BY j.created_at DESC, j.id"
                ),
                {"id": company_id},
            )
        ).mappings().all()
        external_offers = await connection.scalar(
            sa.text("SELECT count(*) FROM external_offers WHERE company_id = :id"),
            {"id": company_id},
        )
    return {
        "company": {
            "id": str(company_id),
            "name": str(company["name"]),
            "description": company["description"],
            "website_url": company["website_url"],
            "is_active": bool(company["is_active"]),
            "sector": (
                {
                    "id": str(cast(UUID, company["sector_id"])),
                    "name": str(company["sector_name"]),
                }
                if company["sector_id"] is not None
                else None
            ),
        },
        "contacts": [
            {
                "id": str(cast(UUID, row["id"])),
                "name": str(row["name"]),
                "email": str(row["email"]),
                "phone": row["phone"],
                "designation": row["designation"],
                "is_primary": bool(row["is_primary"]),
            }
            for row in contacts
        ],
        "jobs": [
            {
                "id": str(cast(UUID, row["id"])),
                "title": str(row["title"]),
                "outcome": str(row["outcome"]),
                "is_published": bool(row["is_published"]),
                "is_cancelled": row["cancelled_at"] is not None,
                "cycle": {
                    "id": str(cast(UUID, row["cycle_id"])),
                    "name": str(row["cycle_name"]),
                },
            }
            for row in jobs
        ],
        "external_offer_count": int(external_offers or 0),
    }
