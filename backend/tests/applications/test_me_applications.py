"""The student's applications screen (LLD section 11.3, Behavior APP-3).

The screen's job is not only to list rows: it tells the student what they can
still *do*, and that answer has to be the one the command would give.  A card
offering Edit on an application the server will refuse to edit is the same class
of lie as a job card offering Apply to an ineligible student, so it is tested
the same way -- against the command, not against a hand-written expectation.
"""

from __future__ import annotations

import os
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import DomainRejection
from app.core.plan import Result
from app.modules.applications.queries import me_applications
from tests.applications.conftest import World, build_test_executor, seed_world

pytestmark = pytest.mark.asyncio


async def _execute(statement: str, params: dict[str, object]) -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(sa.text(statement), params)
    finally:
        await engine.dispose()


async def _run(name: str, payload: dict[str, object], world: World) -> Result:
    executor, engine = build_test_executor()
    model = executor.registry.commands[name].input_model
    try:
        return cast(
            Result,
            await executor.run(name, model.model_validate(payload), world.student.actor),
        )
    finally:
        await engine.dispose()


async def _screen(world: World) -> dict[str, object]:
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        return await me_applications(engine, world.student.enrollment_id)
    finally:
        await engine.dispose()


async def _applied(world: World) -> UUID:
    result = await _run(
        "apply",
        {
            "cycle_id": str(world.cycle_id),
            "job_id": str(world.job_id),
            "enrollment_id": str(world.student.enrollment_id),
        },
        world,
    )
    return UUID(cast(str, result.summary["application_id"]))


def _card(body: dict[str, object], application_id: UUID) -> dict[str, object]:
    return next(
        row
        for row in cast("list[dict[str, object]]", body["applications"])
        if row["id"] == str(application_id)
    )


async def test_APP3_the_screen_reports_the_position_and_the_timeline() -> None:
    world = await seed_world(with_rounds=True)
    application_id = await _applied(world)

    card = _card(await _screen(world), application_id)

    assert card["status"] == "in_progress"
    assert cast("dict[str, object]", card["round"])["name"] == "Screening"
    assert cast("dict[str, object]", card["job"])["title"] == "Backend Engineer"
    assert [event["event_type"] for event in cast("list[Any]", card["timeline"])] == [
        "created"
    ]


async def test_JOB6_an_open_cycle_application_reports_no_position() -> None:
    world = await seed_world(kind="open", outcome="internship", with_deadline=False)
    application_id = await _applied(world)

    card = _card(await _screen(world), application_id)

    assert card["round"] is None
    # No deadline means no window to be outside of, so both actions stand.
    assert card["can_edit"] is True
    assert card["can_withdraw"] is True


async def test_APP3_what_the_screen_offers_is_what_the_command_allows() -> None:
    """The offer and the decision come from one evaluator; prove they agree.

    Each case moves the world, then asks the screen what it offers and the
    command what it does, and requires the two to match. A card that offers an
    action the command refuses -- or hides one it would allow -- fails here.
    """
    world = await seed_world()
    application_id = await _applied(world)
    payload: dict[str, object] = {
        "cycle_id": str(world.cycle_id),
        "enrollment_id": str(world.student.enrollment_id),
        "application_id": str(application_id),
    }

    async def command_allows() -> bool:
        try:
            await _run("edit_application", payload, world)
        except DomainRejection:
            return False
        return True

    # 1. In window.
    assert _card(await _screen(world), application_id)["can_edit"] is True
    assert await command_allows() is True

    # 2. Past the deadline, default policy.
    await _execute(
        "UPDATE jobs SET application_deadline = now() - interval '1 day' WHERE id = :id",
        {"id": world.job_id},
    )
    card = _card(await _screen(world), application_id)
    assert card["can_edit"] is False
    assert card["window_reasons"], "a closed window must say why"
    assert await command_allows() is False

    # 3. Past the deadline, but the cycle allows edits anyway.
    await _execute(
        "UPDATE cycle_policies SET allow_edit_after_deadline = true WHERE cycle_id = :id",
        {"id": world.cycle_id},
    )
    assert _card(await _screen(world), application_id)["can_edit"] is True
    assert await command_allows() is True

    # 4. An override on this one application, with the policy flag off again.
    await _execute(
        "UPDATE cycle_policies SET allow_edit_after_deadline = false WHERE cycle_id = :id",
        {"id": world.cycle_id},
    )
    await _execute(
        "INSERT INTO overrides (id, rule_domain, application_id, allow, reason, "
        "granted_by, created_at) SELECT :id, 'edit_window', :application, "
        "true, 'Agreed with the coordinator', u.id, now() FROM users u "
        "WHERE u.role = 'admin' LIMIT 1",
        {"id": uuid4(), "application": application_id},
    )
    assert _card(await _screen(world), application_id)["can_edit"] is True
    assert await command_allows() is True


async def test_CYC2_edit_and_withdrawal_windows_are_separate_knobs() -> None:
    """A cycle can freeze edits while still letting a student pull out."""
    world = await seed_world()
    application_id = await _applied(world)
    await _execute(
        "UPDATE jobs SET application_deadline = now() - interval '1 day' WHERE id = :id",
        {"id": world.job_id},
    )
    await _execute(
        "UPDATE cycle_policies SET allow_withdrawal_after_deadline = true, "
        "allow_edit_after_deadline = false WHERE cycle_id = :id",
        {"id": world.cycle_id},
    )

    card = _card(await _screen(world), application_id)

    assert card["can_edit"] is False
    assert card["can_withdraw"] is True


async def test_APP3_a_withdrawn_application_stays_listed_and_offers_nothing() -> None:
    world = await seed_world()
    application_id = await _applied(world)
    await _run(
        "withdraw_application",
        {
            "cycle_id": str(world.cycle_id),
            "enrollment_id": str(world.student.enrollment_id),
            "application_id": str(application_id),
        },
        world,
    )

    body = await _screen(world)
    card = _card(body, application_id)

    assert card["status"] == "withdrawn"
    assert (card["can_edit"], card["can_withdraw"]) == (False, False)
    assert card["window_reasons"] == []
    assert [event["event_type"] for event in cast("list[Any]", card["timeline"])] == [
        "created",
        "withdrawn",
    ]
    assert cast("dict[str, object]", body["counts"]) == {"total": 1, "in_progress": 0}


async def test_APP3_an_archived_cycle_freezes_the_card() -> None:
    world = await seed_world()
    application_id = await _applied(world)
    await _execute(
        "UPDATE cycles SET archived_at = now() WHERE id = :id", {"id": world.cycle_id}
    )

    card = _card(await _screen(world), application_id)

    assert cast("dict[str, object]", card["cycle"])["archived"] is True
    assert (card["can_edit"], card["can_withdraw"]) == (False, False)
