"""Pure standing-gate evaluation for ELG-3 and DER-1 inputs.

Every ``human`` here is written for the student, because JOB-4 requires an
ineligible job card to show "the exact failing reasons" and the student is the
overwhelming reader of them.  Staff see the same strings in an impact preview,
where reading one student's own view of the card is exactly the point
(the design review section 4.19).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.core.errors import (
    BLOCKED_BY_OVERRIDE,
    CYCLE_ARCHIVED,
    DEADLINE_PASSED,
    DUPLICATE_APPLICATION,
    JOB_CANCELLED,
    JOB_UNPUBLISHED,
    JOIN_RULE_FAILED,
    MEMBERSHIP_NOT_ACTIVE,
    OFFER_CAP_REACHED,
    OUTCOME_GATE_INTERNSHIP,
    OUTCOME_GATE_PLACEMENT,
    PENALTY_ACTIVE,
    REGISTRATION_CLOSED,
    WINDOW_CLOSED,
)
from app.core.plan import Reason
from app.domain.rules import EvaluationResult
from app.domain.shared import CycleKind, MembershipStatus, Outcome, RuleDomain


@dataclass(frozen=True, slots=True)
class GateOverride:
    id: UUID
    rule_domain: RuleDomain
    allow: bool = True


@dataclass(frozen=True, slots=True)
class GateContext:
    membership_status: MembershipStatus
    job_published: bool
    job_cancelled: bool
    cycle_archived: bool
    application_deadline: datetime | None
    now: datetime
    outcome: Outcome
    cycle_kind: CycleKind
    has_active_duplicate: bool
    penalty_active: bool
    penalty_blocks_applications: bool
    placement_placed_global: bool
    internship_placed_in_cycle: bool
    max_accepted_offers: int | None
    cap_used: int
    applicable_overrides: tuple[GateOverride, ...] = ()


@dataclass(frozen=True, slots=True)
class GateResult:
    failures: tuple[Reason, ...]
    applied_override_ids: tuple[UUID, ...] = ()

    @property
    def verdict(self) -> bool:
        return not self.failures


#: The override domains each gate can consult.  Command ``rule_domains`` are an
#: executor contract, so the static contract test follows loader/decider calls
#: to this catalog instead of trying to infer a generic helper's dynamic domain
#: argument.  Private wrappers are included deliberately: a command that calls
#: one directly still has to declare everything it can consult.
GATE_DOMAINS: Mapping[str, frozenset[RuleDomain]] = {
    "evaluate_gates": frozenset(
        {
            RuleDomain.APPLICATION_DEADLINE,
            RuleDomain.OUTCOME_GATE,
            RuleDomain.OFFER_CAP,
        }
    ),
    "evaluate_acceptance_constraints": frozenset(
        {RuleDomain.OUTCOME_GATE, RuleDomain.OFFER_CAP}
    ),
    "evaluate_outcome_gate": frozenset({RuleDomain.OUTCOME_GATE}),
    "evaluate_offer_cap": frozenset({RuleDomain.OFFER_CAP}),
    "evaluate_expiry_acceptance_constraints": frozenset(
        {RuleDomain.OUTCOME_GATE, RuleDomain.OFFER_CAP}
    ),
    "evaluate_offer_deadline": frozenset({RuleDomain.OFFER_DEADLINE}),
    "evaluate_edit_window": frozenset({RuleDomain.EDIT_WINDOW}),
    "evaluate_withdraw_window": frozenset({RuleDomain.WITHDRAW_WINDOW}),
    "_evaluate_application_window": frozenset(
        {RuleDomain.EDIT_WINDOW, RuleDomain.WITHDRAW_WINDOW}
    ),
    "evaluate_cycle_registration_window": frozenset(
        {RuleDomain.CYCLE_REGISTRATION_WINDOW}
    ),
    "evaluate_cycle_join_rule": frozenset({RuleDomain.CYCLE_JOIN_RULE}),
    "apply_eligibility_override": frozenset({RuleDomain.ELIGIBILITY}),
    "_append_acceptance_constraints": frozenset(
        {RuleDomain.OUTCOME_GATE, RuleDomain.OFFER_CAP}
    ),
    "_append_override_decision": frozenset(RuleDomain),
}


def evaluate_gates(context: GateContext) -> GateResult:
    """Return every non-overridden ELG-3 failure in the mandated order."""
    failures: list[Reason] = []
    applied: list[UUID] = []

    if context.membership_status is not MembershipStatus.ACTIVE:
        failures.append(
            Reason(
                code=MEMBERSHIP_NOT_ACTIVE,
                human="Your membership in this cycle is not active yet.",
                path="membership_status",
            )
        )

    if context.cycle_archived:
        failures.append(
            Reason(
                code=CYCLE_ARCHIVED,
                human="This cycle has been archived and is no longer accepting applications.",
                path="cycle_archived",
            )
        )
    elif context.job_cancelled:
        failures.append(
            Reason(
                code=JOB_CANCELLED,
                human="This job has been cancelled.",
                path="job_cancelled",
            )
        )
    elif not context.job_published:
        failures.append(
            Reason(
                code=JOB_UNPUBLISHED,
                human="This job is not open for applications.",
                path="job_published",
            )
        )

    deadline_failure = (
        Reason(
            code=DEADLINE_PASSED,
            human="The application deadline has passed.",
            path="application_deadline",
        )
        if context.application_deadline is not None and context.now >= context.application_deadline
        else None
    )
    _append_override_decision(
        failures,
        applied,
        deadline_failure,
        RuleDomain.APPLICATION_DEADLINE,
        context.applicable_overrides,
    )

    if context.has_active_duplicate:
        failures.append(
            Reason(
                code=DUPLICATE_APPLICATION,
                human="You have already applied to this job.",
                path="application",
            )
        )

    if context.penalty_blocks_applications and context.penalty_active:
        failures.append(
            Reason(
                code=PENALTY_ACTIVE,
                human="A disciplinary penalty is blocking your applications in this cycle.",
                path="penalty",
            )
        )

    _append_acceptance_constraints(
        failures,
        applied,
        outcome=context.outcome,
        cycle_kind=context.cycle_kind,
        placement_placed_global=context.placement_placed_global,
        internship_placed_in_cycle=context.internship_placed_in_cycle,
        max_accepted_offers=context.max_accepted_offers,
        cap_used=context.cap_used,
        overrides=context.applicable_overrides,
    )

    return GateResult(failures=tuple(failures), applied_override_ids=tuple(applied))


def evaluate_acceptance_constraints(
    *,
    outcome: Outcome,
    cycle_kind: CycleKind,
    placement_placed_global: bool,
    internship_placed_in_cycle: bool,
    max_accepted_offers: int | None,
    cap_used: int,
    overrides: tuple[GateOverride, ...],
) -> GateResult:
    """Re-check only OFR-3's outcome and cap guards at acceptance time.

    Applying and accepting do not share all standing gates: the offered
    application is itself an active duplicate and its application deadline may
    already have passed.  Keeping this narrow helper beside ``evaluate_gates``
    lets both paths reuse the exact outcome/cap reasons without accidentally
    re-running apply-only guards.
    """
    failures: list[Reason] = []
    applied: list[UUID] = []
    _append_acceptance_constraints(
        failures,
        applied,
        outcome=outcome,
        cycle_kind=cycle_kind,
        placement_placed_global=placement_placed_global,
        internship_placed_in_cycle=internship_placed_in_cycle,
        max_accepted_offers=max_accepted_offers,
        cap_used=cap_used,
        overrides=overrides,
    )
    return GateResult(tuple(failures), tuple(applied))


def evaluate_outcome_gate(
    *,
    outcome: Outcome,
    cycle_kind: CycleKind,
    placement_placed_global: bool,
    internship_placed_in_cycle: bool,
    overrides: tuple[GateOverride, ...],
) -> GateResult:
    """Evaluate only the portal-wide or cycle-local placed-state gate."""
    failure: Reason | None = None
    if outcome is Outcome.PLACEMENT and placement_placed_global:
        failure = Reason(
            code=OUTCOME_GATE_PLACEMENT,
            human=(
                "You have already accepted a placement offer, so placement "
                "roles are closed to you."
            ),
            path="outcome",
        )
    elif (
        outcome is Outcome.INTERNSHIP
        and cycle_kind is CycleKind.INTERNSHIP
        and internship_placed_in_cycle
    ):
        failure = Reason(
            code=OUTCOME_GATE_INTERNSHIP,
            human="You have already accepted an internship offer in this cycle.",
            path="outcome",
        )
    failures: list[Reason] = []
    applied: list[UUID] = []
    _append_override_decision(
        failures,
        applied,
        failure,
        RuleDomain.OUTCOME_GATE,
        overrides,
    )
    return GateResult(tuple(failures), tuple(applied))


def evaluate_offer_cap(
    *,
    max_accepted_offers: int | None,
    cap_used: int,
    overrides: tuple[GateOverride, ...],
) -> GateResult:
    """Evaluate only the cycle cap for a decision that adds to its count.

    Attaching an already accepted external offer changes the cycle-local cap
    count but does not accept the offer again.  In particular, re-running the
    placement outcome gate there would reject the offer against its own global
    placed state.
    """
    failure = (
        Reason(
            code=OFFER_CAP_REACHED,
            human=(
                "You have accepted the maximum of "
                f"{max_accepted_offers} "
                f"{'offer' if max_accepted_offers == 1 else 'offers'} "
                "allowed in this cycle."
            ),
            path="max_accepted_offers",
        )
        if max_accepted_offers is not None and cap_used >= max_accepted_offers
        else None
    )
    failures: list[Reason] = []
    applied: list[UUID] = []
    _append_override_decision(
        failures,
        applied,
        failure,
        RuleDomain.OFFER_CAP,
        overrides,
    )
    return GateResult(tuple(failures), tuple(applied))


def evaluate_expiry_acceptance_constraints(
    *,
    membership_active: bool,
    outcome: Outcome,
    cycle_kind: CycleKind,
    placement_placed_global: bool,
    internship_placed_in_cycle: bool,
    max_accepted_offers: int | None,
    cap_used: int,
    overrides: tuple[GateOverride, ...],
) -> GateResult:
    """Standing OFR-4 auto-accept gates, including current membership.

    The offered row itself is an active application and its application
    deadline is normally past, so those apply-only checks are deliberately not
    re-run. M5's expiry ruling requires membership plus every acceptance
    constraint; any failure falls back to decline and a consistency finding.
    """
    failures: list[Reason] = []
    applied: list[UUID] = []
    if not membership_active:
        failures.append(
            Reason(
                code=MEMBERSHIP_NOT_ACTIVE,
                human="Your membership in this cycle is not active yet.",
                path="membership_status",
            )
        )
    _append_acceptance_constraints(
        failures,
        applied,
        outcome=outcome,
        cycle_kind=cycle_kind,
        placement_placed_global=placement_placed_global,
        internship_placed_in_cycle=internship_placed_in_cycle,
        max_accepted_offers=max_accepted_offers,
        cap_used=cap_used,
        overrides=overrides,
    )
    return GateResult(tuple(failures), tuple(applied))


def evaluate_offer_deadline(
    *,
    now: datetime,
    deadline: datetime | None,
    overrides: tuple[GateOverride, ...],
) -> GateResult:
    """Apply the same closed-boundary rule to dedicated-cycle offer acceptance."""
    failure = (
        Reason(
            code=DEADLINE_PASSED,
            human="The offer acceptance deadline has passed.",
            path="offer_acceptance_deadline",
        )
        if deadline is not None and now >= deadline
        else None
    )
    failures: list[Reason] = []
    applied: list[UUID] = []
    _append_override_decision(
        failures,
        applied,
        failure,
        RuleDomain.OFFER_DEADLINE,
        overrides,
    )
    return GateResult(tuple(failures), tuple(applied))


def evaluate_edit_window(
    *,
    now: datetime,
    deadline: datetime | None,
    allowed_after_deadline: bool,
    overrides: tuple[GateOverride, ...],
) -> GateResult:
    """APP-3's answer-edit window, independently overrideable from exit."""
    return _evaluate_application_window(
        now=now,
        deadline=deadline,
        allowed_after_deadline=allowed_after_deadline,
        domain=RuleDomain.EDIT_WINDOW,
        overrides=overrides,
    )


