"""PRO-1/2, ELG-4: collection for existing enrollments without revoking access."""

from __future__ import annotations

import os
from typing import cast
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.core.db import create_engine
from app.core.errors import DomainRejection
from app.core.plan import Preview
from app.modules.offers.screens import student_dashboard
from app.modules.profiles.queries import me_profile
from tests.cycles.conftest import seed_application, seed_cycle, seed_membership
from tests.profiles.conftest import build_test_executor, seed_admin, seed_student
from tests.profiles.test_profile_commands import _run
from tests.profiles.test_staged_login import _login, _stage

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("clean_profiles")]


async def test_PRO1_existing_student_collects_year_with_preview_and_audit() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_student(connection, "year@example.edu")
            await connection.execute(sa.text(
                "INSERT INTO profiles (enrollment_id, declared_at) VALUES (:id, now())"
            ), {"id": student.enrollment_id})
        await _run(
            executor, "set_setting",
            {"key": "academic_session_start_year", "value": 2026}, admin,
        )
        before = await me_profile(engine, student.enrollment_id)
        assert cast(dict, before["academic_standing"])["status"] == "missing"
        registry = {f["key"]: f for f in cast(list[dict], before["fields"])}
        assert registry["study_year"]["editable"] is True
        assert registry["study_year_session"]["editable"] is True
        spec = executor.registry.commands["update_student_fields"]
        payload = spec.input_model.model_validate({
            "enrollment_id": student.enrollment_id,
            "fields": {"study_year": 8, "study_year_session": 2026},
        })
        preview = await executor.run("update_student_fields", payload, student.actor, dry_run=True)
        assert isinstance(preview, Preview)
        during = cast(dict, (await me_profile(engine, student.enrollment_id))["values"])
        assert during["study_year"] is None
        result = await _run(executor, "update_student_fields", payload.model_dump(), student.actor)
        changed = cast(list[str], result.summary["changed_fields"])
        assert sorted(changed) == ["study_year", "study_year_session"]
        after = await me_profile(engine, student.enrollment_id)
        assert cast(dict, after["academic_standing"])["status"] == "current"
        dashboard = await student_dashboard(engine, student.enrollment_id)
        assert cast(dict, dashboard["academic_standing"])["status"] == "current"
        async with migration.connect() as connection:
            detail = await connection.scalar(sa.text(
                "SELECT details FROM audit_log WHERE action='update_student_fields' "
                "ORDER BY audit_seq DESC LIMIT 1"
            ))
        assert detail["before"] == {"study_year": None, "study_year_session": None}
        assert detail["after"] == {"study_year": 8, "study_year_session": 2026}
    finally:
        await engine.dispose()
        await migration.dispose()


async def test_PRO1_declaration_and_admin_correction_support_years_one_through_eight() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_student(connection, "declare-year@example.edu")
        await _run(
            executor, "set_setting",
            {"key": "academic_session_start_year", "value": 2026}, admin,
        )
        await _run(executor, "declare_profile", {
            "enrollment_id": student.enrollment_id,
            "fields": {"study_year": 1, "study_year_session": 2026},
        }, student.actor)
        await _run(executor, "admin_update_profile", {
            "enrollment_id": student.enrollment_id,
            "fields": {"study_year": 8, "study_year_session": 2026},
        }, admin)
        # Like CPI, the student's ongoing academic fact remains maintainable.
        await _run(executor, "update_student_fields", {
            "enrollment_id": student.enrollment_id,
            "fields": {"study_year": 7, "study_year_session": 2026},
        }, student.actor)
        values = cast(dict, (await me_profile(engine, student.enrollment_id))["values"])
        assert values["study_year"] == 7
    finally:
        await engine.dispose()
        await migration.dispose()


