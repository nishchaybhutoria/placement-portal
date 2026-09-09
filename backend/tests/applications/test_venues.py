"""Publishing where and when a round happens (RND-4, RND-2)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import (
    CYCLE_ARCHIVED,
    DUPLICATE_ROW,
    INVALID_FIELD_VALUE,
    INVALID_TRANSITION,
    UNMATCHED_IDENTIFIER,
    DomainRejection,
)
from app.core.plan import Preview, Result
from app.modules.applications.slots import parse_slot_time
from app.modules.notifications.wording import schedule_note
from tests.applications.conftest import (
    World,
    build_test_executor,
    seed_job,
    seed_round,
    seed_world,
)

pytestmark = pytest.mark.asyncio


async def _execute(statement: str, params: dict[str, object]) -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(sa.text(statement), params)
    finally:
        await engine.dispose()


async def _rows(query: str, params: dict[str, object]) -> list[sa.RowMapping]:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            return list((await connection.execute(sa.text(query), params)).mappings().all())
    finally:
        await engine.dispose()


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


async def _assign(
    world: World,
    rows: list[dict[str, str]],
    *,
    round_id: UUID | None = None,
    dry_run: bool = False,
) -> Preview | Result:
    executor, engine = build_test_executor()
    try:
        return await executor.run_bulk(
            "assign_venue_timing",
            rows,  # type: ignore[arg-type]
            f"venue-{uuid4()}",
            world.staff_actor,
            dry_run=dry_run,
            batch_fields={
                "cycle_id": world.cycle_id,
                "job_id": world.job_id,
                "round_id": round_id or world.round_id,
            },
        )
    finally:
        await engine.dispose()


def _reported(outcome: Preview | Result) -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", outcome.summary["rows"])


async def _slot(application_id: UUID) -> sa.RowMapping:
    return (
        await _rows(
            "SELECT venue_override, scheduled_at_override, notified_at "
            "FROM application_round_states WHERE application_id = :id",
            {"id": application_id},
        )
    )[0]


async def test_RND4_a_published_slot_lands_on_the_round_state() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)

    await _assign(
        world,
        [{"identifier": world.roll_number, "venue": "AB 5 / 201", "time": "2026-03-14 09:30"}],
    )

    slot = await _slot(application_id)
    assert slot["venue_override"] == "AB 5 / 201"
    assert slot["scheduled_at_override"] == parse_slot_time("2026-03-14 09:30")
    assert slot["notified_at"] is not None


async def test_RND4_publishing_puts_the_slot_on_the_timeline() -> None:
    """Two hundred students told where to go, and the timeline says so."""
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)

    await _assign(
        world,
        [{"identifier": world.roll_number, "venue": "AB 5 / 201", "time": "2026-03-14 09:30"}],
    )

    event = (
        await _rows(
            "SELECT from_round_id, to_round_id, from_status, to_status, payload "
            "FROM application_events "
            "WHERE application_id = :id AND event_type = 'venue_assigned'",
            {"id": application_id},
        )
    )[0]
    assert event["from_round_id"] == event["to_round_id"] == world.round_id
    assert event["from_status"] == event["to_status"] == "in_progress"
    payload = event["payload"]
    assert payload["venue"] == "AB 5 / 201"
    assert payload["is_update"] is False


async def test_RND4_the_second_mail_says_it_is_an_update() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    await _applied(world)

    first = await _assign(
        world, [{"identifier": world.roll_number, "venue": "AB 5 / 201"}]
    )
    second = await _assign(
        world, [{"identifier": world.roll_number, "venue": "AB 5 / 204"}]
    )

    assert _reported(first)[0]["is_update"] is False
    assert _reported(second)[0]["is_update"] is True
    tasks = await _rows(
        "SELECT task_name, args FROM procrastinate_jobs ORDER BY id", {}
    )
    notifications = [
        _args(row)
        for row in tasks
        if row["task_name"] == "deliver_notification"
        and _args(row)["event_key"] == "venue_timing"
    ]
    assert len(notifications) == 2
    context = [item["context"] for item in notifications]
    # The student reads the clause, not the flag: "Updated schedule: False"
    # reached fifteen of them in the mock run (the design review section 4.44).
    assert [item["is_update"] for item in context] == [
        schedule_note(False),
        schedule_note(True),
    ]
    assert [item["venue"] for item in context] == ["AB 5 / 201", "AB 5 / 204"]


def _args(row: sa.RowMapping) -> dict[str, Any]:
    args = row["args"]
    return cast("dict[str, Any]", json.loads(args) if isinstance(args, str) else args)


async def test_RND4_an_empty_cell_leaves_that_override_alone() -> None:
    """A time-only correction must not wipe the venue (the design review section 4.23)."""
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)
    await _assign(
        world,
        [{"identifier": world.roll_number, "venue": "AB 5 / 201", "time": "2026-03-14 09:30"}],
    )

    result = await _assign(
        world, [{"identifier": world.roll_number, "time": "2026-03-14 11:00"}]
    )

    slot = await _slot(application_id)
    assert slot["venue_override"] == "AB 5 / 201"
    assert slot["scheduled_at_override"] == parse_slot_time("2026-03-14 11:00")
    # The report states the slot as it now stands, not just the half that moved.
    assert _reported(result)[0]["venue"] == "AB 5 / 201"


async def test_RND4_a_row_naming_neither_a_venue_nor_a_time_is_an_error() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    await _applied(world)

    result = await _assign(world, [{"identifier": world.roll_number}])

    assert [(row["status"], row["reason"]) for row in _reported(result)] == [
        ("error", INVALID_FIELD_VALUE)
    ]


async def test_RND4_a_bad_time_stops_its_own_row_and_no_other() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)

    result = await _assign(
        world,
        [
            {"identifier": world.roll_number, "time": "14/03/2026 09:30"},
            {"identifier": "asha@example.edu", "venue": "AB 5 / 201"},
        ],
    )

    reported = _reported(result)
    assert reported[0]["status"] == "error"
    assert reported[0]["reason"] == INVALID_FIELD_VALUE
    assert "2026-03-14 09:30" in cast(str, reported[0]["human"])
    # The same student, matched by email on the second row, still gets a venue.
    assert reported[1]["status"] == "ok"
    assert (await _slot(application_id))["venue_override"] == "AB 5 / 201"


async def test_RND2_unmatched_identifiers_are_named_never_counted() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    await _applied(world)

    result = await _assign(
        world,
        [
            {"identifier": "21119999", "venue": "AB 5 / 201"},
            {"identifier": world.roll_number, "venue": "AB 5 / 201"},
        ],
    )

    assert [
        row["identifier"] for row in _reported(result) if row["reason"] == UNMATCHED_IDENTIFIER
    ] == ["21119999"]


async def test_RND2_the_preview_states_the_slot_before_it_publishes_it() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)
    rows = [
        {"identifier": world.roll_number, "venue": "AB 5 / 201", "time": "2026-03-14 09:30"}
    ]

    preview = await _assign(world, rows, dry_run=True)
    assert (await _slot(application_id))["notified_at"] is None
    committed = await _assign(world, rows)

    assert _reported(preview) == _reported(committed)
    assert _reported(preview)[0]["scheduled_at"] is not None


async def test_RND2_one_student_named_twice_takes_the_first_slot() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)

    result = await _assign(
        world,
        [
            {"identifier": world.roll_number, "venue": "AB 5 / 201"},
            {"identifier": "asha@example.edu", "venue": "AB 5 / 204"},
        ],
    )

    assert [(row["status"], row["reason"]) for row in _reported(result)] == [
        ("ok", None),
        ("skipped", DUPLICATE_ROW),
    ]
    assert (await _slot(application_id))["venue_override"] == "AB 5 / 201"


async def test_RND4_a_round_of_another_job_is_refused_outright() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    await _applied(world)
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            other_job = await seed_job(connection, cycle_id=world.cycle_id)
            elsewhere = await seed_round(connection, job_id=other_job)
    finally:
        await engine.dispose()

    with pytest.raises(DomainRejection) as rejection:
        await _assign(
            world,
            [{"identifier": world.roll_number, "venue": "AB 5 / 201"}],
            round_id=elsewhere,
        )

    assert [reason.code for reason in rejection.value.rejection.reasons] == [
        INVALID_TRANSITION
    ]


async def test_RND4_a_row_not_sitting_in_the_round_is_skipped() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    await _applied(world)
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            second = await seed_round(
                connection, job_id=world.job_id, ord=2, name="Interview"
            )
    finally:
        await engine.dispose()

    result = await _assign(
        world,
        [{"identifier": world.roll_number, "venue": "AB 5 / 201"}],
        round_id=second,
    )

    assert [(row["status"], row["reason"]) for row in _reported(result)] == [
        ("skipped", INVALID_TRANSITION)
    ]


async def test_CYC1_an_archived_cycle_publishes_nothing() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    await _applied(world)
    await _execute(
        "UPDATE cycles SET archived_at = now() WHERE id = :id", {"id": world.cycle_id}
    )

    with pytest.raises(DomainRejection) as rejection:
        await _assign(world, [{"identifier": world.roll_number, "venue": "AB 5 / 201"}])

    assert [reason.code for reason in rejection.value.rejection.reasons] == [
        CYCLE_ARCHIVED
    ]


async def test_RND4_republishing_the_same_slot_changes_nothing_and_mails_nobody() -> None:
    """the design review 4.46: a corrected sheet re-uploaded must not re-mail the room."""
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)
    row = {"identifier": world.roll_number, "venue": "AB 5 / 201", "time": "2027-07-01 09:30"}

    first = await _assign(world, [row])
    published = await _slot(application_id)
    second = await _assign(world, [dict(row)])
    after = await _slot(application_id)

    assert [item["status"] for item in _reported(first)] == ["ok"]
    assert [item["status"] for item in _reported(second)] == ["unchanged"]
    # No fresh stamp, so nothing claims the student was told a second time.
    assert after["notified_at"] == published["notified_at"]
    assert after["venue_override"] == "AB 5 / 201"
    assert len(await _venue_notifications()) == 1
    events = await _rows(
        "SELECT id FROM application_events WHERE application_id = :id "
        "AND event_type = 'venue_assigned'",
        {"id": application_id},
    )
    assert len(events) == 1


async def test_RND4_a_first_publish_of_the_rounds_own_defaults_still_tells_the_student() -> None:
    """Nothing moves, but nobody has been told -- publishing is the telling."""
    world = await seed_world(with_rounds=True, with_staff=True)
    await _applied(world)
    await _execute(
        "UPDATE job_rounds SET venue = 'LT 1', scheduled_at = :when WHERE id = :id",
        {"id": world.round_id, "when": datetime(2027, 7, 1, 4, 0, tzinfo=UTC)},
    )

    outcome = await _assign(
        world,
        [{"identifier": world.roll_number, "venue": "LT 1", "time": "2027-07-01 09:30"}],
    )

    assert [item["status"] for item in _reported(outcome)] == ["ok"]
    notifications = await _venue_notifications()
    assert len(notifications) == 1
    assert notifications[0]["context"]["time"] == "01 Jul 2027, 09:30 IST"


async def test_RND4_a_moved_time_notifies_even_when_the_venue_is_unchanged() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    await _applied(world)
    row = {"identifier": world.roll_number, "venue": "AB 5 / 201", "time": "2027-07-01 09:30"}

    await _assign(world, [row])
    moved = await _assign(
        world,
        [{"identifier": world.roll_number, "venue": "AB 5 / 201", "time": "2027-07-01 11:00"}],
    )

    assert [item["status"] for item in _reported(moved)] == ["ok"]
    notifications = await _venue_notifications()
    assert [item["context"]["time"] for item in notifications] == [
        "01 Jul 2027, 09:30 IST",
        "01 Jul 2027, 11:00 IST",
    ]
    assert notifications[1]["context"]["is_update"] == schedule_note(True)


async def test_RND4_a_time_only_row_mails_the_rounds_default_venue() -> None:
    """RND-1: the student sees the override, or the round's default. So must the mail."""
    world = await seed_world(with_rounds=True, with_staff=True)
    await _applied(world)
    await _execute(
        "UPDATE job_rounds SET venue = 'LT 1' WHERE id = :id", {"id": world.round_id}
    )

    outcome = await _assign(
        world, [{"identifier": world.roll_number, "time": "2027-07-01 09:30"}]
    )

    assert [item["status"] for item in _reported(outcome)] == ["ok"]
    notifications = await _venue_notifications()
    assert notifications[0]["context"]["venue"] == "LT 1"
    assert [item["venue"] for item in _reported(outcome)] == ["LT 1"]


async def test_RND2_the_preview_reports_unchanged_exactly_as_execution_does() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)
    row = {"identifier": world.roll_number, "venue": "AB 5 / 201", "time": "2027-07-01 09:30"}
    await _assign(world, [row])
    published = await _slot(application_id)

    preview = await _assign(world, [dict(row)], dry_run=True)

    assert [item["status"] for item in _reported(preview)] == ["unchanged"]
    assert (await _slot(application_id))["notified_at"] == published["notified_at"]
    assert len(await _venue_notifications()) == 1


async def _venue_notifications() -> list[dict[str, Any]]:
    tasks = await _rows("SELECT task_name, args FROM procrastinate_jobs ORDER BY id", {})
    return [
        _args(row)
        for row in tasks
        if row["task_name"] == "deliver_notification"
        and _args(row)["event_key"] == "venue_timing"
    ]
