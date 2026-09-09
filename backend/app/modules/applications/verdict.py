"""One answer to "may this student apply to this job right now?" (ELG-3, APP-1).

Two call sites ask that question: the student's job card (Behavior JOB-4, which
must show *every* failing reason) and ``apply`` itself, which enforces it.  When
those two disagree the product lies to a student -- a card that says eligible
and an apply that rejects is the worst failure this system has -- so they do not
merely share a scoring function, they share the **whole populate path**: one SQL
column list, one context loader, one override conversion, one pure verdict.

Sharing only ``evaluate_gates`` would not be enough.  The context has sixteen
fields; two call sites that each fill them from their own query drift in what
they put *in* the fields long before they drift in how they score them.  So the
rule here is: nothing in this module takes a pre-built ``GateContext``, and
neither caller builds one.

the design review section 4.21 sanctions this as a deliberate edit to M9's
``modules/jobs/queries.py``; ``tests/applications/test_verdict_equivalence.py``
runs the full display path and the full apply path for one student and one job
and asserts the verdicts and their reason lists are identical.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.core.plan import Reason, ScopeIds
from app.domain.gates import (
    GateContext,
    GateOverride,
    apply_eligibility_override,
    evaluate_gates,
)
from app.domain.policy import resolve_policy
from app.domain.rules import Labels, RuleContext, evaluate, profile_taxonomy_ids, taxonomy_ids
from app.domain.shared import CycleKind, MembershipStatus, Outcome, RuleDomain
from app.modules.cycles.commands import POLICY_COLUMNS
from app.modules.jobs.commands import JOB_COLUMNS
from app.modules.jobs.eligibility import MEMBER_PROFILE_SELECT
from app.modules.offers.derivations import offer_facts
from app.modules.overrides.service import ApplicableOverride, applicable
from app.modules.taxonomies.labels import resolve_labels

Executor = AsyncConnection | AsyncSession

#: The gate domains an override may bypass on the apply path (the design review
#: section 4.14).  The registry entry for ``apply`` and the display screens read
#: this same tuple, so a domain can never be overridable at apply time and
#: invisible on the card.
APPLY_RULE_DOMAINS: tuple[RuleDomain, ...] = (
    RuleDomain.ELIGIBILITY,
    RuleDomain.APPLICATION_DEADLINE,
    RuleDomain.OUTCOME_GATE,
    RuleDomain.OFFER_CAP,
)

_JOB_SELECT = ", ".join(f"j.{column.strip()}" for column in JOB_COLUMNS.split(","))

#: Every column either caller needs about a job *and* this student's standing
#: application against it.  One constant, so the duplicate-application fact is
#: computed from the same lateral join on both paths.
STUDENT_JOB_SELECT = f"""
    SELECT {_JOB_SELECT},
        c.name AS company_name,
        s.name AS sector_name,
        (SELECT count(*) FROM job_rounds r WHERE r.job_id = j.id) AS round_count,
        (SELECT count(*) FROM job_questions q WHERE q.job_id = j.id) AS question_count,
        (
            SELECT count(*) FROM applications a
            WHERE a.job_id = j.id
              AND a.status NOT IN ('withdrawn', 'auto_withdrawn')
        ) AS application_count,
        app.id AS application_id,
        app.status AS application_status
    FROM jobs j
    JOIN companies c ON c.id = j.company_id
    LEFT JOIN sectors s ON s.id = j.sector_id
    LEFT JOIN LATERAL (
        SELECT a.id, a.status FROM applications a
        WHERE a.job_id = j.id AND a.enrollment_id = :enrollment_id
        -- APP-2: a prior application blocks re-applying unless every one of
        -- them is withdrawn/auto_withdrawn -- exactly the partial-unique
        -- predicate.  Preferring a blocking row over a merely newer one keeps
        -- that fact true no matter what order the rows were written in.
        ORDER BY (a.status NOT IN ('withdrawn', 'auto_withdrawn')) DESC,
                 a.applied_at DESC
        LIMIT 1
    ) app ON true
    WHERE {{filter}}
    ORDER BY j.application_deadline NULLS LAST, c.name, j.title, j.id
"""


CYCLE_HEADER_SELECT = """
    SELECT c.id, c.name, c.kind, c.archived_at, {policy}
    FROM cycles c LEFT JOIN cycle_policies cp ON cp.cycle_id = c.id
    WHERE c.id = :id
