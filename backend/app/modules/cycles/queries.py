"""Read-only screen queries for cycles and memberships (LLD section 11.3)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.errors import CYCLE_ARCHIVED, INVALID_TRANSITION
from app.core.plan import ActorContext, ScopeIds
from app.domain.gates import (
    evaluate_cycle_join_rule,
    evaluate_cycle_registration_window,
)
from app.domain.memberships import (
    check_profile_completeness,
    legal_membership_transitions,
    required_join_fields,
)
from app.domain.policy import resolve_policy
from app.domain.rules import RuleContext, evaluate, taxonomy_ids
from app.domain.shared import CycleKind, MembershipStatus, RuleDomain
from app.domain.transitions import TransitionActor
from app.modules.applications.verdict import gate_overrides
from app.modules.cycles.commands import POLICY_COLUMNS
from app.modules.offers.derivations import placement_placed_global
from app.modules.overrides.service import applicable_many
from app.modules.profiles.fields import PROFILE_COLUMNS
from app.modules.taxonomies.labels import resolve_labels


def outcome_tag_permission(
    actor: ActorContext, *, cycle_id: UUID, archived: bool
) -> dict[str, object]:
    """Whether this actor may tag this membership's ANA-3 outcome.

    ``set_outcome_tag`` is ``actor="staff"``, ``scope="cycle"``, so the two
    answers the executor gives are repeated here and nowhere else: a coordinator
    tags inside their own cycles, an administrator anywhere, and an archived
    season is read-only for every cycle-scoped command (CYC-1).  Both screens
    that render a membership row -- the approvals queue and the staff student
    record -- read this one function, so neither can offer a button the command
    would refuse (the design review section 4.22).
    """
    if archived:
        return {
            "allowed": False,
            "reason": CYCLE_ARCHIVED,
            "human": "The cycle is archived and is now read-only",
        }
    in_scope = actor.role == "admin" or cycle_id in actor.coordinated_cycle_ids
    return {
        "allowed": in_scope,
        "reason": None,
        "human": None if in_scope else "You do not coordinate this cycle",
    }


#: The two staff-side membership exits, by the CYC-3 transition each runs.
MEMBERSHIP_EXIT_COMMANDS = {
    "remove_membership": "remove",
    "restore_membership": "restore",
}


def membership_exit_permissions(
    actor: ActorContext,
    *,
    cycle_id: UUID,
    archived: bool,
    status: MembershipStatus,
) -> dict[str, dict[str, object]]:
    """Whether this actor may remove or restore this membership (CYC-3.7, 3.8).

    Same shape and the same two answers as ``outcome_tag_permission`` -- both
    commands are ``actor="staff"``, ``scope="cycle"`` -- plus the third the
    exits have and the tag does not: the transition table itself, which allows
    ``remove`` only from ``active`` and ``restore`` only from ``withdrawn`` or
    ``removed``. Read here rather than re-derived, so a screen cannot offer a
    control the executor would refuse (the design review section 4.22), and never
    inverted into "hide it": a refused control that says why is how staff learn
    the rule, and a missing one teaches nothing.
    """
    scope = outcome_tag_permission(actor, cycle_id=cycle_id, archived=archived)
    legal = legal_membership_transitions(status, TransitionActor.STAFF)
    permissions: dict[str, dict[str, object]] = {}
    for command, transition in MEMBERSHIP_EXIT_COMMANDS.items():
        if not scope["allowed"]:
            permissions[command] = dict(scope)
            continue
        allowed = transition in legal
        permissions[command] = {
            "allowed": allowed,
            "reason": None if allowed else INVALID_TRANSITION,
            # The rule, not the negation of this row's status: "only an active
            # membership can be removed" tells staff what to do next, where
            # "a pending membership cannot be removed" only says no.
            "human": None if allowed else _EXIT_RULE[command],
        }
    return permissions


_EXIT_RULE = {
    "remove_membership": "Only an active membership can be removed",
    "restore_membership": "Only a withdrawn or removed membership can be restored",
}


_MEMBERSHIP_COUNTS = """
    SELECT status, count(*) AS total
    FROM cycle_memberships
    WHERE cycle_id = :cycle_id
    GROUP BY status