def evaluate_withdraw_window(
    *,
    now: datetime,
    deadline: datetime | None,
    allowed_after_deadline: bool,
    overrides: tuple[GateOverride, ...],
) -> GateResult:
    """APP-3's self-withdrawal window, independently overrideable from edit."""
    return _evaluate_application_window(
        now=now,
        deadline=deadline,
        allowed_after_deadline=allowed_after_deadline,
        domain=RuleDomain.WITHDRAW_WINDOW,
        overrides=overrides,
    )


def _evaluate_application_window(
    *,
    now: datetime,
    deadline: datetime | None,
    allowed_after_deadline: bool,
    domain: RuleDomain,
    overrides: tuple[GateOverride, ...],
) -> GateResult:
    """The shared closed-boundary calculation behind the two APP-3 gates."""
    failure = (
        Reason(
            code=WINDOW_CLOSED,
            human="The deadline for changing this application has passed.",
            path="application_deadline",
        )
        if deadline is not None and not allowed_after_deadline and now >= deadline
        else None
    )
    failures: list[Reason] = []
    applied: list[UUID] = []
    _append_override_decision(failures, applied, failure, domain, overrides)
    return GateResult(tuple(failures), tuple(applied))


def evaluate_cycle_registration_window(
    *,
    now: datetime,
    opens_at: datetime | None,
    closes_at: datetime | None,
    overrides: tuple[GateOverride, ...],
) -> GateResult:
    """CYC-3's registration dates, excluding the non-overridable active flag."""
    failure = (
        Reason(
            code=REGISTRATION_CLOSED,
            human="The registration window for this cycle is not open",
            path="cycle_id",
        )
        if (opens_at is not None and now < opens_at)
        or (closes_at is not None and now >= closes_at)
        else None
    )
    failures: list[Reason] = []
    applied: list[UUID] = []
    _append_override_decision(
        failures,
        applied,
        failure,
        RuleDomain.CYCLE_REGISTRATION_WINDOW,
        overrides,
    )
    return GateResult(tuple(failures), tuple(applied))


