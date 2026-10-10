"""Re-check submitted, in-progress applications against a changed job rule/profile.

Only the ELG-2 rule is re-evaluated: duplicate, window, offer-cap and
membership gates are admission-time facts, not reasons to expel a candidate.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plan import Deferred, Event, ScopeIds, StateOp
from app.domain.gates import GateOverride, apply_eligibility_override
from app.domain.pathways import ProgramPathway, derived_rule_facts
from app.domain.rules import RuleContext, RuleSemantics, evaluate, taxonomy_ids
from app.domain.shared import ApplicationStatus, EventType, Outcome, RoundResult, RuleDomain
from app.modules.jobs.eligibility import MEMBER_PROFILE_SELECT
from app.modules.offers.derivations import placement_placed_enrollments
from app.modules.overrides.service import applicable_many
from app.modules.profiles.fields import PROFILE_COLUMNS
from app.modules.taxonomies.labels import resolve_labels


@dataclass(frozen=True, slots=True)
class Candidate:
    id: UUID
    enrollment_id: UUID
    job_id: UUID
    cycle_id: UUID
    job: str
    company: str
    name: str
    email: str
    current_round_id: UUID | None
    round_state_id: UUID | None
    profile: dict[str, object]
    rule: dict[str, object] | None
    version: int
    outcome: Outcome
    placed: bool
    overrides: tuple[GateOverride, ...]


async def load_candidates(
    tx: AsyncSession, *, job_id: UUID | None = None,
    enrollment_id: UUID | None = None, lock: bool,
) -> tuple[Candidate, ...]:
    """Load only applications that can be withdrawn from the active pipeline."""
    if (job_id is None) == (enrollment_id is None):
        raise ValueError("Exactly one requalification scope is required")
    rows = (
        await tx.execute(
            sa.text(
                "SELECT a.id AS application_id, a.enrollment_id, "
                "a.current_round_id, ars.id AS round_state_id, "
                "j.id AS job_id, j.cycle_id, j.title AS job_title, "
                "j.outcome, j.eligibility_rule, j.eligibility_rule_version, "
                "co.name AS company_name, u.full_name, u.email, "
                "prog.structure AS program_structure, "
                "prog.primary_degree_id AS program_primary_degree_id, "
                "prog.secondary_degree_id AS program_secondary_degree_id, "
                f"{MEMBER_PROFILE_SELECT} "  # noqa: S608
                "FROM applications a JOIN jobs j ON j.id = a.job_id "
                "JOIN companies co ON co.id = j.company_id "
                "JOIN enrollments e ON e.id = a.enrollment_id "
                "JOIN users u ON u.id = e.user_id "
                "LEFT JOIN profiles p ON p.enrollment_id = e.id "
                "LEFT JOIN programs prog ON prog.id = p.program_id "
                "LEFT JOIN application_round_states ars "
                "ON ars.application_id = a.id AND ars.round_id = a.current_round_id "
                "WHERE a.status = 'in_progress' AND j.cancelled_at IS NULL "
                "AND j.published_at IS NOT NULL AND "
                + ("a.job_id = :id" if job_id else "a.enrollment_id = :id")
                + " ORDER BY a.id" + (" FOR UPDATE OF a" if lock else "")
            ),
            {"id": job_id or enrollment_id},
        )
    ).mappings().all()
    if not rows:
        return ()
    placed = await placement_placed_enrollments(
        tx, tuple(cast(UUID, row["enrollment_id"]) for row in rows)
    )
    scopes = {
        cast(UUID, row["application_id"]): ScopeIds(
            cycle_id=cast(UUID, row["cycle_id"]),
            job_id=cast(UUID, row["job_id"]),
            enrollment_id=cast(UUID, row["enrollment_id"]),
            application_id=cast(UUID, row["application_id"]),
        )
        for row in rows
    }
    grants = await applicable_many(tx, (RuleDomain.ELIGIBILITY,), scopes)
    return tuple(
        Candidate(
            id=cast(UUID, row["application_id"]),
            enrollment_id=cast(UUID, row["enrollment_id"]),
            job_id=cast(UUID, row["job_id"]),
            cycle_id=cast(UUID, row["cycle_id"]),
            job=str(row["job_title"]), company=str(row["company_name"]),
            name=str(row["full_name"]), email=str(row["email"]),
            current_round_id=cast("UUID | None", row["current_round_id"]),
            round_state_id=cast("UUID | None", row["round_state_id"]),
            profile={key: row[key] for key in PROFILE_COLUMNS}
            | {key: row[key] for key in (
                "program_structure", "program_primary_degree_id",
                "program_secondary_degree_id",
            )},
            rule=cast("dict[str, object] | None", row["eligibility_rule"]),
            version=int(row["eligibility_rule_version"]),
            outcome=Outcome(row["outcome"]),
            placed=cast(UUID, row["enrollment_id"]) in placed,
            overrides=tuple(
                GateOverride(id=grant.id, rule_domain=grant.rule_domain, allow=grant.allow)
                for grant in grants[cast(UUID, row["application_id"])]
            ),
        )
        for row in rows
    )


def revocations(
    candidates: tuple[Candidate, ...], *,
    rule: dict[str, object] | None = None,
    rule_changed: bool = False,
    profile_changes: Mapping[str, object] | None = None,
    current_session: int | None,
    labels: Mapping[UUID, str],
    program_pathways: Mapping[UUID, ProgramPathway] | None = None,
) -> tuple[Candidate, ...]:
    """Pure proposed-state verdict; changes are previewed before any write."""
    rejected: list[Candidate] = []
    for candidate in candidates:
        proposed_rule = rule if rule_changed else candidate.rule
        if proposed_rule is None:
            continue  # Same as the apply verdict: no tree means no ELG-2 check.
        profile = dict(candidate.profile)
        profile.update(profile_changes or {})
        if profile_changes and "program_id" in profile_changes and program_pathways:
            program_id = profile_changes["program_id"]
            pathway = program_pathways.get(program_id) if isinstance(program_id, UUID) else None
            profile["program_structure"] = pathway.structure.value if pathway else None
            profile["program_primary_degree_id"] = pathway.primary_degree_id if pathway else None
            profile["program_secondary_degree_id"] = (
                pathway.secondary_degree_id if pathway else None
            )
        profile.update(
            derived_rule_facts(profile, outcome=candidate.outcome, current_session=current_session)
        )
        result = evaluate(
            proposed_rule, profile,
            RuleContext(not_placement_placed=not candidate.placed),
            labels=labels,
            semantics=RuleSemantics.CURRENT if rule_changed else RuleSemantics(candidate.version),
        )
        if apply_eligibility_override(result, candidate.overrides).failures:
            rejected.append(candidate)
    return tuple(rejected)


async def candidate_labels(
    tx: AsyncSession, candidates: tuple[Candidate, ...],
    *, rule: dict[str, object] | None = None,
) -> dict[UUID, str]:
    ids = set(taxonomy_ids(rule))
    for candidate in candidates:
        ids |= taxonomy_ids(candidate.rule)
    return await resolve_labels(tx, ids)


def removal_plan(
    candidates: tuple[Candidate, ...], *, source: str,
) -> tuple[list[StateOp], list[Event], list[Deferred]]:
    """Keep the application and its timeline; never touch an open offer."""
    operations: list[StateOp] = []
    events: list[Event] = []
    deferred: list[Deferred] = []
    for candidate in candidates:
        operations.append(StateOp(
            op="update", model="applications",
            values={"status": ApplicationStatus.REJECTED.value}, where={"id": candidate.id},
        ))
        if candidate.round_state_id is not None:
            operations.append(StateOp(
                op="update", model="application_round_states",
                values={"result": RoundResult.ELIMINATED.value},
                where={"id": candidate.round_state_id},
            ))
        events.append(Event(
            application_id=candidate.id, event_type=EventType.ELIMINATED,
            from_status=ApplicationStatus.IN_PROGRESS.value,
            to_status=ApplicationStatus.REJECTED.value,
            from_round=candidate.current_round_id, to_round=candidate.current_round_id,
            reason="Eligibility changed",
            payload={"job_id": str(candidate.job_id), "source": source},
        ))
        deferred.append(Deferred(task="deliver_notification", args={
            "event_key": "eligibility_removed", "recipient": candidate.email,
            "context": {
                "student": candidate.name, "job": candidate.job,
                "company": candidate.company, "cycle_id": str(candidate.cycle_id),
            },
        }))
    return operations, events, deferred