"""

_CYCLE_LIST = """
    SELECT
        c.id, c.name, c.kind, c.description, c.starts_on, c.ends_on,
        c.registration_opens_at, c.registration_closes_at, c.is_active, c.archived_at,
        (
            SELECT count(*) FROM cycle_memberships m
            WHERE m.cycle_id = c.id AND m.status = 'pending'
        ) AS pending_count,
        (
            SELECT count(*) FROM cycle_memberships m
            WHERE m.cycle_id = c.id AND m.status = 'active'
        ) AS active_count,
        (SELECT count(*) FROM jobs j WHERE j.cycle_id = c.id) AS job_count
    FROM cycles c
    WHERE (:include_archived OR c.archived_at IS NULL)
      AND (CAST(:kind AS cycle_kind_t) IS NULL OR c.kind = CAST(:kind AS cycle_kind_t))
      AND (
        CAST(:cycle_ids AS uuid[]) IS NULL
        OR c.id = ANY(CAST(:cycle_ids AS uuid[]))
      )
    ORDER BY c.is_active DESC, c.name, c.id
"""


def _cycle_payload(row: sa.RowMapping) -> dict[str, object]:
    return {
        "id": str(cast(UUID, row["id"])),
        "name": str(row["name"]),
        "kind": str(row["kind"]),
        "description": row["description"],
        "starts_on": row["starts_on"].isoformat() if row["starts_on"] else None,
        "ends_on": row["ends_on"].isoformat() if row["ends_on"] else None,
        "registration_opens_at": (
            row["registration_opens_at"].isoformat()
            if row["registration_opens_at"]
            else None
        ),
        "registration_closes_at": (
            row["registration_closes_at"].isoformat()
            if row["registration_closes_at"]
            else None
        ),
        "is_active": bool(row["is_active"]),
        "archived_at": row["archived_at"].isoformat() if row["archived_at"] else None,
    }


async def staff_cycles(
    engine: AsyncEngine,
    *,
    kind: str | None = None,
    include_archived: bool = False,
    cycle_ids: Sequence[UUID] | None = None,
) -> dict[str, object]:
    """The cycle list with the counts staff triage from.

    ``cycle_ids`` restricts the list to the cycles the caller coordinates.  The
    screen passes it for anyone but an administrator, so the list offers only
    cycles that open when clicked -- ``require_staff_cycle`` guards the detail
    screen, and a row leading to a 403 would be a worse answer than no row.
    """
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                sa.text(_CYCLE_LIST),
                {
                    "include_archived": include_archived,
                    "kind": kind,
                    "cycle_ids": list(cycle_ids) if cycle_ids is not None else None,
                },
            )
        ).mappings().all()
    return {
        "filters": {"kind": kind, "include_archived": include_archived},
        "cycles": [
            _cycle_payload(row)
            | {
                "pending_count": int(row["pending_count"]),
                "active_count": int(row["active_count"]),
                "job_count": int(row["job_count"]),
            }
            for row in rows
        ],
    }


async def staff_cycle(engine: AsyncEngine, cycle_id: UUID) -> dict[str, object] | None:
    """One cycle: its policy with provenance, coordinators, and funnel counts."""
    async with engine.connect() as connection:
        cycle = (
            await connection.execute(
                sa.text(
                    "SELECT id, name, kind, description, starts_on, ends_on, "
                    "registration_opens_at, registration_closes_at, is_active, "
                    "archived_at FROM cycles WHERE id = :id"
                ),
                {"id": cycle_id},
            )
        ).mappings().one_or_none()
        if cycle is None:
            return None
        policy_row = (
            await connection.execute(
                sa.text(
                    f"SELECT {', '.join(POLICY_COLUMNS)} FROM cycle_policies "  # noqa: S608
                    "WHERE cycle_id = :cycle_id"
                ),
                {"cycle_id": cycle_id},
            )
        ).mappings().one_or_none()
        counts = (
            await connection.execute(sa.text(_MEMBERSHIP_COUNTS), {"cycle_id": cycle_id})
        ).mappings().all()
        coordinators = (
            await connection.execute(
                sa.text(
                    "SELECT u.id, u.email, u.full_name FROM cycle_coordinators cc "
                    "JOIN users u ON u.id = cc.user_id WHERE cc.cycle_id = :cycle_id "
                    "ORDER BY u.full_name, u.id"
                ),
                {"cycle_id": cycle_id},
            )
        ).mappings().all()
        applications = (
            await connection.execute(
                sa.text(
                    "SELECT a.status, count(*) AS total FROM applications a "
                    "JOIN jobs j ON j.id = a.job_id WHERE j.cycle_id = :cycle_id "
                    "GROUP BY a.status"
                ),
                {"cycle_id": cycle_id},
            )
        ).mappings().all()

    policy = resolve_policy(
        CycleKind(cycle["kind"]),
        cycle_policy=dict(policy_row) if policy_row is not None else None,
    )
    return {
        "cycle": _cycle_payload(cycle),
        # Provenance travels with each value so the screen can show whether a
        # knob was set for this cycle or inherited (LLD section 9.4).
        "policy": {
            "membership_requires_approval": {
                "value": policy.membership_requires_approval.value,
                "source": policy.membership_requires_approval.source,
            },
            "join_rule": {
                "value": policy.join_rule.value,
                "source": policy.join_rule.source,
            },
            "max_accepted_offers": {
                "value": policy.max_accepted_offers.value,
                "source": policy.max_accepted_offers.source,
            },
            "penalty_blocks_applications": {
                "value": policy.penalty_blocks_applications.value,
                "source": policy.penalty_blocks_applications.source,
            },
            "allow_withdrawal_after_deadline": {
                "value": policy.allow_withdrawal_after_deadline.value,
                "source": policy.allow_withdrawal_after_deadline.source,
            },
            "allow_edit_after_deadline": {
                "value": policy.allow_edit_after_deadline.value,
                "source": policy.allow_edit_after_deadline.source,
            },
            "strike_on_absence": {
                "value": policy.strike_on_absence.value,
                "source": policy.strike_on_absence.source,
            },
            "offer_expiry_behavior": {
                "value": policy.offer_expiry_behavior.value.value,
                "source": policy.offer_expiry_behavior.source,
            },
            "deadline_reminder_hours": {
                "value": policy.deadline_reminder_hours.value,
                "source": policy.deadline_reminder_hours.source,
            },
            "round_reminder_hours": {
                "value": policy.round_reminder_hours.value,
                "source": policy.round_reminder_hours.source,
            },
        },
        "memberships": {str(row["status"]): int(row["total"]) for row in counts},
        "pending_approvals": next(
            (int(row["total"]) for row in counts if row["status"] == "pending"), 0
        ),
        "coordinators": [
            {
                "user_id": str(cast(UUID, row["id"])),
                "email": str(row["email"]),
                "full_name": str(row["full_name"]),
            }
            for row in coordinators
        ],
        # The funnel fills in as M9 and M10 populate jobs and applications.
        "applications": {str(row["status"]): int(row["total"]) for row in applications},
    }


_APPROVAL_QUEUE = """
    SELECT
        m.id, m.status, m.enrollment_id, m.consented_at, m.rejection_reason,
        m.decided_at, m.outcome_tag, u.email, u.full_name, e.roll_number,
        p.cpi, p.graduating_year, pr.name AS program_name, b.name AS branch_name,
        r.label AS resume_label, r.drive_url AS resume_url
    FROM cycle_memberships m
    JOIN enrollments e ON e.id = m.enrollment_id
    JOIN users u ON u.id = e.user_id
    LEFT JOIN profiles p ON p.enrollment_id = e.id
    LEFT JOIN programs pr ON pr.id = p.program_id
    LEFT JOIN branches b ON b.id = p.primary_branch_id
    LEFT JOIN resumes r ON r.id = m.default_resume_id
    WHERE m.cycle_id = :cycle_id AND m.status = ANY(:statuses)
    ORDER BY m.created_at, m.id