def evaluate_cycle_join_rule(
    evaluation: EvaluationResult | None,
    overrides: tuple[GateOverride, ...],
) -> GateResult:
    """CYC-3's optional profile rule as its own overrideable pure gate."""
    failures: list[Reason] = []
    if evaluation is not None and not evaluation.verdict:
        failures.extend(
            Reason(code=JOIN_RULE_FAILED, human=item.human, path=item.path)
            for item in evaluation.failures
        )
    applied: list[UUID] = []
    if failures:
        original = tuple(failures)
        failures.clear()
        # One override decides the whole configured rule.  Preserve every
        # path-addressed shortfall when no override applies.
        override = _selected_override(RuleDomain.CYCLE_JOIN_RULE, overrides)
        if override is None:
            failures.extend(original)
        elif not override.allow:
            failures.append(_blocked_by_override(original[0].path or "cycle_join_rule"))
            applied.append(override.id)
        else:
            applied.append(override.id)
    else:
        _append_override_decision(
            failures,
            applied,
            None,
            RuleDomain.CYCLE_JOIN_RULE,
            overrides,
        )
    return GateResult(tuple(failures), tuple(applied))


def apply_eligibility_override(
    evaluation: EvaluationResult, overrides: tuple[GateOverride, ...]
) -> GateResult:
    """Apply the eligibility domain only to the job rule, never standing gates."""
    override = _selected_override(RuleDomain.ELIGIBILITY, overrides)
    if override is not None and not override.allow:
        return GateResult(
            failures=(_blocked_by_override(RuleDomain.ELIGIBILITY.value),),
            applied_override_ids=(override.id,),
        )
    if evaluation.verdict:
        return GateResult(failures=())
    if override is not None:
        return GateResult(failures=(), applied_override_ids=(override.id,))
    return GateResult(failures=evaluation.failures)


