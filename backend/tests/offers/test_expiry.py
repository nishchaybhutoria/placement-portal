"""OFR-4 fire-time authority, revalidation, and system transitions."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.plan import ActorContext, Preview, Result
from app.domain.shared import EventType
from tests.offers.conftest import (
    build_test_executor,
    seed_admin,
    seed_application,
    seed_cycle,
    seed_job,
    seed_membership,
    seed_person,
    seed_portal_offer,
)
from tests.offers.test_gate_cutover import _seed_external_acceptance

pytestmark = pytest.mark.asyncio
SYSTEM = ActorContext(principal_id="system", is_system=True)


@dataclass(frozen=True, slots=True)
class ExpiryWorld:
    cycle_id: UUID
    job_id: UUID
    enrollment_id: UUID
    application_id: UUID
    offer_id: UUID
    scheduled_deadline: datetime


async def _seed_expiry_world(
    *,
    deadline: datetime | None = None,
    cycle_kind: str = "placement",
    application_status: str = "offered",
    response: str | None = None,
    terminated: bool = False,
    membership_status: str = "active",
    auto_accept: bool = False,
) -> ExpiryWorld:
    scheduled = datetime.now(UTC) - timedelta(minutes=2)
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await seed_admin(connection)
            student = await seed_person(connection, email="student@example.edu")
            cycle_id = await seed_cycle(connection, kind=cycle_kind)
            await seed_membership(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status=membership_status,
            )
            if auto_accept:
                await connection.execute(
                    sa.text(
                        "UPDATE cycle_policies SET offer_expiry_behavior = 'auto_accept' "
                        "WHERE cycle_id = :id"
                    ),
                    {"id": cycle_id},
                )
            job_id = await seed_job(
                connection,
                cycle_id=cycle_id,
                outcome=("internship" if cycle_kind == "internship" else "placement"),
                with_deadline=cycle_kind != "open",
            )
            application_id, _ = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status=application_status,
                job_id=job_id,
            )
            offer_id = await seed_portal_offer(
                connection,
                application_id=application_id,
                response=response,
                deadline=scheduled if deadline is None else deadline,
                terminated=terminated,
            )
    finally:
        await engine.dispose()
    return ExpiryWorld(
        cycle_id=cycle_id,
        job_id=job_id,
        enrollment_id=student.enrollment_id,
        application_id=application_id,
        offer_id=offer_id,
        scheduled_deadline=scheduled,
    )


async def _enforce(
    world: ExpiryWorld,
    *,
    scheduled_deadline: datetime | None = None,
    dry_run: bool = False,
) -> Preview | Result:
    executor, engine = build_test_executor()
    spec = executor.registry.commands["enforce_offer_expiry"]
    try:
        return await executor.run(
            "enforce_offer_expiry",
            spec.input_model.model_validate(
                {
                    "offer_id": world.offer_id,
                    "scheduled_deadline": scheduled_deadline
                    or world.scheduled_deadline,
                }
            ),
            SYSTEM,
            dry_run=dry_run,
        )
    finally:
        await engine.dispose()


async def test_OFR4_responded_offer_is_a_fire_time_noop() -> None:
    world = await _seed_expiry_world(response="declined")
    result = await _enforce(world)
    assert result.summary["action"] == "noop"


async def test_OFR4_terminated_offer_is_a_fire_time_noop() -> None:
    world = await _seed_expiry_world(terminated=True)
    result = await _enforce(world)
    assert result.summary["action"] == "noop"


async def test_OFR4_offer_that_is_no_longer_latest_is_a_fire_time_noop() -> None:
    world = await _seed_expiry_world()
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await seed_portal_offer(
                connection,
                application_id=world.application_id,
                deadline=datetime.now(UTC) + timedelta(days=1),
                extended_at=datetime.now(UTC) + timedelta(seconds=1),
            )
    finally:
        await engine.dispose()
    result = await _enforce(world)
    assert result.summary["action"] == "noop"


async def test_OFR4_application_that_is_no_longer_offered_is_a_fire_time_noop() -> None:
    world = await _seed_expiry_world(application_status="in_progress")
    result = await _enforce(world)
    assert result.summary["action"] == "noop"


async def test_OFR4_moved_deadline_uses_current_offer_authority_and_reschedules() -> None:
    moved = datetime.now(UTC) + timedelta(days=2)
    world = await _seed_expiry_world(deadline=moved)
    result = await _enforce(world)
    assert result.summary["action"] == "reschedule"
    assert result.summary["reschedule_at"] == moved.isoformat()

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            task = (
                await connection.execute(
                    sa.text(
                        "SELECT args, scheduled_at FROM procrastinate_jobs "
                        "WHERE task_name = 'enforce_offer_expiry'"
                    )
                )
            ).mappings().one()
    finally:
        await engine.dispose()
    assert task["scheduled_at"] == moved
    assert task["args"]["scheduled_deadline"] == moved.isoformat()


async def test_OFR4_task_fired_early_reschedules_from_the_authoritative_deadline() -> None:
    future = datetime.now(UTC) + timedelta(hours=4)
    world = await _seed_expiry_world(deadline=future)
    result = await _enforce(world, scheduled_deadline=future)
    assert result.summary["action"] == "reschedule"
    assert result.summary["reschedule_at"] == future.isoformat()


async def test_OFR4_open_cycle_has_no_expiry_automation() -> None:
    world = await _seed_expiry_world(cycle_kind="open")
    result = await _enforce(world)
    assert result.summary["action"] == "noop"


async def test_OFR4_null_authoritative_deadline_has_no_expiry_automation() -> None:
    world = await _seed_expiry_world()
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text("UPDATE offers SET deadline_at = NULL WHERE id = :id"),
                {"id": world.offer_id},
            )
    finally:
        await engine.dispose()
    result = await _enforce(world)
    assert result.summary["action"] == "noop"


async def test_OFR4_auto_decline_has_internal_preview_parity_and_system_event() -> None:
    world = await _seed_expiry_world()
    preview = await _enforce(world, dry_run=True)
    execution = await _enforce(world)
    assert isinstance(preview, Preview)
    assert isinstance(execution, Result)
    assert preview.summary == execution.summary
    assert preview.events == execution.events
    assert execution.summary["action"] == "auto_decline"
    assert [event.event_type for event in execution.events] == [EventType.DECLINED]
    assert execution.events[0].payload["system_initiated"] is True

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    sa.text(
                        "SELECT a.status, o.response FROM applications a "
                        "JOIN offers o ON o.application_id = a.id WHERE o.id = :id"
                    ),
                    {"id": world.offer_id},
                )
            ).mappings().one()
            actor_user_id = await connection.scalar(
                sa.text(
                    "SELECT actor_user_id FROM application_events "
                    "WHERE application_id = :id ORDER BY created_at DESC LIMIT 1"
                ),
                {"id": world.application_id},
            )
            event_key = await connection.scalar(
                sa.text(
                    "SELECT args->>'event_key' FROM procrastinate_jobs "
                    "WHERE task_name = 'deliver_notification'"
                )
            )
    finally:
        await engine.dispose()
    assert dict(row) == {"status": "declined", "response": "declined"}
    assert actor_user_id is None
    assert event_key == "offer_expired"


async def test_OFR4_auto_accept_uses_shared_cascade_and_marks_every_event_system() -> None:
    world = await _seed_expiry_world(auto_accept=True)
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            other_cycle = await seed_cycle(connection, name="Other placements")
            other_job = await seed_job(
                connection, cycle_id=other_cycle, title="Other placement"
            )
            other_application, _ = await seed_application(
                connection,
                cycle_id=other_cycle,
                enrollment_id=world.enrollment_id,
                status="in_progress",
                job_id=other_job,
            )
    finally:
        await engine.dispose()

    execution = await _enforce(world)
    assert execution.summary["action"] == "auto_accept"
    assert [event.event_type for event in execution.events] == [
        EventType.ACCEPTED,
        EventType.AUTO_WITHDRAWN,
    ]
    assert all(event.payload["system_initiated"] is True for event in execution.events)
    cascade = cast("list[dict[str, object]]", execution.summary["cascade"])
    assert [UUID(cast(str, row["application_id"])) for row in cascade] == [
        other_application
    ]


async def test_OFR4_auto_accept_inactive_membership_falls_back_with_finding() -> None:
    world = await _seed_expiry_world(
        auto_accept=True, membership_status="pending"
    )
    execution = await _enforce(world)
    assert execution.summary["action"] == "auto_decline_gate_fallback"
    assert execution.summary["failed_gate_codes"] == ["membership_not_active"]
    await _assert_finding(world.offer_id, "membership_not_active")


async def test_OFR4_auto_accept_outcome_gate_failure_falls_back_with_finding() -> None:
    world = await _seed_expiry_world(auto_accept=True)
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin_id = cast(
                UUID,
                await connection.scalar(
                    sa.text("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
                ),
            )
            await _seed_external_acceptance(
                connection,
                enrollment_id=world.enrollment_id,
                created_by=admin_id,
                outcome="placement",
            )
    finally:
        await engine.dispose()

    execution = await _enforce(world)
    assert execution.summary["action"] == "auto_decline_gate_fallback"
    assert execution.summary["failed_gate_codes"] == ["outcome_gate_placement"]
    assert execution.events[0].payload["failed_gate_codes"] == [
        "outcome_gate_placement"
    ]
    await _assert_finding(world.offer_id, "outcome_gate_placement")


async def _assert_finding(offer_id: UUID, code: str) -> None:
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            finding = (
                await connection.execute(
                    sa.text(
                        "SELECT invariant, subject, detail, status "
                        "FROM consistency_findings"
                    )
                )
            ).mappings().one()
    finally:
        await engine.dispose()
    assert finding["invariant"] == "offer_expiry_auto_accept_gate_failed"
    assert finding["subject"]["offer_id"] == str(offer_id)
    assert code in finding["detail"]
    assert finding["status"] == "open"
