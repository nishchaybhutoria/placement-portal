"""Closing a round, and the strikes that follow (RND-3, DIS)."""

from __future__ import annotations

import json
import os
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import (
    CYCLE_ARCHIVED,
    INVALID_TRANSITION,
    ROUND_ALREADY_FINALIZED,
    DomainRejection,
)
from app.core.plan import Preview, Result
from tests.applications.conftest import (
    World,
    build_test_executor,
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


async def _rows(query: str, params: dict[str, object] | None = None) -> list[sa.RowMapping]:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            return list(
                (await connection.execute(sa.text(query), params or {})).mappings().all()
            )
    finally:
        await engine.dispose()


async def _applied(world: World, *, enrollment_id: UUID | None = None) -> UUID:
    executor, engine = build_test_executor()
    model = executor.registry.commands["apply"].input_model
    try:
        result = await executor.run(
            "apply",
            model.model_validate(
                {
                    "cycle_id": str(world.cycle_id),
                    "job_id": str(world.job_id),
                    "enrollment_id": str(enrollment_id or world.student.enrollment_id),
                }
            ),
            world.student.actor,
        )
        return UUID(cast(str, cast(Result, result).summary["application_id"]))
    finally:
        await engine.dispose()


async def _mark(world: World, application_id: UUID, attendance: str, expected: str) -> None:
    executor, engine = build_test_executor()
    model = executor.registry.commands["mark_attendance"].input_model
    try:
        await executor.run(
            "mark_attendance",
            model.model_validate(
                {
                    "cycle_id": str(world.cycle_id),
                    "job_id": str(world.job_id),
                    "round_id": str(world.round_id),
                    "application_id": str(application_id),
                    "attendance": attendance,
                    "expected_attendance": expected,
                }
            ),
            world.staff_actor,
        )
    finally:
        await engine.dispose()


async def _finalize(
    world: World, *, round_id: UUID | None = None, dry_run: bool = False
) -> Preview | Result:
    executor, engine = build_test_executor()
    model = executor.registry.commands["finalize_round"].input_model
    try:
        return await executor.run(
            "finalize_round",
            model.model_validate(
                {
                    "cycle_id": str(world.cycle_id),
                    "job_id": str(world.job_id),
                    "round_id": str(round_id or world.round_id),
                }
            ),
            world.staff_actor,
            dry_run=dry_run,
        )
    finally:
        await engine.dispose()


def _reported(outcome: Preview | Result) -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", outcome.summary["rows"])


def _row(outcome: Preview | Result, application_id: UUID) -> dict[str, Any]:
    return next(
        row for row in _reported(outcome) if row["application_id"] == str(application_id)
    )


async def _state(application_id: UUID) -> sa.RowMapping:
    return (
        await _rows(
            "SELECT a.status, s.attendance, s.result FROM applications a "
            "JOIN application_round_states s ON s.application_id = a.id "
            "WHERE a.id = :id",
            {"id": application_id},
        )
    )[0]


async def _sent() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in await _rows("SELECT args FROM procrastinate_jobs ORDER BY id"):
        args = row["args"]
        out.append(cast("dict[str, Any]", json.loads(args) if isinstance(args, str) else args))
    return out


@pytest.mark.parametrize(
    ("attendance", "expected_status", "expected_attendance", "earns_strike"),
    [
        ("pending", "rejected", "absent", True),
        ("absent", "rejected", "absent", True),
        ("excused", "rejected", "excused", False),
        ("present", "in_progress", "present", False),
    ],
)
async def test_RND3_the_finalization_matrix(
    attendance: str, expected_status: str, expected_attendance: str, earns_strike: bool
) -> None:
    """Absent and pending are rejected with a strike; excused without; present stands."""
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)
    if attendance != "pending":
        await _mark(world, application_id, attendance, "pending")

    await _finalize(world)

    state = await _state(application_id)
    assert state["status"] == expected_status
    assert state["attendance"] == expected_attendance
    strikes = await _rows(
        "SELECT source FROM strikes WHERE enrollment_id = :id",
        {"id": world.student.enrollment_id},
    )
    assert [row["source"] for row in strikes] == (["auto_absence"] if earns_strike else [])


async def test_RND3_strike_on_absence_off_rejects_without_a_strike() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)
    await _execute(
        "UPDATE cycle_policies SET strike_on_absence = false WHERE cycle_id = :id",
        {"id": world.cycle_id},
    )

    outcome = await _finalize(world)

    assert (await _state(application_id))["status"] == "rejected"
    assert await _rows("SELECT id FROM strikes") == []
    assert outcome.summary["strike_on_absence"] is False
    assert _row(outcome, application_id)["earns_strike"] is False


async def test_RND3_the_preview_says_who_will_earn_a_strike_before_committing() -> None:
    """RND-2 names this: the per-row effect includes 'will earn a strike'."""
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)

    preview = await _finalize(world, dry_run=True)

    assert (await _state(application_id))["status"] == "in_progress"
    planned = _row(preview, application_id)
    assert planned["earns_strike"] is True
    assert planned["attendance_after"] == "absent"
    assert planned["to_status"] == "rejected"
    committed = await _finalize(world)
    assert _reported(committed) == _reported(preview)


