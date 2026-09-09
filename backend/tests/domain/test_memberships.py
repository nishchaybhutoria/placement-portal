"""Pure membership decisions for CYC-3 and CYC-4, with no database."""

from __future__ import annotations

from uuid import UUID

import pytest

from app.core.errors import INVALID_TRANSITION, PROFILE_INCOMPLETE
from app.core.plan import Rejection
from app.domain.memberships import (
    JOIN_FIELD_LABELS,
    MEMBERSHIP_TRANSITIONS,
    REQUIRED_JOIN_FIELDS,
    MembershipApplicationState,
    MembershipExitTrigger,
    check_profile_completeness,
    compute_membership_exit_cascade,
    decide_membership_transition,
    legal_membership_transitions,
    required_join_fields,
)
from app.domain.shared import ApplicationStatus, EventType, MembershipStatus
from app.domain.transitions import TransitionActor
from app.modules.profiles.fields import FIELDS_BY_KEY

# Behavior PRO-1's "Required to join a cycle" column, transcribed from the doc
# table.  Institute email is required there but is NOT NULL on users, so it is
# structurally guaranteed rather than checked; secondary branch is required
# only "if dual major", a condition the schema cannot express.
PRO1_REQUIRED_TO_JOIN = {
    "full_name",
    "roll_number",
    "program_id",
    "primary_branch_id",
    "graduating_year",
    "cpi",
    "active_backlogs",
    "total_backlogs",
    "gender",
    "personal_email",
    "contact_number",
    "nationality",
    "tenth_percent",
    "tenth_year",
    "twelfth_percent",
    "twelfth_year",
}
PRO1_NOT_REQUIRED_TO_JOIN = {
    "secondary_branch_id",
    "minor1_id",
    "minor2_id",
    "github_url",
    "linkedin_url",
    "portfolio_url",
}


def complete_profile() -> dict[str, object]:
    return {
        "full_name": "Asha Rao",
        "roll_number": "21110001",
        "program_id": UUID("00000000-0000-0000-0000-0000000000a1"),
        "primary_branch_id": UUID("00000000-0000-0000-0000-0000000000a2"),
        "graduating_year": 2026,
        "cpi": "8.40",
        "active_backlogs": 0,
        "total_backlogs": 0,
        "gender": "female",
        "personal_email": "asha@example.com",
        "contact_number": "+1 202-555-0100",
        "nationality": "IN",
        "tenth_percent": "92.00",
        "tenth_year": 2019,
        "twelfth_percent": "94.00",
        "twelfth_year": 2021,
    }


def test_CYC3_required_join_fields_equal_the_PRO1_table() -> None:
    assert set(REQUIRED_JOIN_FIELDS) == PRO1_REQUIRED_TO_JOIN
    # Every required field is a field the M6 registry actually knows about.
    assert set(REQUIRED_JOIN_FIELDS) <= set(FIELDS_BY_KEY)
    # Optional-to-join fields stay optional.
    assert set(REQUIRED_JOIN_FIELDS) & PRO1_NOT_REQUIRED_TO_JOIN == set()
    assert PRO1_NOT_REQUIRED_TO_JOIN <= set(FIELDS_BY_KEY)


def test_CYC3_join_field_labels_track_the_M6_field_registry() -> None:
    assert {key: FIELDS_BY_KEY[key].label for key in JOIN_FIELD_LABELS} == dict(
        JOIN_FIELD_LABELS
    )
    # Every checkable requirement, conditional ones included, has a label.
    assert set(required_join_fields(dual_major=True)) <= set(JOIN_FIELD_LABELS)


def test_CYC3_a_complete_declared_profile_with_a_resume_passes() -> None:
    assert check_profile_completeness(
        complete_profile(), resume_count=1, declared=True
    ) == ()


def test_CYC3_secondary_branch_is_required_only_for_a_dual_major() -> None:
    """Resolved by the M9 amendment; see tests/taxonomies/test_dual_major.py."""
    profile = complete_profile()
    assert "secondary_branch_id" not in profile
    assert check_profile_completeness(profile, resume_count=1, declared=True) == ()
    dual = check_profile_completeness(
        profile | {"is_dual_major": True}, resume_count=1, declared=True
    )
    assert [reason.path for reason in dual] == ["secondary_branch_id"]


def test_CYC3_incomplete_profile_returns_the_whole_checklist() -> None:
    profile = complete_profile()
    del profile["cpi"]
    profile["contact_number"] = "   "
    profile["gender"] = None

    reasons = check_profile_completeness(profile, resume_count=0, declared=False)

    assert {reason.code for reason in reasons} == {PROFILE_INCOMPLETE}
    assert [reason.path for reason in reasons] == [
        "declared_at",
        "cpi",
        "gender",
        "contact_number",
        "resumes",
    ]


def test_CYC3_undeclared_profile_is_blocked_even_when_every_column_is_filled() -> None:
    reasons = check_profile_completeness(
        complete_profile(), resume_count=1, declared=False
    )
    assert [reason.path for reason in reasons] == ["declared_at"]


