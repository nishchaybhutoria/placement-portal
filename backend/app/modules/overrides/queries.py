"""The administrative override register (Behavior INT-2, LLD section 11.3).

INT-2 asks for exactly three things beyond the grant itself: overrides are
listed, filterable, and deactivated in one click.  The list is therefore the
whole screen, and every row carries the same ``allowed`` shape the other
screens use so the button and the command agree (the design review section 4.22).

The three states a row can be in are computed here rather than left to the
client, because "active" is not the same question as ``is_active``: a row with a
past expiry is inert while its flag still says true, and a screen that showed it
as live would be describing something the resolver ignores.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.errors import OVERRIDE_ALREADY_INACTIVE
from app.domain.shared import (
    OVERRIDE_SCOPE_COMBINATIONS,
    RuleDomain,
    override_scope_combination,
    scope_name,
)

_OVERRIDES = """
    SELECT o.id, o.rule_domain, o.allow, o.reason, o.expires_at, o.is_active,
           o.created_at, o.granted_by, g.full_name AS granted_by_name,
           o.cycle_id, o.job_id, o.enrollment_id, o.application_id,
           coalesce(o.cycle_id, jc.cycle_id, ac.cycle_id) AS scope_cycle_id,
           coalesce(c.name, jcy.name, acy.name) AS cycle_name,
           coalesce(jc.title, ac.title) AS job_title,
           coalesce(eu.full_name, au.full_name) AS student_name,
           coalesce(er.roll_number, ar.roll_number) AS student_roll,
           o.expires_at IS NOT NULL AND o.expires_at <= now() AS is_expired
    FROM overrides o
    JOIN users g ON g.id = o.granted_by
    LEFT JOIN cycles c ON c.id = o.cycle_id
    LEFT JOIN jobs jc ON jc.id = o.job_id
    LEFT JOIN cycles jcy ON jcy.id = jc.cycle_id
    LEFT JOIN applications a ON a.id = o.application_id
    LEFT JOIN jobs ac ON ac.id = a.job_id
    LEFT JOIN cycles acy ON acy.id = ac.cycle_id
    LEFT JOIN enrollments er ON er.id = o.enrollment_id
    LEFT JOIN users eu ON eu.id = er.user_id
    LEFT JOIN enrollments ar ON ar.id = a.enrollment_id
    LEFT JOIN users au ON au.id = ar.user_id
    WHERE (CAST(:rule_domain AS text) IS NULL
           OR o.rule_domain::text = CAST(:rule_domain AS text))
      AND (CAST(:scope AS text) IS NULL OR (
            CASE
                WHEN o.application_id IS NOT NULL THEN 'application'
                WHEN o.job_id IS NOT NULL AND o.enrollment_id IS NOT NULL
                    THEN 'job+enrollment'
                WHEN o.cycle_id IS NOT NULL AND o.enrollment_id IS NOT NULL
                    THEN 'cycle+enrollment'
                WHEN o.enrollment_id IS NOT NULL THEN 'enrollment'
                WHEN o.job_id IS NOT NULL THEN 'job'
                ELSE 'cycle'
            END = CAST(:scope AS text)))
      AND (CAST(:cycle_id AS uuid) IS NULL
           OR coalesce(o.cycle_id, jc.cycle_id, ac.cycle_id) = CAST(:cycle_id AS uuid))
      AND (
        CAST(:visible_cycle_ids AS uuid[]) IS NULL
        OR coalesce(o.cycle_id, jc.cycle_id, ac.cycle_id)
             = ANY(CAST(:visible_cycle_ids AS uuid[]))
      )
      AND (CAST(:state AS text) IS NULL OR (
            CASE
                WHEN NOT o.is_active THEN 'deactivated'
                WHEN o.expires_at IS NOT NULL AND o.expires_at <= now() THEN 'expired'
                ELSE 'active'
            END = CAST(:state AS text)))
    ORDER BY o.created_at DESC, o.id
"""

_CYCLES = """
    SELECT id, name, kind, archived_at IS NOT NULL AS archived
    FROM cycles
    WHERE CAST(:visible_cycle_ids AS uuid[]) IS NULL
       OR id = ANY(CAST(:visible_cycle_ids AS uuid[]))
    ORDER BY name
