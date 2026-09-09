"""The membership lifecycle (Behavior CYC-3, CYC-4).

Joining is the one student-driven write here; everything else is a staff
decision or a student's own exit.  All of them audit with the acting person as
the actor, students included (the design review section 4.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    CONSENT_REQUIRED,
    CYCLE_INACTIVE,
    CYCLE_NOT_FOUND,
    DUPLICATE_ROW,
    INVALID_TRANSITION,
    MEMBERSHIP_EXISTS,
    MEMBERSHIP_NOT_FOUND,
    RESUME_NOT_FOUND,
    UNMATCHED_IDENTIFIER,
)
from app.core.plan import (
    ActorContext,
    Deferred,
    Event,
    Plan,
    Reason,
    Rejection,
    ScopeIds,
    StateOp,
)
from app.core.registry import Decider, Registry
from app.domain.gates import (
    evaluate_cycle_join_rule,
    evaluate_cycle_registration_window,
)
from app.domain.memberships import (
    MembershipApplicationState,
    MembershipExitTrigger,
    check_profile_completeness,
    compute_membership_exit_cascade,
    decide_membership_transition,
)
from app.domain.policy import Policy, resolve_policy
from app.domain.rules import RuleContext, evaluate, taxonomy_ids
from app.domain.shared import (
    ApplicationStatus,
    MembershipStatus,
    OutcomeTag,
    RuleDomain,
)
from app.domain.transitions import TransitionActor
from app.modules.applications.verdict import gate_overrides
from app.modules.cycles.commands import CycleRow, fetch_cycle, fetch_policy
from app.modules.notifications.wording import withdrawal_trigger
from app.modules.offers.derivations import placement_placed_global
from app.modules.overrides.service import ApplicableOverride
from app.modules.profiles.fields import PROFILE_COLUMNS
from app.modules.taxonomies.labels import resolve_labels

# The profile columns the join checklist and the join rule both read, plus the
# two fields that live outside the profiles table (the design review section 4.1).
_PROFILE_SELECT = ", ".join(f"p.{column}" for column in PROFILE_COLUMNS)

JOIN_RULE_DOMAINS: tuple[RuleDomain, ...] = (
    RuleDomain.CYCLE_REGISTRATION_WINDOW,
    RuleDomain.CYCLE_JOIN_RULE,
)


class JoinRequestInput(BaseModel):
    """The wire shape shared by both ways into a cycle (CYC-3).

    the design review section 4.34 makes re-entry re-run every join check, so it must
    carry everything a first join carries: the same consent acknowledgement and
    the same cycle-default resume choice.  One base rather than two drifting
    copies -- ``_load_join`` and ``_join_gate_reasons`` are written against it.
    """

    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    enrollment_id: UUID
    default_resume_id: UUID
    consent: bool = False


class JoinCycleInput(JoinRequestInput):
    pass


class MembershipSummary(BaseModel):
    cycle_id: UUID
    membership_id: UUID
    enrollment_id: UUID
    status: MembershipStatus
    changed: bool


class ApproveMembershipsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    rows: list[dict[str, str]]
    batch_key: str

    @field_validator("rows")
    @classmethod
    def validate_rows(cls, value: list[dict[str, str]]) -> list[dict[str, str]]:
        for row in value:
            if set(row) - {"membership_id", "identifier"} or not row:
                raise ValueError("each row carries membership_id or identifier")
        return value


class BulkMembershipSummary(BaseModel):
    rows: list[dict[str, object]]


class RejectMembershipInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    membership_id: UUID
    reason: str

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("a rejection reason is required")
        return stripped


class RerequestMembershipInput(JoinRequestInput):
    pass


class SetOutcomeTagInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    membership_id: UUID
    outcome_tag: OutcomeTag | None = None


class OutcomeTagSummary(BaseModel):
    cycle_id: UUID
    membership_id: UUID
    outcome_tag: OutcomeTag | None
    changed: bool


@dataclass(frozen=True, slots=True)
class MembershipRow:
    id: UUID
    cycle_id: UUID
    enrollment_id: UUID
    status: MembershipStatus
    outcome_tag: OutcomeTag | None
    email: str
    full_name: str
    roll_number: str | None


@dataclass(frozen=True, slots=True)
class JoinState:
    scope_ids: ScopeIds
    cycle_archived: bool
    now: datetime
    cycle: CycleRow | None
    policy: dict[str, object] | None
    membership: MembershipRow | None
    membership_id: UUID
    profile: dict[str, object] | None
    resume_count: int
    resume_owned: bool
    email: str | None
    full_name: str | None
    not_placement_placed: bool
    rule_labels: dict[UUID, str]


@dataclass(frozen=True, slots=True)
class MembershipState:
    scope_ids: ScopeIds
    cycle_archived: bool
    now: datetime
    cycle: CycleRow | None
    membership: MembershipRow | None


@dataclass(frozen=True, slots=True)
class BulkMembershipState:
    scope_ids: ScopeIds
    cycle_archived: bool
    now: datetime
    cycle: CycleRow | None
    memberships: tuple[MembershipRow, ...]


def _membership_row(row: sa.RowMapping) -> MembershipRow:
    return MembershipRow(
        id=row["id"],
        cycle_id=row["cycle_id"],
        enrollment_id=row["enrollment_id"],
        status=MembershipStatus(row["status"]),
        outcome_tag=OutcomeTag(row["outcome_tag"]) if row["outcome_tag"] else None,
        email=str(row["email"]),
        full_name=str(row["full_name"]),
        roll_number=str(row["roll_number"]) if row["roll_number"] else None,
    )


_MEMBERSHIP_SELECT = """
    SELECT m.id, m.cycle_id, m.enrollment_id, m.status, m.outcome_tag,
           u.email, u.full_name, e.roll_number
    FROM cycle_memberships m
    JOIN enrollments e ON e.id = m.enrollment_id
    JOIN users u ON u.id = e.user_id
