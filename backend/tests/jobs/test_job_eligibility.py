"""Job eligibility rules and their impact preview (Behavior JOB-2, JOB-3, ELG-1..4)."""

from __future__ import annotations

import os
from typing import cast
from uuid import UUID

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import DomainRejection
from app.core.plan import Preview, Result
from app.domain.rules import NO_RULE_SUMMARY
from tests.cycles.conftest import Person
from tests.jobs.conftest import (
    build_test_executor,
    seed_admin,
    seed_application,
    seed_company,
    seed_complete_profile,
    seed_cycle,
    seed_job,
    seed_membership,
    seed_person,
    seed_taxonomy,
)


async def _cycle_with_members(
    cpis: tuple[str, ...],
) -> tuple[Person, UUID, UUID, tuple[UUID, ...], UUID, UUID]:
    """A placement cycle whose active members differ only in CPI."""
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            program_id, branch_id = await seed_taxonomy(connection)
            cycle_id = await seed_cycle(connection, kind="placement")
            job_id = await seed_job(connection, cycle_id=cycle_id)
            enrollments: list[UUID] = []
            for index, cpi in enumerate(cpis):
                person = await seed_person(connection, email=f"member{index}@example.edu")
                resume_id = await seed_complete_profile(
                    connection,
                    person,
                    program_id=program_id,
                    branch_id=branch_id,
                    roll_number=f"2111{index:04d}",
                    cpi=cpi,
                )
                await seed_membership(
                    connection,
                    cycle_id=cycle_id,
                    enrollment_id=person.enrollment_id,
                    resume_id=resume_id,
                    status="active",
                )
                enrollments.append(person.enrollment_id)
    finally:
        await engine.dispose()
    return admin, cycle_id, job_id, tuple(enrollments), program_id, branch_id


@pytest.mark.asyncio
async def test_ELG2_a_saved_rule_carries_a_generated_plain_language_summary() -> None:
    admin, cycle_id, job_id, _members, program_id, _branch = await _cycle_with_members(
        ("8.40",)
    )
    executor, engine = build_test_executor()
    try:
        result = await executor.run(
            "update_job_eligibility",
            executor.registry.commands["update_job_eligibility"].input_model.model_validate(
                {
                    "cycle_id": str(cycle_id),
                    "job_id": str(job_id),
                    "eligibility_rule": {
                        "all": [
                            {"field": "program_id", "op": "eq", "value": str(program_id)},
                            {"field": "cpi", "op": "gte", "value": 8.0},
                            {"field": "active_backlogs", "op": "lte", "value": 0},
                        ]
                    },
                }
            ),
            admin.actor,
        )
    finally:
        await engine.dispose()

    # The program renders by name; a stored UUID would be unreadable.
    assert result.summary["eligibility_summary"] == (
        "Eligible when program BTech and CPI at least 8.0 and "
        "active backlogs at most 0."
    )


@pytest.mark.asyncio
async def test_ELG2_clearing_the_rule_says_so_rather_than_leaving_a_blank() -> None:
    admin, cycle_id, job_id, _members, _program, _branch = await _cycle_with_members(())
    executor, engine = build_test_executor()
    model = executor.registry.commands["update_job_eligibility"].input_model
    try:
        await executor.run(
            "update_job_eligibility",
            model.model_validate(
                {
                    "cycle_id": str(cycle_id),
                    "job_id": str(job_id),
                    "eligibility_rule": {"field": "cpi", "op": "gte", "value": 9.0},
                }
            ),
            admin.actor,
        )
        cleared = await executor.run(
            "update_job_eligibility",
            model.model_validate({"cycle_id": str(cycle_id), "job_id": str(job_id)}),
            admin.actor,
        )
    finally:
        await engine.dispose()

    assert cleared.summary["eligibility_summary"] == NO_RULE_SUMMARY