@pytest.mark.parametrize(
    ("name", "from_status", "actor", "expected"),
    [
        ("approve", MembershipStatus.PENDING, TransitionActor.STAFF, True),
        ("approve", MembershipStatus.REJECTED, TransitionActor.STAFF, False),
        ("approve", MembershipStatus.PENDING, TransitionActor.STUDENT, False),
        ("reject", MembershipStatus.PENDING, TransitionActor.STAFF, True),
        ("reject", MembershipStatus.ACTIVE, TransitionActor.STAFF, False),
        ("rerequest", MembershipStatus.REJECTED, TransitionActor.STUDENT, True),
        ("rerequest", MembershipStatus.REJECTED, TransitionActor.STAFF, False),
        ("withdraw", MembershipStatus.ACTIVE, TransitionActor.STUDENT, True),
        ("withdraw", MembershipStatus.PENDING, TransitionActor.STUDENT, True),
        ("withdraw", MembershipStatus.REJECTED, TransitionActor.STUDENT, False),
        ("withdraw", MembershipStatus.ACTIVE, TransitionActor.STAFF, False),
        ("remove", MembershipStatus.ACTIVE, TransitionActor.STAFF, True),
        ("remove", MembershipStatus.PENDING, TransitionActor.STAFF, False),
        ("restore", MembershipStatus.WITHDRAWN, TransitionActor.STAFF, True),
        ("restore", MembershipStatus.REMOVED, TransitionActor.STAFF, True),
        ("restore", MembershipStatus.REJECTED, TransitionActor.STAFF, False),
        ("restore", MembershipStatus.WITHDRAWN, TransitionActor.STUDENT, False),
    ],
)
def test_CYC3_membership_transition_legality_matrix(
    name: str, from_status: MembershipStatus, actor: TransitionActor, expected: bool
) -> None:
    decision = decide_membership_transition(
        name, from_status=from_status, actor=actor, reason="because"
    )
    assert isinstance(decision, Rejection) is not expected


def test_CYC3_a_pending_member_may_cancel_their_own_request() -> None:
    """Reversing the conservative reading: no staff rejection for one's own mistake."""
    assert "withdraw" in legal_membership_transitions(
        MembershipStatus.PENDING, TransitionActor.STUDENT
    )
    assert "remove" not in legal_membership_transitions(
        MembershipStatus.PENDING, TransitionActor.STAFF
    )


@pytest.mark.parametrize("name", ["reject", "remove"])
def test_CYC3_rejection_and_removal_require_a_reason(name: str) -> None:
    from_status = (
        MembershipStatus.PENDING if name == "reject" else MembershipStatus.ACTIVE
    )
    for reason in (None, "", "   "):
        decision = decide_membership_transition(
            name, from_status=from_status, actor=TransitionActor.STAFF, reason=reason
        )
        assert isinstance(decision, Rejection)
        assert [item.code for item in decision.reasons] == [INVALID_TRANSITION]


def test_CYC3_an_unknown_transition_name_is_rejected() -> None:
    decision = decide_membership_transition(
        "promote", from_status=MembershipStatus.PENDING, actor=TransitionActor.STAFF
    )
    assert isinstance(decision, Rejection)


def test_CYC3_only_exits_are_marked_as_cascading() -> None:
    cascading = {
        transition.name for transition in MEMBERSHIP_TRANSITIONS if transition.cascades
    }
    assert cascading == {"withdraw", "remove"}


@pytest.mark.parametrize(
    "trigger", [MembershipExitTrigger.MEMBERSHIP_EXIT, MembershipExitTrigger.ARCHIVAL]
)
def test_CYC4_exit_cascade_auto_withdraws_only_in_flight_applications(
    trigger: MembershipExitTrigger,
) -> None:
    round_id = UUID("00000000-0000-0000-0000-0000000000b9")
    applications = tuple(
        MembershipApplicationState(
            application_id=UUID(f"00000000-0000-0000-0000-0000000000{index:02x}"),
            status=status,
            current_round_id=round_id if status is ApplicationStatus.IN_PROGRESS else None,
        )
        for index, status in enumerate(
            [
                ApplicationStatus.IN_PROGRESS,
                ApplicationStatus.PENDING_OFFER,
                ApplicationStatus.OFFERED,
                ApplicationStatus.ACCEPTED,
                ApplicationStatus.REJECTED,
                ApplicationStatus.WITHDRAWN,
                ApplicationStatus.AUTO_WITHDRAWN,
                ApplicationStatus.DECLINED,
                ApplicationStatus.OFFER_TERMINATED,
            ],
            start=1,
        )
    )

    actions = compute_membership_exit_cascade(applications, trigger=trigger)

    assert [action.from_status for action in actions] == [
        ApplicationStatus.IN_PROGRESS,
        ApplicationStatus.PENDING_OFFER,
    ]
    assert {action.to_status for action in actions} == {
        ApplicationStatus.AUTO_WITHDRAWN
    }
    assert {action.event_type for action in actions} == {EventType.AUTO_WITHDRAWN}
    assert {action.payload["trigger"] for action in actions} == {trigger.value}
    # Position is preserved so reinstatement to the exact round stays possible.
    assert actions[0].from_round_id == round_id
    assert all(action.offer_id is None for action in actions)


def test_CYC4_exit_cascade_is_deterministic_and_empty_without_in_flight_rows() -> None:
    assert compute_membership_exit_cascade(
        (), trigger=MembershipExitTrigger.ARCHIVAL
    ) == ()
    first = UUID("00000000-0000-0000-0000-0000000000c1")
    second = UUID("00000000-0000-0000-0000-0000000000c2")
    unordered = (
        MembershipApplicationState(second, ApplicationStatus.IN_PROGRESS),
        MembershipApplicationState(first, ApplicationStatus.PENDING_OFFER),
    )
    actions = compute_membership_exit_cascade(
        unordered, trigger=MembershipExitTrigger.MEMBERSHIP_EXIT
    )
    assert [action.application_id for action in actions] == [first, second]
