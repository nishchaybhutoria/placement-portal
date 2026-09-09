"""The staff drill-down on one enrollment (LLD section 11.3, Behavior INT-1).

This is the screen staff open during a dispute, which sets every requirement it
has.  A dispute is a question about *what happened and who did it*, so the
timeline is the centre of the page: every application event in order, each row
carrying its actor and its reason, and each application's events kept together
under it.  Anything the record holds that the timeline cannot explain by itself
is shown beside it -- memberships with who decided them, offers portal and
external, discipline, and the profile the application was actually judged on.

Three things here are not obvious and are each a ruling:

* **A strike's revoker lives only in ``audit_log``.** ``strikes`` carries
  ``is_active`` and nothing else, so the design review section 4.25 sends this screen to
  the audit trail for who revoked it and when.  Penalties answer from their own
  columns; the asymmetry is deliberate and visible in the payload.
* **The audit trail is part of the record, not a footnote.** An off-campus offer
  for a student who never applied through the portal writes no application
  event at all (section 4.26), so it would be invisible on the one page staff
  use to inspect a student -- unless the enrollment's audit rows are read here.
* **A coordinator sees the whole record or none of it.** The drill-down spans
  cycles by construction: a placement dispute usually turns on what happened in
  a different cycle.  Access is gated on the coordinator sharing a cycle with
  the student; the *controls* stay cycle-scoped, each row saying why it is
  disabled.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.errors import (
    DUPLICATE_APPLICATION,
    INVALID_TRANSITION,
    JOB_CANCELLED,
    MEMBERSHIP_NOT_ACTIVE,
    AuthorizationDenied,
)
from app.core.plan import ActorContext, ScopeIds
from app.domain.shared import (
    ApplicationStatus,
    MembershipStatus,
    RuleDomain,
    domains_for_scope,
)
from app.modules.cycles.queries import membership_exit_permissions, outcome_tag_permission
from app.modules.interventions.commands import REINSTATABLE
from app.modules.overrides.service import (
    ClassifiedOverride,
    classified_by_scope,
    classified_many,
)
from app.modules.profiles.fields import ADMIN_FIELDS, FIELDS, jsonable
from app.modules.profiles.queries import taxonomy_options

_ENROLLMENTS = """
    SELECT e.id, e.roll_number, e.is_current, e.created_at,
           u.id AS user_id, u.full_name, u.email, u.role, u.is_active
    FROM enrollments e
    JOIN users u ON u.id = e.user_id
    WHERE u.id = (SELECT user_id FROM enrollments WHERE id = :enrollment_id)
    ORDER BY e.is_current DESC, e.created_at DESC
"""

_MEMBERSHIPS = """
    SELECT m.id, m.status, m.consented_at, m.decided_at, m.rejection_reason,
           m.outcome_tag, m.auto_created, m.created_at,
           d.full_name AS decided_by_name,
           c.id AS cycle_id, c.name AS cycle_name, c.kind AS cycle_kind,
           c.archived_at
    FROM cycle_memberships m
    JOIN cycles c ON c.id = m.cycle_id
    LEFT JOIN users d ON d.id = m.decided_by
    WHERE m.enrollment_id = :enrollment_id
    ORDER BY c.name
"""

_APPLICATIONS = """
    SELECT a.id, a.status, a.current_round_id, a.resume_url, a.applied_at,
           a.profile_snapshot, a.job_id,
           j.title AS job_title, j.cancelled_at, j.outcome,
           co.name AS company_name,
           c.id AS cycle_id, c.name AS cycle_name, c.kind AS cycle_kind,
           c.archived_at,
           r.name AS current_round_name, r.ord AS current_round_ord,
           m.status AS membership_status,
           (SELECT count(*) FROM applications d
             WHERE d.job_id = a.job_id AND d.enrollment_id = a.enrollment_id
               AND d.id <> a.id
               AND d.status NOT IN ('withdrawn', 'auto_withdrawn')) AS active_duplicates
    FROM applications a
    JOIN jobs j ON j.id = a.job_id
    JOIN companies co ON co.id = j.company_id
    JOIN cycles c ON c.id = j.cycle_id
    LEFT JOIN job_rounds r ON r.id = a.current_round_id
    LEFT JOIN cycle_memberships m
        ON m.cycle_id = j.cycle_id AND m.enrollment_id = a.enrollment_id
    WHERE a.enrollment_id = :enrollment_id
    ORDER BY a.applied_at DESC, a.id
"""

_ROUNDS = """
    SELECT r.id, r.job_id, r.name, r.ord
    FROM job_rounds r
    WHERE r.job_id = ANY(:job_ids)
    ORDER BY r.job_id, r.ord
