"""Declaration, student edits, and administration ownership (PRO-1, IDN-2)."""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import create_engine
from app.core.errors import (
    FIELD_NOT_EDITABLE,
    INVALID_FIELD_VALUE,
    PROFILE_ALREADY_DECLARED,
    PROFILE_NOT_DECLARED,
    PROGRAM_BRANCH_MISMATCH,
    ROLL_NUMBER_TAKEN,
    UNKNOWN_TAXONOMY_VALUE,
    DomainRejection,
)
from app.core.executor import Executor
from app.core.plan import ActorContext, Result
from tests.profiles.conftest import (
    add_enrollment,
    build_test_executor,
    seed_admin,
    seed_student,
    seed_taxonomy,
)

pytestmark = pytest.mark.usefixtures("clean_profiles")


async def _run(
    executor: Executor, name: str, payload: dict[str, object], actor: ActorContext
) -> Result:
    spec = executor.registry.commands[name]
    result = await executor.run(name, spec.input_model.model_validate(payload), actor)
    assert isinstance(result, Result)
    return result


async def _reasons(
    executor: Executor, name: str, payload: dict[str, object], actor: ActorContext
) -> list[tuple[str, str | None]]:
    with pytest.raises(DomainRejection) as rejection:
        await _run(executor, name, payload, actor)
    return [
        (reason.code, reason.path) for reason in rejection.value.rejection.reasons
    ]


@pytest.mark.asyncio
async def test_PRO1_declare_profile_writes_the_profile_and_the_enrollment_roll() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            taxonomy = await seed_taxonomy(connection)
            student = await seed_student(connection, "declare@example.edu")
        result = await _run(
            executor,
            "declare_profile",
            {
                "enrollment_id": str(student.enrollment_id),
                "fields": {
                    "roll_number": "21110001",
                    "program_id": str(taxonomy.program_id),
                    "is_dual_major": True,
                    "primary_branch_id": str(taxonomy.branch_id),
                    "secondary_branch_id": str(taxonomy.second_branch_id),
                    "graduating_year": 2026,
                    "cpi": "8.55",
                    "gender": "Female",
                    "personal_email": "student@example.com",
                },
            },
            student.actor,
        )
        assert result.summary["retained_fields"] == []
        async with migration.connect() as connection:
            row = (
                await connection.execute(
                    sa.text(
                        "SELECT p.cpi, p.gender, p.declared_at, p.is_dual_major, "
                        "e.roll_number "
                        "FROM profiles p JOIN enrollments e ON e.id = p.enrollment_id "
                        "WHERE p.enrollment_id = :id"
                    ),
                    {"id": student.enrollment_id},
                )
            ).mappings().one()
            audit = (
                await connection.execute(
                    sa.text("SELECT action, details FROM audit_log ORDER BY created_at")
                )
            ).mappings().all()
    finally:
        await engine.dispose()
        await migration.dispose()

    assert row["cpi"] == Decimal("8.55")
    assert row["gender"] == "female"
    assert row["declared_at"] is not None
    # A student states their own dual major at declaration; PRO-1 then locks it
    # as an admin-managed field (the design review 4.32).
    assert row["is_dual_major"] is True
    assert row["roll_number"] == "21110001"
    assert [entry["action"] for entry in audit] == ["declare_profile"]
    assert audit[0]["details"]["after"]["roll_number"] == "21110001"
    assert audit[0]["details"]["before"]["cpi"] is None


@pytest.mark.asyncio
async def test_PRO1_declaration_happens_exactly_once() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            student = await seed_student(connection, "once@example.edu")
        payload = {
            "enrollment_id": str(student.enrollment_id),
            "fields": {"personal_email": "once@example.com"},
        }
        await _run(executor, "declare_profile", payload, student.actor)
        codes = await _reasons(executor, "declare_profile", payload, student.actor)
    finally:
        await engine.dispose()
        await migration.dispose()
    assert codes == [(PROFILE_ALREADY_DECLARED, None)]


