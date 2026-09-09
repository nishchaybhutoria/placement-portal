"""Admin bulk upsert: match key, cross-check, staging, audit (PRO-2, IDN-2)."""

from __future__ import annotations

import os
from decimal import Decimal
from typing import cast

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import (
    DUPLICATE_ROW,
    FIELD_NOT_EDITABLE,
    ROLL_MISMATCH,
    UNKNOWN_TAXONOMY_VALUE,
)
from app.core.executor import Executor
from app.core.plan import ActorContext, Preview, Result
from app.modules.profiles.bulk import ROW_AUDIT_ACTION
from tests.profiles.conftest import (
    add_enrollment,
    build_test_executor,
    seed_admin,
    seed_student,
    seed_taxonomy,
)

pytestmark = pytest.mark.usefixtures("clean_profiles")


def _row(number: int, email: str, **fields: object) -> dict[str, object]:
    return {"row_number": number, "institute_email": email, "fields": fields}


async def _upsert(
    executor: Executor,
    actor: ActorContext,
    rows: list[dict[str, object]],
    batch_key: str,
    *,
    dry_run: bool = False,
) -> list[dict[str, object]]:
    result = await executor.run_bulk(
        "bulk_upsert_profiles", rows, batch_key, actor, dry_run=dry_run
    )
    assert isinstance(result, Preview if dry_run else Result)
    return cast(list[dict[str, object]], result.summary["rows"])


def _outcomes(rows: list[dict[str, object]]) -> list[tuple[int, str]]:
    return [(cast(int, row["row_number"]), cast(str, row["result"])) for row in rows]


def _codes(row: dict[str, object]) -> list[str]:
    return [cast(str, reason["code"]) for reason in cast(list[dict[str, object]], row["reasons"])]


@pytest.mark.asyncio
async def test_PRO2_preview_reports_update_stage_and_error_rows_without_writing() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            await seed_taxonomy(connection)
            await seed_student(connection, "known@example.edu", roll_number="21110010")
        rows = [
            _row(2, "known@example.edu", cpi="8.10", roll_number="21110010"),
            _row(3, "newcomer@example.edu", cpi="9.00"),
            _row(4, "broken@example.edu", cpi="12"),
        ]
        preview = await _upsert(executor, admin, rows, "preview-batch", dry_run=True)
        async with migration.connect() as connection:
            profiles = await connection.scalar(sa.text("SELECT count(*) FROM profiles"))
            staged = await connection.scalar(
                sa.text("SELECT count(*) FROM staged_profile_rows")
            )
            audits = await connection.scalar(sa.text("SELECT count(*) FROM audit_log"))
    finally:
        await engine.dispose()
        await migration.dispose()

    assert _outcomes(preview) == [(2, "updated"), (3, "staged"), (4, "error")]
    assert profiles == 0
    assert staged == 0
    assert audits == 0