async def test_RND1_a_waitlisted_row_survives_finalization_and_is_named() -> None:
    """RND-1: a waitlist resolves only by promotion, so finalize leaves it alone."""
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)
    executor, engine = build_test_executor()
    try:
        await executor.run_bulk(
            "waitlist_applications",
            [{"application_id": str(application_id)}],
            f"waitlist-{uuid4()}",
            world.staff_actor,
            batch_fields={"cycle_id": world.cycle_id, "job_id": world.job_id},
        )
    finally:
        await engine.dispose()

    outcome = await _finalize(world)

    state = await _state(application_id)
    assert state["status"] == "in_progress"
    assert state["result"] == "waitlisted"
    # Named rather than omitted: the coordinator has to see it is still live.
    reported = _row(outcome, application_id)
    assert reported["outcome"] == "untouched"
    assert reported["reason"] == "waitlisted"
    assert outcome.summary["finalized"] == 0


async def test_RND3_a_second_finalization_is_refused() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    await _applied(world)
    await _finalize(world)

    with pytest.raises(DomainRejection) as rejection:
        await _finalize(world)

    assert [reason.code for reason in rejection.value.rejection.reasons] == [
        ROUND_ALREADY_FINALIZED
    ]


async def test_RND3_finalizing_records_who_closed_the_round() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    await _applied(world)

    await _finalize(world)

    round_row = (
        await _rows(
            "SELECT finalized_at, finalized_by FROM job_rounds WHERE id = :id",
            {"id": world.round_id},
        )
    )[0]
    assert round_row["finalized_at"] is not None
    assert round_row["finalized_by"] == world.staff_actor.user_id


async def test_RND3_the_absentee_is_told_the_round_and_the_running_total() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    await _applied(world)

    await _finalize(world)

    absent = [item for item in await _sent() if item["event_key"] == "absent_marked"]
    assert len(absent) == 1
    assert absent[0]["context"]["strike_total"] == 1
    assert absent[0]["recipient"] == world.student.email


async def test_RND3_an_excused_student_is_not_told_they_were_absent() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)
    await _mark(world, application_id, "excused", "pending")

    await _finalize(world)

    keys = [item["event_key"] for item in await _sent()]
    assert "absent_marked" not in keys
    assert "rejected" in keys


async def test_RND3_the_timeline_records_the_finalization() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)

    await _finalize(world)

    event = (
        await _rows(
            "SELECT from_status, to_status, reason, payload FROM application_events "
            "WHERE application_id = :id AND event_type = 'round_finalized'",
            {"id": application_id},
        )
    )[0]
    assert event["from_status"] == "in_progress"
    assert event["to_status"] == "rejected"
    assert event["reason"] == "absence"
    assert event["payload"]["strike_awarded"] is True


async def test_RND3_two_absences_in_one_finalization_convert_once() -> None:
    """The pair is awarded together, so it converts on the pair, not twice."""
    world = await seed_world(with_rounds=True, with_staff=True)
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            second = await seed_round(
                connection, job_id=world.job_id, ord=2, name="Interview"
            )
    finally:
        await engine.dispose()
    application_id = await _applied(world)
    # The same student sitting in both rounds is not reachable through the
    # pipeline, so the second round's state is created directly.
    await _execute(
        "INSERT INTO application_round_states (application_id, round_id, result, "
        "attendance) VALUES (:application, :round, 'pending', 'absent')",
        {"application": application_id, "round": second},
    )
    await _finalize(world)

    penalties = await _rows(
        "SELECT reasons FROM penalties WHERE enrollment_id = :id",
        {"id": world.student.enrollment_id},
    )
    strikes = await _rows(
        "SELECT id FROM strikes WHERE enrollment_id = :id",
        {"id": world.student.enrollment_id},
    )
    assert len(strikes) == 1
    assert penalties == []


async def test_RND3_a_round_of_another_job_is_refused() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    await _applied(world)

    with pytest.raises(DomainRejection) as rejection:
        await _finalize(world, round_id=uuid4())

    assert [reason.code for reason in rejection.value.rejection.reasons] == [
        INVALID_TRANSITION
    ]


async def test_CYC1_an_archived_cycle_finalizes_nothing() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    await _applied(world)
    await _execute(
        "UPDATE cycles SET archived_at = now() WHERE id = :id", {"id": world.cycle_id}
    )

    with pytest.raises(DomainRejection) as rejection:
        await _finalize(world)

    assert [reason.code for reason in rejection.value.rejection.reasons] == [
        CYCLE_ARCHIVED
    ]
    assert await _rows("SELECT id FROM strikes") == []


async def test_RND3_finalizing_an_empty_round_still_closes_it() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)

    outcome = await _finalize(world)

    assert outcome.summary["finalized"] == 0
    round_row = (
        await _rows(
            "SELECT finalized_at FROM job_rounds WHERE id = :id", {"id": world.round_id}
        )
    )[0]
    assert round_row["finalized_at"] is not None
