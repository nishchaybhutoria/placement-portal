"""Directory screens, including the first path-parameter screen (CMP)."""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.db import create_engine
from app.main import create_app
from app.modules.identity.session import hash_session_token
from tests.companies.conftest import (
    company_settings,
    seed_company,
    seed_contact,
    seed_external_offer,
    seed_job,
    seed_sector,
)

pytestmark = pytest.mark.usefixtures("clean_companies")


async def _seed_staff(
    connection: AsyncConnection, *, role: str, raw_token: str
) -> UUID:
    user_id, session_id = uuid4(), uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO users (id, email, full_name, role) "
            "VALUES (:id, :email, 'Directory User', :role)"
        ),
        {"id": user_id, "email": f"{user_id}@example.edu", "role": role},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO sessions (id, token_hash, user_id, expires_at) "
            "VALUES (:id, :token, :user_id, now() + interval '1 day')"
        ),
        {
            "id": session_id,
            "token": hash_session_token(raw_token, company_settings().session_secret),
            "user_id": user_id,
        },
    )
    return user_id


@pytest.mark.asyncio
async def test_CMP_the_directory_screen_filters_by_name_sector_and_active_flag() -> None:
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    admin_token = "directory-admin-token"
    try:
        async with migration.begin() as connection:
            await _seed_staff(connection, role="admin", raw_token=admin_token)
            technology = await seed_sector(connection, "Technology")
            finance = await seed_sector(connection, "Finance")
            acme = await seed_company(connection, "Acme Analytics")
            await connection.execute(
                sa.text("UPDATE companies SET sector_id = :sector WHERE id = :id"),
                {"sector": technology, "id": acme},
            )
            bank = await seed_company(connection, "Bharat Bank")
            await connection.execute(
                sa.text("UPDATE companies SET sector_id = :sector WHERE id = :id"),
                {"sector": finance, "id": bank},
            )
            retired = await seed_company(connection, "Acme Retired", is_active=False)
            await seed_contact(
                connection, acme, name="Recruiter", email="hire@acme.example", is_primary=True
            )
            await seed_job(connection, acme, title="Analyst")

        application = create_app(os.environ["TEST_DATABASE_URL"], settings=company_settings())
        async with application.router.lifespan_context(application):
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
                anonymous = await client.get("/api/v1/screens/staff/companies")
                client.cookies.set("cds_session", admin_token)
                picker = await client.get("/api/v1/screens/staff/companies")
                searched = await client.get("/api/v1/screens/staff/companies?q=acme")
                by_sector = await client.get(
                    f"/api/v1/screens/staff/companies?sector_id={finance}"
                )
                with_inactive = await client.get(
                    "/api/v1/screens/staff/companies?include_inactive=true&q=acme"
                )
    finally:
        await migration.dispose()

    assert anonymous.status_code == 401
    assert picker.status_code == 200
    # The default response is the job picker: inactive companies are absent.
    assert [row["name"] for row in picker.json()["companies"]] == [
        "Acme Analytics",
        "Bharat Bank",
    ]
    assert [row["name"] for row in searched.json()["companies"]] == ["Acme Analytics"]
    assert [row["name"] for row in by_sector.json()["companies"]] == ["Bharat Bank"]
    assert [row["name"] for row in with_inactive.json()["companies"]] == [
        "Acme Analytics",
        "Acme Retired",
    ]

    listed = picker.json()["companies"][0]
    assert listed["sector"] == {"id": str(technology), "name": "Technology"}
    assert listed["contact_count"] == 1
    assert listed["job_count"] == 1
    assert listed["primary_contact"] == {"name": "Recruiter", "email": "hire@acme.example"}
    assert {row["name"] for row in picker.json()["sectors"]} == {"Technology", "Finance"}
    assert retired is not None


@pytest.mark.asyncio
async def test_CMP_the_company_screen_binds_its_path_parameter() -> None:
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    staff_token = "directory-coordinator-token"
    student_token = "directory-student-token"
    try:
        async with migration.begin() as connection:
            admin_id = await _seed_staff(connection, role="admin", raw_token=staff_token)
            student_id = await _seed_staff(connection, role="student", raw_token=student_token)
            await connection.execute(
                sa.text(
                    "INSERT INTO enrollments (user_id, is_current) VALUES (:id, true)"
                ),
                {"id": student_id},
            )
            sector_id = await seed_sector(connection, "Technology")
            company_id = await seed_company(connection, "Acme Analytics")
            await connection.execute(
                sa.text("UPDATE companies SET sector_id = :sector WHERE id = :id"),
                {"sector": sector_id, "id": company_id},
            )
            await seed_contact(
                connection, company_id, name="Second", email="second@acme.example"
            )
            await seed_contact(
                connection,
                company_id,
                name="Primary",
                email="primary@acme.example",
                phone="+1 202-555-0100",
                designation="Campus Lead",
                is_primary=True,
            )
            await seed_job(connection, company_id, title="Analyst")
            await seed_external_offer(connection, company_id, created_by=admin_id)

        application = create_app(os.environ["TEST_DATABASE_URL"], settings=company_settings())
        async with application.router.lifespan_context(application):
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
                client.cookies.set("cds_session", student_token)
                denied = await client.get(f"/api/v1/screens/staff/company/{company_id}")
                client.cookies.set("cds_session", staff_token)
                detail = await client.get(f"/api/v1/screens/staff/company/{company_id}")
                missing = await client.get(f"/api/v1/screens/staff/company/{uuid4()}")
                malformed = await client.get("/api/v1/screens/staff/company/not-a-uuid")
    finally:
        await migration.dispose()

    assert denied.status_code == 403
    assert missing.status_code == 404
    assert malformed.status_code == 422
    assert malformed.json()["reasons"][0]["path"] == "path.id"

    assert detail.status_code == 200
    body = detail.json()
    assert body["company"]["name"] == "Acme Analytics"
    assert body["company"]["sector"]["name"] == "Technology"
    # The primary contact leads the list; phone and designation travel with it.
    assert [row["name"] for row in body["contacts"]] == ["Primary", "Second"]
    assert body["contacts"][0]["phone"] == "+1 202-555-0100"
    assert body["contacts"][0]["designation"] == "Campus Lead"
    assert [row["title"] for row in body["jobs"]] == ["Analyst"]
    assert body["jobs"][0]["is_published"] is False
    assert body["external_offer_count"] == 1
