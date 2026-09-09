"""ANA-4's column registry -- what an export is allowed to contain.

Three families, per ANA-4: the profile registry, the application fields, and
that job's own questions as ``question_{id}``.  The profile half is not
restated here; it is generated from ``modules/profiles/fields.FIELDS``, which
PRO-1's own equality test already pins against the specification.  Two lists of
profile fields would drift the first time somebody added a column, and the
export is where that drift becomes a spreadsheet handed to a company.

The registry exists so that a requested column can be *refused*.  Without it a
preset saved against a deleted question, or a column somebody typed by hand,
fails at download time -- on a screen with no way to explain what went wrong --
and the office concludes the export is broken.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.modules.profiles.fields import FIELDS

QUESTION_PREFIX = "question_"


@dataclass(frozen=True, slots=True)
class ExportColumn:
    """One selectable column, and where its value comes from."""

    key: str
    label: str
    family: str


#: Application-side columns, exactly the four ANA-4 names plus the identifiers
#: any spreadsheet needs to be joined against anything else.  `resume_link` is
#: the one ANA-4 calls out by name: there are no ZIPs in this system, so the
#: link column *is* the resume delivery (Behavior section 17).
APPLICATION_COLUMNS: tuple[ExportColumn, ...] = (
    ExportColumn("institute_email", "Institute email", "application"),
    ExportColumn("status", "Status", "application"),
    ExportColumn("overall_status", "Overall application status", "application"),
    ExportColumn("current_round", "Current round", "application"),
    ExportColumn("applied_at", "Applied at", "application"),
    ExportColumn("resume_link", "Resume link", "application"),
    ExportColumn("selected_round_attendance", "Round attendance", "round"),
    ExportColumn("selected_round_result", "Round result", "round"),
    ExportColumn("selected_round_venue", "Round venue", "round"),
    ExportColumn("selected_round_time", "Round time", "round"),
    ExportColumn("offer_count", "Offers issued", "offer"),
    ExportColumn("offer_statuses", "Offer statuses", "offer"),
    ExportColumn("offer_extended_at", "Latest offer issued at", "offer"),
    ExportColumn("offer_deadline_at", "Latest offer deadline", "offer"),
    ExportColumn("offer_responded_at", "Latest offer responded at", "offer"),
    ExportColumn("offer_termination_reason", "Latest offer termination reason", "offer"),
)

#: Membership export columns (ANA-4: "membership exports for cycles, including
#: approval status and outcome tags").
MEMBERSHIP_COLUMNS: tuple[ExportColumn, ...] = (
    ExportColumn("institute_email", "Institute email", "membership"),
    ExportColumn("membership_status", "Approval status", "membership"),
    ExportColumn("outcome_tag", "Outcome tag", "membership"),
    ExportColumn("auto_created", "Auto-created", "membership"),
    ExportColumn("consented_at", "Consented at", "membership"),
    ExportColumn("decided_at", "Decided at", "membership"),
    ExportColumn("rejection_reason", "Rejection reason", "membership"),
)

PROFILE_COLUMNS: tuple[ExportColumn, ...] = tuple(
    ExportColumn(field.key, field.label, "profile") for field in FIELDS
)


def question_column(question_id: UUID, text: str) -> ExportColumn:
    """A job question as its export column."""
    return ExportColumn(f"{QUESTION_PREFIX}{question_id}", text, "question")


def application_registry(
    questions: tuple[tuple[UUID, str], ...] = (),
) -> tuple[ExportColumn, ...]:
    """Every column a per-job export may carry, questions included."""
    return (
        *PROFILE_COLUMNS,
        *APPLICATION_COLUMNS,
        *(question_column(question_id, text) for question_id, text in questions),
    )


def membership_registry() -> tuple[ExportColumn, ...]:
    """Every column a per-cycle membership export may carry."""
    return (*PROFILE_COLUMNS, *MEMBERSHIP_COLUMNS)


def unknown_columns(
    requested: tuple[str, ...], registry: tuple[ExportColumn, ...]
) -> tuple[str, ...]:
    """The requested columns this registry does not offer, in order.

    Returned rather than raised so the caller can reject with all of them at
    once: a picker that reports one bad column per attempt is a picker somebody
    fights three times.
    """
    known = {column.key for column in registry}
    return tuple(column for column in requested if column not in known)


def default_columns(registry: tuple[ExportColumn, ...]) -> tuple[str, ...]:
    """What an export carries when nobody has chosen: identity and status.

    Deliberately narrow.  An export that defaults to every column encourages
    sending a company more about a student than the job needs.
    """
    wanted = ("full_name", "roll_number", "institute_email", "status", "resume_link")
    known = {column.key for column in registry}
    return tuple(key for key in wanted if key in known)
