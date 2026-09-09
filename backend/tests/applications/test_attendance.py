"""Marking who turned up (RND-3), single and in bulk."""

from __future__ import annotations

import os
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import (
    CYCLE_ARCHIVED,
    DUPLICATE_ROW,
    INVALID_TRANSITION,
    STALE_VIEW,
    UNMATCHED_IDENTIFIER,
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


async def _rows(query: str, params: dict[str, object]) -> list[sa.RowMapping]:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            return list((await connection.execute(sa.text(query), params)).mappings().all())
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


async def _mark(
    world: World,
    application_id: UUID,
    *,
    attendance: str,
    expected: str,
    round_id: UUID | None = None,
    actor: Any = None,
    reason: str | None = None,
) -> Result:
    executor, engine = build_test_executor()
    model = executor.registry.commands["mark_attendance"].input_model
    payload: dict[str, object] = {
        "cycle_id": str(world.cycle_id),
        "job_id": str(world.job_id),
        "round_id": str(round_id or world.round_id),
        "application_id": str(application_id),
        "attendance": attendance,
        "expected_attendance": expected,
    }
    if reason is not None:
        payload["reason"] = reason
    try:
        return cast(
            Result,
            await executor.run(
                "mark_attendance",
                model.model_validate(payload),
                actor or world.staff_actor,
            ),
        )
    finally:
        await engine.dispose()


async def _present(
    world: World,
    rows: list[dict[str, str]],
    *,
    round_id: UUID | None = None,
    dry_run: bool = False,
    command: str = "bulk_mark_present",
) -> Preview | Result:
    executor, engine = build_test_executor()
    try:
        return await executor.run_bulk(
            command,
            rows,  # type: ignore[arg-type]
            f"attendance-{uuid4()}",
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


async def _attendance(application_id: UUID) -> str:
    rows = await _rows(
        "SELECT attendance FROM application_round_states WHERE application_id = :id",
        {"id": application_id},
    )
    return str(rows[0]["attendance"])


async def test_RND3_marking_a_row_records_the_fact_and_moves_nothing_else() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)

    result = await _mark(world, application_id, attendance="present", expected="pending")

    assert result.summary["attendance"] == "present"
    assert result.summary["previous"] == "pending"
    state = (
        await _rows(
            "SELECT s.attendance, s.result, a.status, a.current_round_id "
            "FROM application_round_states s JOIN applications a ON a.id = s.application_id "
            "WHERE s.application_id = :id",
            {"id": application_id},
        )
    )[0]
    # Attendance is a fact about the round, not a verdict on the application:
    # finalize_round (M11) is what turns absence into a consequence.
    assert state["attendance"] == "present"
    assert state["result"] == "pending"
    assert state["status"] == "in_progress"
    assert state["current_round_id"] == world.round_id


async def test_RND3_the_event_names_the_round_and_what_it_moved_from() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)

    await _mark(
        world, application_id, attendance="excused", expected="pending", reason="Medical"
    )

    event = (
        await _rows(
            "SELECT event_type, from_status, to_status, from_round_id, to_round_id, "
            "reason, payload FROM application_events "
            "WHERE application_id = :id AND event_type = 'attendance_marked'",
            {"id": application_id},
        )
    )[0]
    assert event["from_round_id"] == world.round_id
    assert event["to_round_id"] == world.round_id
    # No status moved, so the timeline says so on both sides rather than
    # inventing a transition that did not happen.
    assert event["from_status"] == event["to_status"] == "in_progress"
    assert event["reason"] == "Medical"
    assert event["payload"]["attendance"] == "excused"
    assert event["payload"]["previous"] == "pending"


async def test_RND3_the_chip_walks_every_state_and_comes_back() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)

    for target, expected in (
        ("present", "pending"),
        ("absent", "present"),
        ("excused", "absent"),
        ("pending", "excused"),
    ):
        await _mark(world, application_id, attendance=target, expected=expected)
        assert await _attendance(application_id) == target


async def test_RND3_a_chip_showing_something_else_is_refused() -> None:
    """The compare-and-set: two coordinators, one sheet, no silent overwrite."""
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)
    await _mark(world, application_id, attendance="absent", expected="pending")

    with pytest.raises(DomainRejection) as rejection:
        await _mark(world, application_id, attendance="present", expected="pending")

    assert [reason.code for reason in rejection.value.rejection.reasons] == [STALE_VIEW]
    assert await _attendance(application_id) == "absent"


