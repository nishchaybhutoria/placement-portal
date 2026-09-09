"""The penalty gate, live for the first time (DIS, APP-1, ELG-1).

``domain/gates`` has enforced ``penalty_blocks_applications`` since M5 and
``verdict.py`` has read the real ``penalties`` table since M10 -- both correct
by emptiness, because nothing could write a penalty row until M11.  These are
the tests that the gate actually bites now that ``award_penalty`` exists
(the design review section 4.25).
"""

from __future__ import annotations

import os
from typing import cast
from uuid import UUID

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import PENALTY_ACTIVE, DomainRejection
from app.core.plan import Result
from app.modules.jobs.queries import student_cycle_jobs
from tests.applications.conftest import World, seed_world
from tests.discipline.conftest import build_test_executor

pytestmark = pytest.mark.asyncio


async def _execute(statement: str, params: dict[str, object]) -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(sa.text(statement), params)
    finally:
        await engine.dispose()


async def _admin_actor(world: World) -> object:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    sa.text(
                        "SELECT u.id, s.id AS session_id FROM users u "
                        "JOIN sessions s ON s.user_id = u.id WHERE u.role = 'admin'"
                    )
                )
            ).mappings().one()
    finally:
        await engine.dispose()
    from app.core.plan import ActorContext

    return ActorContext(
        principal_id=str(row["id"]),
        user_id=cast(UUID, row["id"]),
        role="admin",
        session_id=cast(UUID, row["session_id"]),
    )


async def _penalise(world: World) -> None:
    executor, engine = build_test_executor()
    model = executor.registry.commands["award_penalty"].input_model
    try:
        await executor.run(
            "award_penalty",
            model.model_validate(
                {
                    "enrollment_id": str(world.student.enrollment_id),
                    "reasons": "Two absences",
                }
            ),
            await _admin_actor(world),  # type: ignore[arg-type]
        )
    finally:
        await engine.dispose()


async def _apply(world: World) -> Result:
    executor, engine = build_test_executor()
    model = executor.registry.commands["apply"].input_model
    try:
        return cast(
            Result,
            await executor.run(
                "apply",
                model.model_validate(
                    {
                        "cycle_id": str(world.cycle_id),
                        "job_id": str(world.job_id),
                        "enrollment_id": str(world.student.enrollment_id),
                    }
                ),
                world.student.actor,
            ),
        )
    finally:
        await engine.dispose()


async def test_DIS_an_active_penalty_blocks_applying_where_the_policy_is_on() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    await _penalise(world)

    with pytest.raises(DomainRejection) as rejection:
        await _apply(world)

    assert PENALTY_ACTIVE in [
        reason.code for reason in rejection.value.rejection.reasons
    ]


async def test_DIS_the_same_penalty_blocks_nothing_where_the_policy_is_off() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    await _penalise(world)
    await _execute(
        "UPDATE cycle_policies SET penalty_blocks_applications = false "
        "WHERE cycle_id = :id",
        {"id": world.cycle_id},
    )

    result = await _apply(world)

    assert result.summary["application_id"]


async def test_DIS_a_revoked_penalty_stops_blocking() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    await _penalise(world)
    await _execute(
        "UPDATE penalties SET is_active = false, revoked_at = now() "
        "WHERE enrollment_id = :id",
        {"id": world.student.enrollment_id},
    )

    result = await _apply(world)

    assert result.summary["application_id"]


async def test_ELG1_the_job_card_names_the_penalty_the_command_would_refuse() -> None:
    """The card and `apply` must agree, in the direction that matters here."""
    world = await seed_world(with_rounds=True, with_staff=True)
    await _penalise(world)

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        cards = await student_cycle_jobs(
            engine,
            cycle_id=world.cycle_id,
            enrollment_id=world.student.enrollment_id,
        )
    finally:
        await engine.dispose()

    assert cards is not None
    card = next(
        job
        for job in cast("list[dict[str, object]]", cards["jobs"])
        if job["id"] == str(world.job_id)
    )
    assert card["eligible"] is False
    assert PENALTY_ACTIVE in [
        cast(dict[str, object], reason)["code"]
        for reason in cast("list[object]", card["reasons"])
    ]
