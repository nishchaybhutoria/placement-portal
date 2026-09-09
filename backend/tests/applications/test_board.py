"""The ATS board (LLD section 11.3, Behavior RND-1, RND-2).

The board's columns are a rendering question; the buttons on each row are not.
Every row reports what each of the four operations would do to it, and the design review
section 4.22 requires that to be the answer the command actually gives -- so the
pin here drives several worlds and compares the two, rather than asserting what
the board displays and calling it proven.
"""

from __future__ import annotations

import os
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import DomainRejection
from app.core.plan import Preview, Result
from app.modules.applications.queries import staff_job_board
from tests.applications.conftest import World, build_test_executor, seed_round, seed_world

pytestmark = pytest.mark.asyncio

OPERATIONS = ("advance", "eliminate", "waitlist", "promote")
COMMAND = {
    "advance": "advance_applications",
    "eliminate": "eliminate_applications",
    "waitlist": "waitlist_applications",
    "promote": "promote_waitlisted",
}


async def _execute(statement: str, params: dict[str, object]) -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(sa.text(statement), params)
    finally:
        await engine.dispose()


async def _board(world: World) -> dict[str, Any]:
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        board = await staff_job_board(engine, world.job_id)
    finally:
        await engine.dispose()
    assert board is not None
    return cast("dict[str, Any]", board)


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
        return UUID(cast(str, cast(Result, result).summary["application_id"]))
    finally:
        await engine.dispose()


async def _bulk(
    world: World, operation: str, application_id: UUID, *, dry_run: bool = False
) -> Preview | Result:
    executor, engine = build_test_executor()
    fields: dict[str, object] = {"cycle_id": world.cycle_id, "job_id": world.job_id}
    if operation == "eliminate":
        fields["reason"] = "Board pin"
    try:
        return await executor.run_bulk(
            COMMAND[operation],
            [{"application_id": str(application_id)}],
            f"{operation}-{uuid4()}",
            world.staff_actor,
            dry_run=dry_run,
            batch_fields=fields,
        )
    finally:
        await engine.dispose()


def _row(board: dict[str, Any], application_id: UUID) -> dict[str, Any]:
    everywhere = [
        row
        for column in cast("list[dict[str, Any]]", board["columns"])
        for row in cast("list[dict[str, Any]]", column["rows"])
    ] + cast("list[dict[str, Any]]", board["settled"])
    return next(row for row in everywhere if row["application_id"] == str(application_id))


async def test_RND1_the_board_groups_applicants_by_the_round_they_sit_in() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await seed_round(connection, job_id=world.job_id, ord=2, name="Interview")
    finally:
        await engine.dispose()
    application_id = await _applied(world)

    board = await _board(world)

    assert [column["name"] for column in board["columns"]] == ["Screening", "Interview"]
    assert board["columns"][0]["count"] == 1
    assert board["columns"][1]["count"] == 0
    row = _row(board, application_id)
    assert row["full_name"] == world.student_name
    assert row["roll_number"] == world.roll_number
    assert row["attendance"] == "pending"

    await _bulk(world, "advance", application_id)
    moved = await _board(world)

    assert moved["columns"][0]["count"] == 1
    assert moved["columns"][0]["rows"][0]["result"] == "advanced"
    assert moved["columns"][0]["rows"][0]["is_current_round"] is False
    assert moved["columns"][1]["count"] == 1
    assert moved["columns"][1]["rows"][0]["is_current_round"] is True


async def test_JOB6_an_application_with_no_round_position_still_appears() -> None:
    """A round-less applicant is live, not settled, and the board must say so.

    An open-cycle job carries no rounds, so *every* applicant to one holds no
    round position.  Filing them with the finished applications made the only
    live surface on the board a list nobody could act on, and left the four
    pipeline buttons offering moves ``plan_row`` can only refuse.
    """
    world = await seed_world(
        kind="open", outcome="internship", with_deadline=False, with_staff=True
    )
    application_id = await _applied(world)

    board = await _board(world)

    assert board["columns"] == []
    assert board["job"]["has_rounds"] is False
    assert [row["application_id"] for row in board["unrouted"]] == [str(application_id)]
    assert board["settled"] == []
    assert board["counts"] == {
        "total": 1,
        "in_pipeline": 0,
        "unrouted": 1,
        "settled": 0,
    }
    # The row is offered no move the command would refuse, and the one it does
    # allow -- eliminate needs only `in_progress` -- is offered.
    actions = board["unrouted"][0]["actions"]
    assert actions["eliminate"]["allowed"] is True
    assert [name for name in ("advance", "waitlist", "promote") if actions[name]["allowed"]] == []
    assert actions["advance"]["reason"] == "invalid_transition"