def _append_acceptance_constraints(
    failures: list[Reason],
    applied: list[UUID],
    *,
    outcome: Outcome,
    cycle_kind: CycleKind,
    placement_placed_global: bool,
    internship_placed_in_cycle: bool,
    max_accepted_offers: int | None,
    cap_used: int,
    overrides: tuple[GateOverride, ...],
) -> None:
    outcome_gate = evaluate_outcome_gate(
        outcome=outcome,
        cycle_kind=cycle_kind,
        placement_placed_global=placement_placed_global,
        internship_placed_in_cycle=internship_placed_in_cycle,
        overrides=overrides,
    )
    failures.extend(outcome_gate.failures)
    applied.extend(outcome_gate.applied_override_ids)

    cap = evaluate_offer_cap(
        max_accepted_offers=max_accepted_offers,
        cap_used=cap_used,
        overrides=overrides,
    )
    failures.extend(cap.failures)
    applied.extend(cap.applied_override_ids)


def _append_override_decision(
    failures: list[Reason],
    applied: list[UUID],
    failure: Reason | None,
    domain: RuleDomain,
    overrides: tuple[GateOverride, ...],
) -> None:
    override = _selected_override(domain, overrides)
    if override is not None and not override.allow:
        path = (failure.path or domain.value) if failure is not None else domain.value
        failures.append(_blocked_by_override(path))
        applied.append(override.id)
    elif failure is not None and override is None:
        failures.append(failure)
    elif failure is not None and override is not None:
        applied.append(override.id)


def _selected_override(
    domain: RuleDomain, overrides: tuple[GateOverride, ...]
) -> GateOverride | None:
    matching = tuple(override for override in overrides if override.rule_domain is domain)
    return next(
        (override for override in matching if not override.allow),
        matching[0] if matching else None,
    )


def _blocked_by_override(path: str) -> Reason:
    return Reason(
        code=BLOCKED_BY_OVERRIDE,
        human="The placement team has blocked this for you.",
        path=path,
    )
