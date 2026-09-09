"""Advancing, eliminating, waitlisting and promoting (RND-1, RND-2, APP-4)."""

from __future__ import annotations

import os
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import (
    DUPLICATE_ROW,
    INVALID_TRANSITION,
    STALE_VIEW,
    UNMATCHED_IDENTIFIER,
    AuthorizationDenied,
    DomainRejection,
)
from app.core.plan import Preview, Result
from tests.applications.conftest import (
    World,
    build_test_executor,
    seed_person,
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


async def _bulk(
    world: World,
    command: str,
    rows: list[dict[str, str]],
    *,
    reason: str | None = None,
    dry_run: bool = False,
    actor: Any = None,
    key: str | None = None,
) -> Preview | Result:
    executor, engine = build_test_executor()
    fields: dict[str, object] = {"cycle_id": world.cycle_id, "job_id": world.job_id}
    if reason is not None:
        fields["reason"] = reason
    try:
        return await executor.run_bulk(
            command,
            rows,  # type: ignore[arg-type]
            key or f"{command}-{uuid4()}",
            actor or world.staff_actor,
            dry_run=dry_run,
            batch_fields=fields,
        )
    finally:
        await engine.dispose()


async def _applied(world: World, *, enrollment_id: UUID | None = None) -> UUID:
    """One application, filed through APP-1 so the board has a real row."""
    executor, engine = build_test_executor()
    model = executor.registry.commands["apply"].input_model
    actor = world.student.actor
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
            actor,
        )
        return UUID(cast(str, cast(Result, result).summary["application_id"]))
    finally:
        await engine.dispose()


def _rows_of(outcome: Preview | Result) -> list[dict[str, Any]]:
    """The per-row report, which is all `run_bulk` carries across chunks.

    Chunk-level counts do not survive aggregation by design, so the row list is
    the contract a caller actually gets -- and therefore what these tests read.
    """
    return cast("list[dict[str, Any]]", outcome.summary["rows"])


def _matched(outcome: Preview | Result) -> int:
    return sum(1 for row in _rows_of(outcome) if row["status"] == "ok")


def _unmatched(outcome: Preview | Result) -> list[str]:
    return [
        cast(str, row["identifier"])
        for row in _rows_of(outcome)
        if row["reason"] == UNMATCHED_IDENTIFIER
    ]


async def test_RND1_advancing_creates_the_next_round_and_keeps_the_status() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            second = await seed_round(connection, job_id=world.job_id, ord=2, name="Interview")
    finally:
        await engine.dispose()
    application_id = await _applied(world)

    outcome = await _bulk(
        world, "advance_applications", [{"application_id": str(application_id)}]
    )

    assert _matched(outcome) == 1
    application = (
        await _rows("SELECT * FROM applications WHERE id = :id", {"id": application_id})
    )[0]
    assert application["status"] == "in_progress"
    assert application["current_round_id"] == second
    states = await _rows(
        "SELECT r.ord, s.result, s.attendance FROM application_round_states s "
        "JOIN job_rounds r ON r.id = s.round_id WHERE s.application_id = :id "
        "ORDER BY r.ord",
        {"id": application_id},
    )
    assert [(row["ord"], row["result"]) for row in states] == [(1, "advanced"), (2, "pending")]
    assert states[1]["attendance"] == "pending"


async def test_APP4_advancing_past_the_final_round_lands_on_pending_offer() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)

    await _bulk(world, "advance_applications", [{"application_id": str(application_id)}])

    application = (
        await _rows("SELECT * FROM applications WHERE id = :id", {"id": application_id})
    )[0]
    assert application["status"] == "pending_offer"
    # The position stays put: the timeline must still say which round produced
    # the offer, and there is no next round to move onto.
    assert application["current_round_id"] == world.round_id


async def test_RND1_waitlisting_moves_the_result_and_not_the_status() -> None:
    """APP-4 has no waitlisted status, and none is invented here."""
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)

    await _bulk(world, "waitlist_applications", [{"application_id": str(application_id)}])

    application = (
        await _rows("SELECT * FROM applications WHERE id = :id", {"id": application_id})
    )[0]
    assert application["status"] == "in_progress"
    assert application["current_round_id"] == world.round_id
    state = (
        await _rows(
            "SELECT result FROM application_round_states WHERE application_id = :id",
            {"id": application_id},
        )
    )[0]
    assert state["result"] == "waitlisted"
    events = await _rows(
        "SELECT event_type FROM application_events WHERE application_id = :id "
        "ORDER BY created_at",
        {"id": application_id},
    )
    assert [row["event_type"] for row in events] == ["created", "waitlisted"]


async def test_RND1_a_waitlisted_row_resolves_only_by_promotion() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)
    await _bulk(world, "waitlist_applications", [{"application_id": str(application_id)}])

    # Advance refuses it and says why rather than silently doing nothing.
    refused = await _bulk(
        world, "advance_applications", [{"application_id": str(application_id)}]
    )
    assert _rows_of(refused)[0]["status"] == "skipped"
    assert _rows_of(refused)[0]["reason"] == INVALID_TRANSITION

    promoted = await _bulk(
        world, "promote_waitlisted", [{"application_id": str(application_id)}]
    )

    assert _matched(promoted) == 1
    application = (
        await _rows("SELECT * FROM applications WHERE id = :id", {"id": application_id})
    )[0]
    # Promotion follows advance semantics exactly (the design review section 4.21).
    assert application["status"] == "pending_offer"