"""

_EVENTS = """
    SELECT e.id, e.application_id, e.event_type, e.from_status, e.to_status,
           e.from_round_id, e.to_round_id, e.reason, e.payload, e.created_at,
           u.full_name AS actor_name, u.role AS actor_role,
           fr.name AS from_round_name, tr.name AS to_round_name
    FROM application_events e
    LEFT JOIN users u ON u.id = e.actor_user_id
    LEFT JOIN job_rounds fr ON fr.id = e.from_round_id
    LEFT JOIN job_rounds tr ON tr.id = e.to_round_id
    WHERE e.application_id = ANY(:application_ids)
    ORDER BY e.event_seq
"""

_ROUND_STATES = """
    SELECT s.application_id, s.round_id, s.result, s.attendance,
           s.venue_override, s.scheduled_at_override, r.name, r.ord
    FROM application_round_states s
    JOIN job_rounds r ON r.id = s.round_id
    WHERE s.application_id = ANY(:application_ids)
    ORDER BY r.ord
"""

_OFFERS = """
    SELECT o.id, o.application_id, o.extended_at, o.deadline_at, o.response,
           o.responded_at, o.terminated_at, o.termination_kind,
           o.termination_reason, t.full_name AS terminated_by_name,
           j.title AS job_title, j.outcome, co.name AS company_name,
           c.id AS cycle_id, c.name AS cycle_name
    FROM offers o
    JOIN applications a ON a.id = o.application_id
    JOIN jobs j ON j.id = a.job_id
    JOIN companies co ON co.id = j.company_id
    JOIN cycles c ON c.id = j.cycle_id
    LEFT JOIN users t ON t.id = o.terminated_by
    WHERE a.enrollment_id = :enrollment_id
    ORDER BY o.extended_at DESC, o.id
"""

_EXTERNAL = """
    SELECT x.id, x.outcome, x.source, x.status, x.ctc_lpa, x.stipend_month,
           x.offered_on, x.responded_on, x.notes, x.created_at,
           x.source_application_id, x.attached_cycle_id,
           co.name AS company_name, c.name AS cycle_name,
           u.full_name AS created_by_name
    FROM external_offers x
    JOIN companies co ON co.id = x.company_id
    LEFT JOIN cycles c ON c.id = x.attached_cycle_id
    LEFT JOIN users u ON u.id = x.created_by
    WHERE x.enrollment_id = :enrollment_id
    ORDER BY x.created_at DESC, x.id
"""

_STRIKES = """
    SELECT s.id, s.reason, s.source, s.is_active, s.consumed_by_penalty_id,
           s.created_at, s.updated_at, a.full_name AS awarded_by_name
    FROM strikes s
    LEFT JOIN users a ON a.id = s.awarded_by
    WHERE s.enrollment_id = :enrollment_id
    ORDER BY s.created_at, s.id
"""

_PENALTIES = """
    SELECT p.id, p.reasons, p.from_strikes, p.is_active, p.created_at,
           p.revoked_at, c.full_name AS created_by_name, r.full_name AS revoked_by_name
    FROM penalties p
    LEFT JOIN users c ON c.id = p.created_by
    LEFT JOIN users r ON r.id = p.revoked_by
    WHERE p.enrollment_id = :enrollment_id
    ORDER BY p.created_at, p.id
"""

#: Every audit row about this enrollment or about a row that belongs to it.
#: Strike revocations are read from here because the strike row cannot answer
#: who revoked it (the design review section 4.25).
_AUDIT = """
    SELECT l.id, l.action, l.subject_type, l.subject_id, l.details, l.created_at,
           u.full_name AS actor_name, u.role AS actor_role
    FROM audit_log l
    LEFT JOIN users u ON u.id = l.actor_user_id
    WHERE l.subject_id = ANY(:subject_ids)
    -- Append order, not wall clock: two rows written in one transaction share
    -- now(), and the old `l.id` tie-break was a random UUID (the design review 4.48).
    ORDER BY l.audit_seq DESC
"""

_LIVE_PROFILE = """
    SELECT p.*, e.roll_number, u.full_name
    FROM enrollments e
    JOIN users u ON u.id = e.user_id
    LEFT JOIN profiles p ON p.enrollment_id = e.id
    WHERE e.id = :enrollment_id
"""

_OVERRIDE_TARGET_CYCLES = """
    SELECT c.id, c.name, c.kind
    FROM cycles c
    WHERE c.archived_at IS NULL
      AND (CAST(:visible_cycle_ids AS uuid[]) IS NULL
           OR c.id = ANY(CAST(:visible_cycle_ids AS uuid[])))
    ORDER BY c.name, c.id
