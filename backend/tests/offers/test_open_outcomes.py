"""JOB-6 staff-recorded open-cycle outcomes remain APP-4 compositions."""

from __future__ import annotations

import os
from typing import cast
from uuid import UUID

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import DomainRejection
from app.core.plan import ActorContext, Result
from app.domain.shared import EventType, RuleDomain
from tests.offers.conftest import (
    build_test_executor,
    seed_admin,
    seed_application,
    seed_cycle,
    seed_external_offer,
    seed_job,
    seed_person,
    seed_portal_offer,
)
from tests.overrides.conftest import grant

pytestmark = pytest.mark.asyncio


async def _record(
    *,
    admin: ActorContext,
    cycle_id: UUID,
    job_id: UUID,
    application_id: UUID,
    status: str,
    reason: str | None = None,
) -> Result:
    executor, engine = build_test_executor()
    try:
        result = await executor.run_bulk(
            "record_open_outcome",
            [
                {
                    "application_id": str(application_id),
                    "expected_status": "in_progress",
                }
            ],
            f"record-{status}",
            admin,
            batch_fields={
                "cycle_id": cycle_id,
                "job_id": job_id,
                "target_status": status,
                "reason": reason,
            },
        )
    finally:
        await engine.dispose()
    assert isinstance(result, Result)
    return result


@pytest.mark.parametrize(
    ("target_status", "event_types", "offer_response"),
    (
        ("offered", [EventType.OFFER_EXTENDED], None),
        ("accepted", [EventType.OFFER_EXTENDED, EventType.ACCEPTED], "accepted"),
        ("declined", [EventType.OFFER_EXTENDED, EventType.DECLINED], "declined"),
    ),
)
async def test_JOB6_straight_open_outcomes_compose_through_an_offer_row(
    target_status: str,
    event_types: list[EventType],
    offer_response: str | None,
) -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="student@example.edu")
            cycle_id = await seed_cycle(connection, kind="open")
            job_id = await seed_job(
                connection,
                cycle_id=cycle_id,
                outcome="placement",
                with_deadline=False,
            )
            application_id, _ = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status="in_progress",
                job_id=job_id,
            )
    finally:
        await engine.dispose()

    result = await _record(
        admin=admin.actor,
        cycle_id=cycle_id,
        job_id=job_id,
        application_id=application_id,
        status=target_status,
    )

    assert [event.event_type for event in result.events] == event_types
    result_rows = cast("list[dict[str, object]]", result.summary["rows"])
    assert result_rows[0]["to_status"] == target_status
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    sa.text(
                        "SELECT a.status, o.response, o.deadline_at "
                        "FROM applications a JOIN offers o ON o.application_id = a.id "
                        "WHERE a.id = :id"
                    ),
                    {"id": application_id},
                )
            ).mappings().one()
    finally:
        await engine.dispose()
    assert row["status"] == target_status
    assert row["response"] == offer_response
    assert row["deadline_at"] is None


async def test_JOB6_open_placement_acceptance_uses_the_global_OFR3_cascade() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="student@example.edu")
            open_cycle = await seed_cycle(connection, kind="open")
            placement_cycle = await seed_cycle(
                connection, name="Dedicated placements"
            )
            target_job = await seed_job(
                connection,
                cycle_id=open_cycle,
                title="Off-portal placement",
                outcome="placement",
                with_deadline=False,
            )
            other_job = await seed_job(
                connection,
                cycle_id=placement_cycle,
                title="Portal placement",
                outcome="placement",
            )
            target_application, _ = await seed_application(
                connection,
                cycle_id=open_cycle,
                enrollment_id=student.enrollment_id,
                status="in_progress",
                job_id=target_job,
            )
            other_application, _ = await seed_application(
                connection,
                cycle_id=placement_cycle,
                enrollment_id=student.enrollment_id,
                status="in_progress",
                job_id=other_job,
            )
    finally:
        await engine.dispose()

    result = await _record(
        admin=admin.actor,
        cycle_id=open_cycle,
        job_id=target_job,
        application_id=target_application,
        status="accepted",
    )
    result_rows = cast("list[dict[str, object]]", result.summary["rows"])
    cascade = cast("list[dict[str, object]]", result_rows[0]["cascade"])
    assert [UUID(cast(str, row["application_id"])) for row in cascade] == [
        other_application
    ]