@pytest.mark.asyncio
async def test_PRO1_declaration_retains_administration_seeded_values() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_student(connection, "seeded@example.edu", roll_number="21110009")
        await _run(
            executor,
            "admin_update_profile",
            {
                "enrollment_id": str(student.enrollment_id),
                "fields": {"cpi": "9.10", "gender": "female"},
            },
            admin,
        )
        result = await _run(
            executor,
            "declare_profile",
            {
                "enrollment_id": str(student.enrollment_id),
                "fields": {
                    "cpi": "6.00",
                    "gender": "male",
                    "roll_number": "21119999",
                    "personal_email": "seeded@example.com",
                },
            },
            student.actor,
        )
        async with migration.connect() as connection:
            row = (
                await connection.execute(
                    sa.text(
                        "SELECT p.cpi, p.gender, p.personal_email, e.roll_number "
                        "FROM profiles p JOIN enrollments e ON e.id = p.enrollment_id "
                        "WHERE p.enrollment_id = :id"
                    ),
                    {"id": student.enrollment_id},
                )
            ).mappings().one()
    finally:
        await engine.dispose()
        await migration.dispose()

    assert sorted(cast(list[str], result.summary["retained_fields"])) == [
        "gender",
        "roll_number",
    ]
    assert row["gender"] == "female"
    assert row["roll_number"] == "21110009"
    assert row["personal_email"] == "seeded@example.com"
    # CPI is admin-owned but student-maintained: the student's own figure is
    # the later of the two statements, so the declaration supersedes the seed.
    assert row["cpi"] == Decimal("6.00")


@pytest.mark.asyncio
async def test_PRO1_administration_overwrites_admin_fields_after_declaration() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_student(connection, "owned@example.edu")
        await _run(
            executor,
            "declare_profile",
            {
                "enrollment_id": str(student.enrollment_id),
                "fields": {"cpi": "7.00", "roll_number": "21110002"},
            },
            student.actor,
        )
        result = await _run(
            executor,
            "admin_update_profile",
            {
                "enrollment_id": str(student.enrollment_id),
                "fields": {"cpi": "8.25", "roll_number": "21110003", "full_name": "Corrected"},
            },
            admin,
        )
        async with migration.connect() as connection:
            row = (
                await connection.execute(
                    sa.text(
                        "SELECT p.cpi, e.roll_number, u.full_name FROM profiles p "
                        "JOIN enrollments e ON e.id = p.enrollment_id "
                        "JOIN users u ON u.id = e.user_id WHERE p.enrollment_id = :id"
                    ),
                    {"id": student.enrollment_id},
                )
            ).mappings().one()
            audit = (
                await connection.execute(
                    sa.text(
                        "SELECT details FROM audit_log WHERE action = 'admin_update_profile'"
                    )
                )
            ).mappings().one()
    finally:
        await engine.dispose()
        await migration.dispose()

    assert sorted(cast(list[str], result.summary["changed_fields"])) == [
        "cpi",
        "full_name",
        "roll_number",
    ]
    assert row["cpi"] == Decimal("8.25")
    assert row["roll_number"] == "21110003"
    assert row["full_name"] == "Corrected"
    assert audit["details"]["before"]["cpi"] == "7.00"
    assert audit["details"]["after"]["cpi"] == "8.25"


@pytest.mark.asyncio
async def test_PRO1_student_edit_of_admin_fields_lists_every_offending_field() -> None:
    """An admin field that already holds a value is refused, and named (PRO-1).

    The semesterly four are in the same request and absent from the list: the
    lock never closes on them, so the only fields named are the ones the
    student really may not restate.
    """
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            student = await seed_student(
                connection, "locked@example.edu", roll_number="21110004"
            )
        await _run(
            executor,
            "declare_profile",
            {
                "enrollment_id": str(student.enrollment_id),
                "fields": {"cpi": "7.00", "graduating_year": 2026, "gender": "female"},
            },
            student.actor,
        )
        codes = await _reasons(
            executor,
            "update_student_fields",
            {
                "enrollment_id": str(student.enrollment_id),
                "fields": {
                    "cpi": "9.90",
                    "graduating_year": 2027,
                    "gender": "male",
                    "roll_number": "21119998",
                    "institute_email": "new@example.edu",
                    "contact_number": "+1 202-555-0101",
                },
            },
            student.actor,
        )
    finally:
        await engine.dispose()
        await migration.dispose()

    assert sorted(codes) == [
        (FIELD_NOT_EDITABLE, "gender"),
        (FIELD_NOT_EDITABLE, "institute_email"),
        (FIELD_NOT_EDITABLE, "roll_number"),
    ]