"""

_OVERRIDE_TARGET_JOBS = """
    SELECT j.id, j.title, co.name AS company_name,
           c.id AS cycle_id, c.name AS cycle_name
    FROM jobs j
    JOIN companies co ON co.id = j.company_id
    JOIN cycles c ON c.id = j.cycle_id
    WHERE c.archived_at IS NULL
      AND (CAST(:visible_cycle_ids AS uuid[]) IS NULL
           OR c.id = ANY(CAST(:visible_cycle_ids AS uuid[])))
    ORDER BY c.name, co.name, j.title, j.id
"""

_COORDINATED = """
    SELECT 1 FROM cycle_memberships m
    WHERE m.enrollment_id = :enrollment_id AND m.cycle_id = ANY(:cycle_ids)
    UNION ALL
    SELECT 1 FROM applications a JOIN jobs j ON j.id = a.job_id
    WHERE a.enrollment_id = :enrollment_id AND j.cycle_id = ANY(:cycle_ids)
    LIMIT 1
"""

STRIKE_REVOCATION_ACTION = "revoke_strike"

#: The overrides an event's payload stamped itself with, resolved on read.
#:
#: INT-2 requires every influenced decision to record *which* overrides let it
#: through, and the event keeps ids because that is what an append-only row
#: must keep -- a reason can be re-worded and a grant deactivated, and the
#: event still has to point at the same grant.  What a reader needs is the
#: opposite: "why was this person allowed in" is answered by the domain, the
#: granter, the date and the reason, never by `8f2c1a55-...-a91e`.  So the ids
#: stay stored and the prose is resolved here, on read, the way
#: `admin/findings` resolves its subject labels.
_PAYLOAD_OVERRIDES = """
    SELECT o.id, o.rule_domain, o.allow, o.reason, o.created_at,
           g.full_name AS granted_by_name
    FROM overrides o
    JOIN users g ON g.id = o.granted_by
    WHERE o.id = ANY(:ids)