"""


async def load_cycle_header(executor: Executor, cycle_id: UUID) -> sa.RowMapping | None:
    """The cycle row both the screens and ``apply`` judge against.

    It carries the policy columns because two of them -- the offer cap and
    whether penalties block applications -- are gate inputs, and a second query
    somewhere else is a second chance to fill them differently.
    """
    return (
        await executor.execute(
            sa.text(
                CYCLE_HEADER_SELECT.format(
                    policy=", ".join(f"cp.{column}" for column in POLICY_COLUMNS)
                )
            ),
            {"id": cycle_id},
        )
    ).mappings().one_or_none()


def student_job_query(filter_sql: str, *, published_only: bool = True) -> str:
    """The student job select under one filter.

    ``published_only`` is not a convenience: JOB-4's listing shows published
    jobs only, while ``apply`` must *load* an unpublished job in order to reject
    it with ``job_unpublished`` rather than "not found".  A student who applies
    the moment a coordinator unpublishes deserves the real reason.
    """
    clause = f"({filter_sql}) AND j.is_published" if published_only else filter_sql
    return STUDENT_JOB_SELECT.format(filter=clause)


@dataclass(frozen=True, slots=True)
class StudentContext:
    """Everything about the student and the cycle that the gates read."""

    enrollment_id: UUID
    cycle_id: UUID
    cycle_kind: CycleKind
    cycle_archived: bool
    membership_status: MembershipStatus
    profile: dict[str, object]
    penalty_active: bool
    penalty_blocks_applications: bool
    placement_placed_global: bool
    internship_placed_in_cycle: bool
    max_accepted_offers: int | None
    cap_used: int
    now: datetime


@dataclass(frozen=True, slots=True)
class Verdict:
    eligible: bool
    reasons: tuple[Reason, ...]
    applied_override_ids: tuple[UUID, ...] = ()


async def load_student_context(
    executor: Executor,
    *,
    cycle: sa.RowMapping,
    enrollment_id: UUID,
    lock: bool,
) -> StudentContext:
    """Load the per-student half of the verdict from one place.

    ``lock`` takes the membership row ``FOR UPDATE``: the membership-active gate
    is an existence invariant, and CONTRIBUTING.md invariant 9 requires the row it
    judges to be locked when a command is the caller.  Screens pass False --
    a read has nothing to protect.
    """
    membership = (
        await executor.execute(
            sa.text(
                "SELECT status FROM cycle_memberships "
                "WHERE cycle_id = :cycle_id AND enrollment_id = :enrollment_id"
                + (" FOR UPDATE" if lock else "")
            ),
            {"cycle_id": cycle["id"], "enrollment_id": enrollment_id},
        )
    ).scalar_one_or_none()
    profile_row = (
        await executor.execute(
            sa.text(
                # The PRO-1 registry spans three tables (the design review section 4.1):
                # the rule engine only reads the profiles columns, but APP-1's
                # snapshot is "the registry fields", so the name and roll number
                # come along -- an application that cannot say whose it was is
                # not a snapshot.
                f"SELECT {MEMBER_PROFILE_SELECT}, u.full_name, e.roll_number "  # noqa: S608
                "FROM enrollments e "
                "JOIN users u ON u.id = e.user_id "
                "LEFT JOIN profiles p ON p.enrollment_id = e.id "
                "WHERE e.id = :enrollment_id"
            ),
            {"enrollment_id": enrollment_id},
        )
    ).mappings().one_or_none()
    penalty_active = bool(
        await executor.scalar(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM penalties "
                "WHERE enrollment_id = :enrollment_id "
                "AND is_active AND revoked_at IS NULL)"
            ),
            {"enrollment_id": enrollment_id},
        )
    )
    now = cast(datetime, await executor.scalar(sa.select(sa.func.now())))
    policy = resolve_policy(
        CycleKind(cycle["kind"]),
        cycle_policy={column: cycle[column] for column in POLICY_COLUMNS},
    )
    facts = await offer_facts(executor, enrollment_id, cast(UUID, cycle["id"]))
    return StudentContext(
        enrollment_id=enrollment_id,
        cycle_id=cast(UUID, cycle["id"]),
        cycle_kind=CycleKind(cycle["kind"]),
        cycle_archived=cycle["archived_at"] is not None,
        membership_status=(
            MembershipStatus(membership) if membership is not None else MembershipStatus.PENDING
        ),
        profile=dict(profile_row) if profile_row is not None else {},
        penalty_active=penalty_active,
        penalty_blocks_applications=policy.penalty_blocks_applications.value,
        placement_placed_global=facts.placement_placed_global,
        internship_placed_in_cycle=facts.internship_placed_in_cycle,
        max_accepted_offers=policy.max_accepted_offers.value,
        cap_used=facts.cap_used,
        now=now,
    )


async def load_rule_labels(
    executor: Executor, context: StudentContext, rules: list[dict[str, object] | None]
) -> Labels:
    """Name every taxonomy id the rules and the profile mention (ELG-2)."""
    wanted: set[UUID] = set(profile_taxonomy_ids(context.profile))
    for rule in rules:
        wanted |= taxonomy_ids(rule)
    return await resolve_labels(executor, wanted)


async def load_gate_overrides(
    executor: Executor, *, scope_ids: ScopeIds
) -> tuple[GateOverride, ...]:
    """Resolve active overrides for a *screen*.

    The command path gets its overrides from the executor, which consults the
    same ``applicable`` with the same domains; both convert through
    :func:`gate_overrides` so the two paths cannot disagree about what an
    override means.
    """
    if isinstance(executor, AsyncConnection):
        # ``applicable`` resolves specificity through the ORM, so it needs a
        # session; binding one to the connection the screen already holds keeps
        # both paths on the single resolution rather than growing a second.
        async with AsyncSession(bind=executor) as session:
            return gate_overrides(await applicable(session, APPLY_RULE_DOMAINS, scope_ids))
    return gate_overrides(await applicable(executor, APPLY_RULE_DOMAINS, scope_ids))


def gate_overrides(resolved: tuple[ApplicableOverride, ...]) -> tuple[GateOverride, ...]:
    """Convert resolved overrides into the gates' view of them.

    The specificity precedence has already been settled by ``applicable``; the
    gates only need to know which domain each one speaks to and whether it
    allows or denies.
    """
    return tuple(
        GateOverride(id=row.id, rule_domain=row.rule_domain, allow=row.allow)
        for row in resolved
    )


def compute_verdict(
    context: StudentContext,
    job: sa.RowMapping,
    *,
    labels: Labels,
    overrides: tuple[GateOverride, ...] = (),
) -> Verdict:
    """Standing gates then the job rule, every failure kept (JOB-4, ELG-3).

    Both halves run even when the first already failed: a student told only
    "membership not active" fixes that, comes back, and only then discovers the
    CPI floor they could have seen the first time.
    """
    gates = evaluate_gates(
        GateContext(
            membership_status=context.membership_status,
            job_published=bool(job["is_published"]),
            job_cancelled=job["cancelled_at"] is not None,
            cycle_archived=context.cycle_archived,
            application_deadline=job["application_deadline"],
            now=context.now,
            outcome=Outcome(job["outcome"]),
            cycle_kind=context.cycle_kind,
            has_active_duplicate=job["application_status"] is not None
            and str(job["application_status"]) not in {"withdrawn", "auto_withdrawn"},
            penalty_active=context.penalty_active,
            penalty_blocks_applications=context.penalty_blocks_applications,
            placement_placed_global=context.placement_placed_global,
            internship_placed_in_cycle=context.internship_placed_in_cycle,
            max_accepted_offers=context.max_accepted_offers,
            cap_used=context.cap_used,
            applicable_overrides=overrides,
        )
    )
    reasons = list(gates.failures)
    applied = list(gates.applied_override_ids)

    rule = cast("dict[str, object] | None", job["eligibility_rule"])
    if rule is not None:
        outcome = evaluate(
            rule,
            context.profile,
            RuleContext(
                not_placement_placed=not context.placement_placed_global
            ),
            labels=labels,
        )
        # ELG-2's rule is the one domain an eligibility override bypasses; the
        # standing gates above have their own domains and are untouched by it.
        eligibility = apply_eligibility_override(outcome, overrides)
        reasons.extend(eligibility.failures)
        applied.extend(eligibility.applied_override_ids)

    return Verdict(
        eligible=not reasons,
        reasons=tuple(reasons),
        applied_override_ids=tuple(applied),
    )
