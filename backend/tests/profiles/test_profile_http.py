"""Screens and the upload → preview → commit → report round trip (PRO-1/2/3)."""

from __future__ import annotations

import os
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.db import create_engine
from app.main import create_app
from app.modules.identity.session import hash_session_token
from tests.profiles.conftest import (
    DRIVE_URL,
    profiles_settings,
    seed_taxonomy,
)

pytestmark = pytest.mark.usefixtures("clean_profiles")

CSV = (
    b"Institute Email,Roll Number,CPI,Program,Primary Branch\n"
    b"student@example.edu,21110030,8.60,BTech,Computer Science and Engineering\n"
    b"newcomer@example.edu,21110031,9.10,BTech,Computer Science and Engineering\n"
    b"student@example.edu,21110032,7.00,BTech,Computer Science and Engineering\n"
)


async def _seed_session(
    connection: AsyncConnection, user_id: UUID, raw_token: str
) -> None:
    await connection.execute(
        sa.text(
            "INSERT INTO sessions (id, token_hash, user_id, expires_at) "
            "VALUES (:id, :token, :user_id, now() + interval '1 day')"
        ),
        {
            "id": uuid4(),
            "token": hash_session_token(raw_token, profiles_settings().session_secret),
            "user_id": user_id,
        },
    )


@pytest.mark.asyncio
async def test_PRO1_me_profile_screen_reports_ownership_and_the_resume_library() -> None:
    settings = profiles_settings()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    user_id, enrollment_id, resume_id = uuid4(), uuid4(), uuid4()
    raw_token = "me-profile-session-token"
    try:
        async with migration.begin() as connection:
            taxonomy = await seed_taxonomy(connection)
            await connection.execute(
                sa.text(
                    "INSERT INTO users (id, email, full_name, role) "
                    "VALUES (:id, 'student@example.edu', 'Screen Student', 'student')"
                ),
                {"id": user_id},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO enrollments (id, user_id, is_current, roll_number) "
                    "VALUES (:id, :user_id, true, '21110040')"
                ),
                {"id": enrollment_id, "user_id": user_id},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO profiles (enrollment_id, cpi, program_id, declared_at) "
                    "VALUES (:enrollment_id, 8.10, :program_id, now())"
                ),
                {"enrollment_id": enrollment_id, "program_id": taxonomy.program_id},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO resumes (id, enrollment_id, label, drive_url, is_default) "
                    "VALUES (:id, :enrollment_id, 'Primary', :url, true)"
                ),
                {"id": resume_id, "enrollment_id": enrollment_id, "url": DRIVE_URL},
            )
            await _seed_session(connection, user_id, raw_token)

        application = create_app(os.environ["TEST_DATABASE_URL"], settings=settings)
        async with application.router.lifespan_context(application):
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
                anonymous = await client.get("/api/v1/screens/me/profile")
                client.cookies.set("cds_session", raw_token)
                response = await client.get("/api/v1/screens/me/profile")
                forbidden = await client.get("/api/v1/screens/admin/bulk-upsert")
    finally:
        await migration.dispose()

    assert anonymous.status_code == 401
    assert forbidden.status_code == 403
    assert response.status_code == 200
    body = response.json()
    assert body["enrollment"]["institute_email"] == "student@example.edu"
    assert body["declared_at"] is not None
    assert body["values"]["cpi"] == "8.10"
    assert body["values"]["roll_number"] == "21110040"
    assert body["values"]["full_name"] == "Screen Student"
    owners = {item["key"]: item["owner"] for item in body["fields"]}
    assert owners["cpi"] == "admin"
    assert owners["contact_number"] == "student"
    assert body["resumes"] == [
        {
            "id": str(resume_id),
            "label": "Primary",
            "drive_url": DRIVE_URL,
            "is_default": True,
            "preview_url": (
                "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/preview"
            ),
        }
    ]