"""


def _iso(value: object) -> str | None:
    return cast(datetime, value).isoformat() if value is not None else None


def _uuid_array(name: str) -> sa.BindParameter[Sequence[UUID]]:
    return sa.bindparam(name, type_=ARRAY(sa.Uuid()))


def _permission(
    allowed: bool, reason: str | None = None, human: str | None = None
) -> dict[str, object]:
    return {"allowed": allowed, "reason": reason, "human": human}


def _classified_override(
    row: ClassifiedOverride, *, subject_label: str | None = None
) -> dict[str, object]:
    return {
        "id": str(row.id),
        "rule_domain": row.rule_domain.value,
        "allow": row.allow,
        "scope": row.specificity,
        "state": row.state,
        "reason": row.reason,
        "expires_at": _iso(row.expires_at),
        "subject_label": subject_label,
    }


def _payload_override_ids(payload: object) -> list[str]:
    """The `applied_override_ids` an event payload carries, in order."""
    if not isinstance(payload, dict):
        return []
    raw = payload.get("applied_override_ids")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, str)]


async def _override_labels(
    connection: AsyncConnection, events: Sequence[sa.RowMapping]
) -> dict[str, dict[str, object]]:
    """Resolve every override id the given events stamped, in one query."""
    wanted = {
        value
        for row in events
        for value in _payload_override_ids(row["payload"])
    }
    if not wanted:
        return {}
    ids: list[UUID] = []
    for value in wanted:
        try:
            ids.append(UUID(value))
        except ValueError:
            # A payload id that is not a UUID cannot be resolved and is not
            # dropped either: it falls through to the unresolved shape below.
            continue
    rows = (
        (
            await connection.execute(
                sa.text(_PAYLOAD_OVERRIDES).bindparams(_uuid_array("ids")),
                {"ids": ids},
            )
        )
        .mappings()
        .all()
        if ids
        else []
    )
    found = {
        str(cast(UUID, row["id"])): {
            "id": str(cast(UUID, row["id"])),
            "rule_domain": str(row["rule_domain"]),
            "allow": bool(row["allow"]),
            "reason": str(row["reason"]),
            "granted_by": row["granted_by_name"],
            "granted_at": _iso(row["created_at"]),
        }
        for row in rows
    }
    # An id with no row behind it keeps its place with every field null, so the
    # screen says the grant is gone rather than printing the identifier it
    # could not resolve -- the whole point of this pass.
    return {
        value: found.get(
            value,
            {
                "id": value,
                "rule_domain": None,
                "allow": None,
                "reason": None,
                "granted_by": None,
                "granted_at": None,
            },
        )
        for value in wanted
    }


async def _may_view(
    connection: AsyncConnection, actor: ActorContext, enrollment_id: UUID
) -> bool:
    if actor.role == "admin":
        return True
    if not actor.coordinated_cycle_ids:
        return False
    found = await connection.scalar(
        sa.text(_COORDINATED).bindparams(_uuid_array("cycle_ids")),
        {
            "enrollment_id": enrollment_id,
            "cycle_ids": list(actor.coordinated_cycle_ids),
        },
    )
    return found is not None


def _snapshot_diff(
    snapshot: dict[str, object], live: dict[str, object]
) -> list[dict[str, object]]:
    """Field-by-field, what the application was judged on versus what is true now."""
    rows: list[dict[str, object]] = []
    for field in FIELDS:
        was = snapshot.get(field.key)
        now = live.get(field.key)
        in_snapshot = field.key in snapshot
        rows.append(
            {
                "key": field.key,
                "label": field.label,
                "owner": field.owner.value,
                "snapshot": was,
                "live": now,
                # "absent" is its own answer: the field was not part of the
                # profile when the application was filed, which is not the same
                # as having been empty.
                "state": (
                    "absent"
                    if not in_snapshot
                    else "unchanged"
                    if was == now
                    else "changed"
                ),
            }
        )
    return rows


def _reinstate_permission(
    row: sa.RowMapping, actor: ActorContext
) -> dict[str, object]:
    cycle_id = cast(UUID, row["cycle_id"])
    if actor.role != "admin" and cycle_id not in actor.coordinated_cycle_ids:
        return _permission(
            False,
            "out_of_scope",
            "You do not coordinate the cycle this application belongs to",
        )
    if row["archived_at"] is not None:
        return _permission(
            False, "cycle_archived", "The cycle is archived and is now read-only"
        )
    status = ApplicationStatus(row["status"])
    if status not in REINSTATABLE:
        return _permission(
            False,
            INVALID_TRANSITION,
            f"An application that is {status.value.replace('_', ' ')} cannot be reinstated",
        )
    if int(row["active_duplicates"]) > 0:
        return _permission(
            False,
            DUPLICATE_APPLICATION,
            "This student already has another active application to this job. "
            "Resolve that one first.",
        )
    membership = row["membership_status"]
    if membership is None or MembershipStatus(membership) is not MembershipStatus.ACTIVE:
        return _permission(
            False,
            MEMBERSHIP_NOT_ACTIVE,
            "This student's membership in the cycle is not active, so the "
            "application cannot be live. Restore the membership first.",
        )
    if row["cancelled_at"] is not None:
        return _permission(
            False,
            JOB_CANCELLED,
            "This job has been cancelled, so nothing can return to its pipeline",
        )
    return _permission(True)


def _force_permission(row: sa.RowMapping, actor: ActorContext) -> dict[str, object]:
    cycle_id = cast(UUID, row["cycle_id"])
    if actor.role != "admin" and cycle_id not in actor.coordinated_cycle_ids:
        return _permission(
            False,
            "out_of_scope",
            "You do not coordinate the cycle this application belongs to",
        )
    if row["archived_at"] is not None:
        return _permission(
            False, "cycle_archived", "The cycle is archived and is now read-only"
        )
    return _permission(True)


async def staff_student_record(
    engine: AsyncEngine, actor: ActorContext, enrollment_id: UUID
) -> dict[str, object]:
    """One enrollment's complete record, as staff read it during a dispute."""
    async with engine.connect() as connection:
        if not await _may_view(connection, actor, enrollment_id):
            raise AuthorizationDenied(authenticated=actor.user_id is not None)

        enrollments = (
            await connection.execute(
                sa.text(_ENROLLMENTS), {"enrollment_id": enrollment_id}
            )
        ).mappings().all()
        if not enrollments:
            return {
                "enrollment": None,
                "enrollments": [],
                "memberships": [],
                "applications": [],
                "offers": [],
                "external_offers": [],
                "discipline": {"strikes": [], "penalties": []},
                "audit": [],
                "timeline": [],
                "override_domains": [],
                "overrides": [],
                "override_targets": {
                    "cycle_domains": [],
                    "job_domains": [],
                    "cycles": [],
                    "jobs": [],
                },
                "actions": {
                    "edit_profile": _edit_profile_permission(actor),
                    "grant_enrollment_override": _grant_enrollment_override_permission(
                        actor
                    ),
                },
            }

        memberships = (
            await connection.execute(
                sa.text(_MEMBERSHIPS), {"enrollment_id": enrollment_id}
            )
        ).mappings().all()
        applications = (
            await connection.execute(
                sa.text(_APPLICATIONS), {"enrollment_id": enrollment_id}
            )
        ).mappings().all()
        application_ids = [cast(UUID, row["id"]) for row in applications]
        job_ids = sorted({cast(UUID, row["job_id"]) for row in applications})
        events = (
            await connection.execute(
                sa.text(_EVENTS).bindparams(_uuid_array("application_ids")),
                {"application_ids": application_ids},
            )
        ).mappings().all()
        override_labels = await _override_labels(connection, events)
        round_states = (
            await connection.execute(
                sa.text(_ROUND_STATES).bindparams(_uuid_array("application_ids")),
                {"application_ids": application_ids},
            )
        ).mappings().all()
        rounds = (
            await connection.execute(
                sa.text(_ROUNDS).bindparams(_uuid_array("job_ids")),
                {"job_ids": job_ids},
            )
        ).mappings().all()
        offers = (
            await connection.execute(
                sa.text(_OFFERS), {"enrollment_id": enrollment_id}
            )
        ).mappings().all()
        external = (
            await connection.execute(
                sa.text(_EXTERNAL), {"enrollment_id": enrollment_id}
            )
        ).mappings().all()
        strikes = (
            await connection.execute(
                sa.text(_STRIKES), {"enrollment_id": enrollment_id}
            )
        ).mappings().all()
        penalties = (
            await connection.execute(
                sa.text(_PENALTIES), {"enrollment_id": enrollment_id}
            )
        ).mappings().all()
        subject_ids = [
            enrollment_id,
            *application_ids,
            *[cast(UUID, row["id"]) for row in offers],
            *[cast(UUID, row["id"]) for row in external],
            *[cast(UUID, row["id"]) for row in strikes],
            *[cast(UUID, row["id"]) for row in penalties],
            *[cast(UUID, row["id"]) for row in memberships],
        ]
        audit = (
            await connection.execute(
                sa.text(_AUDIT).bindparams(_uuid_array("subject_ids")),
                {"subject_ids": subject_ids},
            )
        ).mappings().all()
        live_row = (
            await connection.execute(
                sa.text(_LIVE_PROFILE), {"enrollment_id": enrollment_id}
            )
        ).mappings().one_or_none()
        taxonomies, program_branches = await taxonomy_options(connection)
        visible_cycle_ids = (
            None
            if actor.role == "admin"
            else list(actor.coordinated_cycle_ids)
        )
        override_cycles = (
            await connection.execute(
                sa.text(_OVERRIDE_TARGET_CYCLES),
                {"visible_cycle_ids": visible_cycle_ids},
            )
        ).mappings().all()
        override_jobs = (
            await connection.execute(
                sa.text(_OVERRIDE_TARGET_JOBS),
                {"visible_cycle_ids": visible_cycle_ids},
            )
        ).mappings().all()
        application_scopes = {
            cast(UUID, row["id"]): ScopeIds(
                cycle_id=cast(UUID, row["cycle_id"]),
                job_id=cast(UUID, row["job_id"]),
                enrollment_id=enrollment_id,
                application_id=cast(UUID, row["id"]),
            )
            for row in applications
        }
        application_override_rows = await classified_by_scope(
            connection,
            domains_for_scope("application"),
            application_scopes,
        )
        student_scopes = (
            ScopeIds(enrollment_id=enrollment_id),
            *(
                ScopeIds(
                    cycle_id=cast(UUID, row["id"]),
                    enrollment_id=enrollment_id,
                )
                for row in override_cycles
            ),
            *(
                ScopeIds(
                    cycle_id=cast(UUID, row["cycle_id"]),
                    job_id=cast(UUID, row["id"]),
                    enrollment_id=enrollment_id,
                )
                for row in override_jobs
            ),
            *application_scopes.values(),
        )
        student_override_rows = tuple(
            row
            for row in await classified_many(
                connection, tuple(RuleDomain), student_scopes
            )
            if row.enrollment_id == enrollment_id and row.application_id is None
        )

    live: dict[str, object] = {}
    if live_row is not None:
        for field in FIELDS:
            if field.key in live_row:
                live[field.key] = jsonable(live_row[field.key])
    live["full_name"] = str(live_row["full_name"]) if live_row is not None else None
    live["roll_number"] = (
        str(live_row["roll_number"])
        if live_row is not None and live_row["roll_number"] is not None
        else None
    )

    current = next(
        (row for row in enrollments if cast(UUID, row["id"]) == enrollment_id),
        enrollments[0],
    )
    rounds_by_job: dict[UUID, list[dict[str, object]]] = {}
    for row in rounds:
        rounds_by_job.setdefault(cast(UUID, row["job_id"]), []).append(
            {
                "id": str(cast(UUID, row["id"])),
                "name": str(row["name"]),
                "ord": int(row["ord"]),
            }
        )
    events_by_application: dict[UUID, list[dict[str, object]]] = {}
    for row in events:
        events_by_application.setdefault(
            cast(UUID, row["application_id"]), []
        ).append(_event(row, override_labels))
    states_by_application: dict[UUID, list[dict[str, object]]] = {}
    for row in round_states:
        states_by_application.setdefault(
            cast(UUID, row["application_id"]), []
        ).append(
            {
                "round_id": str(cast(UUID, row["round_id"])),
                "round_name": str(row["name"]),
                "ord": int(row["ord"]),
                "result": str(row["result"]),
                "attendance": str(row["attendance"]),
                "venue_override": row["venue_override"],
                "scheduled_at_override": _iso(row["scheduled_at_override"]),
            }
        )
    override_cycle_names = {
        cast(UUID, row["id"]): str(row["name"]) for row in override_cycles
    }
    override_job_names = {
        cast(UUID, row["id"]): (
            f"{row['cycle_name']} — {row['company_name']} — {row['title']}"
        )
        for row in override_jobs
    }

    def override_target_label(row: ClassifiedOverride) -> str | None:
        if row.job_id is not None:
            return override_job_names.get(row.job_id)
        if row.cycle_id is not None:
            return override_cycle_names.get(row.cycle_id)
        return None

    offers_by_application: dict[UUID, list[dict[str, object]]] = {}
    for row in offers:
        offers_by_application.setdefault(
            cast(UUID, row["application_id"]), []
        ).append(_offer(row))

    revocations = {
        cast(UUID, row["subject_id"]): row
        for row in audit
        if str(row["action"]) == STRIKE_REVOCATION_ACTION
        and row["subject_id"] is not None
    }

    application_rows = [
        {
            "id": str(cast(UUID, row["id"])),
            "job_id": str(cast(UUID, row["job_id"])),
            "job_title": str(row["job_title"]),
            "company_name": str(row["company_name"]),
            "outcome": str(row["outcome"]),
            "cycle": {
                "id": str(cast(UUID, row["cycle_id"])),
                "name": str(row["cycle_name"]),
                "kind": str(row["cycle_kind"]),
                "archived": row["archived_at"] is not None,
            },
            "status": str(row["status"]),
            "applied_at": _iso(row["applied_at"]),
            "resume_url": str(row["resume_url"]),
            "current_round": (
                {
                    "id": str(cast(UUID, row["current_round_id"])),
                    "name": str(row["current_round_name"]),
                    "ord": int(row["current_round_ord"]),
                }
                if row["current_round_id"] is not None
                else None
            ),
            "rounds": rounds_by_job.get(cast(UUID, row["job_id"]), []),
            "round_states": states_by_application.get(cast(UUID, row["id"]), []),
            "events": events_by_application.get(cast(UUID, row["id"]), []),
            "offers": offers_by_application.get(cast(UUID, row["id"]), []),
            "snapshot_diff": _snapshot_diff(
                cast("dict[str, object]", row["profile_snapshot"]), live
            ),
            "override_domains": [
                domain.value for domain in domains_for_scope("application")
            ],
            "overrides": [
                _classified_override(item)
                for item in application_override_rows.get(
                    cast(UUID, row["id"]), ()
                )
            ],
            "actions": {
                "reinstate": _reinstate_permission(row, actor),
                "force_transition": _force_permission(row, actor),
                "grant_override": _force_permission(row, actor),
            },
        }
        for row in applications
    ]

    # Preserve the SQL's append order across applications (the design review 4.41).
    # Transaction timestamps may precede a lock wait; re-sorting by time would
    # put a later decision before the one whose lock it waited for.
    timeline = [
        {**_event(row, override_labels), "application_id": str(cast(UUID, row["application_id"]))}
        for row in events
    ]

    return {
        "enrollment": {
            "id": str(enrollment_id),
            "user_id": str(cast(UUID, current["user_id"])),
            "full_name": str(current["full_name"]),
            "email": str(current["email"]),
            "role": str(current["role"]),
            "is_active": bool(current["is_active"]),
            "roll_number": (
                str(current["roll_number"]) if current["roll_number"] else None
            ),
            "is_current": bool(current["is_current"]),
        },
        "enrollments": [
            {
                "id": str(cast(UUID, row["id"])),
                "roll_number": str(row["roll_number"]) if row["roll_number"] else None,
                "is_current": bool(row["is_current"]),
                "created_at": _iso(row["created_at"]),
                "selected": cast(UUID, row["id"]) == enrollment_id,
            }
            for row in enrollments
        ],
        "memberships": [
            {
                "id": str(cast(UUID, row["id"])),
                "cycle": {
                    "id": str(cast(UUID, row["cycle_id"])),
                    "name": str(row["cycle_name"]),
                    "kind": str(row["cycle_kind"]),
                    "archived": row["archived_at"] is not None,
                },
                "status": str(row["status"]),
                "consented_at": _iso(row["consented_at"]),
                "decided_at": _iso(row["decided_at"]),
                "decided_by": row["decided_by_name"],
                "rejection_reason": row["rejection_reason"],
                "outcome_tag": row["outcome_tag"],
                "auto_created": bool(row["auto_created"]),
                "actions": {
                    "set_outcome_tag": outcome_tag_permission(
                        actor,
                        cycle_id=cast(UUID, row["cycle_id"]),
                        archived=row["archived_at"] is not None,
                    ),
                    **membership_exit_permissions(
                        actor,
                        cycle_id=cast(UUID, row["cycle_id"]),
                        archived=row["archived_at"] is not None,
                        status=MembershipStatus(row["status"]),
                    ),
                },
            }
            for row in memberships
        ],
        "applications": application_rows,
        "offers": [_offer(row) for row in offers],
        "external_offers": [
            {
                "id": str(cast(UUID, row["id"])),
                "company_name": str(row["company_name"]),
                "outcome": str(row["outcome"]),
                "source": str(row["source"]),
                "status": str(row["status"]),
                "ctc_lpa": jsonable(row["ctc_lpa"]),
                "stipend_month": jsonable(row["stipend_month"]),
                "offered_on": _date(row["offered_on"]),
                "responded_on": _date(row["responded_on"]),
                "attached_cycle_id": (
                    str(cast(UUID, row["attached_cycle_id"]))
                    if row["attached_cycle_id"] is not None
                    else None
                ),
                "attached_cycle_name": row["cycle_name"],
                "source_application_id": (
                    str(cast(UUID, row["source_application_id"]))
                    if row["source_application_id"] is not None
                    else None
                ),
                "notes": row["notes"],
                "created_by": row["created_by_name"],
                "created_at": _iso(row["created_at"]),
            }
            for row in external
        ],
        "discipline": {
            "strikes": [
                {
                    "id": str(cast(UUID, row["id"])),
                    "reason": str(row["reason"]),
                    "source": str(row["source"]),
                    "is_active": bool(row["is_active"]),
                    "awarded_by": row["awarded_by_name"],
                    "created_at": _iso(row["created_at"]),
                    "consumed_by_penalty_id": (
                        str(cast(UUID, row["consumed_by_penalty_id"]))
                        if row["consumed_by_penalty_id"] is not None
                        else None
                    ),
                    # The strike row cannot answer this; the audit trail can.
                    "revocation": _revocation(revocations.get(cast(UUID, row["id"]))),
                }
                for row in strikes
            ],
            "penalties": [
                {
                    "id": str(cast(UUID, row["id"])),
                    "reasons": str(row["reasons"]),
                    "from_strikes": bool(row["from_strikes"]),
                    "is_active": bool(row["is_active"]),
                    "created_by": row["created_by_name"],
                    "created_at": _iso(row["created_at"]),
                    "revoked_at": _iso(row["revoked_at"]),
                    "revoked_by": row["revoked_by_name"],
                }
                for row in penalties
            ],
            "revoker_source": {
                "strikes": "audit_log",
                "penalties": "penalties.revoked_by",
            },
        },
        "audit": [
            {
                "id": str(cast(UUID, row["id"])),
                "action": str(row["action"]),
                "subject_type": row["subject_type"],
                "subject_id": (
                    str(cast(UUID, row["subject_id"]))
                    if row["subject_id"] is not None
                    else None
                ),
                "actor": row["actor_name"],
                "actor_role": row["actor_role"],
                "details": row["details"],
                "created_at": _iso(row["created_at"]),
            }
            for row in audit
        ],
        "timeline": timeline,
        "profile": {
            "fields": [
                {
                    "key": field.key,
                    "label": field.label,
                    "owner": field.owner.value,
                    # INT-1 gives administration the locked fields and nobody
                    # else: what a coordinator may read here, only an admin may
                    # correct.  The flag is the server's, so the dialog renders
                    # a verdict rather than re-deriving one from `owner`.
                    "admin_editable": field.key in ADMIN_FIELDS,
                }
                for field in FIELDS
            ],
            "live": live,
            "taxonomies": taxonomies,
            "program_branches": program_branches,
        },
        "override_domains": [
            domain.value for domain in domains_for_scope("enrollment")
        ],
        "overrides": [
            _classified_override(
                item, subject_label=override_target_label(item)
            )
            for item in student_override_rows
        ],
        "override_targets": {
            "cycle_domains": [
                domain.value
                for domain in domains_for_scope("cycle", "enrollment")
            ],
            "job_domains": [
                domain.value
                for domain in domains_for_scope("job", "enrollment")
            ],
            "cycles": [
                {
                    "id": str(cast(UUID, row["id"])),
                    "name": str(row["name"]),
                    "kind": str(row["kind"]),
                }
                for row in override_cycles
            ],
            "jobs": [
                {
                    "id": str(cast(UUID, row["id"])),
                    "title": str(row["title"]),
                    "company_name": str(row["company_name"]),
                    "cycle": {
                        "id": str(cast(UUID, row["cycle_id"])),
                        "name": str(row["cycle_name"]),
                    },
                }
                for row in override_jobs
            ],
        },
        "actions": {
            "edit_profile": _edit_profile_permission(actor),
            "grant_enrollment_override": _grant_enrollment_override_permission(actor),
        },
    }


