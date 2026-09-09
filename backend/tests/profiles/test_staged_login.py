"""Staged rows applied at the arriving student's sign-in (PRO-2, IDN-1/2)."""

from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.db import create_engine
from app.core.errors import (
    STAGED_ROW_ALREADY_APPLIED,
    STAGED_ROW_NOT_FOUND,
    DomainRejection,
)
from app.core.executor import Executor
from app.core.plan import ActorContext, Result
from app.modules.identity.commands import new_login_input
from app.modules.profiles.staged import ROW_AUDIT_ACTION
from tests.profiles.conftest import (
    build_test_executor,
    profiles_settings,
    seed_admin,
    seed_student,
    seed_taxonomy,
)

pytestmark = pytest.mark.usefixtures("clean_profiles")

SYSTEM = ActorContext(principal_id="system", is_system=True)


async def _stage(
    connection: AsyncConnection,
    email: str,
    fields: dict[str, object],
    *,
    uploaded_by: UUID,
    batch_key: str = "staged-batch",
    row_number: int = 2,
) -> UUID:
    staged_id = uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO staged_profile_rows (id, institute_email, payload, uploaded_by) "
            "VALUES (:id, :email, CAST(:payload AS jsonb), :uploaded_by)"
        ),
        {
            "id": staged_id,
            "email": email,
            "payload": json.dumps(
                {
                    "fields": fields,
                    "raw": fields,
                    "batch_key": batch_key,
                    "row_number": row_number,
                }
            ),
            "uploaded_by": uploaded_by,
        },
    )
    return staged_id


async def _login(executor: Executor, email: str) -> Result:
    result = await executor.run(
        "google_login",
        new_login_input(email=email, full_name="Arriving Student", settings=profiles_settings()),
        SYSTEM,
    )
    assert isinstance(result, Result)
    return result


@pytest.mark.asyncio
async def test_PRO2_staged_rows_apply_at_first_sign_in() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            taxonomy = await seed_taxonomy(connection)
            staged_id = await _stage(
                connection,
                "arriving@example.edu",
                {
                    "cpi": "8.20",
                    "roll_number": "21110020",
                    "program_id": str(taxonomy.program_id),
                    "primary_branch_id": str(taxonomy.branch_id),
                },
                uploaded_by=cast(UUID, admin.user_id),
            )
        await _login(executor, "arriving@example.edu")
        async with migration.connect() as connection:
            profile = (
                await connection.execute(
                    sa.text(
                        "SELECT p.cpi, p.program_id, p.declared_at, e.roll_number "
                        "FROM profiles p JOIN enrollments e ON e.id = p.enrollment_id "
                        "JOIN users u ON u.id = e.user_id WHERE u.email = :email"
                    ),
                    {"email": "arriving@example.edu"},
                )
            ).mappings().one()
            staged = (
                await connection.execute(
                    sa.text(
                        "SELECT applied_at, error FROM staged_profile_rows WHERE id = :id"
                    ),
                    {"id": staged_id},
                )
            ).mappings().one()
            audit = (
                await connection.execute(
                    sa.text("SELECT details FROM audit_log WHERE action = :action"),
                    {"action": ROW_AUDIT_ACTION},
                )
            ).mappings().one()
    finally:
        await engine.dispose()
        await migration.dispose()

    assert profile["cpi"] == Decimal("8.20")
    assert profile["program_id"] == taxonomy.program_id
    assert profile["roll_number"] == "21110020"
    # Administration data never counts as the student's own declaration (PRO-1).
    assert profile["declared_at"] is None
    assert staged["applied_at"] is not None
    assert staged["error"] is None
    assert audit["details"]["after"]["cpi"] == "8.20"
    assert audit["details"]["staged_row_id"] == str(staged_id)


@pytest.mark.asyncio
async def test_PRO2_staged_rows_apply_in_creation_order_with_later_values_winning() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            first = await _stage(
                connection,
                "ordered@example.edu",
                {"cpi": "7.00", "graduating_year": 2025},
                uploaded_by=cast(UUID, admin.user_id),
                batch_key="first",
            )
            await connection.execute(
                sa.text(
                    "UPDATE staged_profile_rows SET created_at = now() - interval '1 hour' "
                    "WHERE id = :id"
                ),
                {"id": first},
            )
            await _stage(
                connection,
                "ordered@example.edu",
                {"cpi": "9.00"},
                uploaded_by=cast(UUID, admin.user_id),
                batch_key="second",
            )
        await _login(executor, "ordered@example.edu")
        async with migration.connect() as connection:
            profile = (
                await connection.execute(
                    sa.text("SELECT cpi, graduating_year FROM profiles")
                )
            ).mappings().one()
            audits = await connection.scalar(
                sa.text("SELECT count(*) FROM audit_log WHERE action = :action"),
                {"action": ROW_AUDIT_ACTION},
            )
    finally:
        await engine.dispose()
        await migration.dispose()

    assert profile["cpi"] == Decimal("9.00")
    assert profile["graduating_year"] == 2025
    assert audits == 2


