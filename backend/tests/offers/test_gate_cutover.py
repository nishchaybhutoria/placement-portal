"""Every eligibility caller consumes the real M12a offer facts."""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.db import create_engine
from app.core.errors import (
    JOIN_RULE_FAILED,
    OFFER_CAP_REACHED,
    OUTCOME_GATE_INTERNSHIP,
    OUTCOME_GATE_PLACEMENT,
    DomainRejection,
)
from app.core.plan import Result
from app.modules.cycles.queries import cycles_joinable
from app.modules.jobs.queries import staff_job_builder, student_cycle_jobs
from tests.applications.conftest import World, seed_world
from tests.offers.conftest import (
    build_test_executor,
    seed_admin,
    seed_complete_profile,
    seed_cycle,
    seed_job,
    seed_membership,
    seed_person,
    seed_taxonomy,
)

pytestmark = pytest.mark.asyncio


async def _seed_external_acceptance(
    connection: AsyncConnection,
    *,
    enrollment_id: UUID,
    created_by: UUID,
    outcome: str,
    attached_cycle_id: UUID | None = None,
) -> UUID:
    company_id, offer_id = uuid4(), uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO companies (id, name, is_active) VALUES (:id, :name, true)"
        ),
        {"id": company_id, "name": f"Off-campus employer {company_id}"},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO external_offers (id, enrollment_id, company_id, outcome, "
            "source, status, attached_cycle_id, created_by) VALUES "
            "(:id, :enrollment_id, :company_id, CAST(:outcome AS outcome_t), "
            "'off_campus', 'accepted', :cycle_id, :created_by)"
        ),
        {
            "id": offer_id,
            "enrollment_id": enrollment_id,
            "company_id": company_id,
            "outcome": outcome,
            "cycle_id": attached_cycle_id,
            "created_by": created_by,
        },
    )
    return offer_id


async def _external_accept_world(world: World, *, attached: bool) -> None:
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
                enrollment_id=world.student.enrollment_id,
                created_by=admin_id,
                outcome=("internship" if attached else "placement"),
                attached_cycle_id=world.cycle_id if attached else None,
            )
    finally:
        await engine.dispose()


async def _displayed_reasons(world: World) -> list[dict[str, object]]:
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        listing = await student_cycle_jobs(
            engine,
            cycle_id=world.cycle_id,
            enrollment_id=world.student.enrollment_id,
        )
    finally:
        await engine.dispose()
    assert listing is not None
    card = next(
        job
        for job in cast("list[dict[str, object]]", listing["jobs"])
        if job["id"] == str(world.job_id)
    )
    assert card["eligible"] is False
    return cast("list[dict[str, object]]", card["reasons"])


async def _apply_reasons(world: World) -> list[dict[str, object]]:
    executor, engine = build_test_executor()
    model = executor.registry.commands["apply"].input_model
    try:
        with pytest.raises(DomainRejection) as error:
            await executor.run(
                "apply",
                model.model_validate(
                    {
                        "cycle_id": str(world.cycle_id),
                        "job_id": str(world.job_id),
                        "enrollment_id": str(world.student.enrollment_id),
                    }
                ),
                world.student.actor,
                dry_run=True,
            )
    finally:
        await engine.dispose()
    return [asdict(reason) for reason in error.value.rejection.reasons]


async def test_DER1_an_unattached_external_placement_blocks_card_and_apply_equally() -> None:
    world = await seed_world(kind="placement", outcome="placement")
    await _external_accept_world(world, attached=False)

    displayed = await _displayed_reasons(world)
    applied = await _apply_reasons(world)

    assert displayed == applied
    assert [reason["code"] for reason in applied] == [OUTCOME_GATE_PLACEMENT]


async def test_ELG36_an_attached_internship_acceptance_drives_gate_and_cap() -> None:
    world = await seed_world(kind="internship", outcome="internship")
    await _external_accept_world(world, attached=True)

    displayed = await _displayed_reasons(world)
    applied = await _apply_reasons(world)

    assert displayed == applied
    assert [reason["code"] for reason in applied] == [
        OUTCOME_GATE_INTERNSHIP,
        OFFER_CAP_REACHED,
    ]


