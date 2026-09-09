"""Pure membership decisions for CYC-3 and CYC-4.

Everything a membership decision needs — the status machine, the join
completeness check, and the exit cascade — lives here as functions over
loader-provided snapshots, so the command layer only loads and applies.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.core.errors import INVALID_TRANSITION, PROFILE_INCOMPLETE
from app.core.plan import Reason, Rejection
from app.domain.shared import (
    ApplicationStatus,
    EventType,
    MembershipStatus,
    is_blank,
)
from app.domain.transitions import CascadeAction, TransitionActor


class MembershipExitTrigger(StrEnum):
    """Why a membership exit auto-withdrew this cycle's applications (CYC-4)."""

    MEMBERSHIP_EXIT = "membership_exit"
    ARCHIVAL = "archival"


@dataclass(frozen=True, slots=True)
class MembershipTransition:
    name: str
    from_statuses: tuple[MembershipStatus | None, ...]
    to_status: MembershipStatus
    actors: tuple[TransitionActor, ...]
    requires_reason: bool
    cascades: bool
    spec: str


# Behavior CYC-3's status machine, verbatim and closed: nothing outside this
# table can move a membership.
MEMBERSHIP_TRANSITIONS: tuple[MembershipTransition, ...] = (
    MembershipTransition(
        "join", (None,), MembershipStatus.PENDING, (TransitionActor.STUDENT,),
        False, False, "CYC-3.1",
    ),
    MembershipTransition(
        "join_active", (None,), MembershipStatus.ACTIVE, (TransitionActor.STUDENT,),
        False, False, "CYC-3.2",
    ),
    MembershipTransition(
        "approve", (MembershipStatus.PENDING,), MembershipStatus.ACTIVE,
        (TransitionActor.STAFF,), False, False, "CYC-3.3",
    ),
    MembershipTransition(
        "reject", (MembershipStatus.PENDING,), MembershipStatus.REJECTED,
        (TransitionActor.STAFF,), True, False, "CYC-3.4",
    ),
    # the design review section 4.34 widens CYC-3.5 to the member who left of their own
    # accord: a withdrawal is a weaker reason to need staff than a rejection is,
    # and re-entry re-runs every join check, so nothing reaches `active` that a
    # fresh join would not.  The pair mirrors join/join_active -- which row runs
    # is the cycle's `membership_requires_approval`, exactly as at first join.
    MembershipTransition(
        "rerequest",
        (MembershipStatus.REJECTED, MembershipStatus.WITHDRAWN),
        MembershipStatus.PENDING, (TransitionActor.STUDENT,), False, False, "CYC-3.5",
    ),
    MembershipTransition(
        "rerequest_active",
        (MembershipStatus.REJECTED, MembershipStatus.WITHDRAWN),
        MembershipStatus.ACTIVE, (TransitionActor.STUDENT,), False, False, "CYC-3.5",
    ),
    # A pending member may cancel their own request.  CYC-3 names only
    # active -> withdrawn, but leaving pending with no student-side exit would
    # force someone who joined the wrong cycle to ask staff for a rejection,
    # putting a rejection on their record for their own mistake.  There is no
    # cascade risk: gate 1 (membership_active) means a pending member cannot
    # hold applications (the design review section 4.17).
    MembershipTransition(
        "withdraw", (MembershipStatus.PENDING, MembershipStatus.ACTIVE),
        MembershipStatus.WITHDRAWN, (TransitionActor.STUDENT,), False, True, "CYC-3.6",
    ),
    MembershipTransition(
        "remove", (MembershipStatus.ACTIVE,), MembershipStatus.REMOVED,
        (TransitionActor.STAFF,), True, True, "CYC-3.7",
    ),
    MembershipTransition(
        "restore", (MembershipStatus.WITHDRAWN, MembershipStatus.REMOVED),
        MembershipStatus.ACTIVE, (TransitionActor.STAFF,), False, False, "CYC-3.8",
    ),
)


def legal_membership_transitions(
    from_status: MembershipStatus | None, actor: TransitionActor
) -> tuple[str, ...]:
    """Return the CYC-3 rows legal for one status/actor pair."""
    return tuple(
        transition.name
        for transition in MEMBERSHIP_TRANSITIONS
        if from_status in transition.from_statuses and actor in transition.actors
    )


def decide_membership_transition(
    name: str,
    *,
    from_status: MembershipStatus | None,
    actor: TransitionActor,
    reason: str | None = None,
) -> MembershipTransition | Rejection:
    """Validate one named CYC-3 membership decision against the table."""
    transition = next(
        (item for item in MEMBERSHIP_TRANSITIONS if item.name == name), None
    )
    if transition is None or name not in legal_membership_transitions(from_status, actor):
        return Rejection(
            reasons=[
                Reason(
                    code=INVALID_TRANSITION,
                    human="The requested membership transition is not legal",
                    path="status",
                )
            ]
        )
    if transition.requires_reason and (reason is None or not reason.strip()):
        return Rejection(
            reasons=[
                Reason(
                    code=INVALID_TRANSITION,
                    human="This membership decision requires a reason",
                    path="reason",
                )
            ]
        )
    return transition