async def test_RND3_a_round_the_coordinator_was_not_looking_at_cannot_be_marked() -> None:
    """the design review section 4.23: round_id is on the wire so this can be refused."""
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            second = await seed_round(connection, job_id=world.job_id, ord=2, name="Interview")
    finally:
        await engine.dispose()

    with pytest.raises(DomainRejection) as rejection:
        await _mark(
            world,
            application_id,
            attendance="present",
            expected="pending",
            round_id=second,
        )

    assert [reason.code for reason in rejection.value.rejection.reasons] == [
        INVALID_TRANSITION
    ]
    assert await _attendance(application_id) == "pending"


async def test_RND3_marking_the_value_it_already_holds_changes_nothing() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)

    with pytest.raises(DomainRejection) as rejection:
        await _mark(world, application_id, attendance="pending", expected="pending")

    assert [reason.code for reason in rejection.value.rejection.reasons] == [DUPLICATE_ROW]


async def test_RND3_a_withdrawn_application_is_not_an_absentee() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)
    await _execute(
        "UPDATE applications SET status = 'withdrawn' WHERE id = :id",
        {"id": application_id},
    )

    with pytest.raises(DomainRejection) as rejection:
        await _mark(world, application_id, attendance="absent", expected="pending")

    assert [reason.code for reason in rejection.value.rejection.reasons] == [
        INVALID_TRANSITION
    ]


async def test_RND3_a_rejected_application_stays_markable_for_the_remedy() -> None:
    """RND-3's post-finalize remedy is to fix the sheet, then reinstate (INT-1)."""
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)
    await _execute(
        "UPDATE applications SET status = 'rejected' WHERE id = :id",
        {"id": application_id},
    )

    await _mark(world, application_id, attendance="excused", expected="pending")

    assert await _attendance(application_id) == "excused"


async def test_CYC1_an_archived_cycle_refuses_the_mark() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)
    await _execute(
        "UPDATE cycles SET archived_at = now() WHERE id = :id", {"id": world.cycle_id}
    )

    with pytest.raises(DomainRejection) as rejection:
        await _mark(world, application_id, attendance="present", expected="pending")

    assert [reason.code for reason in rejection.value.rejection.reasons] == [
        CYCLE_ARCHIVED
    ]


async def test_RND3_a_pasted_sheet_flips_pending_to_present() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    first = await _applied(world)

    result = await _present(
        world,
        [{"identifier": world.roll_number}, {"identifier": "21119999"}],
    )

    assert await _attendance(first) == "present"
    reported = _reported(result)
    assert [row["status"] for row in reported] == ["ok", "error"]
    # Named, never counted: the typo is the one to go and check.
    assert [
        row["identifier"] for row in reported if row["reason"] == UNMATCHED_IDENTIFIER
    ] == ["21119999"]


async def test_RND3_bulk_absent_flips_only_pending_rows() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)

    preview = await _present(
        world,
        [{"identifier": world.roll_number}],
        dry_run=True,
        command="bulk_mark_absent",
    )
    assert await _attendance(application_id) == "pending"
    result = await _present(
        world,
        [{"identifier": world.roll_number}],
        command="bulk_mark_absent",
    )

    assert await _attendance(application_id) == "absent"
    assert _reported(preview)[0]["attendance"] == "absent"
    assert _reported(result)[0]["previous"] == "pending"


async def test_RND3_a_paste_does_not_overwrite_a_decision_somebody_made() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)
    await _mark(world, application_id, attendance="excused", expected="pending")

    result = await _present(world, [{"identifier": world.roll_number}])

    assert await _attendance(application_id) == "excused"
    assert [(row["status"], row["reason"]) for row in _reported(result)] == [
        ("skipped", INVALID_TRANSITION)
    ]


async def test_RND2_the_paste_preview_states_the_per_row_effect_before_committing() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)

    preview = await _present(world, [{"identifier": world.roll_number}], dry_run=True)
    assert await _attendance(application_id) == "pending"
    committed = await _present(world, [{"identifier": world.roll_number}])

    previewed_row = _reported(preview)[0]
    assert previewed_row["full_name"] == world.student_name
    assert previewed_row["attendance"] == "present"
    assert previewed_row["previous"] == "pending"
    assert _reported(committed) == _reported(preview)


async def test_RND2_a_row_named_twice_in_one_paste_is_applied_once() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    await _applied(world)

    result = await _present(
        world,
        [{"identifier": world.roll_number}, {"identifier": "asha@example.edu"}],
    )

    assert [(row["status"], row["reason"]) for row in _reported(result)] == [
        ("ok", None),
        ("skipped", DUPLICATE_ROW),
    ]
