"""0017 migration compatibility for profiles, staging, and rollback recovery."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from app.core.db import create_engine

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("clean_profiles")]


def migration() -> ModuleType:
    path = Path(__file__).parents[2] / "alembic/versions/0017_program_structure.py"
    spec = importlib.util.spec_from_file_location("program_structure_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_migration(connection: Connection, direction: str) -> None:
    with Operations.context(MigrationContext.configure(connection)):
        getattr(migration(), direction)()


async def test_PRO2_name_collision_refuses_without_repurposing_a_programme() -> None:
    """A display-name clash is not evidence that a row is migration-owned."""
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    btech_id, conflicting_id = uuid4(), uuid4()
    user_id, enrollment_id, profile_id = uuid4(), uuid4(), uuid4()
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.run_sync(run_migration, "downgrade")
                await connection.execute(
                    sa.text(
                        "INSERT INTO programs (id, name, is_active) VALUES "
                        "(:btech, 'BTech', true), "
                        "(:conflict, 'BTech Dual Major', true)"
                    ),
                    {"btech": btech_id, "conflict": conflicting_id},
                )
                await connection.execute(
                    sa.text(
                        "INSERT INTO users (id, email, full_name, role) "
                        "VALUES (:user, 'collision@example.edu', 'Collision', 'student')"
                    ),
                    {"user": user_id},
                )
                await connection.execute(
                    sa.text(
                        "INSERT INTO enrollments (id, user_id, is_current) "
                        "VALUES (:enrollment, :user, true)"
                    ),
                    {"enrollment": enrollment_id, "user": user_id},
                )
                await connection.execute(
                    sa.text(
                        "INSERT INTO profiles "
                        "(id, enrollment_id, program_id, is_dual_major, "
                        "is_dual_degree) VALUES "
                        "(:profile, :enrollment, :btech, true, false)"
                    ),
                    {
                        "profile": profile_id,
                        "enrollment": enrollment_id,
                        "btech": btech_id,
                    },
                )
                with pytest.raises(IntegrityError, match="programs_name"):
                    await connection.run_sync(run_migration, "upgrade")
            finally:
                await transaction.rollback()
        async with engine.connect() as connection:
            assert await connection.scalar(sa.text("SELECT count(*) FROM programs")) == 0
    finally:
        await engine.dispose()


async def test_PRO2_upgrade_downgrade_reupgrade_preserves_profiles_and_staging() -> None:
    """Combined IDs survive rollback and staging-only combinations are created."""
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    btech_id, mtech_id, branch_id = uuid4(), uuid4(), uuid4()
    user_id, enrollment_id, profile_id, staged_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.run_sync(run_migration, "downgrade")
                await connection.execute(
                    sa.text(
                        "INSERT INTO programs (id, name, is_active) VALUES "
                        "(:btech, 'BTech', true), (:mtech, 'MTech', true)"
                    ),
                    {"btech": btech_id, "mtech": mtech_id},
                )
                await connection.execute(
                    sa.text(
                        "INSERT INTO branches (id, name, is_active) "
                        "VALUES (:branch, 'CSE', true)"
                    ),
                    {"branch": branch_id},
                )
                await connection.execute(
                    sa.text(
                        "INSERT INTO program_branches (program_id, branch_id) VALUES "
                        "(:btech, :branch), (:mtech, :branch)"
                    ),
                    {"btech": btech_id, "mtech": mtech_id, "branch": branch_id},
                )
                await connection.execute(
                    sa.text(
                        "INSERT INTO users (id, email, full_name, role) "
                        "VALUES (:user, 'migration@example.edu', 'Migration', 'student')"
                    ),
                    {"user": user_id},
                )
                await connection.execute(
                    sa.text(
                        "INSERT INTO enrollments (id, user_id, is_current) "
                        "VALUES (:enrollment, :user, true)"
                    ),
                    {"enrollment": enrollment_id, "user": user_id},
                )
                await connection.execute(
                    sa.text(
                        "INSERT INTO profiles "
                        "(id, enrollment_id, program_id, primary_branch_id, "
                        "secondary_branch_id, is_dual_major, is_dual_degree) VALUES "
                        "(:profile, :enrollment, :btech, :branch, :branch, true, false)"
                    ),
                    {
                        "profile": profile_id,
                        "enrollment": enrollment_id,
                        "btech": btech_id,
                        "branch": branch_id,
                    },
                )
                staged_payload = {
                    "fields": {
                        "program_id": str(btech_id),
                        "secondary_program_id": str(mtech_id),
                        "primary_branch_id": str(branch_id),
                        "secondary_branch_id": str(branch_id),
                        "is_dual_major": False,
                        "is_dual_degree": True,
                    },
                    "batch_key": "migration-staging",
                }
                await connection.execute(
                    sa.text(
                        "INSERT INTO staged_profile_rows "
                        "(id, institute_email, payload, uploaded_by) "
                        "VALUES (:id, 'future@example.edu', CAST(:payload AS jsonb), "
                        ":uploaded_by)"
                    ),
                    {
                        "id": staged_id,
                        "payload": json.dumps(staged_payload),
                        "uploaded_by": user_id,
                    },
                )

                await connection.run_sync(run_migration, "upgrade")
                first = (
                    await connection.execute(
                        sa.text(
                            "SELECT id, structure, primary_degree_id, "
                            "secondary_degree_id FROM programs "
                            "WHERE structure <> 'single' ORDER BY structure"
                        )
                    )
                ).mappings().all()
                first_ids = {str(row["structure"]): row["id"] for row in first}
                assert set(first_ids) == {"dual_major", "dual_degree"}
                assert await connection.scalar(
                    sa.text("SELECT program_id FROM profiles WHERE id = :id"),
                    {"id": profile_id},
                ) == first_ids["dual_major"]
                assert await connection.scalar(
                    sa.text("SELECT payload FROM staged_profile_rows WHERE id = :id"),
                    {"id": staged_id},
                ) == staged_payload

                await connection.run_sync(run_migration, "downgrade")
                restored = (
                    await connection.execute(
                        sa.text(
                            "SELECT program_id, secondary_program_id, is_dual_major, "
                            "is_dual_degree FROM profiles WHERE id = :id"
                        ),
                        {"id": profile_id},
                    )
                ).mappings().one()
                assert restored == {
                    "program_id": btech_id,
                    "secondary_program_id": None,
                    "is_dual_major": True,
                    "is_dual_degree": False,
                }

                await connection.run_sync(run_migration, "upgrade")
                second_ids = {
                    str(row["structure"]): row["id"]
                    for row in (
                        await connection.execute(
                            sa.text(
                                "SELECT id, structure FROM programs "
                                "WHERE structure <> 'single'"
                            )
                        )
                    ).mappings()
                }
                assert second_ids == first_ids
                assert await connection.scalar(
                    sa.text("SELECT program_id FROM profiles WHERE id = :id"),
                    {"id": profile_id},
                ) == first_ids["dual_major"]
                assert isinstance(first_ids["dual_degree"], UUID)
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