async def test_JOB6_open_internship_acceptance_cascades_zero_siblings() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="student@example.edu")
            cycle_id = await seed_cycle(connection, kind="open")
            target_job = await seed_job(
                connection,
                cycle_id=cycle_id,
                title="Open internship A",
                outcome="internship",
                with_deadline=False,
            )
            sibling_job = await seed_job(
                connection,
                cycle_id=cycle_id,
                title="Open internship B",
                outcome="internship",
                with_deadline=False,
            )
            target_application, _ = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status="in_progress",
                job_id=target_job,
            )
            sibling_application, _ = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status="in_progress",
                job_id=sibling_job,
            )
    finally:
        await engine.dispose()

    result = await _record(
        admin=admin.actor,
        cycle_id=cycle_id,
        job_id=target_job,
        application_id=target_application,
        status="accepted",
    )
    result_rows = cast("list[dict[str, object]]", result.summary["rows"])
    assert result_rows[0]["cascade"] == []

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            sibling_status = await connection.scalar(
                sa.text("SELECT status FROM applications WHERE id = :id"),
                {"id": sibling_application},
            )
    finally:
        await engine.dispose()
    assert sibling_status == "in_progress"


async def test_INT2_open_outcome_resolves_outcome_overrides_per_application() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            allowed = await seed_person(connection, email="outcome-allowed@example.edu")
            blocked = await seed_person(connection, email="outcome-blocked@example.edu")
            cycle_id = await seed_cycle(connection, kind="open")
            job_id = await seed_job(
                connection,
                cycle_id=cycle_id,
                outcome="placement",
                with_deadline=False,
            )
            company_id = await connection.scalar(
                sa.text("SELECT company_id FROM jobs WHERE id = :id"), {"id": job_id}
            )
            assert isinstance(company_id, UUID)
            applications: dict[UUID, UUID] = {}
            for student in (allowed, blocked):
                applications[student.enrollment_id], _ = await seed_application(
                    connection,
                    cycle_id=cycle_id,
                    enrollment_id=student.enrollment_id,
                    status="in_progress",
                    job_id=job_id,
                )
                await seed_external_offer(
                    connection,
                    enrollment_id=student.enrollment_id,
                    company_id=company_id,
                    created_by=admin.user_id,
                    status="accepted",
                )
            override_id = await grant(
                connection,
                domain=RuleDomain.OUTCOME_GATE,
                granted_by=admin.user_id,
                application_id=applications[allowed.enrollment_id],
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    try:
        result = await executor.run_bulk(
            "record_open_outcome",
            [
                {
                    "application_id": str(applications[allowed.enrollment_id]),
                    "expected_status": "in_progress",
                },
                {
                    "application_id": str(applications[blocked.enrollment_id]),
                    "expected_status": "in_progress",
                },
            ],
            "open-outcome-per-application",
            admin.actor,
            batch_fields={
                "cycle_id": cycle_id,
                "job_id": job_id,
                "target_status": "accepted",
            },
        )
    finally:
        await command_engine.dispose()
    assert isinstance(result, Result)
    rows = {
        UUID(cast(str, row["application_id"])): row
        for row in cast("list[dict[str, object]]", result.summary["rows"])
    }
    assert rows[applications[allowed.enrollment_id]]["status"] == "ok"
    assert rows[applications[blocked.enrollment_id]]["status"] == "skipped"
    assert rows[applications[blocked.enrollment_id]]["reason"] == "outcome_gate_placement"
    accepted_event = next(
        event
        for event in result.events
        if event.application_id == applications[allowed.enrollment_id]
        and event.event_type is EventType.ACCEPTED
    )
    assert accepted_event.payload["applied_override_ids"] == [str(override_id)]


async def test_INT2_open_outcome_resolves_offer_cap_override_at_application_scope() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="open-cap-override@example.edu")
            cycle_id = await seed_cycle(connection, kind="open")
            await connection.execute(
                sa.text(
                    "UPDATE cycle_policies SET max_accepted_offers = 1 "
                    "WHERE cycle_id = :cycle_id"
                ),
                {"cycle_id": cycle_id},
            )
            accepted_job = await seed_job(
                connection,
                cycle_id=cycle_id,
                title="Existing internship",
                outcome="internship",
                with_deadline=False,
            )
            accepted_application, _ = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status="accepted",
                job_id=accepted_job,
            )
            await seed_portal_offer(
                connection,
                application_id=accepted_application,
                response="accepted",
            )
            target_job = await seed_job(
                connection,
                cycle_id=cycle_id,
                title="Exceptional internship",
                outcome="internship",
                with_deadline=False,
            )
            target_application, _ = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status="in_progress",
                job_id=target_job,
            )
            override_id = await grant(
                connection,
                domain=RuleDomain.OFFER_CAP,
                granted_by=admin.user_id,
                application_id=target_application,
            )
    finally:
        await engine.dispose()

    result = await _record(
        admin=admin.actor,
        cycle_id=cycle_id,
        job_id=target_job,
        application_id=target_application,
        status="accepted",
    )
    accepted_event = next(
        event for event in result.events if event.event_type is EventType.ACCEPTED
    )
    assert accepted_event.payload["applied_override_ids"] == [str(override_id)]