async def test_ELG2_join_screen_and_command_use_the_same_global_placement_fact() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            program_id, branch_id = await seed_taxonomy(connection)
            student = await seed_person(connection, email="joiner@example.edu")
            resume_id = await seed_complete_profile(
                connection,
                student,
                program_id=program_id,
                branch_id=branch_id,
            )
            assert resume_id is not None
            cycle_id = await seed_cycle(
                connection,
                kind="placement",
                join_rule='{"criterion": "not_placement_placed"}',
            )
            await _seed_external_acceptance(
                connection,
                enrollment_id=student.enrollment_id,
                created_by=admin.user_id,
                outcome="placement",
            )
    finally:
        await engine.dispose()

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        screen = await cycles_joinable(engine, student.enrollment_id)
    finally:
        await engine.dispose()
    entry = next(
        row
        for row in cast("list[dict[str, object]]", screen["cycles"])
        if row["id"] == str(cycle_id)
    )
    assert [reason["code"] for reason in entry["reasons"]] == [JOIN_RULE_FAILED]  # type: ignore[index]

    executor, engine = build_test_executor()
    model = executor.registry.commands["join_cycle"].input_model
    try:
        with pytest.raises(DomainRejection) as error:
            await executor.run(
                "join_cycle",
                model.model_validate(
                    {
                        "cycle_id": str(cycle_id),
                        "enrollment_id": str(student.enrollment_id),
                        "default_resume_id": str(resume_id),
                        "consent": True,
                    }
                ),
                student.actor,
                dry_run=True,
            )
    finally:
        await engine.dispose()

    assert [reason.code for reason in error.value.rejection.reasons] == [JOIN_RULE_FAILED]


async def test_ELG2_job_impact_command_and_builder_batch_load_placed_members() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            program_id, branch_id = await seed_taxonomy(connection)
            cycle_id = await seed_cycle(connection, kind="placement")
            job_id = await seed_job(connection, cycle_id=cycle_id)
            placed = await seed_person(connection, email="placed@example.edu")
            unplaced = await seed_person(connection, email="unplaced@example.edu")
            for index, student in enumerate((placed, unplaced), start=1):
                resume_id = await seed_complete_profile(
                    connection,
                    student,
                    program_id=program_id,
                    branch_id=branch_id,
                    roll_number=f"2111000{index}",
                )
                await seed_membership(
                    connection,
                    cycle_id=cycle_id,
                    enrollment_id=student.enrollment_id,
                    resume_id=resume_id,
                )
            await _seed_external_acceptance(
                connection,
                enrollment_id=placed.enrollment_id,
                created_by=admin.user_id,
                outcome="placement",
            )
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    model = executor.registry.commands["update_job_eligibility"].input_model
    try:
        result = await executor.run(
            "update_job_eligibility",
            model.model_validate(
                {
                    "cycle_id": str(cycle_id),
                    "job_id": str(job_id),
                    "eligibility_rule": {"criterion": "not_placement_placed"},
                }
            ),
            admin.actor,
        )
    finally:
        await engine.dispose()
    assert isinstance(result, Result)
    assert result.summary["eligible_count"] == 1
    by_enrollment = {
        UUID(cast(str, row["enrollment_id"])): bool(row["eligible"])
        for row in cast("list[dict[str, object]]", result.summary["members"])
    }
    assert by_enrollment == {
        placed.enrollment_id: False,
        unplaced.enrollment_id: True,
    }

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        builder = await staff_job_builder(
            engine, cycle_id=cycle_id, job_id=job_id
        )
    finally:
        await engine.dispose()
    assert builder is not None
    impact = cast("dict[str, object]", cast("dict[str, object]", builder["eligibility"])["impact"])
    assert impact["eligible_count"] == 1
    builder_by_enrollment = {
        UUID(cast(str, row["enrollment_id"])): bool(row["eligible"])
        for row in cast("list[dict[str, object]]", impact["members"])
    }
    assert builder_by_enrollment == by_enrollment
