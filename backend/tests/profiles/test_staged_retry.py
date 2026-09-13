"""PRO-2: recovering staged rows stranded by a validation that has since changed.

A failed row is terminal so that a permanently invalid one does not retry on
every login (the design review 4.15 ruling 9).  That ruling also strands rows
whose recorded failure came from a rule the portal has since corrected, so an
administrator re-queues those deliberately and the row is revalidated at the
student's next sign-in.
"""

from __future__ import annotations

import os
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import create_engine
from app.core.errors import (
    STAGED_ROW_ALREADY_APPLIED,
    STAGED_ROW_NOT_ERRORED,
    STAGED_ROW_NOT_FOUND,
)
from app.core.plan import Preview
from tests.profiles.conftest import build_test_executor, seed_admin, seed_taxonomy
from tests.profiles.test_profile_commands import _reasons, _run
from tests.profiles.test_staged_login import _login, _stage

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("clean_profiles")]

OBSOLETE = "Secondary branch must differ from the primary branch"


async def _error(migration: AsyncEngine, staged_id: UUID) -> str | None:
    async with migration.connect() as connection:
        return await connection.scalar(
            sa.text("SELECT error FROM staged_profile_rows WHERE id = :id"),
            {"id": staged_id},
        )


async def test_PRO2_retry_reapplies_a_row_stranded_by_a_corrected_rule() -> None:
    """The nine production rows: a real payload, failed on a rule now removed."""
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            taxonomy = await seed_taxonomy(connection)
            staged_id = await _stage(
                connection,
                "stranded@example.edu",
                {
                    "program_id": str(taxonomy.program_id),
                    "secondary_program_id": str(taxonomy.other_program_id),
                    "primary_branch_id": str(taxonomy.branch_id),
                    "secondary_branch_id": str(taxonomy.branch_id),
                    "is_dual_major": False,
                    "is_dual_degree": True,
                },
                uploaded_by=cast(UUID, admin.user_id),
            )
            await connection.execute(
                sa.text("UPDATE staged_profile_rows SET error = :error WHERE id = :id"),
                {"error": OBSOLETE, "id": staged_id},
            )

        # Terminal: signing in leaves the row alone and the profile unpopulated.
        await _login(executor, "stranded@example.edu")
        assert await _error(migration, staged_id) == OBSOLETE
        async with migration.connect() as connection:
            assert await connection.scalar(sa.text("SELECT count(*) FROM profiles")) == 0

        preview = await executor.run(
            "retry_staged_row",
            executor.registry.commands["retry_staged_row"].input_model.model_validate(
                {"staged_row_id": staged_id}
            ),
            admin,
            dry_run=True,
        )
        assert isinstance(preview, Preview)
        assert preview.summary["cleared_error"] == OBSOLETE
        # A preview must not clear it.
        assert await _error(migration, staged_id) == OBSOLETE

        result = await _run(executor, "retry_staged_row", {"staged_row_id": staged_id}, admin)
        assert result.summary["institute_email"] == "stranded@example.edu"
        assert await _error(migration, staged_id) is None

        # Re-queued, it applies at the next sign-in under the corrected rule.
        await _login(executor, "stranded@example.edu")
        async with migration.connect() as connection:
            profile = (
                await connection.execute(
                    sa.text(
                        "SELECT primary_branch_id, secondary_branch_id, program_id "
                        "FROM profiles"
                    )
                )
            ).mappings().one()
            assert profile["primary_branch_id"] == taxonomy.branch_id
            assert profile["secondary_branch_id"] == taxonomy.branch_id
            assert profile["program_id"] == taxonomy.dual_degree_program_id
            applied = await connection.scalar(
                sa.text("SELECT applied_at FROM staged_profile_rows WHERE id = :id"),
                {"id": staged_id},
            )
            assert applied is not None
            cleared = await connection.scalar(
                sa.text(
                    "SELECT details FROM audit_log WHERE action = 'retry_staged_row' "
                    "ORDER BY audit_seq DESC LIMIT 1"
                )
            )
            assert cleared["cleared_error"] == OBSOLETE
    finally:
        await engine.dispose()
        await migration.dispose()


async def test_PRO2_retry_revalidates_rather_than_applying_unchecked() -> None:
    """A row that is still invalid fails again; retry is not a bypass."""
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            staged_id = await _stage(
                connection,
                "still-bad@example.edu",
                {"graduating_year": 1600},
                uploaded_by=cast(UUID, admin.user_id),
            )
        await _login(executor, "still-bad@example.edu")
        first = await _error(migration, staged_id)
        assert first is not None
        await _run(executor, "retry_staged_row", {"staged_row_id": staged_id}, admin)
        assert await _error(migration, staged_id) is None
        await _login(executor, "still-bad@example.edu")
        assert await _error(migration, staged_id) == first
        async with migration.connect() as connection:
            assert await connection.scalar(
                sa.text("SELECT graduating_year FROM profiles")
            ) is None
    finally:
        await engine.dispose()
        await migration.dispose()


async def test_PRO2_retry_refuses_unknown_pending_and_applied_rows() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            pending_id = await _stage(
                connection, "pending@example.edu", {"cpi": "8.00"},
                uploaded_by=cast(UUID, admin.user_id),
            )
            applied_id = await _stage(
                connection, "applied@example.edu", {"cpi": "9.00"},
                uploaded_by=cast(UUID, admin.user_id),
            )
        for row_id, code in (
            (uuid4(), STAGED_ROW_NOT_FOUND),
            (pending_id, STAGED_ROW_NOT_ERRORED),
        ):
            assert await _reasons(
                executor, "retry_staged_row", {"staged_row_id": row_id}, admin
            ) == [(code, "staged_row_id")]

        await _login(executor, "applied@example.edu")
        assert await _reasons(
            executor, "retry_staged_row", {"staged_row_id": applied_id}, admin
        ) == [(STAGED_ROW_ALREADY_APPLIED, "staged_row_id")]
    finally:
        await engine.dispose()
        await migration.dispose()
