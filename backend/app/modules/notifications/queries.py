"""Read models and template resolution for notifications (Behavior NTF)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from app.modules.notifications.catalog import EVENT_KEYS, TEMPLATE_VARIABLES

Executor = AsyncConnection | AsyncSession


@dataclass(frozen=True, slots=True)
class ResolvedTemplate:
    id: UUID
    event_key: str
    cycle_id: UUID | None
    subject: str
    body: str
    enabled: bool


async def resolve_template(
    executor: Executor, event_key: str, cycle_id: UUID | None
) -> ResolvedTemplate | None:
    """Resolve a cycle override first, then the global row (LLD section 12)."""
    row = (
        (
            await executor.execute(
                sa.text(
                    "SELECT id, event_key, cycle_id, subject, body, enabled "
                    "FROM notification_templates "
                    "WHERE event_key = :event_key "
                    "AND (cycle_id = :cycle_id OR cycle_id IS NULL) "
                    "ORDER BY (cycle_id IS NOT NULL) DESC LIMIT 1"
                ),
                {"event_key": event_key, "cycle_id": cycle_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return ResolvedTemplate(
        id=cast(UUID, row["id"]),
        event_key=str(row["event_key"]),
        cycle_id=cast("UUID | None", row["cycle_id"]),
        subject=str(row["subject"]),
        body=str(row["body"]),
        enabled=bool(row["enabled"]),
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def admin_templates(engine: AsyncEngine) -> dict[str, object]:
    """The global catalog, per-cycle overrides, and actionable dead letters."""
    async with engine.connect() as connection:
        rows = (
            (
                await connection.execute(
                    sa.text(
                        "SELECT t.id, t.event_key, t.cycle_id, t.subject, t.body, "
                        "t.enabled, t.updated_at, c.name AS cycle_name "
                        "FROM notification_templates t "
                        "LEFT JOIN cycles c ON c.id = t.cycle_id "
                        "ORDER BY t.event_key, c.name NULLS FIRST"
                    )
                )
            )
            .mappings()
            .all()
        )
        cycles = (
            (
                await connection.execute(
                    sa.text(
                        "SELECT id, name, kind, archived_at FROM cycles "
                        "ORDER BY archived_at NULLS FIRST, name, id"
                    )
                )
            )
            .mappings()
            .all()
        )
        dead = (
            (
                await connection.execute(
                    sa.text(
                        "SELECT id, recipient, event_key, subject, attempts, last_error, "
                        "created_at, updated_at FROM notification_log "
                        "WHERE status = 'dead' ORDER BY updated_at DESC, id DESC LIMIT 100"
                    )
                )
            )
            .mappings()
            .all()
        )

    by_key: dict[str, dict[str, object]] = {
        event_key: {
            "event_key": event_key,
            "variables": list(TEMPLATE_VARIABLES[event_key]),
            "global": None,
            "overrides": [],
        }
        for event_key in EVENT_KEYS
    }
    for row in rows:
        event_key = str(row["event_key"])
        if event_key not in by_key:
            raise RuntimeError(
                f"Notification template {event_key!r} is outside the effective catalog"
            )
        payload = {
            "id": str(cast(UUID, row["id"])),
            "cycle_id": str(cast(UUID, row["cycle_id"])) if row["cycle_id"] else None,
            "cycle_name": row["cycle_name"],
            "subject": str(row["subject"]),
            "body": str(row["body"]),
            "enabled": bool(row["enabled"]),
            "updated_at": _iso(cast(datetime, row["updated_at"])),
        }
        if row["cycle_id"] is None:
            by_key[event_key]["global"] = payload
        else:
            cast(list[dict[str, object]], by_key[event_key]["overrides"]).append(payload)

    return {
        "templates": list(by_key.values()),
        "cycles": [
            {
                "id": str(cast(UUID, row["id"])),
                "name": str(row["name"]),
                "kind": str(row["kind"]),
                "archived_at": _iso(cast("datetime | None", row["archived_at"])),
            }
            for row in cycles
        ],
        "dead_letters": [
            {
                "id": str(cast(UUID, row["id"])),
                "recipient": str(row["recipient"]),
                "event_key": str(row["event_key"]),
                "subject": str(row["subject"]),
                "attempts": int(row["attempts"]),
                "last_error": row["last_error"],
                "created_at": _iso(cast(datetime, row["created_at"])),
                "updated_at": _iso(cast(datetime, row["updated_at"])),
            }
            for row in dead
        ],
    }

#: What a student may see of their own delivery record. Deliberately not
#: `context`: it holds the rendered variables, and this screen is a record of
#: what was sent, not a second renderer that could disagree with the email.
_MY_NOTIFICATIONS = """
    SELECT n.id, n.event_key, n.subject, n.status, n.sent_at, n.updated_at
    FROM notification_log n
    WHERE lower(n.recipient) = lower(:recipient)
    ORDER BY COALESCE(n.sent_at, n.updated_at) DESC, n.id
    LIMIT 200
"""


async def me_notifications(engine: AsyncEngine, recipient: str) -> dict[str, object]:
    """Every notice this address was sent (LLD section 18, deferred until now).

    A read, and only a read: the rows already exist because delivery records
    them, so this adds no write path and no schema. It exists because a student
    who deletes an email had no way to see what the portal told them, and
    because mock Step 33 -- "review every email received" -- was human-only for
    the want of a screen to assert against.

    Subject only, never the body. The body is rendered at delivery from a
    template that an operator may since have edited; showing it again from
    today's template would state, in the student's own record, something other
    than what they were sent.
    """
    async with engine.connect() as connection:
        rows = (
            await connection.execute(sa.text(_MY_NOTIFICATIONS), {"recipient": recipient})
        ).mappings().all()
    return {
        "notifications": [
            {
                "id": str(cast(UUID, row["id"])),
                "event_key": str(row["event_key"]),
                "subject": str(row["subject"]),
                "status": str(row["status"]),
                # `sent_at` is null until delivery succeeds; the row still
                # exists, and a student watching for a notice that has not
                # arrived is exactly who this screen is for.
                "sent_at": _iso(row["sent_at"]),
                "recorded_at": _iso(row["updated_at"]),
            }
            for row in rows
        ]
    }
