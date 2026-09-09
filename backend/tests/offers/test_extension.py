"""OFR-1/OFR-2 offer extension and bulk resolution."""

from __future__ import annotations

import os
from typing import cast
from uuid import uuid4

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.plan import Preview, Result
from app.domain.shared import EventType
from tests.offers.conftest import (
    build_test_executor,
    seed_admin,
    seed_application,
    seed_cycle,
    seed_person,
    set_offer_deadline,
)

pytestmark = pytest.mark.asyncio


async def test_OFR2_bulk_extension_creates_current_offers_events_notices_and_expiry() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            first = await seed_person(connection, email="first@example.edu")
            second = await seed_person(connection, email="second@example.edu")
            cycle_id = await seed_cycle(connection)
            first_application, _ = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=first.enrollment_id,
                status="in_progress",
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
                status="pending_offer",
                job_id=job_id,
            )
            deadline = await set_offer_deadline(connection, job_id)
    finally:
        await engine.dispose()

    rows: list[dict[str, object]] = [
        {
            "application_id": str(first_application),
            "expected_status": "in_progress",
        },
        {"identifier": "second@example.edu", "expected_status": "pending_offer"},
        {"identifier": "nobody@example.edu"},
        {"application_id": str(first_application)},
    ]
    executor, engine = build_test_executor()
    try:
        preview = await executor.run_bulk(
            "extend_offers",
            rows,
            "extension-preview",
            admin.actor,
            dry_run=True,
            batch_fields={"cycle_id": cycle_id, "job_id": job_id},
        )
        execution = await executor.run_bulk(
            "extend_offers",
            rows,
            "extension-execute",
            admin.actor,
            batch_fields={"cycle_id": cycle_id, "job_id": job_id},
        )
    finally:
        await engine.dispose()

    assert isinstance(preview, Preview)
    assert isinstance(execution, Result)
    assert preview.events == execution.events
    result_rows = cast("list[dict[str, object]]", execution.summary["rows"])
    assert [row["status"] for row in result_rows] == [
        "ok",
        "ok",
        "error",
        "skipped",
    ]
    assert [row["reason"] for row in result_rows] == [
        None,
        None,
        "unmatched_identifier",
        "duplicate_row",
    ]
    assert [event.event_type for event in execution.events] == [
        EventType.OFFER_EXTENDED,
        EventType.OFFER_EXTENDED,
    ]

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            applications = (
                await connection.execute(
                    sa.text(
                        "SELECT id, status FROM applications "
                        "WHERE id = ANY(:ids) ORDER BY id"
                    ),
                    {"ids": [first_application, second_application]},
                )
            ).mappings().all()
            offers = (
                await connection.execute(
                    sa.text(
                        "SELECT application_id, deadline_at, response, terminated_at "
                        "FROM offers WHERE application_id = ANY(:ids) "
                        "ORDER BY application_id"
                    ),
                    {"ids": [first_application, second_application]},
                )
            ).mappings().all()
            tasks = (
                await connection.execute(
                    sa.text(
                        "SELECT task_name, args, scheduled_at FROM procrastinate_jobs "
                        "WHERE task_name IN ('deliver_notification', "
                        "'enforce_offer_expiry') ORDER BY task_name, id"
                    )
                )
            ).mappings().all()
    finally:
        await engine.dispose()

    assert {row["status"] for row in applications} == {"offered"}
    assert len(offers) == 2
    assert all(row["deadline_at"] == deadline for row in offers)
    assert all(row["response"] is None and row["terminated_at"] is None for row in offers)
    assert [row["task_name"] for row in tasks].count("offer_extended") == 0
    assert [row["task_name"] for row in tasks].count("deliver_notification") == 2
    expiry = [row for row in tasks if row["task_name"] == "enforce_offer_expiry"]
    assert len(expiry) == 2
    assert all(row["scheduled_at"] == deadline for row in expiry)
    assert all(row["args"]["scheduled_deadline"] == deadline.isoformat() for row in expiry)


async def test_OFR2_stale_or_ineligible_extension_rows_do_not_mutate() -> None:
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
                status="rejected",
            )
            job_id = await connection.scalar(
                sa.text("SELECT job_id FROM applications WHERE id = :id"),
                {"id": application_id},
            )
            assert job_id is not None
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    try:
        result = await executor.run_bulk(
            "extend_offers",
            [
                {
                    "application_id": str(application_id),
                    "expected_status": "in_progress",
                },
                {"application_id": str(uuid4())},
            ],
            "extension-rejections",
            admin.actor,
            batch_fields={"cycle_id": cycle_id, "job_id": job_id},
        )
    finally:
        await engine.dispose()

    result_rows = cast("list[dict[str, object]]", result.summary["rows"])
    assert [row["reason"] for row in result_rows] == [
        "stale_view",
        "unmatched_identifier",
    ]
    assert result.events == []
