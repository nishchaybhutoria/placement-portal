"""S16: event-order migration refuses invention and preserves append-only grants."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from tests.admin.conftest import build_checker_world, read_engine, write_engine

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("clean_findings")]


def migration() -> ModuleType:
    path = Path(__file__).parents[2] / "alembic/versions/0012_application_event_order.py"
    spec = importlib.util.spec_from_file_location("event_order_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_migration(connection: Connection, direction: str) -> None:
    with Operations.context(MigrationContext.configure(connection)):
        getattr(migration(), direction)()


async def test_S16_event_sequence_is_identity_unique_and_history_stays_append_only() -> None:
    engine = read_engine()
    try:
        async with engine.connect() as connection:
            column = (
                (
                    await connection.execute(
                        sa.text(
                            "SELECT data_type,is_nullable,is_identity,identity_generation "
                            "FROM information_schema.columns WHERE table_name='application_events' "
                            "AND column_name='event_seq'"
                        )
                    )
                )
                .mappings()
                .one()
            )
            assert dict(column) == {
                "data_type": "bigint",
                "is_nullable": "NO",
                "is_identity": "YES",
                "identity_generation": "ALWAYS",
            }
            assert (
                await connection.scalar(
                    sa.text(
                        "SELECT count(*) FROM pg_constraint "
                        "WHERE conrelid='application_events'::regclass "
                        "AND conname='uq_application_events_event_seq' AND contype='u'"
                    )
                )
                == 1
            )
            sequence = (
                await connection.execute(
                    sa.text(
                        "SELECT cache_size,cycle FROM pg_sequences "
                        "WHERE sequencename='application_events_event_seq_seq'"
                    )
                )
            ).one()
            assert tuple(sequence) == (1, False)
        for statement in (
            "UPDATE application_events SET event_seq=DEFAULT WHERE false",
            "DELETE FROM application_events WHERE false",
        ):
            async with engine.connect() as connection:
                with pytest.raises(DBAPIError) as error:
                    await connection.execute(sa.text(statement))
                assert getattr(error.value.orig, "sqlstate", None) == "42501"
    finally:
        await engine.dispose()


async def test_S16_empty_history_migrates_without_changing_table_grants() -> None:
    engine = write_engine()
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.run_sync(run_migration, "downgrade")
                await connection.run_sync(run_migration, "upgrade")
                assert (
                    await connection.scalar(sa.text("SELECT count(*) FROM application_events")) == 0
                )
                assert set(
                    (
                        await connection.execute(
                            sa.text(
                                "SELECT privilege_type FROM information_schema.role_table_grants "
                                "WHERE grantee='cds_app' AND table_name='application_events'"
                            )
                        )
                    ).scalars()
                ) == {"SELECT", "INSERT"}
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
async def test_S16_populated_history_refuses_migration_without_deleting_it(direction: str) -> None:
    await build_checker_world()
    engine = write_engine()
    try:
        async with engine.connect() as connection:
            original = (
                await connection.execute(
                    sa.text("SELECT * FROM application_events ORDER BY event_seq")
                )
            ).all()
            await connection.rollback()
            transaction = await connection.begin()
            try:
                if direction == "upgrade":
                    # Emulate the previous schema only inside this rolled-back
                    # fixture transaction; do not delete a single event row.
                    await connection.execute(
                        sa.text("ALTER TABLE application_events DROP COLUMN event_seq")
                    )
                with pytest.raises(DBAPIError, match="explicitly reset"):
                    await connection.run_sync(run_migration, direction)
            finally:
                await transaction.rollback()
            assert (
                await connection.execute(
                    sa.text("SELECT * FROM application_events ORDER BY event_seq")
                )
            ).all() == original
    finally:
        await engine.dispose()