async def test_ELG4_session_rollover_preserves_membership_and_application() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_student(connection, "registered-year@example.edu")
            await connection.execute(sa.text(
                "INSERT INTO profiles (enrollment_id, declared_at) VALUES (:id, now())"
            ), {"id": student.enrollment_id})
            cycle = await seed_cycle(connection)
            membership = await seed_membership(
                connection, cycle_id=cycle, enrollment_id=student.enrollment_id
            )
            application, _ = await seed_application(
                connection, cycle_id=cycle, enrollment_id=student.enrollment_id
            )
            original_application = (await connection.execute(sa.text(
                "SELECT * FROM applications WHERE id=:id"
            ), {"id": application})).mappings().one()
        await _run(
            executor, "set_setting",
            {"key": "academic_session_start_year", "value": 2026}, admin,
        )
        await _run(executor, "update_student_fields", {
            "enrollment_id": student.enrollment_id,
            "fields": {"study_year": 3, "study_year_session": 2026},
        }, student.actor)
        await _run(
            executor, "set_setting",
            {"key": "academic_session_start_year", "value": 2027}, admin,
        )
        screen = await me_profile(engine, student.enrollment_id)
        assert cast(dict, screen["academic_standing"])["status"] == "stale"
        assert cast(dict, screen["values"])["study_year"] == 3  # Never automatically increment.
        with pytest.raises(DomainRejection):
            await _run(executor, "update_student_fields", {
                "enrollment_id": student.enrollment_id,
                "fields": {"study_year": 4, "study_year_session": 2026},
            }, student.actor)
        # Unrelated edits are still possible while the standing is stale.
        await _run(executor, "update_student_fields", {
            "enrollment_id": student.enrollment_id, "fields": {"cpi": "8.10"},
        }, student.actor)
        dashboard = await student_dashboard(engine, student.enrollment_id)
        assert cast(dict, dashboard["academic_standing"])["status"] == "stale"
        async with migration.connect() as connection:
            assert await connection.scalar(sa.text(
                "SELECT status FROM cycle_memberships WHERE id=:id"
            ), {"id": membership}) == "active"
            assert dict((await connection.execute(sa.text(
                "SELECT * FROM applications WHERE id=:id"
            ), {"id": application})).mappings().one()) == dict(original_application)
            assert await connection.scalar(sa.text("SELECT count(*) FROM application_events")) == 0
    finally:
        await engine.dispose()
        await migration.dispose()


async def test_PRO2_bulk_upsert_validates_pairs_for_existing_and_staged_students() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_student(connection, "bulk-year@example.edu")
        result = await _run(executor, "bulk_upsert_profiles", {
            "batch_key": "academic-collection", "rows": [
                {"row_number": 2, "institute_email": student.email,
                 "fields": {"study_year": "8", "study_year_session": "2026"}},
                {"row_number": 3, "institute_email": "staged-year@example.edu",
                 "fields": {"study_year": "1", "study_year_session": "2026"}},
                {"row_number": 4, "institute_email": "invalid-year@example.edu",
                 "fields": {"study_year": 9, "study_year_session": 2026}},
                {"row_number": 5, "institute_email": "missing-session@example.edu",
                 "fields": {"study_year": 3}},
            ],
        }, admin)
        rows = cast(list[dict], result.summary["rows"])
        assert [row["result"] for row in rows] == ["updated", "staged", "error", "error"]
        await _login(executor, "staged-year@example.edu")
        async with migration.connect() as connection:
            standing = (await connection.execute(sa.text(
                "SELECT study_year, study_year_session FROM profiles WHERE enrollment_id=:id"
            ), {"id": student.enrollment_id})).one()
            assert tuple(standing) == (8, 2026)
            staged = (await connection.execute(sa.text(
                "SELECT applied_at, error FROM staged_profile_rows"
            ))).mappings().one()
            assert staged["applied_at"] is not None and staged["error"] is None
    finally:
        await engine.dispose()
        await migration.dispose()


async def test_PRO2_staged_import_keeps_its_original_session_and_rejects_partial_pairs() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            await _stage(connection, "old-standing@example.edu", {
                "study_year": 3, "study_year_session": 2025,
            }, uploaded_by=cast(UUID, admin.user_id))
            bad_id = await _stage(connection, "bad-standing@example.edu", {
                "study_year": 3,
            }, uploaded_by=cast(UUID, admin.user_id))
        await _run(
            executor, "set_setting",
            {"key": "academic_session_start_year", "value": 2026}, admin,
        )
        await _login(executor, "old-standing@example.edu")
        await _login(executor, "bad-standing@example.edu")
        async with migration.connect() as connection:
            year = (await connection.execute(sa.text(
                "SELECT study_year, study_year_session FROM profiles WHERE study_year IS NOT NULL"
            ))).one()
            assert tuple(year) == (3, 2025)
            error = await connection.scalar(
                sa.text("SELECT error FROM staged_profile_rows WHERE id=:id"), {"id": bad_id}
            )
            assert "together" in error
    finally:
        await engine.dispose()
        await migration.dispose()


@pytest.mark.parametrize(
    "year, session", [(0, 2026), (9, 2026), (3, None), (None, 2026), (3, 2101)]
)
async def test_PRO1_database_enforces_year_range_and_pair(
    year: int | None, session: int | None,
) -> None:
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            student = await seed_student(connection, "db-year@example.edu")
        with pytest.raises(IntegrityError):
            async with migration.begin() as connection:
                await connection.execute(sa.text(
                    "INSERT INTO profiles (enrollment_id, study_year, study_year_session) "
                    "VALUES (:id, :year, :session)"
                ), {"id": student.enrollment_id, "year": year, "session": session})
    finally:
        await migration.dispose()