@pytest.mark.asyncio
async def test_PRO1_the_semesterly_academic_fields_stay_the_students_to_correct() -> None:
    """CPI, backlogs, and the graduating year move; the student says so.

    They are admin-*owned* -- PRO-2 still refreshes them from the roster -- but
    locking them on the declared value left the student's own row stale for a
    semester at a time, which is what these edits exist to prevent.
    """
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            student = await seed_student(connection, "semester@example.edu")
        await _run(
            executor,
            "declare_profile",
            {
                "enrollment_id": str(student.enrollment_id),
                "fields": {
                    "cpi": "7.00",
                    "graduating_year": 2026,
                    "active_backlogs": 2,
                    "total_backlogs": 3,
                },
            },
            student.actor,
        )
        result = await _run(
            executor,
            "update_student_fields",
            {
                "enrollment_id": str(student.enrollment_id),
                "fields": {
                    "cpi": "8.57",
                    "graduating_year": 2027,
                    "active_backlogs": 0,
                    "total_backlogs": 3,
                },
            },
            student.actor,
        )
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    sa.text(
                        "SELECT cpi, graduating_year, active_backlogs, total_backlogs "
                        "FROM profiles WHERE enrollment_id = :id"
                    ),
                    {"id": student.enrollment_id},
                )
            ).mappings().one()
    finally:
        await engine.dispose()
        await migration.dispose()

    assert row["cpi"] == Decimal("8.57")
    assert row["graduating_year"] == 2027
    assert row["active_backlogs"] == 0
    assert row["total_backlogs"] == 3
    # An unchanged count is not a change; the audit records only what moved.
    assert result.summary["changed_fields"] == [
        "active_backlogs",
        "cpi",
        "graduating_year",
    ]


@pytest.mark.asyncio
async def test_PRO1_an_admin_field_left_blank_is_still_the_students_to_supply() -> None:
    """The lock follows the value, not `declared_at` (the design review section 4.33).

    A declaration that leaves gender blank used to write NULL into an
    immediately locked column, which the CYC-3 join checklist then required
    forever and only an administrator could ever supply.  The student fills it
    once, and only once: the second attempt is refused exactly as an admin
    field always was.
    """
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            student = await seed_student(connection, "blank@example.edu")
        await _run(
            executor,
            "declare_profile",
            {
                "enrollment_id": str(student.enrollment_id),
                "fields": {"contact_number": "+1 202-555-0103"},
            },
            student.actor,
        )
        await _run(
            executor,
            "update_student_fields",
            {
                "enrollment_id": str(student.enrollment_id),
                "fields": {
                    "gender": "female",
                    "roll_number": "21119997",
                },
            },
            student.actor,
        )
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    sa.text(
                        "SELECT p.gender, e.roll_number "
                        "FROM profiles p JOIN enrollments e ON e.id = p.enrollment_id "
                        "WHERE p.enrollment_id = :id"
                    ),
                    {"id": student.enrollment_id},
                )
            ).mappings().one()
        codes = await _reasons(
            executor,
            "update_student_fields",
            {
                "enrollment_id": str(student.enrollment_id),
                "fields": {"gender": "male", "roll_number": "2111000"},
            },
            student.actor,
        )
    finally:
        await engine.dispose()
        await migration.dispose()

    assert row["gender"] == "female"
    assert row["roll_number"] == "21119997"
    assert sorted(codes) == [
        (FIELD_NOT_EDITABLE, "gender"),
        (FIELD_NOT_EDITABLE, "roll_number"),
    ]


@pytest.mark.asyncio
async def test_PRO1_a_field_the_declaration_omits_keeps_its_column_default() -> None:
    """PRO-1 gives nationality a default of IN; omitting it must not clear it."""
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            student = await seed_student(connection, "default@example.edu")
        await _run(
            executor,
            "declare_profile",
            {
                "enrollment_id": str(student.enrollment_id),
                "fields": {"contact_number": "+1 202-555-0104"},
            },
            student.actor,
        )
        async with engine.connect() as connection:
            nationality = await connection.scalar(
                sa.text(
                    "SELECT nationality FROM profiles WHERE enrollment_id = :id"
                ),
                {"id": student.enrollment_id},
            )
    finally:
        await engine.dispose()
        await migration.dispose()

    assert nationality == "IN"


@pytest.mark.asyncio
async def test_PRO1_student_edits_require_a_declared_profile() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            student = await seed_student(connection, "undeclared@example.edu")
        codes = await _reasons(
            executor,
            "update_student_fields",
            {
                "enrollment_id": str(student.enrollment_id),
                "fields": {"contact_number": "+1 202-555-0102"},
            },
            student.actor,
        )
    finally:
        await engine.dispose()
        await migration.dispose()
    assert codes == [(PROFILE_NOT_DECLARED, None)]


