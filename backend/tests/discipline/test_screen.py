"""The administrative discipline read model and its command controls (DIS)."""

from __future__ import annotations

import os
from typing import Any, cast
from uuid import UUID

import pytest

from app.core.db import create_engine
from app.core.errors import DomainRejection
from app.core.plan import Result
from app.modules.discipline.queries import admin_discipline
from tests.discipline.conftest import (
    DisciplineWorld,
    build_test_executor,
    seed_discipline_world,
    set_threshold,
)

pytestmark = pytest.mark.asyncio


async def _run(
    world: DisciplineWorld,
    command: str,
    payload: dict[str, object],
    *,
    dry_run: bool = False,
) -> Result:
    executor, engine = build_test_executor()
    model = executor.registry.commands[command].input_model
    try:
        return cast(
            Result,
            await executor.run(
                command,
                model.model_validate(payload),
                world.admin.actor,
                dry_run=dry_run,
            ),
        )
    finally:
        await engine.dispose()


async def _screen(enrollment_id: UUID | None = None) -> dict[str, Any]:
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        return cast(
            "dict[str, Any]",
            await admin_discipline(engine, enrollment_id=enrollment_id),
        )
    finally:
        await engine.dispose()


async def test_DIS_a_clean_student_is_in_the_roster_so_the_first_award_is_reachable() -> None:
    world = await seed_discipline_world()

    body = await _screen(world.student.enrollment_id)

    row = next(
        item for item in body["roster"] if item["enrollment_id"] == str(world.student.enrollment_id)
    )
    assert row["active_strikes"] == 0
    assert row["active_penalties"] == 0
    assert row["blocked"] is False
    assert body["student"]["strikes"] == []
    assert body["student"]["penalties"] == []


async def test_DIS_roster_counts_do_not_fan_out_and_the_panel_names_the_actors() -> None:
    world = await seed_discipline_world()
    await set_threshold(None)
    for reason in ("First", "Second"):
        await _run(
            world,
            "award_strike",
            {"enrollment_id": str(world.student.enrollment_id), "reason": reason},
        )
    for reasons in ("Direct one", "Direct two"):
        await _run(
            world,
            "award_penalty",
            {"enrollment_id": str(world.student.enrollment_id), "reasons": reasons},
        )

    body = await _screen(world.student.enrollment_id)
    row = next(
        item for item in body["roster"] if item["enrollment_id"] == str(world.student.enrollment_id)
    )
    panel = body["student"]

    # Two joins over two rows each would report four of each without the
    # pre-aggregated roster query.
    assert row["active_strikes"] == 2
    assert row["active_penalties"] == 2
    assert len(panel["strikes"]) == 2
    assert len(panel["penalties"]) == 2
    assert {item["awarded_by"]["name"] for item in panel["strikes"]} == {"Administrator"}
    assert {item["created_by"]["name"] for item in panel["penalties"]} == {"Administrator"}
    assert all(item["created_at"] for item in panel["penalties"])


async def test_DIS_revoke_controls_and_commands_agree_in_both_directions() -> None:
    world = await seed_discipline_world()
    await set_threshold(None)
    await _run(
        world,
        "award_strike",
        {"enrollment_id": str(world.student.enrollment_id), "reason": "Wrong room"},
    )
    await _run(
        world,
        "award_penalty",
        {
            "enrollment_id": str(world.student.enrollment_id),
            "reasons": "Manual intervention",
        },
    )
    panel = (await _screen(world.student.enrollment_id))["student"]
    strike_id = panel["strikes"][0]["id"]
    penalty_id = panel["penalties"][0]["id"]

    assert panel["strikes"][0]["actions"]["revoke"]["allowed"] is True
    assert panel["penalties"][0]["actions"]["revoke"]["allowed"] is True
    await _run(
        world,
        "revoke_strike",
        {"strike_id": strike_id, "reason": "Attendance corrected"},
        dry_run=True,
    )
    await _run(
        world,
        "revoke_penalty",
        {"penalty_id": penalty_id, "reason": "Administrative correction"},
        dry_run=True,
    )

    await _run(
        world,
        "revoke_strike",
        {"strike_id": strike_id, "reason": "Attendance corrected"},
    )
    await _run(
        world,
        "revoke_penalty",
        {"penalty_id": penalty_id, "reason": "Administrative correction"},
    )
    after = (await _screen(world.student.enrollment_id))["student"]

    assert after["strikes"][0]["actions"]["revoke"]["allowed"] is False
    assert after["penalties"][0]["actions"]["revoke"]["allowed"] is False
    with pytest.raises(DomainRejection):
        await _run(
            world,
            "revoke_strike",
            {"strike_id": strike_id, "reason": "Again"},
            dry_run=True,
        )
    with pytest.raises(DomainRejection):
        await _run(
            world,
            "revoke_penalty",
            {"penalty_id": penalty_id, "reason": "Again"},
            dry_run=True,
        )