"""

STATES: tuple[str, ...] = ("active", "expired", "deactivated")


def _scope_of(row: sa.RowMapping) -> tuple[str, UUID, str]:
    """The row's combination, primary id, and non-empty human label."""
    combination = override_scope_combination(
        cycle_id=row["cycle_id"],
        job_id=row["job_id"],
        enrollment_id=row["enrollment_id"],
        application_id=row["application_id"],
    )
    if combination is None:
        raise ValueError("Override row names an illegal scope combination")
    kind = scope_name(combination)
    student = str(row["student_name"] or "").strip()
    roll = row["student_roll"]
    student_label = f"{student} ({roll})" if student and roll else student
    job = str(row["job_title"] or "").strip()
    cycle = str(row["cycle_name"] or "").strip()

    if kind == "application":
        named = " — ".join(part for part in (student, job) if part)
        return kind, cast(UUID, row["application_id"]), (
            named or "Application no longer available"
        )
    if kind == "job+enrollment":
        named = " — ".join(
            (student_label or "Student no longer available", job or "Job no longer available")
        )
        return kind, cast(UUID, row["job_id"]), named
    if kind == "cycle+enrollment":
        named = " — ".join(
            (
                student_label or "Student no longer available",
                cycle or "Cycle no longer available",
            )
        )
        return kind, cast(UUID, row["enrollment_id"]), named
    if kind == "enrollment":
        return (
            kind,
            cast(UUID, row["enrollment_id"]),
            student_label or "Student no longer available",
        )
    if kind == "job":
        return kind, cast(UUID, row["job_id"]), job or "Job no longer available"
    return kind, cast(UUID, row["cycle_id"]), cycle or "Cycle no longer available"


def _state(row: sa.RowMapping) -> str:
    if not bool(row["is_active"]):
        return "deactivated"
    return "expired" if bool(row["is_expired"]) else "active"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def admin_overrides(
    engine: AsyncEngine,
    *,
    rule_domain: str | None = None,
    scope: str | None = None,
    cycle_id: UUID | None = None,
    state: str | None = None,
    visible_cycle_ids: Sequence[UUID] | None = None,
) -> dict[str, object]:
    """Every override, filtered as INT-2 requires, with its own deactivate verdict.

    ``create_override`` is a staff command, so the register that shows what was
    granted has to be readable by the person who granted it.  A coordinator sees
    the cycles they coordinate: ``visible_cycle_ids`` restricts both the rows and
    the cycle filter to those.  Enrollment-only grants belong to no cycle and
    stay out of a coordinator's list; cycle+enrollment and job+enrollment grants
    resolve through their cycle like every other coordinator-owned target.
    """
    scope_ids = list(visible_cycle_ids) if visible_cycle_ids is not None else None
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                sa.text(_OVERRIDES),
                {
                    "rule_domain": rule_domain,
                    "scope": scope,
                    "cycle_id": str(cycle_id) if cycle_id is not None else None,
                    "state": state,
                    "visible_cycle_ids": scope_ids,
                },
            )
        ).mappings().all()
        cycles = (
            await connection.execute(
                sa.text(_CYCLES), {"visible_cycle_ids": scope_ids}
            )
        ).mappings().all()

    overrides: list[dict[str, object]] = []
    for row in rows:
        kind, subject_id, label = _scope_of(row)
        row_state = _state(row)
        # An expired override is inert but not yet deactivated, and INT-2's
        # one-click deactivation is exactly how staff make that permanent -- so
        # the button stays live for it, and only an already-deactivated row
        # refuses, with the reason the command itself would give.
        deactivatable = bool(row["is_active"])
        overrides.append(
            {
                "id": str(cast(UUID, row["id"])),
                "rule_domain": str(row["rule_domain"]),
                "allow": bool(row["allow"]),
                "scope": kind,
                "subject_id": str(subject_id),
                "subject_label": label,
                "cycle_id": (
                    str(cast(UUID, row["scope_cycle_id"]))
                    if row["scope_cycle_id"] is not None
                    else None
                ),
                "cycle_name": (
                    str(row["cycle_name"]) if row["cycle_name"] is not None else None
                ),
                "reason": str(row["reason"]),
                "granted_by": {
                    "id": str(cast(UUID, row["granted_by"])),
                    "name": str(row["granted_by_name"]),
                },
                "created_at": _iso(cast("datetime | None", row["created_at"])),
                "expires_at": _iso(cast("datetime | None", row["expires_at"])),
                "state": row_state,
                "is_active": bool(row["is_active"]),
                "actions": {
                    "deactivate": {
                        "allowed": deactivatable,
                        "reason": None if deactivatable else OVERRIDE_ALREADY_INACTIVE,
                        "human": (
                            None
                            if deactivatable
                            else "This override has already been deactivated"
                        ),
                    }
                },
            }
        )

    return {
        "overrides": overrides,
        "filters": {
            "rule_domain": rule_domain,
            "scope": scope,
            "cycle_id": str(cycle_id) if cycle_id is not None else None,
            "state": state,
        },
        "rule_domains": [domain.value for domain in RuleDomain],
        "scopes": [scope_name(item) for item in OVERRIDE_SCOPE_COMBINATIONS],
        "states": list(STATES),
        "cycles": [
            {
                "id": str(cast(UUID, row["id"])),
                "name": str(row["name"]),
                "kind": str(row["kind"]),
                "archived": bool(row["archived"]),
            }
            for row in cycles
        ],
        "counts": {
            item: sum(1 for row in overrides if row["state"] == item) for item in STATES
        },
    }