# Behavior PRO-1's "Required to join a cycle" column.  The institute email is
# absent deliberately: it is NOT NULL on users, so it cannot be missing and is
# not a checkable requirement.  Secondary branch is conditional rather than
# absent -- PRO-1 requires it "if dual major", which `profiles.is_dual_major`
# expresses: the student who has a second major is exactly the student asked to
# name it (the design review section 4.32).
REQUIRED_JOIN_FIELDS: tuple[str, ...] = (
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
)
# Required only of a dual major -- the student with a second major to name
# (Behavior PRO-1).
CONDITIONAL_JOIN_FIELDS: tuple[str, ...] = ("secondary_branch_id",)
DUAL_DEGREE_JOIN_FIELDS: tuple[str, ...] = (
    "secondary_program_id",
    "secondary_branch_id",
)

# Mirrors the M6 field registry's labels; tests/domain/test_memberships.py
# asserts the two agree, so a relabelling there cannot drift from here without
# failing the suite.
JOIN_FIELD_LABELS: Mapping[str, str] = {
    "full_name": "Full name",
    "roll_number": "Roll number",
    "program_id": "Program",
    "primary_branch_id": "Primary branch",
    "graduating_year": "Graduating year",
    "cpi": "CPI",
    "active_backlogs": "Active backlog count",
    "total_backlogs": "Total backlog count",
    "gender": "Gender",
    "personal_email": "Personal email",
    "contact_number": "Contact number",
    "nationality": "Nationality",
    "tenth_percent": "10th percentage",
    "tenth_year": "10th year",
    "twelfth_percent": "12th percentage",
    "twelfth_year": "12th year",
    "secondary_program_id": "Secondary program",
    "secondary_branch_id": "Secondary branch",
}


def required_join_fields(
    *, dual_major: bool, dual_degree: bool = False
) -> tuple[str, ...]:
    """The PRO-1 requirement list for one student's degree structure."""
    if dual_degree:
        return REQUIRED_JOIN_FIELDS + DUAL_DEGREE_JOIN_FIELDS
    return REQUIRED_JOIN_FIELDS + (CONDITIONAL_JOIN_FIELDS if dual_major else ())


def check_profile_completeness(
    profile: Mapping[str, object], *, resume_count: int, declared: bool
) -> tuple[Reason, ...]:
    """Return the CYC-3 join checklist as one reason per unmet requirement.

    Every failure is returned, never just the first: the student needs the
    whole list to fix their profile in one pass.  ``is_dual_major`` is a profile
    column like any other here, so a dual major is additionally required to name
    a secondary branch (Behavior PRO-1).
    """
    reasons: list[Reason] = []
    if not declared:
        reasons.append(
            Reason(
                code=PROFILE_INCOMPLETE,
                human="Your profile has not been declared yet",
                path="declared_at",
            )
        )
    for key in required_join_fields(
        dual_major=bool(profile.get("is_dual_major", False)),
        dual_degree=bool(profile.get("is_dual_degree", False)),
    ):
        if is_blank(profile.get(key)):
            reasons.append(
                Reason(
                    code=PROFILE_INCOMPLETE,
                    human=f"{JOIN_FIELD_LABELS[key]} is required to join a cycle",
                    path=key,
                )
            )
    if resume_count < 1:
        reasons.append(
            Reason(
                code=PROFILE_INCOMPLETE,
                human="At least one resume is required to join a cycle",
                path="resumes",
            )
        )
    return tuple(reasons)


@dataclass(frozen=True, slots=True)
class MembershipApplicationState:
    application_id: UUID
    status: ApplicationStatus
    current_round_id: UUID | None = None


# APP-4 row 13: only in-flight applications auto-withdraw.  offered, accepted,
# and every terminal status are outside the row and stay exactly as they are.
EXIT_CASCADE_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {ApplicationStatus.IN_PROGRESS, ApplicationStatus.PENDING_OFFER}
)


def compute_membership_exit_cascade(
    applications: tuple[MembershipApplicationState, ...],
    *,
    trigger: MembershipExitTrigger,
) -> tuple[CascadeAction, ...]:
    """Auto-withdraw a cycle's in-flight applications on exit (CYC-4, APP-4.13).

    Position is preserved: the round the application sits in rides along in the
    event so reinstatement to the exact round stays possible (INT-1).
    """
    return tuple(
        CascadeAction(
            application_id=application.application_id,
            offer_id=None,
            from_status=application.status,
            to_status=ApplicationStatus.AUTO_WITHDRAWN,
            from_round_id=application.current_round_id,
            event_type=EventType.AUTO_WITHDRAWN,
            payload={"trigger": trigger.value},
        )
        for application in sorted(
            applications, key=lambda item: item.application_id.int
        )
        if application.status in EXIT_CASCADE_STATUSES
    )