@pytest.mark.asyncio
async def test_PRO1_program_branch_map_and_taxonomy_state_are_enforced() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            taxonomy = await seed_taxonomy(connection)
            student = await seed_student(connection, "map@example.edu")
            other = await seed_student(connection, "map2@example.edu")
        unmapped = await _reasons(
            executor,
            "declare_profile",
            {
                "enrollment_id": str(student.enrollment_id),
                "fields": {
                    "program_id": str(taxonomy.program_id),
                    "primary_branch_id": str(taxonomy.unmapped_branch_id),
                },
            },
            student.actor,
        )
        unknown = await _reasons(
            executor,
            "declare_profile",
            {
                "enrollment_id": str(other.enrollment_id),
                "fields": {"program_id": str(uuid4())},
            },
            other.actor,
        )
        secondary_without_flag = await _reasons(
            executor,
            "declare_profile",
            {
                "enrollment_id": str(student.enrollment_id),
                "fields": {
                    "program_id": str(taxonomy.program_id),
                    "primary_branch_id": str(taxonomy.branch_id),
                    "secondary_branch_id": str(taxonomy.unmapped_branch_id),
                },
            },
            student.actor,
        )
    finally:
        await engine.dispose()
        await migration.dispose()

    assert unmapped == [(PROGRAM_BRANCH_MISMATCH, "primary_branch_id")]
    assert unknown == [(UNKNOWN_TAXONOMY_VALUE, "program_id")]
    # A second major named by somebody who has not got one (the design review 4.32).
    assert (INVALID_FIELD_VALUE, "secondary_branch_id") in secondary_without_flag


@pytest.mark.asyncio
async def test_PRO1_a_dual_student_may_name_the_same_branch_twice() -> None:
    """A BTech and an MTech in one discipline is an enrollment, not a typo.

    The pair used to be refused outright, which left every dual degree
    continuing in its own discipline -- and the dual majors the office reports
    the same of -- unable to state the branches they actually hold.
    """
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            taxonomy = await seed_taxonomy(connection)
            degree = await seed_student(connection, "dualdegree@example.edu")
            major = await seed_student(connection, "dualmajor@example.edu")
        await _run(
            executor,
            "declare_profile",
            {
                "enrollment_id": str(degree.enrollment_id),
                "fields": {
                    "program_id": str(taxonomy.program_id),
                    "primary_branch_id": str(taxonomy.branch_id),
                    "is_dual_degree": True,
                    "secondary_program_id": str(taxonomy.other_program_id),
                    "secondary_branch_id": str(taxonomy.branch_id),
                },
            },
            degree.actor,
        )
        await _run(
            executor,
            "declare_profile",
            {
                "enrollment_id": str(major.enrollment_id),
                "fields": {
                    "program_id": str(taxonomy.program_id),
                    "primary_branch_id": str(taxonomy.branch_id),
                    "is_dual_major": True,
                    "secondary_branch_id": str(taxonomy.branch_id),
                },
            },
            major.actor,
        )
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    sa.text(
                        "SELECT enrollment_id, primary_branch_id, secondary_branch_id "
                        "FROM profiles"
                    )
                )
            ).mappings().all()
    finally:
        await engine.dispose()
        await migration.dispose()

    assert {row["enrollment_id"] for row in rows} == {
        degree.enrollment_id,
        major.enrollment_id,
    }
    assert all(
        row["primary_branch_id"] == taxonomy.branch_id
        and row["secondary_branch_id"] == taxonomy.branch_id
        for row in rows
    )


@pytest.mark.asyncio
async def test_PRO1_invalid_values_are_reported_per_field() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            student = await seed_student(connection, "values@example.edu")
        codes = await _reasons(
            executor,
            "declare_profile",
            {
                "enrollment_id": str(student.enrollment_id),
                "fields": {"cpi": "11", "graduating_year": "soon"},
            },
            student.actor,
        )
    finally:
        await engine.dispose()
        await migration.dispose()
    assert sorted(codes) == [
        (INVALID_FIELD_VALUE, "cpi"),
        (INVALID_FIELD_VALUE, "graduating_year"),
    ]


