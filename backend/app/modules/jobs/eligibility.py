"""Job eligibility rules and their live impact preview (Behavior JOB-2.2, ELG-2).

Editing a rule never re-judges anyone: ELG-1 says a rule runs against the live
profile at the instant it is consulted, and ELG-4 says whoever got in validly
stays in.  So this command writes two columns and nothing else -- there is
deliberately no re-evaluation pass over existing applications, and a test
asserts that an application survives an edit that would have excluded it.

The impact preview answers the only question a rule author actually has:
"who does this let in right now?"  It evaluates the tree against every active
member's live profile, in the same code path the student's card will use, so
the count staff see and the verdict a student gets cannot disagree.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import CYCLE_NOT_FOUND
from app.core.plan import ActorContext, Plan, Reason, Rejection, ScopeIds, StateOp
from app.core.registry import Registry
from app.domain.pathways import derived_rule_facts
from app.domain.rules import (
    RuleContext,
    RuleSemantics,
    evaluate,
    parse_rule,
    summarize,
    taxonomy_ids,
)
from app.domain.shared import CycleKind, Outcome
from app.modules.jobs.commands import (
    JobRow,
    fetch_job,
    job_cancelled_reason,
    job_not_found,
    now,
)
from app.modules.offers.derivations import (
    internship_placed_enrollments,
    placement_placed_enrollments,
)
from app.modules.profiles.academics import load_academic_session
from app.modules.profiles.fields import PROFILE_COLUMNS
from app.modules.taxonomies.labels import resolve_labels

# Every column an ELG-2 leaf can read.  All of them are `profiles` columns,
# which is what LLD section 9.1 says a rule field is: `is_dual_major` used to
# be joined in from the programs taxonomy to arrive as though it were one
# (the design review section 4.32 moved it onto the profile, where it belongs).
MEMBER_PROFILE_SELECT = ", ".join(f"p.{column}" for column in PROFILE_COLUMNS)
ACTIVE_MEMBERS = f"""
    SELECT
        e.id AS enrollment_id, e.roll_number, u.full_name, u.email,
        prog.structure AS program_structure,
        prog.primary_degree_id AS program_primary_degree_id,
        prog.secondary_degree_id AS program_secondary_degree_id,
        {MEMBER_PROFILE_SELECT}
    FROM cycle_memberships m
    JOIN enrollments e ON e.id = m.enrollment_id
    JOIN users u ON u.id = e.user_id
    LEFT JOIN profiles p ON p.enrollment_id = e.id
    LEFT JOIN programs prog ON prog.id = p.program_id
    WHERE m.cycle_id = :cycle_id AND m.status = 'active'
    ORDER BY u.full_name, e.id
