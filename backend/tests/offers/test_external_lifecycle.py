"""EXT-1..4 external CRUD, acceptance, restoration, and audit."""

from __future__ import annotations

import os
from datetime import date
from typing import cast
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.db import create_engine
from app.core.errors import DomainRejection
from app.core.plan import Preview, Result
from app.domain.shared import RuleDomain
from app.modules.offers.derivations import placement_placed_global
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


async def _company_for(connection: AsyncConnection, job_id: UUID) -> UUID:
    company_id = await connection.scalar(
        sa.text("SELECT company_id FROM jobs WHERE id = :id"), {"id": job_id}
    )
    assert isinstance(company_id, UUID)
    return company_id


async def test_EXT2_create_accepted_unattached_offer_audits_and_gates_placement_immediately() -> (
    None
):
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="external@example.edu")
            cycle = await seed_cycle(connection)
            source_job = await seed_job(
                connection, cycle_id=cycle, outcome="internship", title="Source internship"
            )
            source_application, _ = await seed_application(
                connection,
                cycle_id=cycle,
                enrollment_id=student.enrollment_id,
                status="in_progress",
                job_id=source_job,
            )
            company_id = await _company_for(connection, source_job)
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    spec = executor.registry.commands["create_external_offer"]
    try:
        result = await executor.run(
            "create_external_offer",
            spec.input_model.model_validate(
                {
                    "enrollment_id": student.enrollment_id,
                    "company_id": company_id,
                    "outcome": "placement",
                    "source": "ppo",
                    "ctc_lpa": "24.50",
                    "status": "accepted",
                    "offered_on": date.today(),
                    "responded_on": date.today(),
                    "source_application_id": source_application,
                    "reason": "PPO confirmed over email",
                }
            ),
            admin.actor,
        )
    finally:
        await command_engine.dispose()
    assert isinstance(result, Result)
    external_offer_id = UUID(cast(str, result.summary["external_offer_id"]))
    assert result.summary["attached_cycle_id"] is None
    assert result.events[0].event_type.value == "external_recorded"

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            assert await placement_placed_global(connection, student.enrollment_id)
            row = (
                (
                    await connection.execute(
                        sa.text(
                            "SELECT status, attached_cycle_id FROM external_offers WHERE id = :id"
                        ),
                        {"id": external_offer_id},
                    )
                )
                .mappings()
                .one()
            )
            audit = (
                (
                    await connection.execute(
                        sa.text(
                            "SELECT subject_type, subject_id, details FROM audit_log "
                            "WHERE action = 'create_external_offer'"
                        )
                    )
                )
                .mappings()
                .one()
            )
    finally:
        await engine.dispose()
    assert row == {"status": "accepted", "attached_cycle_id": None}
    assert audit["subject_type"] == "enrollment"
    assert audit["subject_id"] == student.enrollment_id
    assert audit["details"]["reason"] == "PPO confirmed over email"


async def test_INT2_external_create_preserves_the_override_credit_in_event_and_audit() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="external-credit@example.edu")
            cycle = await seed_cycle(connection)
            source_job = await seed_job(
                connection,
                cycle_id=cycle,
                outcome="internship",
                title="Source application",
            )
            source_application, _ = await seed_application(
                connection,
                cycle_id=cycle,
                enrollment_id=student.enrollment_id,
                status="rejected",
                job_id=source_job,
            )
            company_id = await _company_for(connection, source_job)
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
                enrollment_id=student.enrollment_id,
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    spec = executor.registry.commands["create_external_offer"]
    try:
        result = await executor.run(
            "create_external_offer",
            spec.input_model.model_validate(
                {
                    "enrollment_id": student.enrollment_id,
                    "company_id": company_id,
                    "outcome": "placement",
                    "source": "ppo",
                    "status": "accepted",
                    "source_application_id": source_application,
                    "reason": "A second placement was exceptionally approved",
                }
            ),
            admin.actor,
        )
    finally:
        await command_engine.dispose()
    assert isinstance(result, Result)
    own_event = next(
        event for event in result.events if event.event_type.value == "external_recorded"
    )
    assert own_event.payload["applied_override_ids"] == [str(override_id)]

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            details = await connection.scalar(
                sa.text(
                    "SELECT details FROM audit_log "
                    "WHERE action = 'create_external_offer'"
                )
            )
    finally:
        await engine.dispose()
    assert details["applied_override_ids"] == [str(override_id)]
    assert details["status"] == "accepted"