@pytest.mark.asyncio
async def test_PRO2_commit_applies_updates_stages_unmatched_and_audits_each_row() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            taxonomy = await seed_taxonomy(connection)
            student = await seed_student(connection, "known@example.edu", roll_number="21110011")
        rows = [
            _row(
                2,
                "KNOWN@example.edu",
                cpi="8.10",
                program_id=taxonomy.program_name,
                primary_branch_id=taxonomy.branch_name,
                gender="male",
                full_name="Renamed Student",
            ),
            _row(3, "newcomer@example.edu", cpi="9.00"),
        ]
        applied = await _upsert(executor, admin, rows, "commit-batch")
        async with migration.connect() as connection:
            profile = (
                await connection.execute(
                    sa.text(
                        "SELECT cpi, program_id, primary_branch_id, gender FROM profiles "
                        "WHERE enrollment_id = :id"
                    ),
                    {"id": student.enrollment_id},
                )
            ).mappings().one()
            full_name = await connection.scalar(
                sa.text("SELECT full_name FROM users WHERE id = :id"),
                {"id": student.user_id},
            )
            staged = (
                await connection.execute(
                    sa.text(
                        "SELECT institute_email, payload, applied_at, error "
                        "FROM staged_profile_rows"
                    )
                )
            ).mappings().one()
            audit = (
                await connection.execute(
                    sa.text(
                        "SELECT action, subject_id, details FROM audit_log "
                        "WHERE action = :action"
                    ),
                    {"action": ROW_AUDIT_ACTION},
                )
            ).mappings().all()
    finally:
        await engine.dispose()
        await migration.dispose()

    assert _outcomes(applied) == [(2, "updated"), (3, "staged")]
    assert profile["cpi"] == Decimal("8.10")
    assert profile["program_id"] == taxonomy.program_id
    assert profile["primary_branch_id"] == taxonomy.branch_id
    assert profile["gender"] == "male"
    assert full_name == "Renamed Student"
    assert staged["institute_email"] == "newcomer@example.edu"
    assert staged["payload"]["fields"] == {"cpi": "9.00"}
    assert staged["applied_at"] is None and staged["error"] is None
    assert len(audit) == 1
    assert audit[0]["subject_id"] == student.enrollment_id
    assert audit[0]["details"]["before"] == {
        "cpi": None,
        "program_id": None,
        "primary_branch_id": None,
        "gender": None,
        "full_name": "Test Student",
    }
    assert audit[0]["details"]["after"]["cpi"] == "8.10"
    assert audit[0]["details"]["batch_key"] == "commit-batch"
    assert audit[0]["details"]["row_number"] == 2


@pytest.mark.asyncio
async def test_PRO2_roll_cross_check_errors_on_mismatch_and_adopts_when_unset() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            held = await seed_student(connection, "held@example.edu", roll_number="21110012")
            blank = await seed_student(connection, "blank@example.edu")
        rows = [
            _row(2, "held@example.edu", roll_number="21110099", cpi="8.00"),
            _row(3, "blank@example.edu", roll_number="21110013", cpi="7.00"),
        ]
        applied = await _upsert(executor, admin, rows, "roll-batch")
        async with migration.connect() as connection:
            roll_rows = (
                await connection.execute(
                    sa.text("SELECT id, roll_number FROM enrollments")
                )
            ).mappings().all()
            rolls = {row["id"]: row["roll_number"] for row in roll_rows}
            profiles = await connection.scalar(sa.text("SELECT count(*) FROM profiles"))
    finally:
        await engine.dispose()
        await migration.dispose()

    assert _outcomes(applied) == [(2, "error"), (3, "updated")]
    assert _codes(applied[0]) == [ROLL_MISMATCH]
    assert rolls[held.enrollment_id] == "21110012"
    assert rolls[blank.enrollment_id] == "21110013"
    assert profiles == 1


@pytest.mark.asyncio
async def test_IDN2_a_stale_roll_never_writes_onto_the_new_enrollment() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_student(connection, "rejoin@example.edu", roll_number="18110001")
            historical = student.enrollment_id
            current = await add_enrollment(connection, student, roll_number="21110014")
        applied = await _upsert(
            executor,
            admin,
            [_row(2, "rejoin@example.edu", roll_number="18110001", cpi="9.99")],
            "stale-batch",
        )
        async with migration.connect() as connection:
            profiles = (
                await connection.execute(sa.text("SELECT enrollment_id FROM profiles"))
            ).scalars().all()
    finally:
        await engine.dispose()
        await migration.dispose()

    assert _outcomes(applied) == [(2, "error")]
    assert _codes(applied[0]) == [ROLL_MISMATCH]
    assert profiles == []
    assert historical != current


