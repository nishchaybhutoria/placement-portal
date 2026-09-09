"""OFR-3 response guards and the always-on acceptance cascade."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import DomainRejection
from app.core.plan import ActorContext, Result
from app.domain.shared import EventType
from tests.offers.conftest import (
    build_test_executor,
    seed_admin,
    seed_application,
    seed_cycle,
    seed_job,
    seed_person,
    seed_portal_offer,
)
from tests.offers.test_gate_cutover import _seed_external_acceptance

pytestmark = pytest.mark.asyncio


async def _accept(
    *,
    actor: ActorContext,
    cycle_id: UUID,
    job_id: UUID,
    application_id: UUID,
    offer_id: UUID,
    enrollment_id: UUID,
) -> Result:
    executor, engine = build_test_executor()
    spec = executor.registry.commands["accept_offer"]
    try:
        result = await executor.run(
            "accept_offer",
            spec.input_model.model_validate(
                {
                    "cycle_id": cycle_id,
                    "job_id": job_id,
                    "application_id": application_id,
                    "offer_id": offer_id,
                    "enrollment_id": enrollment_id,
                    "expected_status": "offered",
                }
            ),
            actor,
        )
    finally:
        await engine.dispose()
    assert isinstance(result, Result)
    return result


async def test_OFR3_placement_acceptance_cascades_across_three_cycles_and_open() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await seed_admin(connection)
            student = await seed_person(connection, email="student@example.edu")
            target_cycle = await seed_cycle(connection, name="Placements A")
            second_cycle = await seed_cycle(connection, name="Placements B")
            third_cycle = await seed_cycle(connection, name="Placements C")
            open_cycle = await seed_cycle(connection, name="Open roles", kind="open")
            internship_cycle = await seed_cycle(
                connection, name="Internships", kind="internship"
            )

            target_job = await seed_job(
                connection, cycle_id=target_cycle, title="Accepted role"
            )
            target_application, _ = await seed_application(
                connection,
                cycle_id=target_cycle,
                enrollment_id=student.enrollment_id,
                status="offered",
                job_id=target_job,
            )
            target_offer = await seed_portal_offer(
                connection,
                application_id=target_application,
                deadline=datetime.now(UTC) + timedelta(days=10),
            )

            offered_job = await seed_job(
                connection, cycle_id=second_cycle, title="Other offer"
            )
            offered_application, _ = await seed_application(
                connection,
                cycle_id=second_cycle,
                enrollment_id=student.enrollment_id,
                status="offered",
                job_id=offered_job,
            )
            offered_offer = await seed_portal_offer(
                connection, application_id=offered_application
            )

            pending_job = await seed_job(
                connection, cycle_id=third_cycle, title="Pending offer"
            )
            pending_application, pending_round = await seed_application(
                connection,
                cycle_id=third_cycle,
                enrollment_id=student.enrollment_id,
                status="pending_offer",
                with_round=True,
                job_id=pending_job,
            )

            open_job = await seed_job(
                connection,
                cycle_id=open_cycle,
                title="Open placement",
                with_deadline=False,
            )
            open_application, _ = await seed_application(
                connection,
                cycle_id=open_cycle,
                enrollment_id=student.enrollment_id,
                status="in_progress",
                job_id=open_job,
            )

            internship_job = await seed_job(
                connection,
                cycle_id=internship_cycle,
                title="Different outcome",
                outcome="internship",
            )
            internship_application, _ = await seed_application(
                connection,
                cycle_id=internship_cycle,
                enrollment_id=student.enrollment_id,
                status="in_progress",
                job_id=internship_job,
            )
    finally:
        await engine.dispose()

    result = await _accept(
        actor=student.actor,
        cycle_id=target_cycle,
        job_id=target_job,
        application_id=target_application,
        offer_id=target_offer,
        enrollment_id=student.enrollment_id,
    )

    assert result.events[0].event_type is EventType.ACCEPTED
    assert {event.event_type for event in result.events[1:]} == {
        EventType.AUTO_DECLINED,
        EventType.AUTO_WITHDRAWN,
    }
    cascade = cast("list[dict[str, object]]", result.summary["cascade"])
    assert {UUID(cast(str, row["application_id"])) for row in cascade} == {
        offered_application,
        pending_application,
        open_application,
    }
    assert all(
        event.payload["acceptance_offer_id"] == str(target_offer)
        for event in result.events[1:]
    )

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    sa.text(
                        "SELECT id, status, current_round_id FROM applications "
                        "WHERE id = ANY(:ids)"
                    ),
                    {
                        "ids": [
                            target_application,
                            offered_application,
                            pending_application,
                            open_application,
                            internship_application,
                        ]
                    },
                )
            ).mappings().all()
            statuses = {row["id"]: row["status"] for row in rows}
            rounds = {row["id"]: row["current_round_id"] for row in rows}
            response_rows = (
                await connection.execute(
                    sa.text("SELECT id, response FROM offers WHERE id = ANY(:ids)"),
                    {"ids": [target_offer, offered_offer]},
                )
            ).mappings().all()
            responses = {row["id"]: row["response"] for row in response_rows}
    finally:
        await engine.dispose()

    assert statuses == {
        target_application: "accepted",
        offered_application: "declined",
        pending_application: "auto_withdrawn",
        open_application: "auto_withdrawn",
        internship_application: "in_progress",
    }
    assert rounds[pending_application] == pending_round
    assert responses == {target_offer: "accepted", offered_offer: "declined"}


async def test_OFR3_dedicated_internship_cascades_only_inside_its_cycle() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await seed_admin(connection)
            student = await seed_person(connection, email="student@example.edu")
            first_cycle = await seed_cycle(
                connection, name="Internship A", kind="internship"
            )
            second_cycle = await seed_cycle(
                connection, name="Internship B", kind="internship"
            )
            target_job = await seed_job(
                connection,
                cycle_id=first_cycle,
                title="Accepted internship",
                outcome="internship",
            )
            target_application, _ = await seed_application(
                connection,
                cycle_id=first_cycle,
                enrollment_id=student.enrollment_id,
                status="offered",
                job_id=target_job,
            )
            target_offer = await seed_portal_offer(
                connection, application_id=target_application
            )
            same_job = await seed_job(
                connection,
                cycle_id=first_cycle,
                title="Same summer",
                outcome="internship",
            )
            same_application, _ = await seed_application(
                connection,
                cycle_id=first_cycle,
                enrollment_id=student.enrollment_id,
                status="in_progress",
                job_id=same_job,
            )
            other_job = await seed_job(
                connection,
                cycle_id=second_cycle,
                title="Different summer",
                outcome="internship",
            )
            other_application, _ = await seed_application(
                connection,
                cycle_id=second_cycle,
                enrollment_id=student.enrollment_id,
                status="in_progress",
                job_id=other_job,
            )
    finally:
        await engine.dispose()

    result = await _accept(
        actor=student.actor,
        cycle_id=first_cycle,
        job_id=target_job,
        application_id=target_application,
        offer_id=target_offer,
        enrollment_id=student.enrollment_id,
    )
    cascade = cast("list[dict[str, object]]", result.summary["cascade"])
    assert [UUID(cast(str, row["application_id"])) for row in cascade] == [
        same_application
    ]

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            assert await connection.scalar(
                sa.text("SELECT status FROM applications WHERE id = :id"),
                {"id": other_application},
            ) == "in_progress"
    finally:
        await engine.dispose()


@pytest.mark.parametrize("override_live", (True, False))
async def test_OFR3_offer_deadline_override_is_live_only_until_its_expiry(
    override_live: bool,
) -> None:
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
                status="offered",
                job_id=job_id,
            )
            offer_id = await seed_portal_offer(
                connection,
                application_id=application_id,
                deadline=datetime.now(UTC) - timedelta(minutes=1),
            )
            override_id = await connection.scalar(
                sa.text(
                    "INSERT INTO overrides (rule_domain, allow, application_id, "
                    "reason, granted_by, expires_at) VALUES "
                    "('offer_deadline', true, :application_id, 'Test extension', "
                    ":admin_id, :expires_at) RETURNING id"
                ),
                {
                    "application_id": application_id,
                    "admin_id": admin.user_id,
                    "expires_at": datetime.now(UTC)
                    + (timedelta(days=1) if override_live else -timedelta(days=1)),
                },
            )
            assert isinstance(override_id, UUID)
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    spec = executor.registry.commands["accept_offer"]
    try:
        if override_live:
            result = await executor.run(
                "accept_offer",
                spec.input_model.model_validate(
                    {
                        "cycle_id": cycle_id,
                        "job_id": job_id,
                        "application_id": application_id,
                        "offer_id": offer_id,
                        "enrollment_id": student.enrollment_id,
                        "expected_status": "offered",
                    }
                ),
                student.actor,
            )
            assert isinstance(result, Result)
            assert result.summary["applied_override_ids"] == [str(override_id)]
            assert result.events[0].payload["applied_override_ids"] == [
                str(override_id)
            ]
        else:
            with pytest.raises(DomainRejection) as error:
                await executor.run(
                    "accept_offer",
                    spec.input_model.model_validate(
                        {
                            "cycle_id": cycle_id,
                            "job_id": job_id,
                            "application_id": application_id,
                            "offer_id": offer_id,
                            "enrollment_id": student.enrollment_id,
                            "expected_status": "offered",
                        }
                    ),
                    student.actor,
                    dry_run=True,
                )
            assert [reason.code for reason in error.value.rejection.reasons] == [
                "deadline_passed"
            ]
    finally:
        await engine.dispose()


async def test_OFR3_acceptance_rechecks_an_existing_external_placement() -> None:
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
                status="offered",
                job_id=job_id,
            )
            offer_id = await seed_portal_offer(
                connection, application_id=application_id
            )
            await _seed_external_acceptance(
                connection,
                enrollment_id=student.enrollment_id,
                created_by=admin.user_id,
                outcome="placement",
            )
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    spec = executor.registry.commands["accept_offer"]
    try:
        with pytest.raises(DomainRejection) as error:
            await executor.run(
                "accept_offer",
                spec.input_model.model_validate(
                    {
                        "cycle_id": cycle_id,
                        "job_id": job_id,
                        "application_id": application_id,
                        "offer_id": offer_id,
                        "enrollment_id": student.enrollment_id,
                        "expected_status": "offered",
                    }
                ),
                student.actor,
                dry_run=True,
            )
    finally:
        await engine.dispose()

    assert [reason.code for reason in error.value.rejection.reasons] == [
        "outcome_gate_placement"
    ]


async def test_OFR3_student_decline_updates_only_the_current_offer() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await seed_admin(connection)
            student = await seed_person(connection, email="student@example.edu")
            cycle_id = await seed_cycle(connection)
            job_id = await seed_job(connection, cycle_id=cycle_id)
            application_id, _ = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status="offered",
                job_id=job_id,
            )
            offer_id = await seed_portal_offer(
                connection,
                application_id=application_id,
                deadline=datetime.now(UTC) + timedelta(days=1),
            )
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    spec = executor.registry.commands["decline_offer"]
    try:
        result = await executor.run(
            "decline_offer",
            spec.input_model.model_validate(
                {
                    "cycle_id": cycle_id,
                    "job_id": job_id,
                    "application_id": application_id,
                    "offer_id": offer_id,
                    "enrollment_id": student.enrollment_id,
                    "expected_status": "offered",
                }
            ),
            student.actor,
        )
    finally:
        await engine.dispose()

    assert isinstance(result, Result)
    assert result.summary["status"] == "declined"
    assert result.summary["cascade"] == []
    assert [event.event_type for event in result.events] == [EventType.DECLINED]

    check = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with check.connect() as connection:
            notification_key = await connection.scalar(
                sa.text(
                    "SELECT args->>'event_key' FROM procrastinate_jobs "
                    "WHERE task_name = 'deliver_notification'"
                )
            )
    finally:
        await check.dispose()
    assert notification_key == "declined_confirm"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (("past_deadline", "deadline_passed"), ("newer_offer", "stale_view")),
)
async def test_OFR3_response_revalidates_deadline_and_latest_offer(
    mutation: str, expected_code: str
) -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await seed_admin(connection)
            student = await seed_person(connection, email="student@example.edu")
            cycle_id = await seed_cycle(connection)
            job_id = await seed_job(connection, cycle_id=cycle_id)
            application_id, _ = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status="offered",
                job_id=job_id,
            )
            offer_id = await seed_portal_offer(
                connection,
                application_id=application_id,
                deadline=(
                    datetime.now(UTC) - timedelta(seconds=1)
                    if mutation == "past_deadline"
                    else None
                ),
                extended_at=datetime.now(UTC) - timedelta(days=1),
            )
            if mutation == "newer_offer":
                await seed_portal_offer(connection, application_id=application_id)
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    spec = executor.registry.commands["accept_offer"]
    try:
        with pytest.raises(DomainRejection) as error:
            await executor.run(
                "accept_offer",
                spec.input_model.model_validate(
                    {
                        "cycle_id": cycle_id,
                        "job_id": job_id,
                        "application_id": application_id,
                        "offer_id": offer_id,
                        "enrollment_id": student.enrollment_id,
                        "expected_status": "offered",
                    }
                ),
                student.actor,
                dry_run=True,
            )
    finally:
        await engine.dispose()

    assert expected_code in [reason.code for reason in error.value.rejection.reasons]
