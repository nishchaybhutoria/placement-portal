"""OFR-5 termination, causal restoration, discipline, and re-extension."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import DomainRejection
from app.core.plan import Preview, Result
from tests.cycles.conftest import Person
from tests.offers.conftest import (
    build_test_executor,
    seed_admin,
    seed_application,
    seed_cycle,
    seed_job,
    seed_person,
    seed_portal_offer,
)

pytestmark = pytest.mark.asyncio


async def _accept(
    *,
    cycle_id: UUID,
    job_id: UUID,
    application_id: UUID,
    offer_id: UUID,
    student: Person,
) -> None:
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
                    "enrollment_id": student.enrollment_id,
                    "expected_status": "offered",
                }
            ),
            student.actor,
        )
        assert isinstance(result, Result)
    finally:
        await engine.dispose()


async def test_OFR5_accepted_termination_restores_only_selected_causal_subset() -> None:
    restore_deadline = datetime.now(UTC) + timedelta(days=21)
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="cascade@example.edu")
            target_cycle = await seed_cycle(connection, name="Accepted cycle")
            declined_cycle = await seed_cycle(connection, name="Declined cycle")
            withdrawn_cycle = await seed_cycle(connection, name="Withdrawn cycle")
            unselected_cycle = await seed_cycle(connection, name="Unselected cycle")
            target_job = await seed_job(connection, cycle_id=target_cycle, title="Winner")
            target_application, _ = await seed_application(
                connection,
                cycle_id=target_cycle,
                enrollment_id=student.enrollment_id,
                status="offered",
                job_id=target_job,
            )
            target_offer = await seed_portal_offer(
                connection, application_id=target_application
            )
            declined_job = await seed_job(
                connection, cycle_id=declined_cycle, title="Restore as offer"
            )
            declined_application, declined_round = await seed_application(
                connection,
                cycle_id=declined_cycle,
                enrollment_id=student.enrollment_id,
                status="offered",
                with_round=True,
                job_id=declined_job,
            )
            declined_offer = await seed_portal_offer(
                connection, application_id=declined_application
            )
            withdrawn_job = await seed_job(
                connection, cycle_id=withdrawn_cycle, title="Restore exact round"
            )
            withdrawn_application, withdrawn_round = await seed_application(
                connection,
                cycle_id=withdrawn_cycle,
                enrollment_id=student.enrollment_id,
                status="pending_offer",
                with_round=True,
                job_id=withdrawn_job,
            )
            unselected_job = await seed_job(
                connection, cycle_id=unselected_cycle, title="Leave withdrawn"
            )
            unselected_application, _ = await seed_application(
                connection,
                cycle_id=unselected_cycle,
                enrollment_id=student.enrollment_id,
                status="in_progress",
                job_id=unselected_job,
            )
    finally:
        await engine.dispose()

    await _accept(
        cycle_id=target_cycle,
        job_id=target_job,
        application_id=target_application,
        offer_id=target_offer,
        student=student,
    )

    executor, command_engine = build_test_executor()
    spec = executor.registry.commands["terminate_offer"]
    input_value = spec.input_model.model_validate(
        {
            "cycle_id": target_cycle,
            "job_id": target_job,
            "application_id": target_application,
            "offer_id": target_offer,
            "expected_status": "accepted",
            "termination_kind": "company_revoked",
            "reason": "Company withdrew the role",
            "restore": [
                {
                    "application_id": declined_application,
                    "deadline_at": restore_deadline,
                },
                {"application_id": withdrawn_application},
            ],
        }
    )
    try:
        preview = await executor.run(
            "terminate_offer", input_value, admin.actor, dry_run=True
        )
        execution = await executor.run("terminate_offer", input_value, admin.actor)
    finally:
        await command_engine.dispose()

    assert isinstance(preview, Preview)
    assert isinstance(execution, Result)
    assert preview.summary == execution.summary
    automatic_effects = cast(
        "list[dict[str, object]]", preview.summary["automatic_effects"]
    )
    assert [row["effect"] for row in automatic_effects] == [
        "offer_terminated",
        "application_transition",
        "placed_dimensions_rederived",
        "cycle_cap_released",
    ]
    candidates = cast(
        "list[dict[str, object]]", preview.summary["restoration_candidates"]
    )
    assert {UUID(cast(str, row["application_id"])) for row in candidates} == {
        declined_application,
        withdrawn_application,
        unselected_application,
    }
    by_id = {UUID(cast(str, row["application_id"])): row for row in candidates}
    assert by_id[declined_application] | {
        "target_round_id": (
            str(declined_round) if declined_round is not None else None
        ),
        "requires_fresh_offer": True,
        "deadline_editable": True,
        "selected": True,
    } == by_id[declined_application]
    assert by_id[withdrawn_application]["restore_status"] == "pending_offer"
    assert by_id[withdrawn_application]["target_round_id"] == str(withdrawn_round)
    assert by_id[withdrawn_application]["selected"] is True
    assert by_id[unselected_application]["selected"] is False

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            applications = (
                await connection.execute(
                    sa.text(
                        "SELECT id, status, current_round_id FROM applications "
                        "WHERE id = ANY(:ids)"
                    ),
                    {
                        "ids": [
                            target_application,
                            declined_application,
                            withdrawn_application,
                            unselected_application,
                        ]
                    },
                )
            ).mappings().all()
            app_rows = {row["id"]: row for row in applications}
            restored_offers = (
                await connection.execute(
                    sa.text(
                        "SELECT id, response, deadline_at, terminated_at FROM offers "
                        "WHERE application_id = :application_id "
                        "ORDER BY extended_at, id"
                    ),
                    {"application_id": declined_application},
                )
            ).mappings().all()
            target_row = (
                await connection.execute(
                    sa.text(
                        "SELECT terminated_at, termination_kind, termination_reason "
                        "FROM offers WHERE id = :id"
                    ),
                    {"id": target_offer},
                )
            ).mappings().one()
    finally:
        await engine.dispose()

    assert {item: row["status"] for item, row in app_rows.items()} == {
        target_application: "offer_terminated",
        declined_application: "offered",
        withdrawn_application: "pending_offer",
        unselected_application: "auto_withdrawn",
    }
    assert app_rows[withdrawn_application]["current_round_id"] == withdrawn_round
    assert len(restored_offers) == 2
    assert restored_offers[0]["id"] == declined_offer
    assert restored_offers[0]["response"] == "declined"
    assert restored_offers[1]["response"] is None
    assert restored_offers[1]["deadline_at"] == restore_deadline
    assert target_row["terminated_at"] is not None
    assert target_row["termination_kind"] == "company_revoked"
    assert target_row["termination_reason"] == "Company withdrew the role"


async def test_OFR5_restore_candidates_drop_rows_whose_status_moved_after_cascade() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="stale@example.edu")
            cycle = await seed_cycle(connection)
            other_cycle = await seed_cycle(connection, name="Other placement")
            job = await seed_job(connection, cycle_id=cycle)
            application, _ = await seed_application(
                connection,
                cycle_id=cycle,
                enrollment_id=student.enrollment_id,
                status="offered",
                job_id=job,
            )
            offer = await seed_portal_offer(connection, application_id=application)
            other_job = await seed_job(connection, cycle_id=other_cycle)
            other_application, _ = await seed_application(
                connection,
                cycle_id=other_cycle,
                enrollment_id=student.enrollment_id,
                status="in_progress",
                job_id=other_job,
            )
    finally:
        await engine.dispose()
    await _accept(
        cycle_id=cycle,
        job_id=job,
        application_id=application,
        offer_id=offer,
        student=student,
    )
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text("UPDATE applications SET status = 'rejected' WHERE id = :id"),
                {"id": other_application},
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    spec = executor.registry.commands["terminate_offer"]
    try:
        preview = await executor.run(
            "terminate_offer",
            spec.input_model.model_validate(
                {
                    "cycle_id": cycle,
                    "job_id": job,
                    "application_id": application,
                    "offer_id": offer,
                    "expected_status": "accepted",
                    "termination_kind": "admin_correction",
                    "reason": "Correct the record",
                }
            ),
            admin.actor,
            dry_run=True,
        )
    finally:
        await command_engine.dispose()
    assert isinstance(preview, Preview)
    assert preview.summary["restoration_candidates"] == []


@pytest.mark.parametrize("discipline", ("strike", "penalty"))
async def test_OFR5_termination_chains_M11_discipline_helpers(
    discipline: str,
) -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(
                connection, email=f"{discipline}@example.edu"
            )
            cycle = await seed_cycle(connection)
            job = await seed_job(connection, cycle_id=cycle)
            application, _ = await seed_application(
                connection,
                cycle_id=cycle,
                enrollment_id=student.enrollment_id,
                status="offered",
                job_id=job,
            )
            offer = await seed_portal_offer(connection, application_id=application)
            if discipline == "strike":
                await connection.execute(
                    sa.text(
                        "INSERT INTO strikes (id, enrollment_id, reason, source, "
                        "is_active) VALUES (:id, :enrollment, 'Existing', 'manual', true)"
                    ),
                    {"id": uuid4(), "enrollment": student.enrollment_id},
                )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    spec = executor.registry.commands["terminate_offer"]
    try:
        result = await executor.run(
            "terminate_offer",
            spec.input_model.model_validate(
                {
                    "cycle_id": cycle,
                    "job_id": job,
                    "application_id": application,
                    "offer_id": offer,
                    "expected_status": "offered",
                    "termination_kind": "student_renege",
                    "reason": "Student reneged",
                    "discipline": discipline,
                    "notify": False,
                }
            ),
            admin.actor,
        )
    finally:
        await command_engine.dispose()
    assert isinstance(result, Result)
    discipline_summary = cast("dict[str, object]", result.summary["discipline"])
    assert discipline_summary["kind"] == discipline

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            strikes = await connection.scalar(
                sa.text("SELECT count(*) FROM strikes WHERE enrollment_id = :id"),
                {"id": student.enrollment_id},
            )
            penalty = (
                await connection.execute(
                    sa.text(
                        "SELECT from_strikes FROM penalties WHERE enrollment_id = :id"
                    ),
                    {"id": student.enrollment_id},
                )
            ).mappings().one()
    finally:
        await engine.dispose()
    assert strikes == (2 if discipline == "strike" else 0)
    assert penalty["from_strikes"] is (discipline == "strike")


@pytest.mark.parametrize("status", ("declined", "offer_terminated"))
async def test_OFR5_re_extend_creates_fresh_offer_after_decline_or_termination(
    status: str,
) -> None:
    deadline = datetime.now(UTC) + timedelta(days=14)
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email=f"{status}@example.edu")
            cycle = await seed_cycle(connection)
            job = await seed_job(connection, cycle_id=cycle)
            application, _ = await seed_application(
                connection,
                cycle_id=cycle,
                enrollment_id=student.enrollment_id,
                status=status,
                job_id=job,
            )
            old_offer = await seed_portal_offer(
                connection,
                application_id=application,
                response="declined" if status == "declined" else None,
                terminated=status == "offer_terminated",
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    spec = executor.registry.commands["re_extend_offer"]
    try:
        result = await executor.run(
            "re_extend_offer",
            spec.input_model.model_validate(
                {
                    "cycle_id": cycle,
                    "job_id": job,
                    "application_id": application,
                    "offer_id": old_offer,
                    "expected_status": status,
                    "reason": "Office approved another extension",
                    "deadline_at": deadline,
                }
            ),
            admin.actor,
        )
    finally:
        await command_engine.dispose()
    assert isinstance(result, Result)
    assert result.summary["status"] == "offered"
    assert UUID(cast(str, result.summary["offer_id"])) != old_offer

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    sa.text(
                        "SELECT id, response, terminated_at, deadline_at FROM offers "
                        "WHERE application_id = :id ORDER BY extended_at, id"
                    ),
                    {"id": application},
                )
            ).mappings().all()
            current_status = await connection.scalar(
                sa.text("SELECT status FROM applications WHERE id = :id"),
                {"id": application},
            )
    finally:
        await engine.dispose()
    assert current_status == "offered"
    assert len(rows) == 2
    assert rows[0]["id"] == old_offer
    assert rows[1]["response"] is None
    assert rows[1]["terminated_at"] is None
    assert rows[1]["deadline_at"] == deadline


async def test_OFR5_selected_stale_restore_is_rejected_instead_of_silently_skipped() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="reject-stale@example.edu")
            cycle = await seed_cycle(connection)
            other_cycle = await seed_cycle(connection, name="Stale other")
            job = await seed_job(connection, cycle_id=cycle)
            application, _ = await seed_application(
                connection,
                cycle_id=cycle,
                enrollment_id=student.enrollment_id,
                status="offered",
                job_id=job,
            )
            offer = await seed_portal_offer(connection, application_id=application)
            other_job = await seed_job(connection, cycle_id=other_cycle)
            other_application, _ = await seed_application(
                connection,
                cycle_id=other_cycle,
                enrollment_id=student.enrollment_id,
                status="in_progress",
                job_id=other_job,
            )
    finally:
        await engine.dispose()
    await _accept(
        cycle_id=cycle,
        job_id=job,
        application_id=application,
        offer_id=offer,
        student=student,
    )
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text("UPDATE applications SET status = 'rejected' WHERE id = :id"),
                {"id": other_application},
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    spec = executor.registry.commands["terminate_offer"]
    try:
        with pytest.raises(DomainRejection) as error:
            await executor.run(
                "terminate_offer",
                spec.input_model.model_validate(
                    {
                        "cycle_id": cycle,
                        "job_id": job,
                        "application_id": application,
                        "offer_id": offer,
                        "expected_status": "accepted",
                        "termination_kind": "admin_correction",
                        "reason": "Correction",
                        "restore": [{"application_id": other_application}],
                    }
                ),
                admin.actor,
                dry_run=True,
            )
    finally:
        await command_engine.dispose()
    assert [reason.code for reason in error.value.rejection.reasons] == ["stale_view"]
