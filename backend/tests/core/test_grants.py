"""M2 Procrastinate grants for the application role (LLD sections 5 and 8)."""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import RowMapping

from app.core.db import create_engine


async def _catalog_rows(statement: str) -> list[RowMapping]:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            result = await connection.execute(sa.text(statement))
            return list(result.mappings())
    finally:
        await engine.dispose()


async def _table_privileges(table_name: str) -> set[str]:
    rows = await _catalog_rows(
        "SELECT privilege_type FROM information_schema.role_table_grants "
        f"WHERE grantee = 'cds_app' AND table_schema = 'public' "
        f"AND table_name = '{table_name}'"
    )
    return {str(row["privilege_type"]) for row in rows}


@pytest.mark.asyncio
async def test_procrastinate_privileges_are_migration_managed_without_superuser() -> None:
    revision_rows = await _catalog_rows("SELECT version_num FROM alembic_version")
    assert [str(row["version_num"]) for row in revision_rows] == [
        "0015_override_scope_domains"
    ]

    role_rows = await _catalog_rows("SELECT rolsuper FROM pg_roles WHERE rolname = 'cds_app'")
    assert [bool(row["rolsuper"]) for row in role_rows] == [False]

    expected_crud = {"DELETE", "INSERT", "SELECT", "UPDATE"}
    table_rows = await _catalog_rows(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name LIKE 'procrastinate_%'"
    )
    queue_tables = {str(row["table_name"]) for row in table_rows}
    assert queue_tables
    for table_name in queue_tables:
        assert await _table_privileges(table_name) == expected_crud

    sequence_rows = await _catalog_rows(
        "SELECT sequence_name FROM information_schema.sequences "
        "WHERE sequence_schema = 'public' AND sequence_name LIKE 'procrastinate_%'"
    )
    queue_sequences = {str(row["sequence_name"]) for row in sequence_rows}
    assert queue_sequences
    for sequence_name in queue_sequences:
        privilege_rows = await _catalog_rows(
            "SELECT privilege_type FROM information_schema.role_usage_grants "
            "WHERE grantee = 'cds_app' AND object_schema = 'public' "
            f"AND object_name = '{sequence_name}'"
        )
        assert {str(row["privilege_type"]) for row in privilege_rows} == {"USAGE"}

    function_rows = await _catalog_rows(
        "SELECT DISTINCT routine_name FROM information_schema.routines "
        "WHERE routine_schema = 'public' AND routine_name LIKE 'procrastinate_%'"
    )
    queue_functions = {str(row["routine_name"]) for row in function_rows}
    assert queue_functions
    execute_rows = await _catalog_rows(
        "SELECT DISTINCT routine_name FROM information_schema.routine_privileges "
        "WHERE grantee = 'cds_app' AND routine_schema = 'public' "
        "AND routine_name LIKE 'procrastinate_%' AND privilege_type = 'EXECUTE'"
    )
    assert {str(row["routine_name"]) for row in execute_rows} == queue_functions