@pytest.mark.parametrize("state", ["fresh", "waitlisted", "final_round", "settled"])
async def test_RND2_every_action_the_board_offers_is_one_the_command_performs(
    state: str,
) -> None:
    """the design review section 4.22, for all four operations in each state a row has.

    Ask the board what it offers and each command what it does, and require
    them to agree -- in both directions. A button the command refuses is a lie;
    a missing button for an action the command would perform is a feature the
    coordinator cannot reach. Parametrized rather than looped so each state gets
    a clean world and a failure names the state it failed in.
    """
    world = await seed_world(with_rounds=True, with_staff=True)
    if state != "final_round":
        engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
        try:
            async with engine.begin() as connection:
                await seed_round(connection, job_id=world.job_id, ord=2, name="Interview")
        finally:
            await engine.dispose()
    application_id = await _applied(world)
    if state == "waitlisted":
        await _bulk(world, "waitlist", application_id)
    elif state == "settled":
        await _bulk(world, "eliminate", application_id)

    offered = _row(await _board(world), application_id)["actions"]

    for operation in OPERATIONS:
        outcome = await _bulk(world, operation, application_id, dry_run=True)
        rows = cast("list[dict[str, Any]]", outcome.summary["rows"])
        performed = rows[0]["status"] == "ok"
        assert offered[operation]["allowed"] == performed, (
            f"{state}: board says {offered[operation]['allowed']} for "
            f"{operation}, command says {performed}"
        )
        if performed:
            # And when it is offered, it is offered as the same effect.
            assert offered[operation]["to_status"] == rows[0]["to_status"]
            assert offered[operation]["to_round"] == rows[0]["to_round"]


async def test_CYC1_an_archived_cycle_offers_nothing_on_the_board() -> None:
    """check_scope refuses every command first, so no button may promise one."""
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)
    await _execute(
        "UPDATE cycles SET archived_at = now() WHERE id = :id", {"id": world.cycle_id}
    )

    row = _row(await _board(world), application_id)

    assert [row["actions"][operation]["allowed"] for operation in OPERATIONS] == [
        False,
        False,
        False,
        False,
    ]
    for operation in OPERATIONS:
        with pytest.raises(DomainRejection):
            await _bulk(world, operation, application_id, dry_run=True)


async def _mark(world: World, row: dict[str, Any]) -> bool:
    """Run the real command with exactly what the board handed the client."""
    executor, engine = build_test_executor()
    model = executor.registry.commands["mark_attendance"].input_model
    current = cast(str, row["attendance"] or "pending")
    cycled = {"pending": "present", "present": "absent", "absent": "excused", "excused": "pending"}
    try:
        await executor.run(
            "mark_attendance",
            model.model_validate(
                {
                    "cycle_id": str(world.cycle_id),
                    "job_id": str(world.job_id),
                    "round_id": cast("dict[str, Any]", row["round"])["id"],
                    "application_id": row["application_id"],
                    "attendance": cycled[current],
                    "expected_attendance": current,
                }
            ),
            world.staff_actor,
            dry_run=True,
        )
    except DomainRejection:
        return False
    finally:
        await engine.dispose()
    return True


async def _finalize_allows(world: World, *, execute: bool = False) -> bool:
    """Ask the real finalize command about the board's first round."""
    executor, engine = build_test_executor()
    model = executor.registry.commands["finalize_round"].input_model
    try:
        await executor.run(
            "finalize_round",
            model.model_validate(
                {
                    "cycle_id": str(world.cycle_id),
                    "job_id": str(world.job_id),
                    "round_id": str(world.round_id),
                }
            ),
            world.staff_actor,
            dry_run=not execute,
        )
    except DomainRejection:
        return False
    finally:
        await engine.dispose()
    return True


async def _assign(world: World, row: dict[str, Any]) -> bool:
    executor, engine = build_test_executor()
    try:
        outcome = await executor.run_bulk(
            "assign_venue_timing",
            [{"application_id": row["application_id"], "venue": "AB 5 / 201"}],
            f"pin-{uuid4()}",
            world.staff_actor,
            dry_run=True,
            batch_fields={
                "cycle_id": world.cycle_id,
                "job_id": world.job_id,
                "round_id": UUID(cast("dict[str, Any]", row["round"])["id"]),
            },
        )
    except DomainRejection:
        return False
    finally:
        await engine.dispose()
    return cast("list[dict[str, Any]]", outcome.summary["rows"])[0]["status"] == "ok"