@pytest.mark.asyncio
async def test_JOB2_the_impact_preview_counts_the_members_the_rule_admits() -> None:
    admin, cycle_id, job_id, _members, _program, _branch = await _cycle_with_members(
        ("9.10", "8.00", "7.94", "7.95")
    )
    executor, engine = build_test_executor()
    try:
        result = await executor.run(
            "update_job_eligibility",
            executor.registry.commands["update_job_eligibility"].input_model.model_validate(
                {
                    "cycle_id": str(cycle_id),
                    "job_id": str(job_id),
                    "eligibility_rule": {"field": "cpi", "op": "gte", "value": 8.0},
                }
            ),
            admin.actor,
        )
    finally:
        await engine.dispose()

    # ELG-2's CPI contract rounds half-up to one decimal before comparing, so
    # 7.95 passes and 7.94 does not.
    assert result.summary["member_count"] == 4
    assert result.summary["eligible_count"] == 3


@pytest.mark.asyncio
async def test_JOB2_the_preview_says_which_matches_are_already_placed() -> None:
    """ELG-3 closes a placement role to a placed student; the rule does not.

    The count answers "who does my rule describe", so a placed student stays
    in it. Saying so beside the count is what stops the author reading their
    own rule as broken.
    """
    admin, cycle_id, job_id, members, _program, _branch = await _cycle_with_members(
        ("9.10", "8.50")
    )
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            company_id = await seed_company(connection)
            await connection.execute(
                sa.text(
                    "INSERT INTO external_offers (id, enrollment_id, company_id, "
                    "outcome, source, status, offered_on, responded_on, created_by) "
                    "VALUES (gen_random_uuid(), :enrollment, :company, 'placement', "
                    "'off_campus', 'accepted', CURRENT_DATE, CURRENT_DATE, :admin)"
                ),
                {
                    "enrollment": members[0],
                    "company": company_id,
                    "admin": admin.user_id,
                },
            )
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    try:
        result = await executor.run(
            "update_job_eligibility",
            executor.registry.commands["update_job_eligibility"].input_model.model_validate(
                {
                    "cycle_id": str(cycle_id),
                    "job_id": str(job_id),
                    "eligibility_rule": {"field": "cpi", "op": "gte", "value": 8.0},
                }
            ),
            admin.actor,
        )
    finally:
        await engine.dispose()

    assert result.summary["eligible_count"] == 2
    assert result.summary["placed_count"] == 1
    rows = {
        str(member["enrollment_id"]): member
        for member in cast("list[dict[str, object]]", result.summary["members"])
    }
    assert rows[str(members[0])]["eligible"] is True
    assert rows[str(members[0])]["placed"] is True
    assert rows[str(members[1])]["placed"] is False


@pytest.mark.asyncio
async def test_ELG4_an_eligibility_edit_leaves_an_existing_application_untouched() -> None:
    admin, cycle_id, job_id, members, _program, _branch = await _cycle_with_members(
        ("7.00",)
    )
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            application_id, _round = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=members[0],
                job_id=job_id,
            )
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    try:
        result = await executor.run(
            "update_job_eligibility",
            executor.registry.commands["update_job_eligibility"].input_model.model_validate(
                {
                    "cycle_id": str(cycle_id),
                    "job_id": str(job_id),
                    # A floor this student cannot meet: whoever got in validly
                    # stays in (ELG-4), so nothing about them may move.
                    "eligibility_rule": {"field": "cpi", "op": "gte", "value": 9.5},
                }
            ),
            admin.actor,
        )
    finally:
        await engine.dispose()

    assert result.summary["eligible_count"] == 0
    assert result.events == []

    check = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with check.begin() as connection:
            status = await connection.scalar(
                sa.text("SELECT status FROM applications WHERE id = :id"),
                {"id": application_id},
            )
            events = await connection.scalar(
                sa.text(
                    "SELECT count(*) FROM application_events "
                    "WHERE application_id = :id"
                ),
                {"id": application_id},
            )
    finally:
        await check.dispose()

    assert status == "in_progress"
    assert events == 0


@pytest.mark.asyncio
async def test_ELG2_an_unknown_field_is_refused_before_it_can_be_stored() -> None:
    admin, cycle_id, job_id, _members, _program, _branch = await _cycle_with_members(())
    executor, _engine = build_test_executor()
    model = executor.registry.commands["update_job_eligibility"].input_model
    with pytest.raises(ValueError):
        model.model_validate(
            {
                "cycle_id": str(cycle_id),
                "job_id": str(job_id),
                "eligibility_rule": {"field": "favourite_colour", "op": "eq", "value": "blue"},
            }
        )