"""


async def staff_cycle_approvals(
    engine: AsyncEngine,
    actor: ActorContext,
    cycle_id: UUID,
    *,
    status: str = "pending",
) -> dict[str, object] | None:
    """The queue of membership decisions; also the cycle's roster by status.

    The default filter is the pending queue this screen was built for.  Any
    other status lists that part of the roster instead, which is what makes the
    ANA-3 outcome tag reachable: the students it describes -- a member who left
    for higher studies, one who is not seeking a placement -- are active
    members, never pending ones, and no other screen renders a membership row
    for a whole cycle.
    """
    statuses = ["pending"] if status == "pending" else [status]
    async with engine.connect() as connection:
        cycle = (
            await connection.execute(
                sa.text("SELECT id, name, kind, archived_at FROM cycles WHERE id = :id"),
                {"id": cycle_id},
            )
        ).mappings().one_or_none()
        if cycle is None:
            return None
        rows = (
            await connection.execute(
                sa.text(_APPROVAL_QUEUE),
                {"cycle_id": cycle_id, "statuses": statuses},
            )
        ).mappings().all()
    archived = cycle["archived_at"] is not None
    tag_permission = outcome_tag_permission(actor, cycle_id=cycle_id, archived=archived)
    return {
        "cycle": {
            "id": str(cast(UUID, cycle["id"])),
            "name": str(cycle["name"]),
            "kind": str(cycle["kind"]),
            "archived": archived,
        },
        "filters": {"status": status},
        "statuses": [item.value for item in MembershipStatus],
        "rows": [
            {
                "membership_id": str(cast(UUID, row["id"])),
                "enrollment_id": str(cast(UUID, row["enrollment_id"])),
                "status": str(row["status"]),
                "email": str(row["email"]),
                "full_name": str(row["full_name"]),
                "roll_number": row["roll_number"],
                "program": row["program_name"],
                "branch": row["branch_name"],
                "cpi": str(row["cpi"]) if row["cpi"] is not None else None,
                "graduating_year": row["graduating_year"],
                "consented_at": (
                    row["consented_at"].isoformat() if row["consented_at"] else None
                ),
                "decided_at": row["decided_at"].isoformat() if row["decided_at"] else None,
                "rejection_reason": row["rejection_reason"],
                "outcome_tag": row["outcome_tag"],
                "resume": (
                    {"label": row["resume_label"], "drive_url": row["resume_url"]}
                    if row["resume_url"]
                    else None
                ),
                "actions": {
                    "set_outcome_tag": tag_permission,
                    **membership_exit_permissions(
                        actor,
                        cycle_id=cycle_id,
                        archived=archived,
                        status=MembershipStatus(row["status"]),
                    ),
                },
            }
            for row in rows
        ],
    }


CYCLE_JOIN_DOMAINS: tuple[RuleDomain, ...] = (
    RuleDomain.CYCLE_REGISTRATION_WINDOW,
    RuleDomain.CYCLE_JOIN_RULE,
)

_JOINABLE = """
    SELECT
        c.id, c.name, c.kind, c.description, c.starts_on, c.ends_on,
        c.registration_opens_at, c.registration_closes_at, c.is_active, c.archived_at,
        cp.membership_requires_approval, cp.join_rule, cp.max_accepted_offers,
        cp.penalty_blocks_applications, cp.allow_withdrawal_after_deadline,
        cp.allow_edit_after_deadline, cp.strike_on_absence, cp.offer_expiry_behavior,
        cp.deadline_reminder_hours, cp.round_reminder_hours,
        m.id AS membership_id, m.status AS membership_status, m.rejection_reason
    FROM cycles c
    LEFT JOIN cycle_policies cp ON cp.cycle_id = c.id
    LEFT JOIN cycle_memberships m
        ON m.cycle_id = c.id AND m.enrollment_id = :enrollment_id
    WHERE c.archived_at IS NULL
    ORDER BY c.is_active DESC, c.name, c.id
