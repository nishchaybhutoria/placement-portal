"""Audit-log append order, and the backfill that made it possible on history.

The same defect §4.41 fixed for `application_events`: two audit rows written in
one transaction share `now()`, and the trail's reader broke the tie on a random
UUID. What is different here is that `0012` could refuse a populated table and
`0014` cannot — a production audit trail is the one thing nobody may reset — so
the ordering of pre-migration rows is derived from `(created_at, id)` and is
best effort by construction. These tests pin both halves: the backfill obeys
that rule, and everything written afterwards is authoritative.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import Connection

from tests.admin.conftest import read_engine, write_engine

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("clean_findings")]


def migration() -> ModuleType:
    path = Path(__file__).parents[2] / "alembic/versions/0014_audit_log_order.py"
    spec = importlib.util.spec_from_file_location("audit_order_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_migration(connection: Connection, direction: str) -> None:
    with Operations.context(MigrationContext.configure(connection)):
        getattr(migration(), direction)()


async def _insert(connection: object, *, action: str, created_at: datetime) -> UUID:
    row_id = uuid4()
    await connection.execute(  # type: ignore[attr-defined]
        sa.text(
            "INSERT INTO audit_log (id, action, details, created_at) "
            "VALUES (:id, :action, CAST('{}' AS jsonb), :created_at)"
        ),
        {"id": row_id, "action": action, "created_at": created_at},
    )
    return row_id


async def test_S16_audit_sequence_is_identity_and_unique() -> None:
    engine = read_engine()
    try:
        async with engine.connect() as connection:
            column = (
                await connection.execute(
                    sa.text(
                        "SELECT is_identity, identity_generation, is_nullable "
                        "FROM information_schema.columns "
                        "WHERE table_name = 'audit_log' AND column_name = 'audit_seq'"
                    )
                )
            ).mappings().one()
            assert column["is_identity"] == "YES"
            assert column["identity_generation"] == "ALWAYS"
            assert column["is_nullable"] == "NO"
            constraint = await connection.scalar(
                sa.text(
                    "SELECT count(*) FROM information_schema.table_constraints "
                    "WHERE constraint_name = 'uq_audit_log_audit_seq'"
                )
            )
            assert constraint == 1
    finally:
        await engine.dispose()


async def test_S16_rows_written_in_one_transaction_keep_their_append_order() -> None:
    """The defect itself: identical timestamps, and the order still holds."""
    engine = write_engine()
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                stamp = datetime(2027, 3, 1, 9, 0, tzinfo=UTC)
                first = await _insert(connection, action="first", created_at=stamp)
                second = await _insert(connection, action="second", created_at=stamp)
                third = await _insert(connection, action="third", created_at=stamp)
                ordered = (
                    await connection.execute(
                        sa.text(
                            "SELECT id FROM audit_log WHERE id = ANY(:ids) ORDER BY audit_seq"
                        ),
                        {"ids": [first, second, third]},
                    )
                ).scalars().all()
                assert list(ordered) == [first, second, third]
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


async def test_S16_the_backfill_orders_history_by_created_at_then_id() -> None:
    """0014 cannot refuse a populated table, so it must number it honestly."""
    engine = write_engine()
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.run_sync(run_migration, "downgrade")
                base = datetime(2027, 3, 1, 9, 0, tzinfo=UTC)
                # Deliberately inserted newest-first, so physical order and
                # chronological order disagree: a migration that numbered rows
                # in scan order would pass a weaker test than this one.
                late = await _insert(
                    connection, action="late", created_at=base + timedelta(hours=2)
                )
                early = await _insert(connection, action="early", created_at=base)
                middle = await _insert(
                    connection, action="middle", created_at=base + timedelta(hours=1)
                )
                await connection.run_sync(run_migration, "upgrade")

                ordered = (
                    await connection.execute(
                        sa.text(
                            "SELECT id FROM audit_log WHERE id = ANY(:ids) ORDER BY audit_seq"
                        ),
                        {"ids": [late, early, middle]},
                    )
                ).scalars().all()
                assert list(ordered) == [early, middle, late]

                # And the identity continues past the backfill rather than
                # colliding with it.
                fresh = await _insert(
                    connection, action="after", created_at=base + timedelta(hours=3)
                )
                highest = await connection.scalar(
                    sa.text("SELECT audit_seq FROM audit_log WHERE id = :id"), {"id": fresh}
                )
                backfilled = await connection.scalar(
                    sa.text("SELECT max(audit_seq) FROM audit_log WHERE id = ANY(:ids)"),
                    {"ids": [late, early, middle]},
                )
                assert highest is not None and backfilled is not None
                assert highest > backfilled
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


async def test_S16_the_migration_never_deletes_an_audit_row() -> None:
    """The whole reason this one backfills instead of refusing."""
    engine = write_engine()
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                stamp = datetime(2027, 3, 1, 9, 0, tzinfo=UTC)
                kept = await _insert(connection, action="kept", created_at=stamp)
                before = await connection.scalar(sa.text("SELECT count(*) FROM audit_log"))
                await connection.run_sync(run_migration, "downgrade")
                await connection.run_sync(run_migration, "upgrade")
                after = await connection.scalar(sa.text("SELECT count(*) FROM audit_log"))
                assert before == after
                survivor = await connection.scalar(
                    sa.text("SELECT count(*) FROM audit_log WHERE id = :id"), {"id": kept}
                )
                assert survivor == 1
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


async def test_S16_the_trail_reader_orders_by_sequence_not_wall_clock() -> None:
    """`interventions/queries.py`'s `_AUDIT` is the one reader that displays it."""
    from app.modules.interventions.queries import _AUDIT

    assert "ORDER BY l.audit_seq DESC" in _AUDIT
    assert "l.created_at DESC" not in _AUDIT
