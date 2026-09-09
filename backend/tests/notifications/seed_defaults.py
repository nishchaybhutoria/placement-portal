"""Read immutable migration copy for test worlds that truncate parent cycles."""

from __future__ import annotations

import ast
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection


def _defaults_from_migration(filename: str) -> tuple[tuple[str, str, str], ...]:
    path = Path(__file__).parents[2] / "alembic" / "versions" / filename
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "_DEFAULTS" and node.value is not None:
                value = ast.literal_eval(node.value)
                assert isinstance(value, tuple)
                return value
    raise AssertionError(f"Migration {filename} has no literal _DEFAULTS catalog")


def migration_defaults() -> tuple[tuple[str, str, str], ...]:
    defaults = (
        *_defaults_from_migration("0007_notification_templates.py"),
        *_defaults_from_migration("0008_notification_catalog.py"),
        *_defaults_from_migration("0009_reinstated_notification.py"),
    )
    keys = [event_key for event_key, _subject, _body in defaults]
    assert len(keys) == len(set(keys))
    return defaults


async def restore_migration_defaults(connection: AsyncConnection) -> None:
    await connection.execute(
        sa.text(
            "INSERT INTO notification_templates "
            "(event_key, cycle_id, subject, body, enabled) "
            "VALUES (:event_key, NULL, :subject, :body, true) "
            "ON CONFLICT (event_key, cycle_id) "
            "DO UPDATE SET subject = EXCLUDED.subject, body = EXCLUDED.body, enabled = true"
        ),
        [
            {"event_key": key, "subject": subject, "body": body}
            for key, subject, body in migration_defaults()
        ],
    )
