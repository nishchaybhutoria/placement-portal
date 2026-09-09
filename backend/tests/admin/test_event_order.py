"""S16 / JOB-6 / INT-1 / ANA-2: persisted causality (the design review 4.41)."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import pytest
import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.executor import ExecutorHooks
from app.domain.shared import ApplicationStatus
from app.modules.admin.commands import RunConsistencyCheckerInput
from app.modules.analytics.metrics import _TIME_IN_ROUND_SQL
from app.modules.applications.queries import me_applications
from app.modules.interventions.commands import ForceTransitionInput
from app.modules.interventions.queries import staff_student_record
from app.modules.offers.external import _history as external_history
from app.modules.offers.screens import _history as preview_history
from app.modules.offers.termination import _event_history as portal_history
from tests.admin.conftest import (
    CheckerWorld,
    build_checker_world,
    build_test_executor,
    read_engine,
    seed_application,
    seed_event,
    write_engine,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("clean_findings")]


async def rows(sql: str, **params: object) -> list[sa.RowMapping]:
    engine = read_engine()
    try:
        async with engine.connect() as connection:
            return list((await connection.execute(sa.text(sql), params)).mappings())
    finally:
        await engine.dispose()


async def sequence_state() -> list[sa.RowMapping]:
    return await rows("SELECT last_value, is_called FROM application_events_event_seq_seq")


async def open_application(world: CheckerWorld) -> UUID:
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            app = await seed_application(
                connection,
                job_id=world.open_job_id,
                enrollment_id=world.student.enrollment_id,
                status="in_progress",
            )
            await seed_event(
                connection, application_id=app, event_type="created", to_status="in_progress"
            )
            return app
    finally:
        await engine.dispose()


async def assert_readers(
    world: CheckerWorld, application_id: UUID, expected: list[str], statuses: list[str]
) -> None:
    """Execute the real timelines and all three restoration history adapters."""
    engine = read_engine()
    try:
        own = await me_applications(engine, world.student.enrollment_id)
        staff = await staff_student_record(engine, world.admin_actor, world.student.enrollment_id)
        own_apps = cast(list[dict[str, object]], own["applications"])
        staff_apps = cast(list[dict[str, object]], staff["applications"])
        for apps, event_key in ((own_apps, "timeline"), (staff_apps, "events")):
            app = next(
                a for a in apps if a.get("application_id", a.get("id")) == str(application_id)
            )
            events = cast(list[dict[str, object]], app[event_key])
            assert [e["event_type"] for e in events] == expected
            assert [e["to_status"] for e in events] == statuses
        timeline = cast(list[dict[str, object]], staff["timeline"])
        assert [
            e["event_type"] for e in timeline if e["application_id"] == str(application_id)
        ] == expected
        assert [
            e["to_status"] for e in timeline if e["application_id"] == str(application_id)
        ] == statuses
        async with AsyncSession(engine) as session:
            for load in (portal_history, external_history, preview_history):
                history = await load(session, world.student.enrollment_id)
                selected = [e for e in history if e.application_id == application_id]
                assert [e.event_type.value for e in selected] == expected
                assert [e.to_status.value for e in selected if e.to_status is not None] == statuses
                persisted = await rows(
                    "SELECT event_seq FROM application_events "
                    "WHERE application_id=:id ORDER BY event_seq",
                    id=application_id,
                )
                assert [e.sequence for e in selected] == [r["event_seq"] for r in persisted]
    finally:
        await engine.dispose()


@pytest.mark.parametrize("outcome", ["accepted", "declined"])
async def test_JOB6_composed_outcome_checker_and_every_reader_agree(outcome: str) -> None:
    world = await build_checker_world()
    app = await open_application(world)
    executor, engine = build_test_executor()
    args = {"cycle_id": world.open_cycle, "job_id": world.open_job_id, "target_status": outcome}
    inputs: list[dict[str, object]] = [
        {"application_id": str(app), "expected_status": "in_progress"}
    ]
    try:
        before = await sequence_state()
        preview = await executor.run_bulk(
            "record_open_outcome",
            inputs,
            "ordered-outcome",
            world.admin_actor,
            batch_fields=args,
            dry_run=True,
        )
        assert await sequence_state() == before
        result = await executor.run_bulk(
            "record_open_outcome",
            inputs,
            "ordered-outcome",
            world.admin_actor,
            batch_fields=args,
        )
        assert result.events == preview.events
        after = await sequence_state()
        replay = await executor.run_bulk(
            "record_open_outcome",
            inputs,
            "ordered-outcome",
            world.admin_actor,
            batch_fields=args,
        )
        assert replay == result
        assert await sequence_state() == after
    finally:
        await engine.dispose()

    events = await rows(
        "SELECT event_type, created_at FROM application_events "
        "WHERE application_id=:id ORDER BY event_seq",
        id=app,
    )
    assert [r["event_type"] for r in events] == ["created", "offer_extended", outcome]
    assert events[1]["created_at"] == events[2]["created_at"]
    # Superuser corruption fixture: force UUID ordering to contradict causality,
    # rather than hoping random UUIDs happen to expose the old bug in this run.
    writer = write_engine()
    try:
        async with writer.begin() as connection:
            await connection.execute(
                sa.text(
                    "UPDATE application_events SET id = CASE WHEN event_type='offer_extended' "
                    "THEN 'ffffffff-ffff-4fff-afff-ffffffffffff'::uuid "
                    "ELSE '00000000-0000-4000-a000-000000000001'::uuid END "
                    "WHERE application_id=:id "
                    "AND event_type IN ('offer_extended','accepted','declined')"
                ),
                {"id": app},
            )
    finally:
        await writer.dispose()
    executor, engine = build_test_executor()
    try:
        check = await executor.run(
            "run_consistency_checker", RunConsistencyCheckerInput(), world.admin_actor
        )
        assert check.summary["violations"] == 0
        assert await rows("SELECT * FROM consistency_findings") == []
    finally:
        await engine.dispose()
    await assert_readers(
        world, app, ["created", "offer_extended", outcome], ["in_progress", "offered", outcome]
    )


async def test_S16_rollback_discards_sequenced_events_and_retry_appends_once() -> None:
    world = await build_checker_world()
    app = await open_application(world)
    executor, engine = build_test_executor()
    original = await rows("SELECT * FROM application_events ORDER BY event_seq")
    before = await sequence_state()

    async def fail() -> None:
        raise RuntimeError("after events before commit")

    executor.hooks = ExecutorHooks(before_commit=fail)
    value = ForceTransitionInput(
        cycle_id=world.open_cycle,
        application_id=app,
        to_status=ApplicationStatus.REJECTED,
        reason="Ordering test",
    )
    try:
        with pytest.raises(RuntimeError, match="after events before commit"):
            await executor.run(
                "force_transition", value, world.admin_actor, idempotency_key="ordered-rollback"
            )
        assert await rows("SELECT * FROM application_events ORDER BY event_seq") == original
        assert await sequence_state() != before  # PostgreSQL sequence gaps are legitimate.
        executor.hooks = ExecutorHooks()
        await executor.run(
            "force_transition", value, world.admin_actor, idempotency_key="ordered-rollback"
        )
        assert (
            len(await rows("SELECT * FROM application_events ORDER BY event_seq"))
            == len(original) + 1
        )
    finally:
        await engine.dispose()


async def test_S16_waiting_older_transaction_appends_after_its_newer_predecessor() -> None:
    world = await build_checker_world()
    app = await open_application(world)
    older, older_engine = build_test_executor()
    newer, newer_engine = build_test_executor()
    started, locked, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    pid: list[int] = []
    spec = older.registry.commands["force_transition"]

    async def delayed_loader(tx: AsyncSession, value: BaseModel, *, lock: bool) -> object:
        # Establish an earlier transaction timestamp, then let the newer
        # command acquire the real application lock before this loader does.
        pid.append(int(await tx.scalar(sa.text("SELECT pg_backend_pid()"))))
        started.set()
        await locked.wait()
        return await spec.loader(tx, value, lock=lock)

    async def hold_newer_lock() -> None:
        locked.set()
        await release.wait()

    older.registry.commands["force_transition"] = replace(spec, loader=delayed_loader)
    newer.hooks = ExecutorHooks(before_commit=hold_newer_lock)
    old_task = asyncio.create_task(
        older.run(
            "force_transition",
            ForceTransitionInput(
                cycle_id=world.open_cycle,
                application_id=app,
                to_status=ApplicationStatus.WITHDRAWN,
                reason="Later decision",
            ),
            world.admin_actor,
        )
    )
    new_task = None
    try:
        await asyncio.wait_for(started.wait(), 5)
        new_task = asyncio.create_task(
            newer.run(
                "force_transition",
                ForceTransitionInput(
                    cycle_id=world.open_cycle,
                    application_id=app,
                    to_status=ApplicationStatus.REJECTED,
                    reason="First decision",
                ),
                world.admin_actor,
            )
        )
        await asyncio.wait_for(locked.wait(), 5)

        async def wait_for_real_lock_wait() -> None:
            # PostgreSQL owns this signal; there is no in-process Event for it.
            while not (  # noqa: ASYNC110
                await rows("SELECT cardinality(pg_blocking_pids(:pid)) AS blockers", pid=pid[0])
            )[0]["blockers"]:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_real_lock_wait(), 5)
        release.set()
        await asyncio.wait_for(asyncio.gather(old_task, new_task), 10)
    finally:
        locked.set()
        release.set()
        for task in (old_task, new_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(t for t in (old_task, new_task) if t is not None), return_exceptions=True
        )
        await older_engine.dispose()
        await newer_engine.dispose()
    events = await rows(
        "SELECT to_status, created_at FROM application_events "
        "WHERE application_id=:id ORDER BY event_seq",
        id=app,
    )
    assert [e["to_status"] for e in events] == ["in_progress", "rejected", "withdrawn"]
    assert events[2]["created_at"] < events[1]["created_at"]
    await assert_readers(
        world,
        app,
        ["created", "forced_transition", "forced_transition"],
        ["in_progress", "rejected", "withdrawn"],
    )
    # Distinguish those two same-type timeline entries by their status, too.
    record = await rows(
        "SELECT a.status, e.to_status FROM applications a JOIN LATERAL "
        "(SELECT to_status FROM application_events WHERE application_id=a.id "
        "ORDER BY event_seq DESC LIMIT 1) e ON true WHERE a.id=:id",
        id=app,
    )
    assert record[0]["status"] == record[0]["to_status"] == "withdrawn"
    executor, engine = build_test_executor()
    try:
        check = await executor.run(
            "run_consistency_checker", RunConsistencyCheckerInput(), world.admin_actor
        )
        assert check.summary["violations"] == 0
    finally:
        await engine.dispose()


async def test_ANA2_same_transaction_successor_closes_a_zero_duration_passage() -> None:
    world = await build_checker_world()
    writer = write_engine()
    instant = datetime(2026, 1, 1, tzinfo=UTC)
    try:
        async with writer.begin() as connection:
            # Test-only controlled event history: one round entry, an immediate
            # exit, then a later event that must not be mistaken for that exit.
            await connection.execute(
                sa.text("DELETE FROM application_events WHERE application_id=:id"),
                {"id": world.application_id},
            )
            for index, round_id in enumerate((world.rounds[0], None, None)):
                await connection.execute(
                    sa.text(
                        "INSERT INTO application_events "
                        "(application_id,event_type,to_round_id,created_at) "
                        "VALUES (:id,'advanced',:round,:at)"
                    ),
                    {
                        "id": world.application_id,
                        "round": round_id,
                        "at": instant if index < 2 else instant + timedelta(hours=1),
                    },
                )
    finally:
        await writer.dispose()
    passages = await rows(_TIME_IN_ROUND_SQL, job_id=world.job_id)
    assert len(passages) == 1
    assert passages[0]["closed_passages"] == 1
    assert passages[0]["median_seconds"] == 0
