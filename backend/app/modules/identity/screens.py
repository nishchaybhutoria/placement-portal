"""Administrative identity screens for IDN-2 and IDN-3."""

from __future__ import annotations

from typing import cast
from uuid import UUID

import sqlalchemy as sa
from fastapi import Query, Request
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.plan import ActorContext
from app.core.registry import Registry


def _permission(allowed: bool, human: str | None = None) -> dict[str, object]:
    return {"allowed": allowed, "reason": None, "human": human}


async def _admin_users_screen(
    request: Request,
    actor: ActorContext,
    q: str | None = Query(default=None),
    include_inactive: bool = Query(default=True),
) -> dict[str, object]:
    """List users with enrollment history and the identity controls they permit."""
    engine = cast(AsyncEngine, request.app.state.database_engine)
    conditions = [] if include_inactive else ["u.is_active"]
    parameters: dict[str, object] = {}
    if q and q.strip():
        conditions.append(
            "(u.full_name ILIKE :query OR u.email ILIKE :query "
            "OR EXISTS (SELECT 1 FROM enrollments searched "
            "WHERE searched.user_id = u.id AND searched.roll_number ILIKE :query))"
        )
        parameters["query"] = f"%{q.strip()}%"
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    async with engine.connect() as connection:
        users = (
            await connection.execute(
                sa.text(
                    "SELECT u.id, u.email, u.full_name, u.role, u.is_active, u.created_at, "
                    "e.id AS current_enrollment_id, e.roll_number, "
                    "p.declared_at, "
                    "(SELECT count(*) FROM enrollments counted WHERE counted.user_id = u.id) "
                    "AS enrollment_count "
                    "FROM users u "
                    "LEFT JOIN enrollments e ON e.user_id = u.id AND e.is_current "
                    "LEFT JOIN profiles p ON p.enrollment_id = e.id "
                    f"{where} ORDER BY u.full_name, u.email, u.id"  # noqa: S608
                ),
                parameters,
            )
        ).mappings().all()
        enrollment_rows = (
            await connection.execute(
                sa.text(
                    "SELECT id, user_id, roll_number, is_current, created_at "
                    "FROM enrollments ORDER BY user_id, created_at DESC, id"
                )
            )
        ).mappings().all()
        active_admins = int(
            await connection.scalar(
                sa.text("SELECT count(*) FROM users WHERE role = 'admin' AND is_active")
            )
            or 0
        )

    histories: dict[UUID, list[dict[str, object]]] = {}
    for enrollment in enrollment_rows:
        histories.setdefault(cast(UUID, enrollment["user_id"]), []).append(
            {
                "id": str(cast(UUID, enrollment["id"])),
                "roll_number": (
                    str(enrollment["roll_number"])
                    if enrollment["roll_number"] is not None
                    else None
                ),
                "is_current": bool(enrollment["is_current"]),
                "created_at": enrollment["created_at"].isoformat(),
            }
        )

    rendered: list[dict[str, object]] = []
    for row in users:
        user_id = cast(UUID, row["id"])
        protected_admin = (
            bool(row["is_active"])
            and str(row["role"]) == "admin"
            and (actor.user_id == user_id or active_admins <= 1)
        )
        protected_human = (
            "This administrator cannot remove their own or the last active admin access."
            if protected_admin
            else None
        )
        rendered.append(
            {
                "id": str(user_id),
                "email": str(row["email"]),
                "full_name": str(row["full_name"]),
                "role": str(row["role"]),
                "is_active": bool(row["is_active"]),
                "created_at": row["created_at"].isoformat(),
                "current_enrollment": (
                    {
                        "id": str(cast(UUID, row["current_enrollment_id"])),
                        "roll_number": (
                            str(row["roll_number"])
                            if row["roll_number"] is not None
                            else None
                        ),
                        "profile_declared": row["declared_at"] is not None,
                    }
                    if row["current_enrollment_id"] is not None
                    else None
                ),
                "enrollment_count": int(row["enrollment_count"]),
                "enrollments": histories.get(user_id, []),
                "actions": {
                    "start_new_enrollment": _permission(
                        bool(row["is_active"]),
                        None if row["is_active"] else "Inactive users cannot start an enrollment.",
                    ),
                    "set_role": _permission(not protected_admin, protected_human),
                    "deactivate": _permission(
                        bool(row["is_active"]) and not protected_admin,
                        protected_human
                        if protected_admin
                        else "This user is already inactive.",
                    ),
                },
            }
        )

    return {
        "filters": {"q": q, "include_inactive": include_inactive},
        "users": rendered,
        "counts": {
            "total": len(rendered),
            "active": sum(1 for row in rendered if row["is_active"]),
            "admins": sum(1 for row in rendered if row["role"] == "admin"),
        },
    }


def register_identity_screens(registry: Registry) -> None:
    registry.screen(id="admin/users", roles=("admin",))(_admin_users_screen)