"""


async def _now(tx: AsyncSession) -> datetime:
    return cast(datetime, await tx.scalar(sa.select(sa.func.now())))


async def _fetch_membership(
    tx: AsyncSession,
    *,
    cycle_id: UUID,
    membership_id: UUID | None = None,
    enrollment_id: UUID | None = None,
    lock: bool,
) -> MembershipRow | None:
    row = (
        await tx.execute(
            sa.text(
                _MEMBERSHIP_SELECT
                + " WHERE m.cycle_id = :cycle_id"
                + (" AND m.id = :membership_id" if membership_id else "")
                + (" AND m.enrollment_id = :enrollment_id" if enrollment_id else "")
                + (" FOR UPDATE OF m" if lock else "")
            ),
            {
                "cycle_id": cycle_id,
                "membership_id": membership_id,
                "enrollment_id": enrollment_id,
            },
        )
    ).mappings().one_or_none()
    return _membership_row(row) if row is not None else None


async def _load_join(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> JoinState:
    if not isinstance(input_value, JoinRequestInput):
        raise TypeError("join_cycle requires a JoinRequestInput")
    cycle = await fetch_cycle(tx, input_value.cycle_id, lock=lock)
    profile = (
        await tx.execute(
            sa.text(
                # `_PROFILE_SELECT` carries `is_dual_major` like any other
                # profile column now (the design review section 4.32); PRO-1's
                # conditional secondary-branch requirement and ELG-2's
                # dual-major rules both read it from there.
                f"SELECT {_PROFILE_SELECT}, p.declared_at, e.roll_number, u.full_name, "  # noqa: S608
                "u.email "
                "FROM enrollments e "
                "JOIN users u ON u.id = e.user_id "
                "LEFT JOIN profiles p ON p.enrollment_id = e.id "
                "WHERE e.id = :enrollment_id"
            ),
            {"enrollment_id": input_value.enrollment_id},
        )
    ).mappings().one_or_none()
    resume_count = await tx.scalar(
        sa.text("SELECT count(*) FROM resumes WHERE enrollment_id = :enrollment_id"),
        {"enrollment_id": input_value.enrollment_id},
    )
    resume_owned = await tx.scalar(
        sa.text(
            "SELECT count(*) FROM resumes "
            "WHERE id = :resume_id AND enrollment_id = :enrollment_id"
        ),
        {
            "resume_id": input_value.default_resume_id,
            "enrollment_id": input_value.enrollment_id,
        },
    )
    policy = await fetch_policy(tx, input_value.cycle_id)
    join_rule = (policy or {}).get("join_rule")
    return JoinState(
        scope_ids=ScopeIds(
            cycle_id=input_value.cycle_id, enrollment_id=input_value.enrollment_id
        ),
        cycle_archived=cycle is not None and cycle.archived_at is not None,
        now=await _now(tx),
        cycle=cycle,
        policy=policy,
        membership=await _fetch_membership(
            tx,
            cycle_id=input_value.cycle_id,
            enrollment_id=input_value.enrollment_id,
            lock=lock,
        ),
        membership_id=uuid4(),
        profile=dict(profile) if profile is not None else None,
        resume_count=int(resume_count or 0),
        resume_owned=bool(resume_owned),
        email=str(profile["email"]) if profile is not None else None,
        full_name=str(profile["full_name"]) if profile is not None else None,
        not_placement_placed=not await placement_placed_global(
            tx, input_value.enrollment_id
        ),
        # A rejection a student reads must name programs and branches, not
        # the UUIDs the rule stores them as (Behavior ELG-2).
        rule_labels=await resolve_labels(
            tx, taxonomy_ids(cast(dict[str, object] | None, join_rule))
        ),
    )


def _window_reasons(
    cycle: CycleRow,
    now: datetime,
    overrides: tuple[ApplicableOverride, ...],
) -> tuple[list[Reason], list[UUID]]:
    """CYC-1's active flag plus CYC-3's overrideable registration dates."""
    reasons: list[Reason] = []
    if not cycle.is_active:
        reasons.append(
            Reason(
                code=CYCLE_INACTIVE,
                human="The cycle is not open for registration",
                path="cycle_id",
            )
        )
    window = evaluate_cycle_registration_window(
        now=now,
        opens_at=cycle.registration_opens_at,
        closes_at=cycle.registration_closes_at,
        overrides=gate_overrides(overrides),
    )
    reasons.extend(window.failures)
    return reasons, list(window.applied_override_ids)


def _join_gate_reasons(
    state: JoinState,
    input_value: JoinRequestInput,
    cycle: CycleRow,
    policy: Policy,
    overrides: object,
) -> tuple[list[Reason], list[UUID]]:
    """Everything CYC-3 asks of someone entering a cycle, in one place.

    Both ways in run this: a first ``join_cycle`` and the ``rerequest_membership``
    of the design review section 4.34.  Written once because the two must not be able to
    disagree about what joining requires -- re-entry that skipped the profile
    checklist or the join rule would put someone into ``active`` that a fresh
    join would have refused.  Every failure is collected, never just the first,
    so the student fixes their profile in one pass.
    """
    resolved = cast("tuple[ApplicableOverride, ...]", overrides)
    reasons, applied = _window_reasons(cycle, state.now, resolved)
    if not input_value.consent:
        reasons.append(
            Reason(
                code=CONSENT_REQUIRED,
                human="You must acknowledge the cycle's participation terms to join",
                path="consent",
            )
        )
    if not state.resume_owned:
        reasons.append(
            Reason(
                code=RESUME_NOT_FOUND,
                human="Choose a default resume from your own library",
                path="default_resume_id",
            )
        )

    profile = state.profile or {}
    reasons.extend(
        check_profile_completeness(
            profile,
            resume_count=state.resume_count,
            declared=profile.get("declared_at") is not None,
        )
    )

    join_rule = policy.join_rule.value
    outcome = (
        evaluate(
            cast(dict[str, object], join_rule),
            profile,
            RuleContext(not_placement_placed=state.not_placement_placed),
            labels=state.rule_labels,
        )
        if join_rule is not None
        else None
    )
    join_gate = evaluate_cycle_join_rule(outcome, gate_overrides(resolved))
    reasons.extend(join_gate.failures)
    applied.extend(join_gate.applied_override_ids)
    return reasons, applied


def _decide_join_cycle(
    input_value: BaseModel,
    state: object,
    _policy: object,
    overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """Join a cycle, landing pending or active per policy (Behavior CYC-3)."""
    if not isinstance(input_value, JoinCycleInput) or not isinstance(state, JoinState):
        raise TypeError("Invalid join_cycle decision input")
    if state.cycle is None:
        return Rejection(
            reasons=[Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")]
        )
    if state.policy is None:
        raise RuntimeError(f"Cycle {state.cycle.id} has no policy row")

    if state.membership is not None:
        return Rejection(
            reasons=[
                Reason(
                    code=MEMBERSHIP_EXISTS,
                    human=(
                        "You already have a "
                        f"{state.membership.status.value} membership in this cycle"
                    ),
                    path="cycle_id",
                )
            ]
        )

    policy = resolve_policy(state.cycle.kind, cycle_policy=state.policy)
    reasons, applied = _join_gate_reasons(
        state, input_value, state.cycle, policy, overrides
    )
    if reasons:
        return Rejection(reasons=reasons)

    requires_approval = policy.membership_requires_approval.value
    status = MembershipStatus.PENDING if requires_approval else MembershipStatus.ACTIVE
    transition = decide_membership_transition(
        "join" if requires_approval else "join_active",
        from_status=None,
        actor=TransitionActor.STUDENT,
    )
    if isinstance(transition, Rejection):
        return transition

    deferred: list[Deferred] = []
    if status is MembershipStatus.PENDING and state.email is not None:
        deferred.append(
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": "membership_pending",
                    "recipient": state.email,
                    "context": {
                        "student": state.full_name,
                        "cycle": state.cycle.name,
                        "cycle_id": str(state.cycle.id),
                    },
                },
            )
        )

    return Plan(
        state_ops=[
            StateOp(
                op="insert",
                model="cycle_memberships",
                values={
                    "id": state.membership_id,
                    "cycle_id": state.cycle.id,
                    "enrollment_id": input_value.enrollment_id,
                    "status": status.value,
                    "default_resume_id": input_value.default_resume_id,
                    "consented_at": state.now,
                    "auto_created": False,
                },
            )
        ],
        events=[],
        deferred=deferred,
        audit={
            "subject_type": "cycle_membership",
            "subject_id": state.membership_id,
            "details": {
                "cycle_id": str(state.cycle.id),
                "enrollment_id": str(input_value.enrollment_id),
                "status": status.value,
                "requires_approval": requires_approval,
                "applied_override_ids": [str(item) for item in applied],
                "actor_user_id": str(actor.user_id) if actor.user_id else None,
            },
        },
        summary={
            "cycle_id": str(state.cycle.id),
            "membership_id": str(state.membership_id),
            "enrollment_id": str(input_value.enrollment_id),
            "status": status.value,
            "changed": True,
        },
    )


async def _load_bulk_approve(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> BulkMembershipState:
    if not isinstance(input_value, ApproveMembershipsInput):
        raise TypeError("approve_memberships requires ApproveMembershipsInput")
    cycle = await fetch_cycle(tx, input_value.cycle_id, lock=lock)
    identifiers = [row["identifier"] for row in input_value.rows if "identifier" in row]
    membership_ids = [
        UUID(row["membership_id"]) for row in input_value.rows if "membership_id" in row
    ]
    rows = (
        await tx.execute(
            sa.text(
                _MEMBERSHIP_SELECT
                + " WHERE m.cycle_id = :cycle_id AND (m.id = ANY(:membership_ids) "
                "OR lower(u.email) = ANY(:identifiers) "
                "OR lower(e.roll_number) = ANY(:identifiers))"
                + (" FOR UPDATE OF m" if lock else "")
            ),
            {
                "cycle_id": input_value.cycle_id,
                "membership_ids": membership_ids,
                "identifiers": [item.strip().casefold() for item in identifiers],
            },
        )
    ).mappings().all()
    return BulkMembershipState(
        scope_ids=ScopeIds(cycle_id=input_value.cycle_id),
        cycle_archived=cycle is not None and cycle.archived_at is not None,
        now=await _now(tx),
        cycle=cycle,
        memberships=tuple(_membership_row(row) for row in rows),
    )


def _resolve_row(
    row: dict[str, str], memberships: tuple[MembershipRow, ...]
) -> MembershipRow | None:
    if "membership_id" in row:
        target = UUID(row["membership_id"])
        return next((item for item in memberships if item.id == target), None)
    identifier = row["identifier"].strip().casefold()
    return next(
        (
            item
            for item in memberships
            if item.email.casefold() == identifier
            or (item.roll_number or "").casefold() == identifier
        ),
        None,
    )


def _decide_approve_memberships(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """Approve pending memberships in bulk (Behavior CYC-3, RND-2 contract)."""
    if not isinstance(input_value, ApproveMembershipsInput) or not isinstance(
        state, BulkMembershipState
    ):
        raise TypeError("Invalid approve_memberships decision input")
    if state.cycle is None:
        return Rejection(
            reasons=[Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")]
        )

    results: list[dict[str, object]] = []
    operations: list[StateOp] = []
    deferred: list[Deferred] = []
    seen: set[UUID] = set()

    for row in input_value.rows:
        label = row.get("identifier") or row.get("membership_id", "")
        membership = _resolve_row(row, state.memberships)
        if membership is None:
            results.append(
                {
                    "identifier": label,
                    "membership_id": None,
                    "status": "error",
                    "reason": UNMATCHED_IDENTIFIER,
                }
            )
            continue
        if membership.id in seen:
            results.append(
                {
                    "identifier": label,
                    "membership_id": str(membership.id),
                    "status": "skipped",
                    "reason": DUPLICATE_ROW,
                }
            )
            continue
        transition = decide_membership_transition(
            "approve", from_status=membership.status, actor=TransitionActor.STAFF
        )
        if isinstance(transition, Rejection):
            results.append(
                {
                    "identifier": label,
                    "membership_id": str(membership.id),
                    "status": "skipped",
                    "reason": INVALID_TRANSITION,
                }
            )
            continue

        seen.add(membership.id)
        operations.append(
            StateOp(
                op="update",
                model="cycle_memberships",
                values={
                    "status": MembershipStatus.ACTIVE.value,
                    "decided_by": actor.user_id,
                    "decided_at": state.now,
                    "rejection_reason": None,
                },
                where={"id": membership.id},
            )
        )
        deferred.append(
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": "membership_approved",
                    "recipient": membership.email,
                    "context": {
                        "student": membership.full_name,
                        "cycle": state.cycle.name,
                        "cycle_id": str(state.cycle.id),
                    },
                },
            )
        )
        results.append(
            {
                "identifier": label,
                "membership_id": str(membership.id),
                "status": "applied",
                "reason": None,
            }
        )

    return Plan(
        state_ops=operations,
        events=[],
        deferred=deferred,
        audit=None,
        summary={"rows": results},
    )


# Staff address a membership by its id, from the queue entry in front of them.
# A student addresses their own by enrollment and never sees an id, so the two
# student commands -- join and re-request -- load through `_load_join` instead.
async def _load_membership_by_id(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> MembershipState:
    if not isinstance(input_value, (RejectMembershipInput, SetOutcomeTagInput)):
        raise TypeError("Membership commands require a membership-target input")
    cycle_id = input_value.cycle_id
    membership_id = input_value.membership_id
    enrollment_id = None
    cycle = await fetch_cycle(tx, cycle_id, lock=lock)
    return MembershipState(
        scope_ids=ScopeIds(cycle_id=cycle_id, enrollment_id=enrollment_id),
        cycle_archived=cycle is not None and cycle.archived_at is not None,
        now=await _now(tx),
        cycle=cycle,
        membership=await _fetch_membership(
            tx,
            cycle_id=cycle_id,
            membership_id=membership_id,
            enrollment_id=enrollment_id,
            lock=lock,
        ),
    )


def _membership_not_found() -> Rejection:
    return Rejection(
        reasons=[
            Reason(
                code=MEMBERSHIP_NOT_FOUND,
                human="No membership exists for this cycle",
                path="membership_id",
            )
        ]
    )


def _decide_reject_membership(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """Reject a pending membership with a mandatory reason (Behavior CYC-3)."""
    if not isinstance(input_value, RejectMembershipInput) or not isinstance(
        state, MembershipState
    ):
        raise TypeError("Invalid reject_membership decision input")
    if state.cycle is None:
        return Rejection(
            reasons=[Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")]
        )
    if state.membership is None:
        return _membership_not_found()
    transition = decide_membership_transition(
        "reject",
        from_status=state.membership.status,
        actor=TransitionActor.STAFF,
        reason=input_value.reason,
    )
    if isinstance(transition, Rejection):
        return transition

    return Plan(
        state_ops=[
            StateOp(
                op="update",
                model="cycle_memberships",
                values={
                    "status": MembershipStatus.REJECTED.value,
                    "decided_by": actor.user_id,
                    "decided_at": state.now,
                    "rejection_reason": input_value.reason,
                },
                where={"id": state.membership.id},
            )
        ],
        events=[],
        deferred=[
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": "membership_rejected",
                    "recipient": state.membership.email,
                    "context": {
                        "student": state.membership.full_name,
                        "cycle": state.cycle.name,
                        "cycle_id": str(state.cycle.id),
                        "reason": input_value.reason,
                    },
                },
            )
        ],
        audit={
            "subject_type": "cycle_membership",
            "subject_id": state.membership.id,
            "details": {
                "from_status": state.membership.status.value,
                "to_status": MembershipStatus.REJECTED.value,
                "reason": input_value.reason,
            },
        },
        summary={
            "cycle_id": str(state.cycle.id),
            "membership_id": str(state.membership.id),
            "enrollment_id": str(state.membership.enrollment_id),
            "status": MembershipStatus.REJECTED.value,
            "changed": True,
        },
    )


def _decide_rerequest_membership(
    input_value: BaseModel,
    state: object,
    _policy: object,
    overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """Re-enter a cycle after a rejection or a withdrawal (CYC-3, the design review 4.34).

    Not a status flip: this runs the *whole* join gauntlet through the same
    helper ``join_cycle`` runs, and honours ``membership_requires_approval`` the
    way first joining does, so nothing reaches ``active`` that a fresh join
    would have refused.  The applications the exit auto-withdrew stay
    auto-withdrawn -- CYC-3 keeps reinstatement a separate, per-application
    staff decision.
    """
    if not isinstance(input_value, RerequestMembershipInput) or not isinstance(
        state, JoinState
    ):
        raise TypeError("Invalid rerequest_membership decision input")
    if state.cycle is None:
        return Rejection(
            reasons=[Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")]
        )
    if state.policy is None:
        raise RuntimeError(f"Cycle {state.cycle.id} has no policy row")
    if state.membership is None:
        return _membership_not_found()

    policy = resolve_policy(state.cycle.kind, cycle_policy=state.policy)
    requires_approval = policy.membership_requires_approval.value
    transition = decide_membership_transition(
        "rerequest" if requires_approval else "rerequest_active",
        from_status=state.membership.status,
        actor=TransitionActor.STUDENT,
    )
    if isinstance(transition, Rejection):
        return transition
    reasons, applied = _join_gate_reasons(
        state, input_value, state.cycle, policy, overrides
    )
    if reasons:
        return Rejection(reasons=reasons)

    status = transition.to_status
    deferred: list[Deferred] = []
    if status is MembershipStatus.PENDING and state.membership.email:
        deferred.append(
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": "membership_pending",
                    "recipient": state.membership.email,
                    "context": {
                        "student": state.membership.full_name,
                        "cycle": state.cycle.name,
                        "cycle_id": str(state.cycle.id),
                    },
                },
            )
        )

    return Plan(
        state_ops=[
            StateOp(
                op="update",
                model="cycle_memberships",
                values={
                    "status": status.value,
                    # The student re-consented and re-chose just now; carrying
                    # the values from the membership they left would record a
                    # consent they did not give this time.
                    "default_resume_id": input_value.default_resume_id,
                    "consented_at": state.now,
                    "decided_by": None,
                    "decided_at": None,
                    "rejection_reason": None,
                },
                where={"id": state.membership.id},
            )
        ],
        events=[],
        deferred=deferred,
        audit={
            "subject_type": "cycle_membership",
            "subject_id": state.membership.id,
            "details": {
                "from_status": state.membership.status.value,
                "to_status": status.value,
                "requires_approval": requires_approval,
                "applied_override_ids": [str(item) for item in applied],
                "actor_user_id": str(actor.user_id) if actor.user_id else None,
            },
        },
        summary={
            "cycle_id": str(state.cycle.id),
            "membership_id": str(state.membership.id),
            "enrollment_id": str(state.membership.enrollment_id),
            "status": status.value,
            "changed": True,
        },
    )


def _decide_set_outcome_tag(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Record a compliance outcome tag on a membership (Behavior ANA-3)."""
    if not isinstance(input_value, SetOutcomeTagInput) or not isinstance(
        state, MembershipState
    ):
        raise TypeError("Invalid set_outcome_tag decision input")
    if state.cycle is None:
        return Rejection(
            reasons=[Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")]
        )
    if state.membership is None:
        return _membership_not_found()

    before = state.membership.outcome_tag
    after = input_value.outcome_tag
    changed = before is not after
    return Plan(
        state_ops=(
            [
                StateOp(
                    op="update",
                    model="cycle_memberships",
                    values={"outcome_tag": after.value if after else None},
                    where={"id": state.membership.id},
                )
            ]
            if changed
            else []
        ),
        events=[],
        deferred=[],
        audit={
            "subject_type": "cycle_membership",
            "subject_id": state.membership.id,
            "details": {
                "before": before.value if before else None,
                "after": after.value if after else None,
            },
        },
        summary={
            "cycle_id": str(state.cycle.id),
            "membership_id": str(state.membership.id),
            "outcome_tag": after.value if after else None,
            "changed": changed,
        },
    )


def register_membership_commands(registry: Registry) -> None:
    registry.command(
        name="join_cycle",
        input_model=JoinCycleInput,
        output_model=MembershipSummary,
        actor="student",
        scope="cycle",
        loader=_load_join,
        rule_domains=JOIN_RULE_DOMAINS,
        spec_ids=("CYC-3", "INT-2"),
    )(_decide_join_cycle)
    registry.command(
        name="approve_memberships",
        input_model=ApproveMembershipsInput,
        output_model=BulkMembershipSummary,
        actor="staff",
        scope="cycle",
        loader=_load_bulk_approve,
        rule_domains=(),
        spec_ids=("CYC-3",),
        rate_limit="10/min",
        execution_mode="bulk",
    )(_decide_approve_memberships)
    registry.command(
        name="reject_membership",
        input_model=RejectMembershipInput,
        output_model=MembershipSummary,
        actor="staff",
        scope="cycle",
        loader=_load_membership_by_id,
        rule_domains=(),
        spec_ids=("CYC-3",),
    )(_decide_reject_membership)
    registry.command(
        name="rerequest_membership",
        input_model=RerequestMembershipInput,
        output_model=MembershipSummary,
        actor="student",
        scope="cycle",
        # Re-entry re-runs every join check (the design review section 4.34), so it
        # needs everything joining needs: the profile, the resume library, the
        # placement derivation and the join rule's labels.
        loader=_load_join,
        rule_domains=JOIN_RULE_DOMAINS,
        spec_ids=("CYC-3", "INT-2"),
    )(_decide_rerequest_membership)
    registry.command(
        name="set_outcome_tag",
        input_model=SetOutcomeTagInput,
        output_model=OutcomeTagSummary,
        actor="staff",
        scope="cycle",
        loader=_load_membership_by_id,
        rule_domains=(),
        spec_ids=("ANA-3", "CYC-3"),
    )(_decide_set_outcome_tag)


class WithdrawMembershipInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    enrollment_id: UUID


class RemoveMembershipInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    membership_id: UUID
    reason: str

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("a removal reason is required")
        return stripped


class RestoreMembershipInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    membership_id: UUID


class MembershipExitSummary(BaseModel):
    cycle_id: UUID
    membership_id: UUID
    enrollment_id: UUID
    status: MembershipStatus
    auto_withdrawn: list[dict[str, object]]
    untouched: list[dict[str, object]]
    changed: bool


@dataclass(frozen=True, slots=True)
class ExitApplicationRow:
    application_id: UUID
    status: ApplicationStatus
    current_round_id: UUID | None
    email: str
    full_name: str
    job_title: str


@dataclass(frozen=True, slots=True)
class MembershipExitState:
    scope_ids: ScopeIds
    cycle_archived: bool
    now: datetime
    cycle: CycleRow | None
    membership: MembershipRow | None
    applications: tuple[ExitApplicationRow, ...]


CYCLE_APPLICATIONS_SELECT = """
    SELECT a.id, a.status, a.current_round_id, u.email, u.full_name, j.title
    FROM applications a
    JOIN jobs j ON j.id = a.job_id
    JOIN enrollments e ON e.id = a.enrollment_id
    JOIN users u ON u.id = e.user_id
    WHERE j.cycle_id = :cycle_id
"""


def exit_application_row(row: sa.RowMapping) -> ExitApplicationRow:
    return ExitApplicationRow(
        application_id=row["id"],
        status=ApplicationStatus(row["status"]),
        current_round_id=row["current_round_id"],
        email=str(row["email"]),
        full_name=str(row["full_name"]),
        job_title=str(row["title"]),
    )


async def fetch_cycle_applications(
    tx: AsyncSession,
    *,
    cycle_id: UUID,
    enrollment_id: UUID | None,
    lock: bool,
) -> tuple[ExitApplicationRow, ...]:
    """Load the cycle's applications the cascade may touch, locked when applying."""
    rows = (
        await tx.execute(
            sa.text(
                CYCLE_APPLICATIONS_SELECT
                + (" AND a.enrollment_id = :enrollment_id" if enrollment_id else "")
                + " ORDER BY a.id"
                + (" FOR UPDATE OF a" if lock else "")
            ),
            {"cycle_id": cycle_id, "enrollment_id": enrollment_id},
        )
    ).mappings().all()
    return tuple(exit_application_row(row) for row in rows)


def cascade_plan_parts(
    applications: tuple[ExitApplicationRow, ...],
    *,
    cycle: CycleRow,
    trigger: MembershipExitTrigger,
) -> tuple[list[StateOp], list[Event], list[Deferred], list[dict[str, object]]]:
    """Realise the pure CYC-4 cascade as state ops, events, and notifications."""
    by_id = {row.application_id: row for row in applications}
    actions = compute_membership_exit_cascade(
        tuple(
            MembershipApplicationState(
                application_id=row.application_id,
                status=row.status,
                current_round_id=row.current_round_id,
            )
            for row in applications
        ),
        trigger=trigger,
    )

    operations: list[StateOp] = []
    events: list[Event] = []
    deferred: list[Deferred] = []
    reported: list[dict[str, object]] = []
    for action in actions:
        row = by_id[action.application_id]
        operations.append(
            StateOp(
                op="update",
                model="applications",
                # current_round_id is deliberately untouched: CYC-4 preserves the
                # position underneath so reinstatement to the exact round works.
                values={"status": action.to_status.value},
                where={"id": action.application_id},
            )
        )
        events.append(
            Event(
                application_id=action.application_id,
                event_type=action.event_type,
                from_status=action.from_status.value,
                to_status=action.to_status.value,
                from_round=action.from_round_id,
                to_round=None,
                reason=None,
                payload=dict(action.payload),
            )
        )
        deferred.append(
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": "auto_withdrawn",
                    "recipient": row.email,
                    "context": {
                        "student": row.full_name,
                        "trigger": withdrawal_trigger(trigger.value),
                        "cycle": cycle.name,
                        "job": row.job_title,
                        "cycle_id": str(cycle.id),
                    },
                },
            )
        )
        reported.append(
            {
                "application_id": str(action.application_id),
                "full_name": row.full_name,
                "job": row.job_title,
                "from_status": action.from_status.value,
            }
        )
    return operations, events, deferred, reported