"""


class UpdateJobEligibilityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    job_id: UUID
    # Null clears the rule, leaving only the ELG-3 standing gates: "open to
    # every active member" is a legitimate and common eligibility policy.
    eligibility_rule: dict[str, object] | None = None

    @field_validator("eligibility_rule")
    @classmethod
    def validate_rule(cls, value: dict[str, object] | None) -> dict[str, object] | None:
        """An unknown field or operator is a 422 at save (LLD section 9.1)."""
        if value is not None:
            parse_rule(value)
        return value


class JobEligibilitySummary(BaseModel):
    cycle_id: UUID
    job_id: UUID
    eligibility_summary: str
    eligibility_rule_version: int
    eligible_count: int
    #: Of those the rule admits, how many already hold an accepted offer of
    #: this outcome -- the fact that usually explains ELG-3 refusing them.
    placed_count: int
    member_count: int
    # Who, not just how many. The builder's impact preview is a dry run of this
    # command, and "3 of 6 qualify" without naming the three is the same
    # unanimity problem the preview exists to expose: a coordinator raising a
    # CPI floor needs to see which students it costs them, before saving.
    members: list[dict[str, object]]
    changed: bool


@dataclass(frozen=True, slots=True)
class MemberVerdict:
    enrollment_id: UUID
    full_name: str
    roll_number: str | None
    eligible: bool
    reasons: tuple[Reason, ...]
    #: Already holds an accepted offer of this job's outcome. A fact, not
    #: ELG-3's verdict: the rule author is told it because it is what usually
    #: explains why someone their rule describes cannot apply.
    placed: bool


@dataclass(frozen=True, slots=True)
class JobEligibilityState:
    scope_ids: ScopeIds
    cycle_archived: bool
    cycle_exists: bool
    cycle_kind: CycleKind | None
    job: JobRow | None
    members: tuple[dict[str, object], ...]
    labels: dict[UUID, str]
    current_academic_session: int | None


def member_profiles_with_placement(
    rows: Sequence[sa.RowMapping],
    placed: Collection[UUID],
    internship_placed: Collection[UUID] = (),
) -> tuple[dict[str, object], ...]:
    """Add the derived facts a rule reads to profiles before pure evaluation.

    The batch-loaded DER-1 placement fact, and the disciplines the student may
    be matched on (ELG-2) -- which no column holds, because it depends on the
    enrollment's shape and, for a dual major, their year of study.
    """
    profiles: list[dict[str, object]] = []
    for row in rows:
        profile: dict[str, object] = dict(row)
        profile["placement_placed_global"] = (
            cast(UUID, row["enrollment_id"]) in placed
        )
        profile["internship_placed_in_cycle"] = (
            cast(UUID, row["enrollment_id"]) in internship_placed
        )
        profiles.append(profile)
    return tuple(profiles)


async def _load_eligibility(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> JobEligibilityState:
    if not isinstance(input_value, UpdateJobEligibilityInput):
        raise TypeError("update_job_eligibility requires UpdateJobEligibilityInput")
    cycle = await tx.execute(
        sa.text("SELECT archived_at, kind FROM cycles WHERE id = :id"),
        {"id": input_value.cycle_id},
    )
    cycle_row = cycle.mappings().one_or_none()
    job = await fetch_job(
        tx, cycle_id=input_value.cycle_id, job_id=input_value.job_id, lock=lock
    )
    members = (
        await tx.execute(sa.text(ACTIVE_MEMBERS), {"cycle_id": input_value.cycle_id})
    ).mappings().all()
    enrollment_ids = tuple(cast(UUID, row["enrollment_id"]) for row in members)
    placed = await placement_placed_enrollments(tx, enrollment_ids)
    cycle_kind = (
        CycleKind(str(cycle_row["kind"])) if cycle_row is not None else None
    )
    # Only a dedicated internship cycle carries the cycle-local gate, so only
    # there is the second roster query worth running.
    internship_placed = (
        await internship_placed_enrollments(tx, enrollment_ids, input_value.cycle_id)
        if cycle_kind is CycleKind.INTERNSHIP
        else frozenset()
    )
    await now(tx)
    return JobEligibilityState(
        scope_ids=ScopeIds(cycle_id=input_value.cycle_id, job_id=input_value.job_id),
        cycle_archived=cycle_row is not None and cycle_row["archived_at"] is not None,
        cycle_exists=cycle_row is not None,
        cycle_kind=cycle_kind,
        job=job,
        members=member_profiles_with_placement(members, placed, internship_placed),
        labels=await resolve_labels(tx, taxonomy_ids(input_value.eligibility_rule)),
        current_academic_session=await load_academic_session(tx, lock=lock),
    )


def evaluate_members(
    rule: dict[str, object] | None,
    members: tuple[dict[str, object], ...],
    labels: dict[UUID, str],
    *,
    outcome: Outcome,
    cycle_kind: CycleKind,
    current_session: int | None,
    semantics: RuleSemantics = RuleSemantics.CURRENT,
) -> tuple[MemberVerdict, ...]:
    """The rule alone against every active member's live profile (JOB-2.2).

    The verdict stays the rule's alone: standing gates are per-student
    circumstances (an accepted offer, a penalty) answering "can they apply
    today", where a rule author is asking "who does my rule describe".
    Subtracting the placed from the count would hide a rule that is wrong
    behind students who happen to be placed, and the number would drift every
    time an offer landed without the rule changing.

    Each verdict does carry ``placed``, the one standing fact that most often
    explains a name on the list -- ELG-3 closes a placement role to a student
    who has accepted one. Reported beside the count, never subtracted from it.
    """
    verdicts: list[MemberVerdict] = []
    for member in members:
        enrollment_id = cast(UUID, member["enrollment_id"])
        evaluated = dict(member)
        evaluated.update(
            derived_rule_facts(
                evaluated, outcome=outcome, current_session=current_session
            )
        )
        if rule is None:
            verdicts.append(
                MemberVerdict(
                    enrollment_id=enrollment_id,
                    full_name=str(member["full_name"]),
                    roll_number=cast("str | None", member["roll_number"]),
                    eligible=True,
                    reasons=(),
                    placed=_already_placed(member, outcome=outcome, cycle_kind=cycle_kind),
                )
            )
            continue
        evaluation = evaluate(
            rule,
            evaluated,
            RuleContext(
                not_placement_placed=not bool(member["placement_placed_global"])
            ),
            labels=labels,
            semantics=semantics,
        )
        verdicts.append(
            MemberVerdict(
                enrollment_id=enrollment_id,
                full_name=str(member["full_name"]),
                roll_number=cast("str | None", member["roll_number"]),
                eligible=evaluation.verdict,
                reasons=evaluation.failures,
                placed=_already_placed(member, outcome=outcome, cycle_kind=cycle_kind),
            )
        )
    return tuple(verdicts)


def _already_placed(
    member: Mapping[str, object], *, outcome: Outcome, cycle_kind: CycleKind
) -> bool:
    """Whether this student already holds an accepted offer of this kind.

    A fact about the student, deliberately not ELG-3's verdict about them.
    Asking ``domain.gates`` here would make this command a consulter of the
    outcome-gate domain, and a roster-wide preview cannot resolve the
    per-student grants that domain exists for -- it would declare that it
    honours overrides and then quietly not. So the panel reports the fact that
    usually explains the gate, and the gate itself still decides, on the
    student's own card, where their overrides are known.
    """
    if outcome is Outcome.PLACEMENT:
        return bool(member["placement_placed_global"])
    return cycle_kind is CycleKind.INTERNSHIP and bool(
        member["internship_placed_in_cycle"]
    )


def _decide_update_job_eligibility(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Store the tree and its generated summary (Behavior JOB-2.2, JOB-3, ELG-2)."""
    if not isinstance(input_value, UpdateJobEligibilityInput) or not isinstance(
        state, JobEligibilityState
    ):
        raise TypeError("Invalid update_job_eligibility decision input")
    if not state.cycle_exists:
        return Rejection(
            reasons=[Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")]
        )
    if state.job is None:
        return job_not_found()
    if state.job.cancelled_at is not None:
        return Rejection(reasons=[job_cancelled_reason()])

    rule = input_value.eligibility_rule
    summary_text = summarize(rule, state.labels)
    verdicts = evaluate_members(
        rule,
        state.members,
        state.labels,
        outcome=state.job.outcome,
        cycle_kind=state.cycle_kind or CycleKind.OPEN,
        current_session=state.current_academic_session,
        semantics=RuleSemantics.CURRENT,
    )
    eligible = [verdict for verdict in verdicts if verdict.eligible]
    placed = [verdict for verdict in eligible if verdict.placed]
    changed = (
        rule != state.job.eligibility_rule
        or state.job.eligibility_rule_version != int(RuleSemantics.CURRENT)
        or summary_text != state.job.eligibility_summary
    )

    return Plan(
        state_ops=(
            [
                StateOp(
                    op="update",
                    model="jobs",
                    values={
                        "eligibility_rule": rule,
                        "eligibility_rule_version": int(RuleSemantics.CURRENT),
                        "eligibility_summary": summary_text,
                    },
                    where={"id": state.job.id},
                )
            ]
            if changed
            else []
        ),
        events=[],
        deferred=[],
        audit={
            "subject_type": "job",
            "subject_id": state.job.id,
            "details": {
                "before": {
                    "eligibility_rule": state.job.eligibility_rule,
                    "eligibility_rule_version": state.job.eligibility_rule_version,
                    "eligibility_summary": state.job.eligibility_summary,
                },
                "after": {
                    "eligibility_rule": rule,
                    "eligibility_rule_version": int(RuleSemantics.CURRENT),
                    "eligibility_summary": summary_text,
                },
                # Recorded because a rule edit is invisible in its effects: it
                # changes nobody's existing application (ELG-4), so the impact
                # at the moment of the edit is the only trace of what it meant.
                "eligible_count": len(eligible),
                "member_count": len(verdicts),
            },
        },
        summary={
            "cycle_id": str(state.job.cycle_id),
            "job_id": str(state.job.id),
            "eligibility_summary": summary_text,
            "eligibility_rule_version": int(RuleSemantics.CURRENT),
            "eligible_count": len(eligible),
            "placed_count": len(placed),
            "member_count": len(verdicts),
            "members": [
                {
                    "enrollment_id": str(verdict.enrollment_id),
                    "full_name": verdict.full_name,
                    "roll_number": verdict.roll_number,
                    "eligible": verdict.eligible,
                    "placed": verdict.placed,
                    "reasons": [asdict(reason) for reason in verdict.reasons],
                }
                for verdict in verdicts
            ],
            "changed": changed,
        },
    )


def register_job_eligibility_commands(registry: Registry) -> None:
    registry.command(
        name="update_job_eligibility",
        input_model=UpdateJobEligibilityInput,
        output_model=JobEligibilitySummary,
        actor="staff",
        scope="cycle",
        loader=_load_eligibility,
        rule_domains=(),
        spec_ids=("JOB-2", "JOB-3", "ELG-2"),
    )(_decide_update_job_eligibility)
