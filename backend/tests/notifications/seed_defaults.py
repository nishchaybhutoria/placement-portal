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


def _copy_rewrites(filename: str) -> tuple[tuple[str, ...], ...]:
    path = Path(__file__).parents[2] / "alembic" / "versions" / filename
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "_REWRITES" and node.value is not None:
                return ast.literal_eval(node.value)
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_REWRITES"
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"Migration {filename} has no literal copy rewrites")


def migration_defaults() -> tuple[tuple[str, str, str], ...]:
    defaults = {
        key: (subject, body)
        for key, subject, body in (
            *_defaults_from_migration("0007_notification_templates.py"),
            *_defaults_from_migration("0008_notification_catalog.py"),
            *_defaults_from_migration("0009_reinstated_notification.py"),
            *_defaults_from_migration("0021_placement_replaced_notice.py"),
            *_defaults_from_migration("0022_notification_identity.py"),
        )
    }
    for key, old_body, new_body in _copy_rewrites("0013_notification_copy.py"):
        subject, body = defaults[key]
        assert body == old_body
        defaults[key] = (subject, new_body)
    for key, old_subject, old_body, new_subject, new_body in _copy_rewrites(
        "0022_notification_identity.py"
    ):
        assert defaults[key] == (old_subject, old_body)
        defaults[key] = (new_subject, new_body)
    return tuple((key, *value) for key, value in defaults.items())


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