async def test_RND2_pasted_identifiers_resolve_and_the_unmatched_are_named() -> None:
    """Three typos in a paste are three names, never the number three."""
    world = await seed_world(with_rounds=True, with_staff=True)
    await _applied(world)

    outcome = await _bulk(
        world,
        "advance_applications",
        [
            {"identifier": "asha@example.edu"},
            {"identifier": "21110999"},
            {"identifier": "typo@example.edu"},
        ],
    )

    assert _matched(outcome) == 1
    # Named, not counted.
    assert _unmatched(outcome) == ["21110999", "typo@example.edu"]
    assert [row["status"] for row in _rows_of(outcome)] == ["ok", "error", "error"]


async def test_RND2_a_row_named_twice_is_applied_once() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)

    outcome = await _bulk(
        world,
        "advance_applications",
        [
            {"application_id": str(application_id)},
            {"identifier": "asha@example.edu"},
        ],
    )

    assert _matched(outcome) == 1
    assert [row["status"] for row in _rows_of(outcome)] == ["ok", "skipped"]
    assert _rows_of(outcome)[1]["reason"] == DUPLICATE_ROW


async def test_RND2_expected_status_refuses_a_stale_board() -> None:
    """The board was showing something else when this was submitted."""
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)

    outcome = await _bulk(
        world,
        "advance_applications",
        [{"application_id": str(application_id), "expected_status": "pending_offer"}],
    )

    assert _matched(outcome) == 0
    assert _rows_of(outcome)[0]["reason"] == STALE_VIEW
    assert (
        await _rows("SELECT status FROM applications WHERE id = :id", {"id": application_id})
    )[0]["status"] == "in_progress"


async def test_RND2_the_preview_states_the_per_row_effect_before_committing() -> None:
    """Not a count: what happens to each row, by name, before anything moves."""
    world = await seed_world(with_rounds=True, with_staff=True)
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await seed_round(connection, job_id=world.job_id, ord=2, name="Interview")
    finally:
        await engine.dispose()
    application_id = await _applied(world)

    preview = await _bulk(
        world,
        "advance_applications",
        [{"application_id": str(application_id)}, {"identifier": "nobody@example.edu"}],
        dry_run=True,
    )

    rows = _rows_of(preview)
    assert rows[0]["to_round"] == "Interview"
    assert rows[0]["to_status"] == "in_progress"
    assert rows[0]["full_name"] == world.student_name
    assert rows[1]["status"] == "error"
    # A preview moves nothing.
    assert (
        await _rows("SELECT * FROM applications WHERE id = :id", {"id": application_id})
    )[0]["current_round_id"] == world.round_id


async def test_RND2_eliminating_requires_a_reason_and_records_it() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)

    outcome = await _bulk(
        world,
        "eliminate_applications",
        [{"application_id": str(application_id)}],
        reason="Did not clear the written test",
    )

    assert _matched(outcome) == 1
    application = (
        await _rows("SELECT * FROM applications WHERE id = :id", {"id": application_id})
    )[0]
    assert application["status"] == "rejected"
    event = (
        await _rows(
            "SELECT reason, event_type FROM application_events "
            "WHERE application_id = :id AND event_type = 'eliminated'",
            {"id": application_id},
        )
    )[0]
    assert event["reason"] == "Did not clear the written test"


async def test_RND2_eliminating_without_a_reason_is_refused_outright() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)

    with pytest.raises(DomainRejection) as error:
        await _bulk(
            world, "eliminate_applications", [{"application_id": str(application_id)}]
        )

    # A missing reason is a whole-batch refusal, not a per-row skip: RND-2's
    # reasoned event has nothing to record, and eliminating half a paste before
    # noticing would be worse than eliminating none of it.
    assert [item.code for item in error.value.rejection.reasons] == [INVALID_TRANSITION]
    assert error.value.rejection.reasons[0].path == "reason"
    assert (
        await _rows("SELECT status FROM applications WHERE id = :id", {"id": application_id})
    )[0]["status"] == "in_progress"


async def test_RND2_a_settled_application_is_skipped_not_moved() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)
    await _bulk(
        world,
        "eliminate_applications",
        [{"application_id": str(application_id)}],
        reason="Out",
    )

    outcome = await _bulk(
        world, "advance_applications", [{"application_id": str(application_id)}]
    )

    assert _matched(outcome) == 0
    assert _rows_of(outcome)[0]["status"] == "skipped"
    assert (
        await _rows("SELECT status FROM applications WHERE id = :id", {"id": application_id})
    )[0]["status"] == "rejected"


async def test_IDN3_a_coordinator_of_another_cycle_cannot_move_this_board() -> None:
    world = await seed_world(with_rounds=True, with_staff=True)
    application_id = await _applied(world)
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            outsider = await seed_person(connection, email="other.coord@example.edu")
    finally:
        await engine.dispose()

    # The *shape* is asserted, not just the denial: a denial wrapped in
    # BulkInterrupted reaches the client as a 500 saying "some rows did not
    # apply", with resume coordinates for a retry that cannot succeed. M10c
    # made run_bulk re-raise it (the design review section 4.23), and this is the pin.
    with pytest.raises(AuthorizationDenied):
        await _bulk(
            world,
            "advance_applications",
            [{"application_id": str(application_id)}],
            actor=outsider.actor,
        )

    assert (
        await _rows("SELECT * FROM applications WHERE id = :id", {"id": application_id})
    )[0]["current_round_id"] == world.round_id