def _grant_enrollment_override_permission(
    actor: ActorContext,
) -> dict[str, object]:
    """INT-2: a cross-cycle enrollment grant is administrator-only.

    The target carries no cycle into the executor's scope check, so a
    coordinator cannot own it merely because they share one cycle with the
    student whose full record they may read.
    """
    allowed = actor.role == "admin"
    return _permission(
        allowed,
        None,
        None
        if allowed
        else (
            "An enrollment override applies in every cycle, so only an "
            "administrator may grant one"
        ),
    )


def _edit_profile_permission(actor: ActorContext) -> dict[str, object]:
    """INT-1: correcting a locked profile field is an administrator's power.

    ``admin_update_profile`` is registered ``actor="admin"``, so a coordinator
    who can read this record cannot write to it.  Stating that here is what
    keeps the button and the command from disagreeing (the design review section 4.22).
    """
    allowed = actor.role == "admin"
    return _permission(
        allowed,
        None,
        None if allowed else "Only an administrator can correct a locked profile field",
    )


def _event(
    row: sa.RowMapping, overrides: dict[str, dict[str, object]]
) -> dict[str, object]:
    """One timeline row: what happened, who did it, and why."""
    applied = [
        overrides[value]
        for value in _payload_override_ids(row["payload"])
        if value in overrides
    ]
    return {
        "id": str(cast(UUID, row["id"])),
        "event_type": str(row["event_type"]),
        "from_status": row["from_status"],
        "to_status": row["to_status"],
        "from_round": row["from_round_name"],
        "to_round": row["to_round_name"],
        # Null actor means the system did it -- an expiry, a cascade, an
        # archival -- and the screen says so rather than showing a blank.
        "actor": row["actor_name"],
        "actor_role": row["actor_role"],
        "reason": row["reason"],
        "payload": row["payload"],
        # Parallel to `payload` rather than replacing it, exactly as
        # `subject_labels` sits beside a finding's `subject`: the ids stay
        # authoritative and the prose is what the screen reads out.
        "payload_labels": {"applied_override_ids": applied},
        "created_at": _iso(row["created_at"]),
    }


def _offer(row: sa.RowMapping) -> dict[str, object]:
    return {
        "id": str(cast(UUID, row["id"])),
        "application_id": str(cast(UUID, row["application_id"])),
        "job_title": str(row["job_title"]),
        "company_name": str(row["company_name"]),
        "outcome": str(row["outcome"]),
        "cycle_id": str(cast(UUID, row["cycle_id"])),
        "cycle_name": str(row["cycle_name"]),
        "extended_at": _iso(row["extended_at"]),
        "deadline_at": _iso(row["deadline_at"]),
        "response": row["response"],
        "responded_at": _iso(row["responded_at"]),
        "terminated_at": _iso(row["terminated_at"]),
        "termination_kind": row["termination_kind"],
        "termination_reason": row["termination_reason"],
        "terminated_by": row["terminated_by_name"],
    }


def _revocation(row: sa.RowMapping | None) -> dict[str, object] | None:
    if row is None:
        return None
    details = cast("dict[str, object]", row["details"] or {})
    return {
        "actor": row["actor_name"],
        "at": _iso(row["created_at"]),
        "reason": details.get("reason"),
        "source": "audit_log",
    }


def _date(value: object) -> str | None:
    return value.isoformat() if value is not None else None  # type: ignore[union-attr]
