"""The findings surface the consistency checker feeds (LLD sections 11.3, 12).

A finding is only useful if an administrator can act on it, so each row carries
the command that compensates for it *and* the input that command needs, both
built by ``checker.FIX_CATALOG`` -- the same entry the checker wrote the
suggestion from.  The screen never assembles a payload of its own: if the
button and the finding could disagree, the button would eventually send a
request nobody had ever tried.

Where a fix cannot be prefilled the row says so rather than offering a button
that would be refused: an ``update_job_basics`` repair needs a deadline only the
office can choose, and PRO-3's resume commands belong to the student.
"""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.errors import FINDING_NOT_OPEN
from app.domain.shared import FindingStatus
from app.modules.admin.checker import INVARIANTS, describe, fix_payload

_FINDINGS = """
    SELECT id, invariant, subject, detail, status, suggested_fix,
           created_at, updated_at, resolved_at
    FROM consistency_findings
    WHERE (CAST(:status AS text) IS NULL OR status::text = CAST(:status AS text))
      AND (CAST(:invariant AS text) IS NULL OR invariant = CAST(:invariant AS text))
    ORDER BY (status = 'open') DESC, created_at DESC, id
"""

_COUNTS = """
    SELECT status::text AS status, count(*) AS total
    FROM consistency_findings GROUP BY status
"""


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


#: One SELECT per subject id a finding can carry, returning `id` and `label`.
#:
#: A finding names its subject with the ids the invariant's SQL selected,
#: because that is what the append-only row must keep -- a name can be edited
#: or merged away, and a finding raised last month has to still point at the
#: same object.  What the *screen* needs is the opposite: an administrator
#: deciding whether to resolve a finding cannot recognise
#: `8f2c1a55-…-a91e`.  So the ids stay stored and the labels are resolved on
#: read, here, where a rename is picked up rather than frozen.
_SUBJECT_LABELS: dict[str, str] = {
    "application_id": (
        "SELECT a.id, u.full_name || ' — ' || j.title AS label FROM applications a "
        "JOIN enrollments e ON e.id = a.enrollment_id "
        "JOIN users u ON u.id = e.user_id "
        "JOIN jobs j ON j.id = a.job_id WHERE a.id = ANY(:ids)"
    ),
    "duplicate_application_id": (
        "SELECT a.id, u.full_name || ' — ' || j.title AS label FROM applications a "
        "JOIN enrollments e ON e.id = a.enrollment_id "
        "JOIN users u ON u.id = e.user_id "
        "JOIN jobs j ON j.id = a.job_id WHERE a.id = ANY(:ids)"
    ),
    "job_id": (
        "SELECT j.id, j.title || ' · ' || c.name AS label FROM jobs j "
        "JOIN companies c ON c.id = j.company_id WHERE j.id = ANY(:ids)"
    ),
    "cycle_id": "SELECT id, name AS label FROM cycles WHERE id = ANY(:ids)",
    "company_id": "SELECT id, name AS label FROM companies WHERE id = ANY(:ids)",
    "contact_id": (
        "SELECT id, name || ' (' || email || ')' AS label FROM company_contacts "
        "WHERE id = ANY(:ids)"
    ),
    "user_id": (
        "SELECT id, full_name || ' (' || email || ')' AS label FROM users "
        "WHERE id = ANY(:ids)"
    ),
    "enrollment_id": (
        "SELECT e.id, u.full_name || coalesce(' (' || e.roll_number || ')', '') AS label "
        "FROM enrollments e JOIN users u ON u.id = e.user_id WHERE e.id = ANY(:ids)"
    ),
    "membership_id": (
        "SELECT m.id, u.full_name || ' — ' || c.name AS label FROM cycle_memberships m "
        "JOIN enrollments e ON e.id = m.enrollment_id "
        "JOIN users u ON u.id = e.user_id "
        "JOIN cycles c ON c.id = m.cycle_id WHERE m.id = ANY(:ids)"
    ),
    "offer_id": (
        "SELECT o.id, u.full_name || ' — ' || j.title AS label FROM offers o "
        "JOIN applications a ON a.id = o.application_id "
        "JOIN enrollments e ON e.id = a.enrollment_id "
        "JOIN users u ON u.id = e.user_id "
        "JOIN jobs j ON j.id = a.job_id WHERE o.id = ANY(:ids)"
    ),
    "external_offer_id": (
        "SELECT x.id, u.full_name || ' — ' || co.name AS label "
        "FROM external_offers x JOIN enrollments e ON e.id = x.enrollment_id "
        "JOIN users u ON u.id = e.user_id "
        "JOIN companies co ON co.id = x.company_id WHERE x.id = ANY(:ids)"
    ),
    "current_round_id": "SELECT id, name AS label FROM job_rounds WHERE id = ANY(:ids)",
    "resume_id": "SELECT id, label FROM resumes WHERE id = ANY(:ids)",
    "penalty_id": (
        "SELECT p.id, u.full_name AS label FROM penalties p "
        "JOIN enrollments e ON e.id = p.enrollment_id "
        "JOIN users u ON u.id = e.user_id WHERE p.id = ANY(:ids)"
    ),
}


