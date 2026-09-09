"""The venue upload route: parse-only, staff-only, and the round trip (RND-4)."""

from __future__ import annotations

import os
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.db import create_engine
from app.core.errors import INVALID_FIELD_VALUE
from app.main import create_app
from app.modules.identity.session import hash_session_token
from tests.applications.conftest import World, build_test_executor, seed_world
from tests.cycles.conftest import cycle_settings

pytestmark = pytest.mark.asyncio

CSV = (
    b"identifier,venue,time\n"
    b"21110001,AB 5 / 201,2026-03-14 09:30\n"
    b"nobody@example.edu,AB 5 / 204,14/03/2026 11:00\n"
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
            "token": hash_session_token(raw_token, cycle_settings().session_secret),
            "user_id": user_id,
        },
    )


async def _applied(world: World) -> UUID:
    executor, engine = build_test_executor()
    model = executor.registry.commands["apply"].input_model
    try:
        result = await executor.run(
            "apply",
            model.model_validate(
                {
                    "cycle_id": str(world.cycle_id),
                    "job_id": str(world.job_id),
                    "enrollment_id": str(world.student.enrollment_id),
                }
            ),
            world.student.actor,
        )
        return UUID(cast(str, cast(dict[str, object], result.summary)["application_id"]))
    finally:
        await engine.dispose()


async def test_RND4_the_upload_parses_rows_and_names_the_rows_it_cannot() -> None:
    """Parse-only: the route reports, the command decides (the design review section 4.5)."""
    world = await seed_world(with_rounds=True, with_staff=True)
    await _applied(world)
    token = "venue-upload-coordinator"
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            await _seed_session(connection, world.staff_actor.user_id or uuid4(), token)

        application = create_app(
            os.environ["TEST_DATABASE_URL"], settings=cycle_settings()
        )
        async with application.router.lifespan_context(application):
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(
                transport=transport, base_url="https://test"
            ) as client:
                client.cookies.set("cds_session", token)
                await client.get("/me")
                headers = {"X-CSRF": cast(str, client.cookies.get("cds_csrf"))}
                parsed = await client.post(
                    "/api/v1/uploads/venue-rows",
                    files={"file": ("slots.csv", CSV, "text/csv")},
                    headers=headers,
                )
    finally:
        await migration.dispose()

    assert parsed.status_code == 200
    body = parsed.json()
    assert [row["identifier"] for row in body["rows"]] == ["21110001"]
    # The unreadable time is named by row, not dropped and not guessed at.
    assert [(error["row_number"], error["code"]) for error in body["errors"]] == [
        (3, INVALID_FIELD_VALUE)
    ]


async def test_RND4_parsed_rows_go_straight_to_the_command() -> None:
    """The upload's rows are the command's rows: one format, one validator."""
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)
    token = "venue-upload-round-trip"
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            await _seed_session(connection, world.staff_actor.user_id or uuid4(), token)

        application = create_app(
            os.environ["TEST_DATABASE_URL"], settings=cycle_settings()
        )
        async with application.router.lifespan_context(application):
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(
                transport=transport, base_url="https://test"
            ) as client:
                client.cookies.set("cds_session", token)
                await client.get("/me")
                headers = {"X-CSRF": cast(str, client.cookies.get("cds_csrf"))}
                parsed = await client.post(
                    "/api/v1/uploads/venue-rows",
                    files={
                        "file": (
                            "slots.csv",
                            b"identifier,venue,time\n21110001,AB 5 / 201,2026-03-14 09:30\n",
                            "text/csv",
                        )
                    },
                    headers=headers,
                )
                rows = [
                    {
                        "identifier": row["identifier"],
                        "venue": row["venue"],
                        "time": row["time"],
                    }
                    for row in parsed.json()["rows"]
                ]
                body = {
                    "input": {
                        "cycle_id": str(world.cycle_id),
                        "job_id": str(world.job_id),
                        "round_id": str(world.round_id),
                        "rows": rows,
                        "batch_key": "upload-round-trip",
                    }
                }
                preview = await client.post(
                    "/api/v1/commands/assign_venue_timing",
                    json={**body, "dry_run": True},
                    headers=headers,
                )
                committed = await client.post(
                    "/api/v1/commands/assign_venue_timing", json=body, headers=headers
                )

        async with migration.connect() as connection:
            slot = (
                await connection.execute(
                    sa.text(
                        "SELECT venue_override, scheduled_at_override "
                        "FROM application_round_states WHERE application_id = :id"
                    ),
                    {"id": application_id},
                )
            ).mappings().one()
    finally:
        await migration.dispose()

    assert preview.status_code == 200
    assert committed.status_code == 200
    assert preview.json()["summary"]["rows"] == committed.json()["summary"]["rows"]
    assert slot["venue_override"] == "AB 5 / 201"
    assert slot["scheduled_at_override"] is not None


async def test_RND4_the_upload_route_is_staff_only_and_fails_closed() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    token = "venue-upload-student"
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            await _seed_session(connection, world.student.user_id, token)

        application = create_app(
            os.environ["TEST_DATABASE_URL"], settings=cycle_settings()
        )
        async with application.router.lifespan_context(application):
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(
                transport=transport, base_url="https://test"
            ) as client:
                anonymous = await client.post(
                    "/api/v1/uploads/venue-rows",
                    files={"file": ("slots.csv", CSV, "text/csv")},
                )
                client.cookies.set("cds_session", token)
                await client.get("/me")
                headers = {"X-CSRF": cast(str, client.cookies.get("cds_csrf"))}
                denied = await client.post(
                    "/api/v1/uploads/venue-rows",
                    files={"file": ("slots.csv", CSV, "text/csv")},
                    headers=headers,
                )
    finally:
        await migration.dispose()

    assert anonymous.status_code == 403
    assert denied.status_code == 403