async def test_JOB6_direct_rejection_requires_reason_and_creates_no_offer() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="student@example.edu")
            cycle_id = await seed_cycle(connection, kind="open")
            job_id = await seed_job(
                connection, cycle_id=cycle_id, with_deadline=False
            )
            application_id, _ = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status="in_progress",
                job_id=job_id,
            )
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    try:
        with pytest.raises(DomainRejection):
            await executor.run_bulk(
                "record_open_outcome",
                [{"application_id": str(application_id)}],
                "reject-without-reason",
                admin.actor,
                dry_run=True,
                batch_fields={
                    "cycle_id": cycle_id,
                    "job_id": job_id,
                    "target_status": "rejected",
                },
            )
    finally:
        await engine.dispose()

    result = await _record(
        admin=admin.actor,
        cycle_id=cycle_id,
        job_id=job_id,
        application_id=application_id,
        status="rejected",
        reason="Company did not select the student",
    )
    assert [event.event_type for event in result.events] == [EventType.ELIMINATED]

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            status = await connection.scalar(
                sa.text("SELECT status FROM applications WHERE id = :id"),
                {"id": application_id},
            )
            count = await connection.scalar(
                sa.text("SELECT count(*) FROM offers WHERE application_id = :id"),
                {"id": application_id},
            )
    finally:
        await engine.dispose()
    assert status == "rejected"
    assert count == 0


async def test_JOB6_staff_recording_is_rejected_for_a_dedicated_cycle() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="student@example.edu")
            cycle_id = await seed_cycle(connection)
            job_id = await seed_job(connection, cycle_id=cycle_id)
            application_id, _ = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                job_id=job_id,
            )
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    try:
        with pytest.raises(DomainRejection) as error:
            await executor.run_bulk(
                "record_open_outcome",
                [{"application_id": str(application_id)}],
                "dedicated-record",
                admin.actor,
                dry_run=True,
                batch_fields={
                    "cycle_id": cycle_id,
                    "job_id": job_id,
                    "target_status": "accepted",
                },
            )
    finally:
        await engine.dispose()
    assert [reason.code for reason in error.value.rejection.reasons] == [
        "invalid_transition"
    ]
