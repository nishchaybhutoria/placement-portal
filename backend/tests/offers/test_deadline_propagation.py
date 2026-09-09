"""JOB-3 propagation from a job acceptance deadline to live Offer rows."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.plan import Result
from tests.offers.conftest import (
    build_test_executor,
    seed_admin,
    seed_application,
    seed_cycle,
    seed_person,
    seed_portal_offer,
    set_offer_deadline,
)

pytestmark = pytest.mark.asyncio


async def test_JOB3_acceptance_deadline_updates_only_open_offers_and_keeps_old_jobs() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            first = await seed_person(connection, email="first@example.edu")
            second = await seed_person(connection, email="second@example.edu")
            responded = await seed_person(connection, email="responded@example.edu")
            terminated = await seed_person(connection, email="terminated@example.edu")
            cycle_id = await seed_cycle(connection)
            first_application, _ = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=first.enrollment_id,
            )
            job_id = await connection.scalar(
                sa.text("SELECT job_id FROM applications WHERE id = :id"),
                {"id": first_application},
            )
            assert job_id is not None
            second_application, _ = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=second.enrollment_id,
                job_id=job_id,
            )
            responded_application, _ = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=responded.enrollment_id,
                status="declined",
                job_id=job_id,
            )
            terminated_application, _ = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=terminated.enrollment_id,
                status="offered",
                job_id=job_id,
            )
            old_deadline = await set_offer_deadline(connection, job_id)
            responded_offer = await seed_portal_offer(
                connection,
                application_id=responded_application,
                response="declined",
                deadline=old_deadline,
            )
            terminated_offer = await seed_portal_offer(
                connection,
                application_id=terminated_application,
                deadline=old_deadline,
                terminated=True,
            )
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    try:
        extended = await executor.run_bulk(
            "extend_offers",
            [
                {"application_id": str(first_application)},
                {"application_id": str(second_application)},
            ],
            "deadline-propagation-extension",
            admin.actor,
            batch_fields={"cycle_id": cycle_id, "job_id": job_id},
        )
        assert isinstance(extended, Result)
        open_offer_ids = [
            row["offer_id"]
            for row in cast("list[dict[str, object]]", extended.summary["rows"])
        ]
        new_deadline = datetime.now(UTC) + timedelta(days=90)
        spec = executor.registry.commands["update_job_basics"]
        updated = await executor.run(
            "update_job_basics",
            spec.input_model.model_validate(
                {
                    "cycle_id": cycle_id,
                    "job_id": job_id,
                    "offer_acceptance_deadline": new_deadline,
                }
            ),
            admin.actor,
        )
    finally:
        await engine.dispose()

    assert isinstance(updated, Result)
    assert updated.summary["updated_offer_deadlines"] == 2
    assert updated.summary["scheduled_offer_expiries"] == 2

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    sa.text(
                        "SELECT id, deadline_at FROM offers WHERE id = ANY(:ids)"
                    ),
                    {
                        "ids": [
                            *open_offer_ids,
                            responded_offer,
                            terminated_offer,
                        ]
                    },
                )
            ).mappings().all()
            by_id = {str(row["id"]): row["deadline_at"] for row in rows}
            expiry_tasks = (
                await connection.execute(
                    sa.text(
                        "SELECT args, scheduled_at FROM procrastinate_jobs "
                        "WHERE task_name = 'enforce_offer_expiry' ORDER BY id"
                    )
                )
            ).mappings().all()
    finally:
        await engine.dispose()

    assert all(by_id[cast(str, offer_id)] == new_deadline for offer_id in open_offer_ids)
    assert by_id[str(responded_offer)] == old_deadline
    assert by_id[str(terminated_offer)] == old_deadline
    # Two schedules from extension remain; deadline propagation adds two more.
    assert len(expiry_tasks) == 4
    assert [row["scheduled_at"] for row in expiry_tasks].count(old_deadline) == 2
    assert [row["scheduled_at"] for row in expiry_tasks].count(new_deadline) == 2
    assert [row["args"]["scheduled_deadline"] for row in expiry_tasks].count(
        new_deadline.isoformat()
    ) == 2


async def test_JOB3_null_acceptance_deadline_clears_open_offers_without_new_tasks() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="student@example.edu")
            cycle_id = await seed_cycle(connection)
            application_id, _ = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status="offered",
            )
            job_id = await connection.scalar(
                sa.text("SELECT job_id FROM applications WHERE id = :id"),
                {"id": application_id},
            )
            assert job_id is not None
            old_deadline = await set_offer_deadline(connection, job_id)
            offer_id = await seed_portal_offer(
                connection, application_id=application_id, deadline=old_deadline
            )
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    spec = executor.registry.commands["update_job_basics"]
    try:
        result = await executor.run(
            "update_job_basics",
            spec.input_model.model_validate(
                {
                    "cycle_id": cycle_id,
                    "job_id": job_id,
                    "offer_acceptance_deadline": None,
                }
            ),
            admin.actor,
        )
    finally:
        await engine.dispose()
    assert isinstance(result, Result)
    assert result.summary["updated_offer_deadlines"] == 1
    assert result.summary["scheduled_offer_expiries"] == 0

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            deadline = await connection.scalar(
                sa.text("SELECT deadline_at FROM offers WHERE id = :id"),
                {"id": offer_id},
            )
            task_count = await connection.scalar(
                sa.text(
                    "SELECT count(*) FROM procrastinate_jobs "
                    "WHERE task_name = 'enforce_offer_expiry'"
                )
            )
    finally:
        await engine.dispose()
    assert deadline is None
    assert task_count == 0