@pytest.mark.asyncio
async def test_PRO2_reruns_are_idempotent_and_absent_columns_stay_untouched() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_student(connection, "repeat@example.edu")
        rows = [_row(2, "repeat@example.edu", cpi="8.00", graduating_year="2026")]
        first = await _upsert(executor, admin, rows, "repeat-batch")
        replay = await _upsert(executor, admin, rows, "repeat-batch")
        second = await _upsert(
            executor, admin, [_row(2, "repeat@example.edu", cpi="8.00")], "repeat-batch-2"
        )
        narrowed = await _upsert(
            executor, admin, [_row(2, "repeat@example.edu", cpi="8.40")], "repeat-batch-3"
        )
        async with migration.connect() as connection:
            profile = (
                await connection.execute(
                    sa.text(
                        "SELECT cpi, graduating_year FROM profiles WHERE enrollment_id = :id"
                    ),
                    {"id": student.enrollment_id},
                )
            ).mappings().one()
            row_audits = await connection.scalar(
                sa.text("SELECT count(*) FROM audit_log WHERE action = :action"),
                {"action": ROW_AUDIT_ACTION},
            )
    finally:
        await engine.dispose()
        await migration.dispose()

    assert _outcomes(first) == [(2, "updated")]
    assert _outcomes(replay) == [(2, "updated")]
    assert _outcomes(second) == [(2, "unchanged")]
    assert _outcomes(narrowed) == [(2, "updated")]
    assert profile["cpi"] == Decimal("8.40")
    assert profile["graduating_year"] == 2026
    assert row_audits == 2


@pytest.mark.asyncio
async def test_PRO2_row_errors_cover_taxonomy_ownership_and_duplicates() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            await seed_taxonomy(connection)
            await seed_student(connection, "one@example.edu")
            await seed_student(connection, "two@example.edu")
        rows = [
            _row(2, "one@example.edu", program_id="Astrology"),
            _row(3, "one@example.edu", cpi="8.00"),
            _row(4, "two@example.edu", github_url="https://github.com/x"),
        ]
        applied = await _upsert(executor, admin, rows, "errors-batch")
        async with migration.connect() as connection:
            profiles = await connection.scalar(sa.text("SELECT count(*) FROM profiles"))
    finally:
        await engine.dispose()
        await migration.dispose()

    assert _outcomes(applied) == [(2, "error"), (3, "error"), (4, "error")]
    assert _codes(applied[0]) == [DUPLICATE_ROW]
    assert _codes(applied[1]) == [DUPLICATE_ROW]
    assert _codes(applied[2]) == [FIELD_NOT_EDITABLE]
    assert profiles == 0


@pytest.mark.asyncio
async def test_PRO2_inactive_taxonomy_values_are_row_errors() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            taxonomy = await seed_taxonomy(connection)
            await seed_student(connection, "inactive@example.edu")
            await connection.execute(
                sa.text("UPDATE programs SET is_active = false WHERE id = :id"),
                {"id": taxonomy.program_id},
            )
        applied = await _upsert(
            executor,
            admin,
            [_row(2, "inactive@example.edu", program_id=str(taxonomy.program_id))],
            "inactive-batch",
        )
    finally:
        await engine.dispose()
        await migration.dispose()

    assert _outcomes(applied) == [(2, "error")]
    assert _codes(applied[0]) == [UNKNOWN_TAXONOMY_VALUE]


@pytest.mark.asyncio
async def test_PRO2_restaging_an_identical_row_does_not_duplicate_it() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
        first = await _upsert(
            executor, admin, [_row(2, "ghost@example.edu", cpi="7.00")], "stage-one"
        )
        again = await _upsert(
            executor, admin, [_row(9, "ghost@example.edu", cpi="7.00")], "stage-two"
        )
        changed = await _upsert(
            executor, admin, [_row(9, "ghost@example.edu", cpi="7.50")], "stage-three"
        )
        async with migration.connect() as connection:
            staged = await connection.scalar(
                sa.text("SELECT count(*) FROM staged_profile_rows")
            )
    finally:
        await engine.dispose()
        await migration.dispose()

    assert _outcomes(first) == [(2, "staged")]
    assert _outcomes(again) == [(9, "unchanged")]
    assert _outcomes(changed) == [(9, "staged")]
    assert staged == 2