@pytest.mark.asyncio
async def test_PRO2_csv_round_trip_previews_commits_and_reports() -> None:
    settings = profiles_settings()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    admin_id, student_id, enrollment_id = uuid4(), uuid4(), uuid4()
    raw_token = "bulk-upsert-session-token"
    try:
        async with migration.begin() as connection:
            await seed_taxonomy(connection)
            await connection.execute(
                sa.text(
                    "INSERT INTO users (id, email, full_name, role) VALUES "
                    "(:admin, 'admin@example.edu', 'Administrator', 'admin'), "
                    "(:student, 'student@example.edu', 'Bulk Student', 'student')"
                ),
                {"admin": admin_id, "student": student_id},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO enrollments (id, user_id, is_current, roll_number) "
                    "VALUES (:id, :user_id, true, '21110030')"
                ),
                {"id": enrollment_id, "user_id": student_id},
            )
            await _seed_session(connection, admin_id, raw_token)

        application = create_app(os.environ["TEST_DATABASE_URL"], settings=settings)
        async with application.router.lifespan_context(application):
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
                client.cookies.set("cds_session", raw_token)
                await client.get("/me")
                csrf = client.cookies.get("cds_csrf")
                assert csrf is not None
                headers = {"X-CSRF": csrf}

                parsed = await client.post(
                    "/api/v1/uploads/profile-rows",
                    files={"file": ("load.csv", CSV, "text/csv")},
                    headers=headers,
                )
                rows = parsed.json()["rows"]
                body = {
                    "input": {"rows": rows, "batch_key": "round-trip"},
                }
                preview = await client.post(
                    "/api/v1/commands/bulk_upsert_profiles",
                    json={**body, "dry_run": True},
                    headers=headers,
                )
                committed = await client.post(
                    "/api/v1/commands/bulk_upsert_profiles",
                    json=body,
                    headers=headers,
                )
                screen = await client.get("/api/v1/screens/admin/bulk-upsert")

        async with migration.connect() as connection:
            cpi = await connection.scalar(
                sa.text("SELECT cpi FROM profiles WHERE enrollment_id = :id"),
                {"id": enrollment_id},
            )
    finally:
        await migration.dispose()

    assert parsed.status_code == 200
    # The duplicated address is caught at parse time and never reaches the command.
    assert [error["code"] for error in parsed.json()["errors"]] == [
        "duplicate_row",
        "duplicate_row",
    ]
    assert set(rows[0]["fields"]) == {"roll_number", "cpi", "program_id", "primary_branch_id"}
    assert [row["institute_email"] for row in rows] == ["newcomer@example.edu"]

    assert preview.status_code == 200
    assert [row["result"] for row in preview.json()["summary"]["rows"]] == ["staged"]
    assert committed.status_code == 200
    assert [row["result"] for row in committed.json()["summary"]["rows"]] == ["staged"]
    assert cpi is None

    staged = screen.json()["staged"]
    assert [row["institute_email"] for row in staged["pending"]] == ["newcomer@example.edu"]
    assert staged["pending"][0]["batch_key"] == "round-trip"
    assert staged["errored"] == []
    assert staged["applied"] == []
    assert {column["key"] for column in screen.json()["columns"]} >= {"cpi", "roll_number"}


@pytest.mark.asyncio
async def test_PRO2_upload_route_is_admin_only_and_fails_closed_on_bad_files() -> None:
    settings = profiles_settings()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    admin_id, student_id = uuid4(), uuid4()
    admin_token, student_token = "admin-upload-token", "student-upload-token"
    try:
        async with migration.begin() as connection:
            await connection.execute(
                sa.text(
                    "INSERT INTO users (id, email, full_name, role) VALUES "
                    "(:admin, 'admin@example.edu', 'Administrator', 'admin'), "
                    "(:student, 'student@example.edu', 'Student', 'student')"
                ),
                {"admin": admin_id, "student": student_id},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO enrollments (user_id, is_current) VALUES (:student, true)"
                ),
                {"student": student_id},
            )
            await _seed_session(connection, admin_id, admin_token)
            await _seed_session(connection, student_id, student_token)

        application = create_app(os.environ["TEST_DATABASE_URL"], settings=settings)
        async with application.router.lifespan_context(application):
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
                anonymous = await client.post(
                    "/api/v1/uploads/profile-rows",
                    files={"file": ("load.csv", CSV, "text/csv")},
                )
                client.cookies.set("cds_session", student_token)
                await client.get("/me")
                student_headers = {"X-CSRF": cast(str, client.cookies.get("cds_csrf"))}
                denied = await client.post(
                    "/api/v1/uploads/profile-rows",
                    files={"file": ("load.csv", CSV, "text/csv")},
                    headers=student_headers,
                )
                client.cookies.set("cds_session", admin_token)
                await client.get("/me")
                admin_headers = {"X-CSRF": cast(str, client.cookies.get("cds_csrf"))}
                unparsable = await client.post(
                    "/api/v1/uploads/profile-rows",
                    files={"file": ("load.pdf", b"%PDF-1.4", "application/pdf")},
                    headers=admin_headers,
                )
                no_csrf = await client.post(
                    "/api/v1/uploads/profile-rows",
                    files={"file": ("load.csv", CSV, "text/csv")},
                )
    finally:
        await migration.dispose()

    assert anonymous.status_code == 403
    assert denied.status_code == 403
    assert no_csrf.status_code == 403
    assert unparsable.status_code == 422
    assert unparsable.json()["reasons"][0]["code"] == "unparsable_upload"