def untouched_applications(
    applications: tuple[ExitApplicationRow, ...],
) -> list[dict[str, object]]:
    """Live applications the cascade cannot move, named so staff can act on them.

    APP-4.13 covers in_progress and pending_offer only; an offered or accepted
    application carries an offer, and only terminate_offer may unwind it.  The
    preview names them rather than silently leaving them behind (the design review C3).
    """
    return [
        {
            "application_id": str(row.application_id),
            "full_name": row.full_name,
            "job": row.job_title,
            "status": row.status.value,
            "suggested_command": "terminate_offer",
        }
        for row in applications
        if row.status in {ApplicationStatus.OFFERED, ApplicationStatus.ACCEPTED}
    ]


async def _load_exit(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> MembershipExitState:
    if not isinstance(
        input_value,
        (WithdrawMembershipInput, RemoveMembershipInput, RestoreMembershipInput),
    ):
        raise TypeError("Membership exit commands require an exit input")
    cycle_id = input_value.cycle_id
    cycle = await fetch_cycle(tx, cycle_id, lock=lock)
    membership = await _fetch_membership(
        tx,
        cycle_id=cycle_id,
        membership_id=(
            input_value.membership_id
            if isinstance(input_value, (RemoveMembershipInput, RestoreMembershipInput))
            else None
        ),
        enrollment_id=(
            input_value.enrollment_id
            if isinstance(input_value, WithdrawMembershipInput)
            else None
        ),
        lock=lock,
    )
    applications = (
        await fetch_cycle_applications(
            tx, cycle_id=cycle_id, enrollment_id=membership.enrollment_id, lock=lock
        )
        if membership is not None
        and not isinstance(input_value, RestoreMembershipInput)
        else ()
    )
    return MembershipExitState(
        scope_ids=ScopeIds(
            cycle_id=cycle_id,
            enrollment_id=membership.enrollment_id if membership else None,
        ),
        cycle_archived=cycle is not None and cycle.archived_at is not None,
        now=await _now(tx),
        cycle=cycle,
        membership=membership,
        applications=applications,
    )


def _decide_exit(
    name: str,
    to_status: MembershipStatus,
    *,
    event_key: str | None,
    actor_kind: TransitionActor,
) -> Decider:
    def decide(
        input_value: BaseModel,
        state: object,
        _policy: object,
        _overrides: object,
        actor: ActorContext,
    ) -> Plan | Rejection:
        if not isinstance(state, MembershipExitState):
            raise TypeError(f"Invalid {name} decision input")
        if state.cycle is None:
            return Rejection(
                reasons=[Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")]
            )
        if state.membership is None:
            return _membership_not_found()
        reason = (
            input_value.reason
            if isinstance(input_value, RemoveMembershipInput)
            else None
        )
        transition = decide_membership_transition(
            name, from_status=state.membership.status, actor=actor_kind, reason=reason
        )
        if isinstance(transition, Rejection):
            return transition

        operations, events, deferred, cascaded = cascade_plan_parts(
            state.applications,
            cycle=state.cycle,
            trigger=MembershipExitTrigger.MEMBERSHIP_EXIT,
        )
        values: dict[str, object] = {"status": to_status.value}
        if actor_kind is TransitionActor.STAFF:
            values |= {"decided_by": actor.user_id, "decided_at": state.now}
        operations.insert(
            0,
            StateOp(
                op="update",
                model="cycle_memberships",
                values=values,
                where={"id": state.membership.id},
            ),
        )
        if event_key is not None:
            deferred.insert(
                0,
                Deferred(
                    task="deliver_notification",
                    args={
                        "event_key": event_key,
                        "recipient": state.membership.email,
                        "context": {
                            "student": state.membership.full_name,
                            "cycle": state.cycle.name,
                            "cycle_id": str(state.cycle.id),
                            "reason": reason,
                        },
                    },
                ),
            )

        return Plan(
            state_ops=operations,
            events=events,
            deferred=deferred,
            audit={
                "subject_type": "cycle_membership",
                "subject_id": state.membership.id,
                "details": {
                    "from_status": state.membership.status.value,
                    "to_status": to_status.value,
                    "reason": reason,
                    "auto_withdrawn": cascaded,
                },
            },
            summary={
                "cycle_id": str(state.cycle.id),
                "membership_id": str(state.membership.id),
                "enrollment_id": str(state.membership.enrollment_id),
                "status": to_status.value,
                "auto_withdrawn": cascaded,
                "untouched": untouched_applications(state.applications),
                "changed": True,
            },
        )

    decide.__doc__ = (
        f"Move a membership to {to_status.value}, cascading per Behavior CYC-4."
    )
    return decide



class ArchiveCycleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID


class ArchiveCycleSummary(BaseModel):
    cycle_id: UUID
    archived_at: datetime | None
    auto_withdrawn: list[dict[str, object]]
    untouched: list[dict[str, object]]
    changed: bool


@dataclass(frozen=True, slots=True)
class ArchiveState:
    scope_ids: ScopeIds
    cycle_archived: bool
    now: datetime
    cycle: CycleRow | None
    applications: tuple[ExitApplicationRow, ...]


async def _load_archive(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> ArchiveState:
    if not isinstance(input_value, ArchiveCycleInput):
        raise TypeError("archive_cycle requires ArchiveCycleInput")
    cycle = await fetch_cycle(tx, input_value.cycle_id, lock=lock)
    return ArchiveState(
        scope_ids=ScopeIds(cycle_id=input_value.cycle_id),
        cycle_archived=cycle is not None and cycle.archived_at is not None,
        now=cast(datetime, await tx.scalar(sa.select(sa.func.now()))),
        cycle=cycle,
        applications=await fetch_cycle_applications(
            tx, cycle_id=input_value.cycle_id, enrollment_id=None, lock=lock
        ),
    )


def _decide_archive_cycle(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Force-close a cycle: auto-withdraw its live applications (Behavior CYC-1).

    Re-archiving is impossible by construction: check_scope rejects every
    cycle-scoped command on an archived cycle, this one included.
    """
    if not isinstance(input_value, ArchiveCycleInput) or not isinstance(
        state, ArchiveState
    ):
        raise TypeError("Invalid archive_cycle decision input")
    if state.cycle is None:
        return Rejection(
            reasons=[Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")]
        )

    operations, events, deferred, cascaded = cascade_plan_parts(
        state.applications,
        cycle=state.cycle,
        trigger=MembershipExitTrigger.ARCHIVAL,
    )
    operations.append(
        StateOp(
            op="update",
            model="cycles",
            values={"archived_at": state.now},
            where={"id": state.cycle.id},
        )
    )
    untouched = untouched_applications(state.applications)
    return Plan(
        state_ops=operations,
        events=events,
        deferred=deferred,
        audit={
            "subject_type": "cycle",
            "subject_id": state.cycle.id,
            "details": {
                "auto_withdrawn": cascaded,
                "untouched": untouched,
            },
        },
        summary={
            "cycle_id": str(state.cycle.id),
            "archived_at": state.now.isoformat(),
            "auto_withdrawn": cascaded,
            "untouched": untouched,
            "changed": True,
        },
    )


def register_membership_exit_commands(registry: Registry) -> None:
    registry.command(
        name="withdraw_membership",
        input_model=WithdrawMembershipInput,
        output_model=MembershipExitSummary,
        actor="student",
        scope="cycle",
        loader=_load_exit,
        rule_domains=(),
        spec_ids=("CYC-3", "CYC-4"),
    )(
        _decide_exit(
            "withdraw",
            MembershipStatus.WITHDRAWN,
            event_key=None,
            actor_kind=TransitionActor.STUDENT,
        )
    )
    registry.command(
        name="remove_membership",
        input_model=RemoveMembershipInput,
        output_model=MembershipExitSummary,
        actor="staff",
        scope="cycle",
        loader=_load_exit,
        rule_domains=(),
        spec_ids=("CYC-3", "CYC-4"),
    )(
        _decide_exit(
            "remove",
            MembershipStatus.REMOVED,
            event_key="membership_removed",
            actor_kind=TransitionActor.STAFF,
        )
    )
    registry.command(
        name="restore_membership",
        input_model=RestoreMembershipInput,
        output_model=MembershipExitSummary,
        actor="staff",
        scope="cycle",
        loader=_load_exit,
        rule_domains=(),
        spec_ids=("CYC-3",),
    )(
        _decide_exit(
            "restore",
            MembershipStatus.ACTIVE,
            event_key="membership_restored",
            actor_kind=TransitionActor.STAFF,
        )
    )
    registry.command(
        name="archive_cycle",
        input_model=ArchiveCycleInput,
        output_model=ArchiveCycleSummary,
        actor="admin",
        scope="cycle",
        loader=_load_archive,
        rule_domains=(),
        spec_ids=("CYC-1", "CYC-4"),
    )(_decide_archive_cycle)
