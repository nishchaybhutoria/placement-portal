"""The Procrastinate task invokes the hidden expiry command as system."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.plan import Result
from app.worker import create_procrastinate_app
from tests.offers.conftest import (
    build_test_executor,
    seed_admin,
    seed_application,
    seed_cycle,
    seed_membership,
    seed_person,
    seed_portal_offer,
)

pytestmark = pytest.mark.asyncio


async def test_OFR4_worker_runs_due_expiry_through_the_internal_system_command() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="student@example.edu")
            cycle_id = await seed_cycle(connection)
            await seed_membership(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
            )
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
            application_deadline = datetime.now(UTC) - timedelta(days=2)
            old_offer_deadline = datetime.now(UTC) + timedelta(days=2)
            await connection.execute(
                sa.text(
                    "UPDATE jobs SET application_deadline = :application, "
                    "offer_acceptance_deadline = :offer WHERE id = :id"
                ),
                {
                    "id": job_id,
                    "application": application_deadline,
                    "offer": old_offer_deadline,
                },
            )
            offer_id = await seed_portal_offer(
                connection,
                application_id=application_id,
                deadline=old_offer_deadline,
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    due = datetime.now(UTC) - timedelta(days=1)
    spec = executor.registry.commands["update_job_basics"]
    try:
        updated = await executor.run(
            "update_job_basics",
            spec.input_model.model_validate(
                {
                    "cycle_id": cycle_id,
                    "job_id": job_id,
                    "offer_acceptance_deadline": due,
                }
            ),
            admin.actor,
        )
        assert isinstance(updated, Result)

        worker = create_procrastinate_app(
            conninfo=os.environ["PROCRASTINATE_DATABASE_URL"], executor=executor
        )
        async with worker.open_async():
            await worker.run_worker_async(
                wait=False,
                listen_notify=False,
                install_signal_handlers=False,
            )
    finally:
        await command_engine.dispose()

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    sa.text(
                        "SELECT a.status, o.response FROM applications a "
                        "JOIN offers o ON o.application_id = a.id WHERE o.id = :id"
                    ),
                    {"id": offer_id},
                )
            ).mappings().one()
            task_status = await connection.scalar(
                sa.text(
                    "SELECT status FROM procrastinate_jobs "
                    "WHERE task_name = 'enforce_offer_expiry'"
                )
            )
            audit_count = await connection.scalar(
                sa.text(
                    "SELECT count(*) FROM audit_log "
                    "WHERE action = 'enforce_offer_expiry'"
                )
            )
    finally:
        await engine.dispose()

    assert dict(row) == {"status": "declined", "response": "declined"}
    assert task_status == "succeeded"
    assert audit_count == 1
