"""Read-only screen queries for profiles, resumes, and staged bulk rows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.modules.profiles.fields import (
    DECLARABLE_FIELDS,
    FIELDS,
    PROFILE_COLUMNS,
    jsonable,
    unlocked_admin_fields,
)


def field_registry() -> list[dict[str, object]]:
    """The PRO-1 ownership table as the screens and the upload template render it."""
    return [
        {
            "key": item.key,
            "label": item.label,
            "owner": item.owner.value,
            "home": item.home,
        }
        for item in FIELDS
    ]


def _editable_registry(
    values: Mapping[str, object], *, declared: bool
) -> list[dict[str, object]]:
    """The PRO-1 registry with the server's own verdict on each field.

    The form used to re-derive "can I edit this?" from ``owner`` and
    ``declared_at``, which is how it came to disagree with the command: the two
    rules were written twice.  ``editable`` is now the answer
    ``_decide_student_update`` will actually give (the design review section 4.33), so
    an admin-managed field still holding nothing renders as the input its owner
    can still fill.
    """
    unlocked = unlocked_admin_fields(values, roll_number=values.get("roll_number"))

    def editable(key: str, owner: object) -> bool:
        if not declared:
            return key in DECLARABLE_FIELDS
        return owner == "student" or key in unlocked

    return [
        item | {"editable": editable(cast(str, item["key"]), item["owner"])}
        for item in field_registry()
    ]


async def taxonomy_options(
    connection: AsyncConnection,
) -> tuple[dict[str, list[dict[str, object]]], list[dict[str, object]]]:
    """The choices a profile form offers, and which branches each program admits.

    Shared by ``me/profile`` and the INT-1 admin correction on
    ``staff/student/{enrollment_id}``: a form that offers a program the taxonomy
    has retired, or a branch its program does not admit, is a form whose save
    the server refuses -- so both read the same list rather than each assembling
    one.
    """
    taxonomies: dict[str, list[dict[str, object]]] = {}
    for key, table in (
        ("programs", "programs"),
        ("branches", "branches"),
        ("minors", "minors"),
    ):
        rows = (
            await connection.execute(
                sa.text(f"SELECT id, name FROM {table} WHERE is_active ORDER BY name, id")
            )
        ).mappings().all()
        taxonomies[key] = [
            {"id": str(cast(UUID, row["id"])), "name": str(row["name"])} for row in rows
        ]
    branch_rows = (
        await connection.execute(
            sa.text(
                "SELECT program_id, branch_id FROM program_branches "
                "ORDER BY program_id, branch_id"
            )
        )
    ).mappings().all()
    pairs: list[dict[str, object]] = [
        {
            "program_id": str(cast(UUID, row["program_id"])),
            "branch_id": str(cast(UUID, row["branch_id"])),
        }
        for row in branch_rows
    ]
    return taxonomies, pairs


async def me_profile(engine: AsyncEngine, enrollment_id: UUID) -> dict[str, object]:
    async with engine.connect() as connection:
        enrollment = (
            await connection.execute(
                sa.text(
                    "SELECT e.id, e.roll_number, e.is_current, u.id AS user_id, "
                    "u.email, u.full_name FROM enrollments e JOIN users u ON u.id = e.user_id "
                    "WHERE e.id = :enrollment_id"
                ),
                {"enrollment_id": enrollment_id},
            )
        ).mappings().one_or_none()
        profile = (
            await connection.execute(
                sa.text(
                    "SELECT " + ", ".join(PROFILE_COLUMNS) + ", declared_at FROM profiles "
                    "WHERE enrollment_id = :enrollment_id"
                ),
                {"enrollment_id": enrollment_id},
            )
        ).mappings().one_or_none()
        resumes = (
            await connection.execute(
                sa.text(
                    "SELECT id, label, drive_url, is_default, created_at FROM resumes "
                    "WHERE enrollment_id = :enrollment_id ORDER BY created_at, id"
                ),
                {"enrollment_id": enrollment_id},
            )
        ).mappings().all()
        taxonomies, program_branches = await taxonomy_options(connection)

    values: dict[str, object] = {column: None for column in PROFILE_COLUMNS}
    if profile is not None:
        values.update({column: jsonable(profile[column]) for column in PROFILE_COLUMNS})
    declared_at = profile["declared_at"] if profile is not None else None
    values["roll_number"] = str(enrollment["roll_number"]) if (
        enrollment is not None and enrollment["roll_number"] is not None
    ) else None
    values["full_name"] = str(enrollment["full_name"]) if enrollment is not None else None
    return {
        "enrollment": {
            "id": str(enrollment_id),
            "is_current": bool(enrollment["is_current"]) if enrollment is not None else False,
            "institute_email": str(enrollment["email"]) if enrollment is not None else None,
        },
        "declared_at": declared_at.isoformat() if declared_at is not None else None,
        "fields": _editable_registry(values, declared=declared_at is not None),
        "values": values,
        "resumes": [
            {
                "id": str(cast(UUID, row["id"])),
                "label": str(row["label"]),
                "drive_url": str(row["drive_url"]),
                "is_default": bool(row["is_default"]),
                "preview_url": _preview_url(str(row["drive_url"])),
            }
            for row in resumes
        ],
        "taxonomies": taxonomies,
        "program_branches": program_branches,
    }


def _preview_url(drive_url: str) -> str:
    """PRO-3: the student's own visual check embeds Drive's /preview view."""
    base = drive_url.split("?", 1)[0].rstrip("/")
    for suffix in ("/view", "/edit", "/preview"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return f"{base}/preview" if "/d/" in base else drive_url


async def admin_bulk_upsert(engine: AsyncEngine) -> dict[str, object]:
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                sa.text(
                    "SELECT s.id, s.institute_email, s.payload, s.applied_at, s.error, "
                    "s.created_at, u.email AS uploaded_by_email "
                    "FROM staged_profile_rows s LEFT JOIN users u ON u.id = s.uploaded_by "
                    "ORDER BY s.created_at DESC, s.id"
                )
            )
        ).mappings().all()

    def render(row: sa.RowMapping) -> dict[str, object]:
        payload = cast(dict[str, object], row["payload"] or {})
        return {
            "id": str(cast(UUID, row["id"])),
            "institute_email": str(row["institute_email"]),
            "raw": payload.get("raw", {}),
            "fields": payload.get("fields", {}),
            "batch_key": payload.get("batch_key"),
            "row_number": payload.get("row_number"),
            "uploaded_by_email": (
                str(row["uploaded_by_email"]) if row["uploaded_by_email"] is not None else None
            ),
            "created_at": row["created_at"].isoformat(),
            "applied_at": row["applied_at"].isoformat() if row["applied_at"] else None,
            "error": row["error"],
        }

    rendered = [render(row) for row in rows]
    return {
        "columns": [
            item for item in field_registry() if item["owner"] == "admin"
        ],
        "email_column": "institute_email",
        "staged": {
            "pending": [
                row for row in rendered if row["applied_at"] is None and row["error"] is None
            ],
            "errored": [row for row in rendered if row["error"] is not None],
            "applied": [row for row in rendered if row["applied_at"] is not None],
        },
    }