@pytest.mark.parametrize("state", ["fresh", "eliminated", "withdrawn", "archived"])
async def test_RND3_what_the_board_offers_per_round_is_what_the_command_allows(
    state: str,
) -> None:
    """the design review section 4.22, for the two round-scoped controls M10c adds.

    Attendance and venue are addressed by round, so the pin feeds each command
    exactly what the board handed the client -- the round id and the attendance
    the chip is displaying -- and requires the answers to agree in both
    directions. Asserting only the row that can be marked would prove nothing:
    the failure mode is a control that never appears, or one that appears on a
    row every command refuses.
    """
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)
    if state == "eliminated":
        await _bulk(world, "eliminate", application_id)
    elif state == "withdrawn":
        await _execute(
            "UPDATE applications SET status = 'withdrawn' WHERE id = :id",
            {"id": application_id},
        )
    elif state == "archived":
        await _execute(
            "UPDATE cycles SET archived_at = now() WHERE id = :id",
            {"id": world.cycle_id},
        )

    row = _row(await _board(world), application_id)

    if state == "eliminated":
        # A terminal row remains visible in its round as history, but is read-only.
        assert row["is_current_round"] is False
        assert row["actions"]["mark_attendance"]["allowed"] is False
        assert row["actions"]["assign_venue"]["allowed"] is False
    else:
        assert row["actions"]["mark_attendance"]["allowed"] == await _mark(world, row), (
            f"{state}: board says {row['actions']['mark_attendance']['allowed']} for "
            "attendance"
        )
        assert row["actions"]["assign_venue"]["allowed"] == await _assign(world, row), (
            f"{state}: board says {row['actions']['assign_venue']['allowed']} for venue"
        )


@pytest.mark.parametrize("state", ["fresh", "finalized", "archived", "cancelled"])
async def test_RND3_the_finalize_control_is_exactly_what_the_command_allows(
    state: str,
) -> None:
    """The round-level close control is pinned in both directions (§4.22)."""
    world = await seed_world(with_rounds=True, with_staff=True)
    await _applied(world)
    if state == "finalized":
        assert await _finalize_allows(world, execute=True) is True
    elif state == "archived":
        await _execute(
            "UPDATE cycles SET archived_at = now() WHERE id = :id",
            {"id": world.cycle_id},
        )
    elif state == "cancelled":
        await _execute(
            "UPDATE jobs SET cancelled_at = now() WHERE id = :id",
            {"id": world.job_id},
        )

    board = await _board(world)
    job_round = next(
        item for item in cast("list[dict[str, Any]]", board["rounds"])
        if item["id"] == str(world.round_id)
    )
    command_allows = await _finalize_allows(world)

    assert job_round["actions"]["finalize"]["allowed"] == command_allows
    assert command_allows is (state == "fresh")
    if state == "finalized":
        assert job_round["finalized_at"] is not None
        assert job_round["finalized_by"]["id"] == str(world.staff_actor.user_id)
        assert job_round["finalized_by"]["name"] is not None
    else:
        assert job_round["finalized_at"] is None


async def test_RND4_the_board_states_the_slot_a_student_actually_has() -> None:
    """A per-student override replaces the round default rather than hiding it."""
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)
    await _execute(
        "UPDATE job_rounds SET venue = 'AB 1 / 101' WHERE id = :id",
        {"id": world.round_id},
    )

    before = _row(await _board(world), application_id)
    executor, engine = build_test_executor()
    try:
        await executor.run_bulk(
            "assign_venue_timing",
            [
                {
                    "application_id": str(application_id),
                    "venue": "AB 5 / 201",
                    "time": "2026-03-14 09:30",
                }
            ],
            f"slot-{uuid4()}",
            world.staff_actor,
            batch_fields={
                "cycle_id": world.cycle_id,
                "job_id": world.job_id,
                "round_id": world.round_id,
            },
        )
    finally:
        await engine.dispose()
    after = _row(await _board(world), application_id)

    assert before["venue"] == "AB 1 / 101"
    assert before["slot_is_override"] is False
    assert before["slot_notified_at"] is None
    assert after["venue"] == "AB 5 / 201"
    assert after["scheduled_at"] is not None
    assert after["slot_is_override"] is True
    assert after["slot_notified_at"] is not None