"""


async def cycles_joinable(
    engine: AsyncEngine, enrollment_id: UUID
) -> dict[str, object]:
    """Every live cycle with this student's standing and, if absent, why.

    A pending member gets their status and nothing else: CYC-3 says they see a
    status screen, not a cycle they have not been admitted to.  A member who was
    rejected, or who withdrew, gets the checklist too -- both may re-request
    (the design review section 4.34), and a card that offered the button without saying
    what still fails would send them to a preview to find out.
    """
    async with engine.connect() as connection:
        profile_row = (
            await connection.execute(
                sa.text(
                    f"SELECT {', '.join('p.' + column for column in PROFILE_COLUMNS)}, "  # noqa: S608
                    "p.declared_at, e.roll_number, u.full_name "
                    "FROM enrollments e JOIN users u ON u.id = e.user_id "
                    "LEFT JOIN profiles p ON p.enrollment_id = e.id "
                    "WHERE e.id = :enrollment_id"
                ),
                {"enrollment_id": enrollment_id},
            )
        ).mappings().one_or_none()
        resume_rows = (
            await connection.execute(
                sa.text(
                    "SELECT id, label, drive_url, is_default FROM resumes "
                    "WHERE enrollment_id = :id ORDER BY created_at, id"
                ),
                {"id": enrollment_id},
            )
        ).mappings().all()
        resume_count = len(resume_rows)
        rows = (
            await connection.execute(
                sa.text(_JOINABLE), {"enrollment_id": enrollment_id}
            )
        ).mappings().all()
        # One resolve for every cycle's join rule: the reasons a student reads
        # must name programs and branches, not their UUIDs (ELG-2).
        labels = await resolve_labels(
            connection,
            {
                taxonomy_id
                for row in rows
                for taxonomy_id in taxonomy_ids(
                    cast(dict[str, object] | None, row["join_rule"])
                )
            },
        )
        not_placement_placed = not await placement_placed_global(
            connection, enrollment_id
        )
        now = cast(datetime, await connection.scalar(sa.select(sa.func.now())))
        overrides_by_cycle = await applicable_many(
            connection,
            CYCLE_JOIN_DOMAINS,
            {
                cast(UUID, row["id"]): ScopeIds(
                    cycle_id=cast(UUID, row["id"]),
                    enrollment_id=enrollment_id,
                )
                for row in rows
            },
        )

    profile = dict(profile_row) if profile_row is not None else {}
    checklist = check_profile_completeness(
        profile,
        resume_count=int(resume_count or 0),
        declared=profile.get("declared_at") is not None,
    )

    #: The statuses a student can leave on their own initiative (CYC-3.5).
    re_enterable = {"rejected", "withdrawn"}

    cycles: list[dict[str, object]] = []
    for row in rows:
        payload = _cycle_payload(row)
        status = (
            str(row["membership_status"]) if row["membership_id"] is not None else None
        )
        membership = (
            {
                "membership_id": str(cast(UUID, row["membership_id"])),
                "status": status,
                "rejection_reason": row["rejection_reason"],
            }
            if status is not None
            else None
        )
        if status is not None and status not in re_enterable:
            cycles.append(
                payload
                | {"membership": membership, "can_join": False, "reasons": []}
            )
            continue

        reasons: list[dict[str, object]] = []
        if not row["is_active"]:
            reasons.append(
                {
                    "code": "cycle_inactive",
                    "human": "The cycle is not open for registration",
                    "path": "cycle_id",
                }
            )
        resolved = gate_overrides(
            overrides_by_cycle.get(cast(UUID, row["id"]), ())
        )
        registration = evaluate_cycle_registration_window(
            now=now,
            opens_at=cast("datetime | None", row["registration_opens_at"]),
            closes_at=cast("datetime | None", row["registration_closes_at"]),
            overrides=resolved,
        )
        reasons.extend(
            {"code": reason.code, "human": reason.human, "path": reason.path}
            for reason in registration.failures
        )
        reasons.extend(
            {"code": reason.code, "human": reason.human, "path": reason.path}
            for reason in checklist
        )
        policy = resolve_policy(
            CycleKind(row["kind"]),
            cycle_policy={column: row[column] for column in POLICY_COLUMNS},
        )
        join_rule = policy.join_rule.value
        outcome = (
            evaluate(
                cast(dict[str, object], join_rule),
                profile,
                RuleContext(not_placement_placed=not_placement_placed),
                labels=labels,
            )
            if join_rule is not None
            else None
        )
        join_gate = evaluate_cycle_join_rule(outcome, resolved)
        reasons.extend(
            {"code": reason.code, "human": reason.human, "path": reason.path}
            for reason in join_gate.failures
        )
        cycles.append(
            payload
            | {
                "membership": membership,
                # `can_join` is about the join button, which only a non-member
                # sees; a returning member's control is re-request, and it reads
                # the same `reasons` to know whether it can succeed.
                "can_join": membership is None and not reasons,
                "reasons": reasons,
                "requires_approval": policy.membership_requires_approval.value,
            }
        )

    return {
        "enrollment_id": str(enrollment_id),
        "profile_complete": not checklist,
        "required_fields": list(
            required_join_fields(
                dual_major=bool(profile.get("is_dual_major", False)),
                dual_degree=bool(profile.get("is_dual_degree", False)),
            )
        ),
        "resumes": [
            {
                "id": str(cast(UUID, resume["id"])),
                "label": str(resume["label"]),
                "drive_url": str(resume["drive_url"]),
                "is_default": bool(resume["is_default"]),
            }
            for resume in resume_rows
        ],
        "cycles": cycles,
    }
