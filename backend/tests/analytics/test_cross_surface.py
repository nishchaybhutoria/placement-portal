"""Layer D: no two surfaces may report different numbers for one cycle.

The equivalence suites prove the metrics agree with the derivations.  This one
proves the *screens* agree with each other, over real HTTP, which is the form
the failure actually takes: a coordinator reads 12 placed on the cycle page,
opens the jobs beneath it, adds them up and gets 11, and now nobody trusts
either page.  Screens compose the metrics rather than recomputing them, so this
should hold by construction -- which is exactly why it is worth asserting, as
the moment it stops holding is the moment somebody has started recomputing.
"""

from __future__ import annotations

import os
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.main import create_app
from app.modules.identity.session import hash_session_token
from app.settings import Settings
from tests.analytics.conftest import (
    DefinitionWorld,
    build_definition_world,
    seed_person,
)

pytestmark = pytest.mark.asyncio

STAFF_TOKEN = "cross-surface-staff-token"


def _settings() -> Settings:
    return Settings(
        session_secret="cross-surface-session-secret-32-characters",
        dev_login=False,
    )


async def _world_with_staff() -> tuple[DefinitionWorld, UUID]:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            world = await build_definition_world(connection)
            staff = await seed_person(connection, email="cross-staff@example.edu")
            await connection.execute(
                sa.text(
                    "INSERT INTO cycle_coordinators (id, cycle_id, user_id) "
                    "VALUES (gen_random_uuid(), :cycle, :user)"
                ),
                {"cycle": world.cycle_id, "user": staff.user_id},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO sessions (id, token_hash, user_id, expires_at) "
                    "VALUES (gen_random_uuid(), :hash, :user, now() + interval '1 day')"
                ),
                {
                    "hash": hash_session_token(
                        STAFF_TOKEN, _settings().session_secret
                    ),
                    "user": staff.user_id,
                },
            )
            return world, staff.user_id
    finally:
        await engine.dispose()


async def _screen(path: str) -> Any:
    app = create_app(os.environ["TEST_DATABASE_URL"], settings=_settings())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://cross.test",
        cookies={"cds_session": STAFF_TOKEN},
    ) as client:
        response = await client.get(f"/api/v1/screens/{path}")
    assert response.status_code == 200, f"{path}: {response.status_code} {response.text[:300]}"
    return response.json()


async def test_ANA2_the_cycle_page_and_its_job_pages_report_one_placed_figure(
    clean_cycles: None,
) -> None:
    """Cycle placed = the jobs' accepted students + the cycle's attached externals."""
    world, _staff = await _world_with_staff()

    cycle_body = await _screen(f"staff/cycle/{world.cycle_id}/analytics")
    placed = cast("dict[str, Any]", cycle_body["funnel"]["placed"])

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            job_ids = (
                await connection.execute(
                    sa.text("SELECT id FROM jobs WHERE cycle_id = :cycle"),
                    {"cycle": world.cycle_id},
                )
            ).scalars().all()
    finally:
        await engine.dispose()

    from_jobs = 0
    for job_id in job_ids:
        job_body = await _screen(f"staff/job/{job_id}/analytics")
        from_jobs += int(job_body["funnel"]["accepted"])

    assert from_jobs == placed["split"]["portal"], (
        "the portal half of the cycle's placed figure must be what its own job "
        "pages add up to; a coordinator will do this arithmetic"
    )
    assert placed["split"]["portal"] + placed["split"]["external"] == placed["total"]


async def test_ANA2_the_cycle_breakdowns_sum_to_the_cycle_funnel(
    clean_cycles: None,
) -> None:
    """Every breakdown is a partition, so its column totals are the funnel's."""
    world, _staff = await _world_with_staff()
    body = await _screen(f"staff/cycle/{world.cycle_id}/analytics")
    funnel = cast("dict[str, Any]", body["funnel"])
    breakdowns = cast("dict[str, Any]", body["breakdowns"])

    for dimension in ("program", "branch", "gender"):
        rows = cast("list[dict[str, Any]]", breakdowns[dimension])
        for metric in ("registered", "applied", "offered"):
            assert sum(int(row[metric]) for row in rows) == funnel[metric], (
                f"the {dimension} breakdown's {metric} column must sum to the "
                "funnel above it -- it is a partition of the same cohort"
            )
        assert sum(int(row["placed"]) for row in rows) == funnel["placed"]["total"]


async def test_ANA2_the_company_page_agrees_with_the_cycle_it_hired_into(
    clean_cycles: None,
) -> None:
    """A company's placed figure is the same number the cycle page counted."""
    world, _staff = await _world_with_staff()
    cycle_body = await _screen(f"staff/cycle/{world.cycle_id}/analytics")
    top = cast("list[dict[str, Any]]", cycle_body["top_companies"])
    assert top, "the fixture places students, so the ranking cannot be empty"

    # Ranked by placed students, ties broken by name (the design review 4.30q), and
    # summing to the cycle's placed total because it groups the same attributed
    # acceptances.
    assert sum(int(row["placed"]) for row in top) == (
        cycle_body["funnel"]["placed"]["total"]
    )

    company_id = top[0]["company_id"]
    company_body = await _screen(f"staff/company/{company_id}")
    history = cast("list[dict[str, Any]]", company_body["analytics"]["compensation_history"])
    this_cycle = [
        row for row in history if row["cycle_id"] == str(world.cycle_id)
    ]
    if this_cycle:
        assert int(this_cycle[0]["placed"]["total"]) == int(top[0]["placed"]), (
            "the company's per-cycle placed figure and the cycle's ranking of "
            "that company are the same count of the same students"
        )
