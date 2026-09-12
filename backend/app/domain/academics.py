"""PRO-1/2 academic-standing collection (docs/ACADEMIC-ELIGIBILITY.md).

Study year is a declared fact for a particular academic session, never inferred
from graduation, program duration, the calendar, or internship commencement.
The office explicitly selects the current session; changing it makes previous
statements stale without changing a profile, membership, or application.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.core.errors import INVALID_FIELD_VALUE
from app.core.plan import Reason

STUDY_YEAR_MIN = 1
STUDY_YEAR_MAX = 8
ACADEMIC_SESSION_SETTING = "academic_session_start_year"
ACADEMIC_STANDING_FIELDS = frozenset({"study_year", "study_year_session"})


def session_label(start_year: int) -> str:
    return f"{start_year}\N{EN DASH}{str(start_year + 1)[-2:]}"


def academic_session(value: object) -> int | None:
    """Read a configured session conservatively; there is no calendar default."""
    if isinstance(value, int) and not isinstance(value, bool) and 1900 <= value <= 2100:
        return value
    return None


def academic_standing_status(
    profile: Mapping[str, object], current_session: int | None
) -> dict[str, object]:
    """Read-only prompt state. Collection does not change application gates."""
    year = profile.get("study_year")
    recorded_session = profile.get("study_year_session")
    valid_year = (
        isinstance(year, int) and not isinstance(year, bool)
        and STUDY_YEAR_MIN <= year <= STUDY_YEAR_MAX
    )
    status = (
        "unconfigured" if current_session is None
        else "missing" if not valid_year or academic_session(recorded_session) is None
        else "stale" if recorded_session != current_session
        else "current"
    )
    return {
        "status": status,
        "current_session": current_session,
        "current_session_label": session_label(current_session) if current_session else None,
        "study_year": year,
        "recorded_session": recorded_session,
        "min_year": STUDY_YEAR_MIN,
        "max_year": STUDY_YEAR_MAX,
        "collection_only": True,
    }


def academic_standing_reasons(
    changes: Mapping[str, object],
    *,
    current_session: int | None = None,
    student: bool = False,
) -> list[Reason]:
    """Require an explicit year/session pair, including when clearing or restating.

    Administrative imports may record an older session honestly; the student's
    current-profile form must echo the session it displayed. A stale browser
    cannot accidentally confirm a new academic session on their behalf.
    """
    if not ACADEMIC_STANDING_FIELDS.intersection(changes):
        return []
    if not ACADEMIC_STANDING_FIELDS.issubset(changes):
        return [Reason(
            code=INVALID_FIELD_VALUE,
            human="Submit year of study and its academic session together.",
            path="study_year_session",
        )]
    year = changes.get("study_year")
    session = changes.get("study_year_session")
    if year is None and session is None:
        return []
    if year is None or session is None:
        return [Reason(
            code=INVALID_FIELD_VALUE,
            human="Year of study and its academic session must both be set, or both cleared.",
            path="study_year_session",
        )]
    if student and (current_session is None or session != current_session):
        return [Reason(
            code=INVALID_FIELD_VALUE,
            human=(
                "The office has not configured the current academic session yet."
                if current_session is None else
                "The academic session has changed. Refresh your profile and confirm your year."
            ),
            path="study_year_session",
        )]
    return []