@pytest.mark.asyncio
async def test_JOB2_the_eligibility_preview_matches_what_it_executes() -> None:
    admin, cycle_id, job_id, _members, _program, _branch = await _cycle_with_members(
        ("8.40", "6.00")
    )
    executor, engine = build_test_executor()
    payload = executor.registry.commands[
        "update_job_eligibility"
    ].input_model.model_validate(
        {
            "cycle_id": str(cycle_id),
            "job_id": str(job_id),
            "eligibility_rule": {"field": "cpi", "op": "gte", "value": 8.0},
        }
    )
    try:
        preview = await executor.run(
            "update_job_eligibility", payload, admin.actor, dry_run=True
        )
        result = await executor.run("update_job_eligibility", payload, admin.actor)
    finally:
        await engine.dispose()

    assert isinstance(preview, Preview) and isinstance(result, Result)
    assert preview.summary == result.summary
    assert preview.events == result.events


@pytest.mark.asyncio
async def test_ELG2_resaving_a_legacy_rule_previews_and_audits_v2_conversion() -> None:
    admin, cycle_id, job_id, _members, _program, _branch = await _cycle_with_members(())
    rule = {"not": {"field": "cpi", "op": "gte", "value": 8}}
    database = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with database.begin() as connection:
            await connection.execute(
                sa.text(
                    "UPDATE jobs SET eligibility_rule = CAST(:rule AS jsonb), "
                    "eligibility_rule_version = 1 WHERE id = :id"
                ),
                {"id": job_id, "rule": '{"not":{"field":"cpi","op":"gte","value":8}}'},
            )
    finally:
        await database.dispose()

    executor, engine = build_test_executor()
    payload = executor.registry.commands[
        "update_job_eligibility"
    ].input_model.model_validate(
        {"cycle_id": str(cycle_id), "job_id": str(job_id), "eligibility_rule": rule}
    )
    try:
        preview = await executor.run(
            "update_job_eligibility", payload, admin.actor, dry_run=True
        )
        assert preview.summary["eligibility_rule_version"] == 2
        check = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
        try:
            async with check.begin() as connection:
                assert await connection.scalar(
                    sa.text(
                        "SELECT eligibility_rule_version FROM jobs WHERE id = :id"
                    ),
                    {"id": job_id},
                ) == 1
        finally:
            await check.dispose()
        result = await executor.run("update_job_eligibility", payload, admin.actor)
    finally:
        await engine.dispose()

    assert result.summary["changed"] is True
    verify = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with verify.begin() as connection:
            assert await connection.scalar(
                sa.text("SELECT eligibility_rule_version FROM jobs WHERE id = :id"),
                {"id": job_id},
            ) == 2
            audit = (
                await connection.execute(
                    sa.text(
                        "SELECT details FROM audit_log WHERE subject_id = :id "
                        "ORDER BY created_at DESC, id DESC LIMIT 1"
                    ),
                    {"id": job_id},
                )
            ).scalar_one()
    finally:
        await verify.dispose()
    assert audit["before"]["eligibility_rule_version"] == 1
    assert audit["after"]["eligibility_rule_version"] == 2


@pytest.mark.asyncio
async def test_JOB2_a_cancelled_job_no_longer_accepts_a_rule_edit() -> None:
    admin, cycle_id, job_id, _members, _program, _branch = await _cycle_with_members(())
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text("UPDATE jobs SET cancelled_at = now() WHERE id = :id"),
                {"id": job_id},
            )
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    try:
        with pytest.raises(DomainRejection) as error:
            await executor.run(
                "update_job_eligibility",
                executor.registry.commands[
                    "update_job_eligibility"
                ].input_model.model_validate(
                    {"cycle_id": str(cycle_id), "job_id": str(job_id)}
                ),
                admin.actor,
            )
    finally:
        await engine.dispose()

    assert [reason.code for reason in error.value.rejection.reasons] == ["job_cancelled"]