async def test_INT2_unlinked_external_update_preserves_the_override_credit_in_audit() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="unlinked-credit@example.edu")
            cycle = await seed_cycle(connection)
            job = await seed_job(connection, cycle_id=cycle)
            company_id = await _company_for(connection, job)
            await seed_external_offer(
                connection,
                enrollment_id=student.enrollment_id,
                company_id=company_id,
                created_by=admin.user_id,
                status="accepted",
            )
            target = await seed_external_offer(
                connection,
                enrollment_id=student.enrollment_id,
                company_id=company_id,
                created_by=admin.user_id,
            )
            override_id = await grant(
                connection,
                domain=RuleDomain.OUTCOME_GATE,
                granted_by=admin.user_id,
                enrollment_id=student.enrollment_id,
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    spec = executor.registry.commands["update_external_offer"]
    try:
        result = await executor.run(
            "update_external_offer",
            spec.input_model.model_validate(
                {
                    "external_offer_id": target,
                    "expected_status": "offered",
                    "status": "accepted",
                    "reason": "A second placement was exceptionally approved",
                }
            ),
            admin.actor,
        )
    finally:
        await command_engine.dispose()
    assert isinstance(result, Result)

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            details = await connection.scalar(
                sa.text(
                    "SELECT details FROM audit_log "
                    "WHERE action = 'update_external_offer'"
                )
            )
    finally:
        await engine.dispose()
    assert details["external_offer_id"] == str(target)
    assert details["applied_override_ids"] == [str(override_id)]
    assert details["from_status"] == "offered"
    assert details["to_status"] == "accepted"


async def test_EXT4_unattached_acceptance_does_not_consult_a_cycle_cap_override() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(
                connection, email="unattached-cap-deny@example.edu"
            )
            cycle = await seed_cycle(connection)
            job = await seed_job(connection, cycle_id=cycle, outcome="internship")
            company_id = await _company_for(connection, job)
            target = await seed_external_offer(
                connection,
                enrollment_id=student.enrollment_id,
                company_id=company_id,
                created_by=admin.user_id,
                outcome="internship",
            )
            await grant(
                connection,
                domain=RuleDomain.OFFER_CAP,
                granted_by=admin.user_id,
                enrollment_id=student.enrollment_id,
                allow=False,
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    spec = executor.registry.commands["update_external_offer"]
    try:
        result = await executor.run(
            "update_external_offer",
            spec.input_model.model_validate(
                {
                    "external_offer_id": target,
                    "expected_status": "offered",
                    "status": "accepted",
                    "reason": "Unattached offers have no cycle cap",
                }
            ),
            admin.actor,
        )
    finally:
        await command_engine.dispose()

    assert isinstance(result, Result)
    assert result.summary["status"] == "accepted"
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            details = await connection.scalar(
                sa.text(
                    "SELECT details FROM audit_log "
                    "WHERE action = 'update_external_offer'"
                )
            )
    finally:
        await engine.dispose()
    assert details["applied_override_ids"] == []


async def test_EXT4_status_to_accepted_uses_portal_cascade_and_away_preview_restores() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="cascade-ext@example.edu")
            cycle_a = await seed_cycle(connection, name="Placement A")
            cycle_b = await seed_cycle(connection, name="Placement B")
            cycle_c = await seed_cycle(connection, name="Placement C")
            external_job = await seed_job(connection, cycle_id=cycle_a)
            company_id = await _company_for(connection, external_job)
            external_offer = await seed_external_offer(
                connection,
                enrollment_id=student.enrollment_id,
                company_id=company_id,
                created_by=admin.user_id,
            )
            offered_job = await seed_job(connection, cycle_id=cycle_b, title="Other offer")
            offered_application, offered_round = await seed_application(
                connection,
                cycle_id=cycle_b,
                enrollment_id=student.enrollment_id,
                status="offered",
                with_round=True,
                job_id=offered_job,
            )
            old_offer = await seed_portal_offer(connection, application_id=offered_application)
            pending_job = await seed_job(connection, cycle_id=cycle_c, title="Pending")
            pending_application, pending_round = await seed_application(
                connection,
                cycle_id=cycle_c,
                enrollment_id=student.enrollment_id,
                status="pending_offer",
                with_round=True,
                job_id=pending_job,
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    update = executor.registry.commands["update_external_offer"]
    try:
        accepted = await executor.run(
            "update_external_offer",
            update.input_model.model_validate(
                {
                    "external_offer_id": external_offer,
                    "expected_status": "offered",
                    "status": "accepted",
                    "reason": "Acceptance confirmed",
                }
            ),
            admin.actor,
        )
    finally:
        await command_engine.dispose()
    assert isinstance(accepted, Result)
    cascade = cast("list[dict[str, object]]", accepted.summary["cascade"])
    assert {UUID(cast(str, row["application_id"])) for row in cascade} == {
        offered_application,
        pending_application,
    }

    executor, command_engine = build_test_executor()
    try:
        input_value = update.input_model.model_validate(
            {
                "external_offer_id": external_offer,
                "expected_status": "accepted",
                "status": "declined",
                "restore": [
                    {"application_id": offered_application},
                    {"application_id": pending_application},
                ],
                "reason": "Acceptance record corrected",
            }
        )
        preview = await executor.run(
            "update_external_offer", input_value, admin.actor, dry_run=True
        )
        result = await executor.run("update_external_offer", input_value, admin.actor)
    finally:
        await command_engine.dispose()
    assert isinstance(preview, Preview)
    assert isinstance(result, Result)
    assert preview.summary == result.summary
    candidates = cast("list[dict[str, object]]", preview.summary["restoration_candidates"])
    by_id = {UUID(cast(str, row["application_id"])): row for row in candidates}
    assert by_id[offered_application]["requires_fresh_offer"] is True
    assert by_id[offered_application]["target_round_id"] == str(offered_round)
    assert by_id[pending_application]["restore_status"] == "pending_offer"
    assert by_id[pending_application]["target_round_id"] == str(pending_round)

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            statuses = {
                row["id"]: row["status"]
                for row in (
                    await connection.execute(
                        sa.text("SELECT id, status FROM applications WHERE id = ANY(:ids)"),
                        {"ids": [offered_application, pending_application]},
                    )
                ).mappings()
            }
            offer_rows = (
                (
                    await connection.execute(
                        sa.text(
                            "SELECT id, response FROM offers WHERE application_id = :id "
                            "ORDER BY extended_at, id"
                        ),
                        {"id": offered_application},
                    )
                )
                .mappings()
                .all()
            )
    finally:
        await engine.dispose()
    assert statuses == {
        offered_application: "offered",
        pending_application: "pending_offer",
    }
    assert len(offer_rows) == 2
    assert offer_rows[0] == {"id": old_offer, "response": "declined"}
    assert offer_rows[1]["response"] is None


async def test_EXT4_accepted_outcome_edit_names_the_safe_three_step_path() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="path@example.edu")
            cycle = await seed_cycle(connection)
            job = await seed_job(connection, cycle_id=cycle)
            company_id = await _company_for(connection, job)
            external_offer = await seed_external_offer(
                connection,
                enrollment_id=student.enrollment_id,
                company_id=company_id,
                created_by=admin.user_id,
                status="accepted",
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    spec = executor.registry.commands["update_external_offer"]
    try:
        with pytest.raises(DomainRejection) as error:
            await executor.run(
                "update_external_offer",
                spec.input_model.model_validate(
                    {
                        "external_offer_id": external_offer,
                        "expected_status": "accepted",
                        "outcome": "internship",
                        "reason": "Wrong outcome",
                    }
                ),
                admin.actor,
                dry_run=True,
            )
    finally:
        await command_engine.dispose()
    message = error.value.rejection.reasons[0].human
    assert "move away from accepted with restoration choices" in message
    assert "edit outcome" in message
    assert "accept again" in message


async def test_EXT4_delete_accepted_offer_exposes_and_applies_same_restoration_choices() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="delete-ext@example.edu")
            cycle = await seed_cycle(connection)
            other_cycle = await seed_cycle(connection, name="Delete other")
            job = await seed_job(connection, cycle_id=cycle)
            company_id = await _company_for(connection, job)
            external_offer = await seed_external_offer(
                connection,
                enrollment_id=student.enrollment_id,
                company_id=company_id,
                created_by=admin.user_id,
            )
            other_job = await seed_job(connection, cycle_id=other_cycle)
            application, round_id = await seed_application(
                connection,
                cycle_id=other_cycle,
                enrollment_id=student.enrollment_id,
                status="in_progress",
                with_round=True,
                job_id=other_job,
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    update = executor.registry.commands["update_external_offer"]
    try:
        await executor.run(
            "update_external_offer",
            update.input_model.model_validate(
                {
                    "external_offer_id": external_offer,
                    "expected_status": "offered",
                    "status": "accepted",
                    "reason": "Accepted",
                }
            ),
            admin.actor,
        )
    finally:
        await command_engine.dispose()

    executor, command_engine = build_test_executor()
    delete = executor.registry.commands["delete_external_offer"]
    try:
        preview = await executor.run(
            "delete_external_offer",
            delete.input_model.model_validate(
                {
                    "external_offer_id": external_offer,
                    "expected_status": "accepted",
                    "restore": [{"application_id": application}],
                    "reason": "Duplicate record",
                }
            ),
            admin.actor,
            dry_run=True,
        )
        result = await executor.run(
            "delete_external_offer",
            delete.input_model.model_validate(
                {
                    "external_offer_id": external_offer,
                    "expected_status": "accepted",
                    "restore": [{"application_id": application}],
                    "reason": "Duplicate record",
                }
            ),
            admin.actor,
        )
    finally:
        await command_engine.dispose()
    assert isinstance(preview, Preview)
    assert isinstance(result, Result)
    candidates = cast("list[dict[str, object]]", preview.summary["restoration_candidates"])
    candidate = candidates[0]
    assert candidate["target_round_id"] == str(round_id)
    assert candidate["selected"] is True

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    sa.text("SELECT count(*) FROM external_offers WHERE id = :id"),
                    {"id": external_offer},
                )
                == 0
            )
            restored = (
                (
                    await connection.execute(
                        sa.text("SELECT status, current_round_id FROM applications WHERE id = :id"),
                        {"id": application},
                    )
                )
                .mappings()
                .one()
            )
    finally:
        await engine.dispose()
    assert restored == {"status": "in_progress", "current_round_id": round_id}
