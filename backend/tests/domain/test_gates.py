"""Pure ELG-3 standing-gate and DER-1 scope contracts."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.core.errors import (
    BLOCKED_BY_OVERRIDE,
    CYCLE_ARCHIVED,
    DEADLINE_PASSED,
    DUPLICATE_APPLICATION,
    JOB_CANCELLED,
    JOB_UNPUBLISHED,
    JOIN_RULE_FAILED,
    MEMBERSHIP_NOT_ACTIVE,
    NOT_ELIGIBLE,
    OFFER_CAP_REACHED,
    OUTCOME_GATE_INTERNSHIP,
    OUTCOME_GATE_PLACEMENT,
    PENALTY_ACTIVE,
    REGISTRATION_CLOSED,
    WINDOW_CLOSED,
)
from app.core.plan import Reason
from app.domain.gates import (
    GateContext,
    GateOverride,
    apply_eligibility_override,
    evaluate_cycle_join_rule,
    evaluate_cycle_registration_window,
    evaluate_edit_window,
    evaluate_gates,
    evaluate_offer_deadline,
    evaluate_withdraw_window,
)
from app.domain.rules import EvaluationResult
from app.domain.shared import CycleKind, MembershipStatus, Outcome, RuleDomain

NOW = datetime(2027, 1, 1, tzinfo=UTC)
OVERRIDE_ID = UUID("00000000-0000-0000-0000-000000000201")
DENY_OVERRIDE_ID = UUID("00000000-0000-0000-0000-000000000202")


def _passing() -> GateContext:
    return GateContext(
        membership_status=MembershipStatus.ACTIVE,
        job_published=True,
        job_cancelled=False,
        cycle_archived=False,
        application_deadline=NOW + timedelta(days=1),
        now=NOW,
        outcome=Outcome.PLACEMENT,
        cycle_kind=CycleKind.PLACEMENT,
        has_active_duplicate=False,
        penalty_active=False,
        penalty_blocks_applications=True,
        placement_placed_global=False,
        internship_placed_in_cycle=False,
        max_accepted_offers=1,
        cap_used=0,
    )


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"membership_status": MembershipStatus.PENDING}, MEMBERSHIP_NOT_ACTIVE),
        ({"job_published": False}, JOB_UNPUBLISHED),
        ({"job_cancelled": True}, JOB_CANCELLED),
        ({"cycle_archived": True}, CYCLE_ARCHIVED),
        ({"application_deadline": NOW - timedelta(seconds=1)}, DEADLINE_PASSED),
        ({"has_active_duplicate": True}, DUPLICATE_APPLICATION),
        ({"penalty_active": True}, PENALTY_ACTIVE),
        ({"placement_placed_global": True}, OUTCOME_GATE_PLACEMENT),
        ({"cap_used": 1}, OFFER_CAP_REACHED),
    ],
)
def test_ELG3_each_standing_gate_has_a_pass_and_fail_case(
    changes: dict[str, object], code: str
) -> None:
    assert evaluate_gates(_passing()).verdict is True
    result = evaluate_gates(replace(_passing(), **changes))
    assert [failure.code for failure in result.failures] == [code]


def test_ELG3_job_open_reason_uses_archived_then_cancelled_precedence() -> None:
    cancelled = evaluate_gates(
        replace(_passing(), job_published=False, job_cancelled=True)
    )
    archived = evaluate_gates(
        replace(
            _passing(),
            job_published=False,
            job_cancelled=True,
            cycle_archived=True,
        )
    )
    assert [reason.code for reason in cancelled.failures] == [JOB_CANCELLED]
    assert [reason.code for reason in archived.failures] == [CYCLE_ARCHIVED]


def test_ELG3_returns_all_failures_in_mandated_order() -> None:
    result = evaluate_gates(
        replace(
            _passing(),
            membership_status=MembershipStatus.REJECTED,
            job_published=False,
            application_deadline=NOW - timedelta(days=1),
            has_active_duplicate=True,
            penalty_active=True,
            placement_placed_global=True,
            cap_used=1,
        )
    )
    assert [failure.code for failure in result.failures] == [
        MEMBERSHIP_NOT_ACTIVE,
        JOB_UNPUBLISHED,
        DEADLINE_PASSED,
        DUPLICATE_APPLICATION,
        PENALTY_ACTIVE,
        OUTCOME_GATE_PLACEMENT,
        OFFER_CAP_REACHED,
    ]


@pytest.mark.parametrize(
    ("domain", "changes", "code"),
    [
        (
            RuleDomain.APPLICATION_DEADLINE,
            {"application_deadline": NOW - timedelta(days=1)},
            DEADLINE_PASSED,
        ),
        (
            RuleDomain.OUTCOME_GATE,
            {"placement_placed_global": True},
            OUTCOME_GATE_PLACEMENT,
        ),
        (RuleDomain.OFFER_CAP, {"cap_used": 1}, OFFER_CAP_REACHED),
    ],
)
def test_ELG3_only_sanctioned_gate_domains_are_overrideable(
    domain: RuleDomain, changes: dict[str, object], code: str
) -> None:
    failed = evaluate_gates(replace(_passing(), **changes))
    assert [reason.code for reason in failed.failures] == [code]
    bypassed = evaluate_gates(
        replace(
            _passing(),
            **changes,
            applicable_overrides=(GateOverride(OVERRIDE_ID, domain),),
        )
    )
    assert bypassed.verdict is True
    assert bypassed.applied_override_ids == (OVERRIDE_ID,)


@pytest.mark.parametrize(
    ("domain", "changes", "code"),
    [
        (
            RuleDomain.ELIGIBILITY,
            {"membership_status": MembershipStatus.PENDING},
            MEMBERSHIP_NOT_ACTIVE,
        ),
        (RuleDomain.ELIGIBILITY, {"job_published": False}, JOB_UNPUBLISHED),
        (
            RuleDomain.ELIGIBILITY,
            {"has_active_duplicate": True},
            DUPLICATE_APPLICATION,
        ),
        (RuleDomain.ELIGIBILITY, {"penalty_active": True}, PENALTY_ACTIVE),
    ],
)
def test_ELG3_sanctioned_command_gates_cannot_be_overridden(
    domain: RuleDomain, changes: dict[str, object], code: str
) -> None:
    result = evaluate_gates(
        replace(
            _passing(),
            **changes,
            applicable_overrides=(GateOverride(OVERRIDE_ID, domain),),
        )
    )
    assert [reason.code for reason in result.failures] == [code]
    assert result.applied_override_ids == ()


def test_ELG3_eligibility_override_bypasses_only_the_job_rule() -> None:
    evaluation = EvaluationResult(
        verdict=False,
        failures=(Reason(NOT_ELIGIBLE, "CPI too low", "$.all[0]"),),
    )
    bypassed = apply_eligibility_override(
        evaluation,
        (GateOverride(OVERRIDE_ID, RuleDomain.ELIGIBILITY),),
    )
    assert bypassed.verdict is True
    assert bypassed.applied_override_ids == (OVERRIDE_ID,)


def test_ELG3_deadline_fails_at_the_exact_instant() -> None:
    result = evaluate_gates(replace(_passing(), application_deadline=NOW))
    assert [reason.code for reason in result.failures] == [DEADLINE_PASSED]


def test_ELG3_offer_acceptance_deadline_uses_the_same_boundary() -> None:
    before = evaluate_offer_deadline(
        now=NOW - timedelta(microseconds=1), deadline=NOW, overrides=()
    )
    at_deadline = evaluate_offer_deadline(now=NOW, deadline=NOW, overrides=())
    overridden = evaluate_offer_deadline(
        now=NOW,
        deadline=NOW,
        overrides=(GateOverride(OVERRIDE_ID, RuleDomain.OFFER_DEADLINE),),
    )
    assert before.verdict is True
    assert [reason.code for reason in at_deadline.failures] == [DEADLINE_PASSED]
    assert overridden.verdict is True
    assert overridden.applied_override_ids == (OVERRIDE_ID,)


@pytest.mark.parametrize(
    "domain",
    [
        RuleDomain.APPLICATION_DEADLINE,
        RuleDomain.OUTCOME_GATE,
        RuleDomain.OFFER_CAP,
    ],
)
def test_ELG3_deny_override_beats_allow_and_forces_gate_failure(
    domain: RuleDomain,
) -> None:
    result = evaluate_gates(
        replace(
            _passing(),
            applicable_overrides=(
                GateOverride(OVERRIDE_ID, domain, allow=True),
                GateOverride(DENY_OVERRIDE_ID, domain, allow=False),
            ),
        )
    )
    assert [reason.code for reason in result.failures] == [BLOCKED_BY_OVERRIDE]
    assert result.failures[0].human == "The placement team has blocked this for you."
    assert result.applied_override_ids == (DENY_OVERRIDE_ID,)


def test_ELG3_deny_eligibility_override_blocks_a_passing_job_rule() -> None:
    passing = EvaluationResult(verdict=True, failures=())
    result = apply_eligibility_override(
        passing,
        (GateOverride(DENY_OVERRIDE_ID, RuleDomain.ELIGIBILITY, allow=False),),
    )
    assert [reason.code for reason in result.failures] == [BLOCKED_BY_OVERRIDE]
    assert result.applied_override_ids == (DENY_OVERRIDE_ID,)


def test_ELG3_deny_offer_deadline_override_blocks_before_deadline() -> None:
    result = evaluate_offer_deadline(
        now=NOW,
        deadline=NOW + timedelta(days=1),
        overrides=(
            GateOverride(
                DENY_OVERRIDE_ID,
                RuleDomain.OFFER_DEADLINE,
                allow=False,
            ),
        ),
    )
    assert [reason.code for reason in result.failures] == [BLOCKED_BY_OVERRIDE]


def test_INT2_edit_and_withdrawal_overrides_are_independent() -> None:
    edit_override = GateOverride(OVERRIDE_ID, RuleDomain.EDIT_WINDOW)
    edit = evaluate_edit_window(
        now=NOW,
        deadline=NOW,
        allowed_after_deadline=False,
        overrides=(edit_override,),
    )
    withdraw = evaluate_withdraw_window(
        now=NOW,
        deadline=NOW,
        allowed_after_deadline=False,
        overrides=(edit_override,),
    )

    assert edit.verdict is True
    assert edit.applied_override_ids == (OVERRIDE_ID,)
    assert [reason.code for reason in withdraw.failures] == [WINDOW_CLOSED]


def test_INT2_cycle_join_domains_bypass_only_their_pure_gate() -> None:
    closed = evaluate_cycle_registration_window(
        now=NOW,
        opens_at=NOW + timedelta(days=1),
        closes_at=None,
        overrides=(
            GateOverride(OVERRIDE_ID, RuleDomain.CYCLE_REGISTRATION_WINDOW),
        ),
    )
    failed_rule = EvaluationResult(
        verdict=False,
        failures=(Reason(NOT_ELIGIBLE, "CPI too low", "$.all[0]"),),
    )
    ruled = evaluate_cycle_join_rule(
        failed_rule,
        (
            GateOverride(
                DENY_OVERRIDE_ID,
                RuleDomain.CYCLE_REGISTRATION_WINDOW,
            ),
        ),
    )

    assert closed.verdict is True
    assert closed.applied_override_ids == (OVERRIDE_ID,)
    assert [reason.code for reason in ruled.failures] == [JOIN_RULE_FAILED]
    assert ruled.applied_override_ids == ()

    bypassed = evaluate_cycle_join_rule(
        failed_rule,
        (GateOverride(OVERRIDE_ID, RuleDomain.CYCLE_JOIN_RULE),),
    )
    assert bypassed.verdict is True
    assert bypassed.applied_override_ids == (OVERRIDE_ID,)

    ordinary_closed = evaluate_cycle_registration_window(
        now=NOW,
        opens_at=None,
        closes_at=NOW,
        overrides=(),
    )
    assert [reason.code for reason in ordinary_closed.failures] == [
        REGISTRATION_CLOSED
    ]


def test_ELG3_null_deadline_and_null_cap_skip_their_gates() -> None:
    result = evaluate_gates(
        replace(
            _passing(),
            application_deadline=None,
            max_accepted_offers=None,
            cap_used=999,
        )
    )
    assert result.verdict is True


def test_DER1_internship_gate_is_same_cycle_dedicated_only() -> None:
    dedicated = replace(
        _passing(),
        outcome=Outcome.INTERNSHIP,
        cycle_kind=CycleKind.INTERNSHIP,
        internship_placed_in_cycle=True,
    )
    assert [reason.code for reason in evaluate_gates(dedicated).failures] == [
        OUTCOME_GATE_INTERNSHIP
    ]
    assert evaluate_gates(replace(dedicated, cycle_kind=CycleKind.OPEN)).verdict is True
    assert evaluate_gates(replace(dedicated, internship_placed_in_cycle=False)).verdict is True


def test_ELG3_penalty_gate_skips_when_cycle_policy_disables_it() -> None:
    result = evaluate_gates(
        replace(_passing(), penalty_active=True, penalty_blocks_applications=False)
    )
    assert result.verdict is True