async def _subject_labels(
    connection: AsyncConnection, subjects: list[dict[str, object]]
) -> dict[str, dict[str, str]]:
    """Resolve every id the listed subjects mention, one query per kind."""
    labels: dict[str, dict[str, str]] = {}
    for key, statement in _SUBJECT_LABELS.items():
        wanted = {
            str(subject[key]) for subject in subjects if isinstance(subject.get(key), str)
        }
        if not wanted:
            continue
        rows = (
            await connection.execute(
                sa.text(statement).bindparams(
                    sa.bindparam("ids", type_=ARRAY(sa.Uuid()))
                ),
                {"ids": [UUID(value) for value in wanted]},
            )
        ).mappings().all()
        found = {str(row["id"]): str(row["label"]) for row in rows}
        # An id with no row left is a subject that has since been deleted. Say
        # that, rather than leaving the screen to print the id it could not
        # resolve -- the whole point of this pass.
        labels[key] = {
            value: found.get(value, "No longer available") for value in wanted
        }
    return labels


def _verdict_permission(is_open: bool) -> dict[str, object]:
    return {
        "allowed": is_open,
        "reason": None if is_open else FINDING_NOT_OPEN,
        "human": None if is_open else "This finding has already been closed",
    }


async def admin_findings(
    engine: AsyncEngine,
    *,
    status: str | None = None,
    invariant: str | None = None,
) -> dict[str, object]:
    """Every finding, with the compensating command each one suggests."""
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                sa.text(_FINDINGS), {"status": status, "invariant": invariant}
            )
        ).mappings().all()
        counts = (await connection.execute(sa.text(_COUNTS))).mappings().all()
        labels = await _subject_labels(
            connection, [cast("dict[str, object]", row["subject"]) for row in rows]
        )

    findings: list[dict[str, object]] = []
    for row in rows:
        subject = cast("dict[str, object]", row["subject"])
        invariant_id = str(row["invariant"])
        is_open = FindingStatus(row["status"]) is FindingStatus.OPEN
        fix = fix_payload(invariant_id, subject)
        findings.append(
            {
                "id": str(cast(UUID, row["id"])),
                "invariant": invariant_id,
                "description": describe(invariant_id),
                "subject": subject,
                # The same keys, named. Parallel to `subject` rather than
                # replacing it: the id is still what a fix is sent with.
                "subject_labels": {
                    key: labels[key][str(value)]
                    for key, value in subject.items()
                    if key in labels and isinstance(value, str) and str(value) in labels[key]
                },
                "detail": str(row["detail"]),
                "status": str(row["status"]),
                "created_at": _iso(cast("datetime | None", row["created_at"])),
                "resolved_at": _iso(cast("datetime | None", row["resolved_at"])),
                "suggested_fix": (
                    {
                        "command": str(row["suggested_fix"]),
                        # Null when the repair needs a human decision the
                        # subject cannot supply; the screen then names the
                        # command without offering to run it.
                        "input": fix["input"] if fix is not None else None,
                    }
                    if row["suggested_fix"] is not None
                    else None
                ),
                "actions": {
                    "resolve": _verdict_permission(is_open),
                    "dismiss": _verdict_permission(is_open),
                },
            }
        )

    tallies = {str(row["status"]): int(row["total"]) for row in counts}
    return {
        "findings": findings,
        "filters": {"status": status, "invariant": invariant},
        "statuses": [item.value for item in FindingStatus],
        "invariants": [
            {"id": item.id, "description": item.description} for item in INVARIANTS
        ],
        "counts": {
            item.value: tallies.get(item.value, 0) for item in FindingStatus
        },
        # The screen is admin-only and so is the command, so this is constant
        # here -- and stated anyway, because the control reads the server's
        # verdict rather than a rule the client keeps its own copy of
        # (the design review sections 4.22 and 4.36).
        "actions": {"run_checker": {"allowed": True, "reason": None, "human": None}},
    }