@pytest.mark.asyncio
async def test_PRO2_an_invalid_staged_row_is_terminal_and_never_retries() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            broken = await _stage(
                connection,
                "broken@example.edu",
                {"cpi": "77"},
                uploaded_by=cast(UUID, admin.user_id),
            )
            good = await _stage(
                connection,
                "broken@example.edu",
                {"graduating_year": 2027},
                uploaded_by=cast(UUID, admin.user_id),
            )
        await _login(executor, "broken@example.edu")
        async with migration.connect() as connection:
            staged_rows = (
                await connection.execute(
                    sa.text("SELECT id, error, applied_at FROM staged_profile_rows")
                )
            ).mappings().all()
            rows = {row["id"]: row["error"] for row in staged_rows}
            applied = {row["id"]: row["applied_at"] for row in staged_rows}
        await _login(executor, "broken@example.edu")
        async with migration.connect() as connection:
            audits = await connection.scalar(
                sa.text("SELECT count(*) FROM audit_log WHERE action = :action"),
                {"action": ROW_AUDIT_ACTION},
            )
            still_errored = await connection.scalar(
                sa.text("SELECT error FROM staged_profile_rows WHERE id = :id"),
                {"id": broken},
            )
    finally:
        await engine.dispose()
        await migration.dispose()

    assert rows[broken] is not None
    assert rows[good] is None
    assert applied[broken] is None
    assert applied[good] is not None
    # The second login must not retry the permanently invalid row.
    assert audits == 1
    assert still_errored == rows[broken]


@pytest.mark.asyncio
async def test_IDN2_a_staged_roll_conflict_is_reported_not_crashed() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            await seed_student(connection, "holder@example.edu", roll_number="21110021")
            staged_id = await _stage(
                connection,
                "clash@example.edu",
                {"roll_number": "21110021"},
                uploaded_by=cast(UUID, admin.user_id),
            )
        await _login(executor, "clash@example.edu")
        async with migration.connect() as connection:
            error = await connection.scalar(
                sa.text("SELECT error FROM staged_profile_rows WHERE id = :id"),
                {"id": staged_id},
            )
            holders = await connection.scalar(
                sa.text(
                    "SELECT count(*) FROM enrollments WHERE roll_number = '21110021'"
                )
            )
    finally:
        await engine.dispose()
        await migration.dispose()

    assert error is not None
    assert holders == 1


@pytest.mark.asyncio
async def test_PRO2_staged_rows_also_apply_to_an_existing_user_at_next_login() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_student(
                connection, "existing@example.edu", roll_number="21110022"
            )
            await _stage(
                connection,
                "existing@example.edu",
                {"cpi": "8.80", "roll_number": "21110022"},
                uploaded_by=cast(UUID, admin.user_id),
            )
        await _login(executor, "existing@example.edu")
        async with migration.connect() as connection:
            cpi = await connection.scalar(
                sa.text("SELECT cpi FROM profiles WHERE enrollment_id = :id"),
                {"id": student.enrollment_id},
            )
    finally:
        await engine.dispose()
        await migration.dispose()
    assert cpi == Decimal("8.80")


@pytest.mark.asyncio
async def test_PRO2_pending_staged_rows_can_be_deleted_but_applied_ones_stay() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            pending = await _stage(
                connection,
                "pending@example.edu",
                {"cpi": "8.00"},
                uploaded_by=cast(UUID, admin.user_id),
            )
            applied = await _stage(
                connection,
                "applied@example.edu",
                {"cpi": "8.00"},
                uploaded_by=cast(UUID, admin.user_id),
            )
            await connection.execute(
                sa.text("UPDATE staged_profile_rows SET applied_at = now() WHERE id = :id"),
                {"id": applied},
            )
        spec = executor.registry.commands["delete_staged_row"]
        result = await executor.run(
            "delete_staged_row",
            spec.input_model.model_validate({"staged_row_id": str(pending)}),
            admin,
        )
        with pytest.raises(DomainRejection) as already:
            await executor.run(
                "delete_staged_row",
                spec.input_model.model_validate({"staged_row_id": str(applied)}),
                admin,
            )
        with pytest.raises(DomainRejection) as missing:
            await executor.run(
                "delete_staged_row",
                spec.input_model.model_validate({"staged_row_id": str(uuid4())}),
                admin,
            )
        async with migration.connect() as connection:
            remaining = (
                await connection.execute(sa.text("SELECT id FROM staged_profile_rows"))
            ).scalars().all()
    finally:
        await engine.dispose()
        await migration.dispose()

    assert isinstance(result, Result)
    assert result.summary["institute_email"] == "pending@example.edu"
    assert remaining == [applied]
    assert [reason.code for reason in already.value.rejection.reasons] == [
        STAGED_ROW_ALREADY_APPLIED
    ]
    assert [reason.code for reason in missing.value.rejection.reasons] == [STAGED_ROW_NOT_FOUND]
