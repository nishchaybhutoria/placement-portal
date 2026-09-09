"""Populated migration proof for the design review sections 4.52-4.53."""

from __future__ import annotations

import importlib.util
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import Connection

from app.core.db import create_engine
from tests.cycles.conftest import seed_admin, seed_cycle

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("clean_overrides")]


def migration() -> ModuleType:
    path = Path(__file__).parents[2] / "alembic/versions/0015_override_scope_domains.py"
    spec = importlib.util.spec_from_file_location("override_scope_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_migration(connection: Connection, direction: str) -> None:
    with Operations.context(MigrationContext.configure(connection)):
        getattr(migration(), direction)()


async def test_INT2_populated_domain_split_preserves_the_old_id_and_twins_authority() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.run_sync(run_migration, "downgrade")
                admin = await seed_admin(connection)
                cycle_id = await seed_cycle(connection)
                original_id = uuid4()
                created_at = datetime(2027, 4, 2, 8, 30, tzinfo=UTC)
                expires_at = created_at + timedelta(days=3)
                await connection.execute(
                    sa.text(
                        "INSERT INTO overrides (id, created_at, updated_at, "
                        "rule_domain, allow, cycle_id, reason, granted_by, "
                        "expires_at, is_active) VALUES (:id, :created_at, "
                        ":updated_at, 'edit_withdraw_window', false, :cycle_id, "
                        "'Preserve both powers', :admin, :expires_at, false)"
                    ),
                    {
                        "id": original_id,
                        "created_at": created_at,
                        "updated_at": created_at,
                        "cycle_id": cycle_id,
                        "admin": admin.user_id,
                        "expires_at": expires_at,
                    },
                )

                await connection.run_sync(run_migration, "upgrade")
                rows = (
                    await connection.execute(
                        sa.text(
                            "SELECT id, rule_domain, allow, cycle_id, job_id, "
                            "enrollment_id, application_id, reason, granted_by, "
                            "expires_at, is_active, created_at, updated_at "
                            "FROM overrides ORDER BY rule_domain"
                        )
                    )
                ).mappings().all()
                assert [str(row["rule_domain"]) for row in rows] == [
                    "edit_window",
                    "withdraw_window",
                ]
                edit, withdraw = rows
                assert edit["id"] == original_id
                assert withdraw["id"] != original_id
                for field in (
                    "allow",
                    "cycle_id",
                    "job_id",
                    "enrollment_id",
                    "application_id",
                    "reason",
                    "granted_by",
                    "expires_at",
                    "is_active",
                    "created_at",
                    "updated_at",
                ):
                    assert withdraw[field] == edit[field]
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