@pytest.mark.asyncio
async def test_IDN2_admin_edits_reach_historical_enrollments() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_student(connection, "rejoin@example.edu", roll_number="18110001")
            historical = student.enrollment_id
            current = await add_enrollment(connection, student, roll_number="21110004")
        await _run(
            executor,
            "admin_update_profile",
            {"enrollment_id": str(historical), "fields": {"cpi": "7.77"}},
            admin,
        )
        async with migration.connect() as connection:
            rows = (
                await connection.execute(
                    sa.text(
                        "SELECT enrollment_id, cpi FROM profiles ORDER BY enrollment_id"
                    )
                )
            ).mappings().all()
    finally:
        await engine.dispose()
        await migration.dispose()

    assert [(row["enrollment_id"], row["cpi"]) for row in rows] == [
        (historical, Decimal("7.77"))
    ]
    assert current != historical


@pytest.mark.asyncio
async def test_IDN2_roll_numbers_are_unique_across_current_enrollments() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            await seed_student(connection, "holder@example.edu", roll_number="21110005")
            student = await seed_student(connection, "taker@example.edu")
        codes = await _reasons(
            executor,
            "declare_profile",
            {
                "enrollment_id": str(student.enrollment_id),
                "fields": {"roll_number": "21110005"},
            },
            student.actor,
        )
    finally:
        await engine.dispose()
        await migration.dispose()
    assert codes == [(ROLL_NUMBER_TAKEN, "roll_number")]


@pytest.mark.asyncio
async def test_IDN2_parallel_declarations_of_one_roll_number_serialize() -> None:
    executor, engine = build_test_executor()
    spec = executor.registry.commands["declare_profile"]
    original_loader = spec.loader
    barrier = asyncio.Barrier(2)

    async def synchronized_loader(
        tx: AsyncSession, input_value: object, *, lock: bool
    ) -> object:
        await barrier.wait()
        return await original_loader(tx, input_value, lock=lock)

    executor.registry.commands["declare_profile"] = replace(spec, loader=synchronized_loader)
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            first = await seed_student(connection, "race1@example.edu")
            second = await seed_student(connection, "race2@example.edu")
        results = await asyncio.gather(
            _run(
                executor,
                "declare_profile",
                {
                    "enrollment_id": str(first.enrollment_id),
                    "fields": {"roll_number": "21110006"},
                },
                first.actor,
            ),
            _run(
                executor,
                "declare_profile",
                {
                    "enrollment_id": str(second.enrollment_id),
                    "fields": {"roll_number": "21110006"},
                },
                second.actor,
            ),
            return_exceptions=True,
        )
        async with migration.connect() as connection:
            holders = (
                await connection.scalars(
                    sa.text(
                        "SELECT count(*) FROM enrollments WHERE roll_number = '21110006'"
                    )
                )
            ).one()
    finally:
        await engine.dispose()
        await migration.dispose()

    rejections = [item for item in results if isinstance(item, DomainRejection)]
    assert len(rejections) == 1
    assert [reason.code for reason in rejections[0].rejection.reasons] == [ROLL_NUMBER_TAKEN]
    assert holders == 1


@pytest.mark.asyncio
async def test_PRO1_a_student_cannot_edit_another_students_profile() -> None:
    from app.core.errors import AuthorizationDenied

    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            owner = await seed_student(connection, "owner@example.edu")
            intruder = await seed_student(connection, "intruder@example.edu")
        with pytest.raises(AuthorizationDenied):
            await _run(
                executor,
                "declare_profile",
                {
                    "enrollment_id": str(owner.enrollment_id),
                    "fields": {"personal_email": "x@example.com"},
                },
                intruder.actor,
            )
    finally:
        await engine.dispose()
        await migration.dispose()


@pytest.mark.asyncio
async def test_PRO1_dry_run_declaration_writes_nothing() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            student = await seed_student(connection, "preview@example.edu")
        spec = executor.registry.commands["declare_profile"]
        preview = await executor.run(
            "declare_profile",
            spec.input_model.model_validate(
                {
                    "enrollment_id": str(student.enrollment_id),
                    "fields": {"roll_number": "21110007"},
                }
            ),
            student.actor,
            dry_run=True,
        )
        async with migration.connect() as connection:
            profiles = await connection.scalar(sa.text("SELECT count(*) FROM profiles"))
            audits = await connection.scalar(sa.text("SELECT count(*) FROM audit_log"))
    finally:
        await engine.dispose()
        await migration.dispose()

    assert preview.summary["applied_fields"] == ["roll_number"]
    assert profiles == 0
    assert audits == 0
