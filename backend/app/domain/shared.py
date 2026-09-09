"""Canonical domain enums from LLD section 6."""

from enum import StrEnum
from typing import Literal


class Role(StrEnum):
    STUDENT = "student"
    ADMIN = "admin"


class Gender(StrEnum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class CycleKind(StrEnum):
    PLACEMENT = "placement"
    INTERNSHIP = "internship"
    OPEN = "open"


class MembershipStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    REMOVED = "removed"


class Outcome(StrEnum):
    INTERNSHIP = "internship"
    PLACEMENT = "placement"


class ApplicationStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    PENDING_OFFER = "pending_offer"
    OFFERED = "offered"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    AUTO_WITHDRAWN = "auto_withdrawn"
    OFFER_TERMINATED = "offer_terminated"


class RoundResult(StrEnum):
    PENDING = "pending"
    ADVANCED = "advanced"
    ELIMINATED = "eliminated"
    WAITLISTED = "waitlisted"


class Attendance(StrEnum):
    PENDING = "pending"
    PRESENT = "present"
    ABSENT = "absent"
    EXCUSED = "excused"


class OfferResponse(StrEnum):
    ACCEPTED = "accepted"
    DECLINED = "declined"


class TerminationKind(StrEnum):
    COMPANY_REVOKED = "company_revoked"
    STUDENT_RENEGE = "student_renege"
    ADMIN_CORRECTION = "admin_correction"


class ExternalSource(StrEnum):
    PPO = "ppo"
    OFF_CAMPUS = "off_campus"
    OTHER = "other"


class ExternalStatus(StrEnum):
    OFFERED = "offered"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class QuestionType(StrEnum):
    TEXT = "text"
    LONGTEXT = "longtext"
    SINGLE = "single"
    MULTI = "multi"
    BOOLEAN = "boolean"
    NUMBER = "number"
    DATE = "date"
    EMAIL = "email"
    URL = "url"


class StrikeSource(StrEnum):
    AUTO_ABSENCE = "auto_absence"
    MANUAL = "manual"


class RuleDomain(StrEnum):
    ELIGIBILITY = "eligibility"
    APPLICATION_DEADLINE = "application_deadline"
    EDIT_WINDOW = "edit_window"
    WITHDRAW_WINDOW = "withdraw_window"
    OUTCOME_GATE = "outcome_gate"
    OFFER_CAP = "offer_cap"
    OFFER_DEADLINE = "offer_deadline"
    CYCLE_REGISTRATION_WINDOW = "cycle_registration_window"
    CYCLE_JOIN_RULE = "cycle_join_rule"


OverrideTarget = Literal["cycle", "job", "enrollment", "application"]
type ScopeCombination = tuple[OverrideTarget, ...]

CYCLE_SCOPE: ScopeCombination = ("cycle",)
JOB_SCOPE: ScopeCombination = ("job",)
ENROLLMENT_SCOPE: ScopeCombination = ("enrollment",)
CYCLE_ENROLLMENT_SCOPE: ScopeCombination = ("cycle", "enrollment")
JOB_ENROLLMENT_SCOPE: ScopeCombination = ("job", "enrollment")
APPLICATION_SCOPE: ScopeCombination = ("application",)

#: The only target combinations an override row can represent, in increasing
#: specificity order (the design review section 4.52).  Tuples rather than display
#: strings keep the legality table about columns: ``("job", "enrollment")``
#: means exactly those two stored foreign keys are non-null.
OVERRIDE_SCOPE_COMBINATIONS: tuple[ScopeCombination, ...] = (
    CYCLE_SCOPE,
    JOB_SCOPE,
    ENROLLMENT_SCOPE,
    CYCLE_ENROLLMENT_SCOPE,
    JOB_ENROLLMENT_SCOPE,
    APPLICATION_SCOPE,
)

_PREAPPLICATION_SCOPES = frozenset(OVERRIDE_SCOPE_COMBINATIONS[:-1])
_APPLICATION_SCOPES = frozenset(OVERRIDE_SCOPE_COMBINATIONS)
_JOIN_SCOPES = frozenset(
    {CYCLE_SCOPE, ENROLLMENT_SCOPE, CYCLE_ENROLLMENT_SCOPE}
)

#: A grant outside this table cannot reach the named gate and is rejected
#: rather than stored as a convincing no-op (the design review sections 4.50-4.53).
DOMAIN_SCOPES: dict[RuleDomain, frozenset[ScopeCombination]] = {
    RuleDomain.ELIGIBILITY: _PREAPPLICATION_SCOPES,
    RuleDomain.APPLICATION_DEADLINE: _PREAPPLICATION_SCOPES,
    RuleDomain.EDIT_WINDOW: _APPLICATION_SCOPES,
    RuleDomain.WITHDRAW_WINDOW: _APPLICATION_SCOPES,
    RuleDomain.OUTCOME_GATE: _APPLICATION_SCOPES,
    RuleDomain.OFFER_CAP: _APPLICATION_SCOPES,
    RuleDomain.OFFER_DEADLINE: _APPLICATION_SCOPES,
    RuleDomain.CYCLE_REGISTRATION_WINDOW: _JOIN_SCOPES,
    RuleDomain.CYCLE_JOIN_RULE: _JOIN_SCOPES,
}


def override_scope_combination(
    *,
    cycle_id: object | None,
    job_id: object | None,
    enrollment_id: object | None,
    application_id: object | None,
) -> ScopeCombination | None:
    """Return the canonical combination named by four persisted scope values."""
    present = frozenset(
        target
        for target, value in (
            ("cycle", cycle_id),
            ("job", job_id),
            ("enrollment", enrollment_id),
            ("application", application_id),
        )
        if value is not None
    )
    return next(
        (
            combination
            for combination in OVERRIDE_SCOPE_COMBINATIONS
            if frozenset(combination) == present
        ),
        None,
    )


def scope_name(scope: ScopeCombination) -> str:
    """Stable wire/display name for one legal target combination."""
    return "+".join(scope)


def domains_for_scope(
    first: OverrideTarget, second: OverrideTarget | None = None
) -> tuple[RuleDomain, ...]:
    """Domains whose gate can run with this complete target combination."""
    requested = frozenset((first,)) if second is None else frozenset((first, second))
    combination = next(
        (
            item
            for item in OVERRIDE_SCOPE_COMBINATIONS
            if frozenset(item) == requested
        ),
        None,
    )
    if combination is None:
        return ()
    return tuple(
        domain for domain in RuleDomain if combination in DOMAIN_SCOPES[domain]
    )


class OfferExpiry(StrEnum):
    AUTO_DECLINE = "auto_decline"
    AUTO_ACCEPT = "auto_accept"


class OutcomeTag(StrEnum):
    HIGHER_STUDIES = "higher_studies"
    ENTREPRENEURSHIP = "entrepreneurship"
    NOT_SEEKING = "not_seeking"


class EventType(StrEnum):
    CREATED = "created"
    ADVANCED = "advanced"
    ELIMINATED = "eliminated"
    WAITLISTED = "waitlisted"
    ATTENDANCE_MARKED = "attendance_marked"
    VENUE_ASSIGNED = "venue_assigned"
    ROUND_FINALIZED = "round_finalized"
    OFFER_EXTENDED = "offer_extended"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    AUTO_DECLINED = "auto_declined"
    WITHDRAWN = "withdrawn"
    AUTO_WITHDRAWN = "auto_withdrawn"
    OFFER_TERMINATED = "offer_terminated"
    REINSTATED = "reinstated"
    EDITED = "edited"
    FORCED_TRANSITION = "forced_transition"
    OVERRIDDEN = "overridden"
    EXTERNAL_RECORDED = "external_recorded"
    EXTERNAL_UPDATED = "external_updated"


class FindingStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class NotificationStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"
    DEAD = "dead"



def is_blank(value: object) -> bool:
    """Whether a profile value counts as absent (Behavior PRO-1, CYC-3).

    Two rules read this one predicate: ``check_profile_completeness`` decides
    whether a required field is still missing, and ``unlocked_admin_fields``
    decides whether an admin-owned field has yet accepted its initial value.
    They must agree exactly -- a field the join checklist calls missing is
    precisely the field its owner is still allowed to supply -- so the test
    lives here rather than inline at each site.
    """
    return value is None or (isinstance(value, str) and not value.strip())
