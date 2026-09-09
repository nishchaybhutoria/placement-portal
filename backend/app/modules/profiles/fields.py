"""Profile field registry and pure value validation for Behavior PRO-1.

The registry is the single code-constant statement of which fields the student
owns and which the administration owns.  ``tests/profiles/test_field_registry``
asserts it against the PRO-1 field inventory transcribed from the spec.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Literal
from uuid import UUID

from app.domain.shared import Gender, is_blank


class FieldOwner(StrEnum):
    """Who may write a field once the profile has been declared (PRO-1)."""

    STUDENT = "student"
    ADMIN = "admin"


FieldHome = Literal["profiles", "enrollments", "users"]


@dataclass(frozen=True, slots=True)
class ProfileField:
    key: str
    owner: FieldOwner
    home: FieldHome
    label: str


FIELDS: tuple[ProfileField, ...] = (
    ProfileField("full_name", FieldOwner.ADMIN, "users", "Full name"),
    ProfileField("roll_number", FieldOwner.ADMIN, "enrollments", "Roll number"),
    ProfileField("program_id", FieldOwner.ADMIN, "profiles", "Program"),
    ProfileField("primary_branch_id", FieldOwner.ADMIN, "profiles", "Primary branch"),
    # A student completing two majors at once, one primary and one secondary
    # (the design review section 4.32).  It qualifies the student, not their program:
    # two students on the same BTech differ on exactly this.
    ProfileField("is_dual_major", FieldOwner.ADMIN, "profiles", "Dual major"),
    ProfileField("is_dual_degree", FieldOwner.ADMIN, "profiles", "Dual degree"),
    ProfileField("secondary_program_id", FieldOwner.ADMIN, "profiles", "Secondary program"),
    ProfileField("secondary_branch_id", FieldOwner.ADMIN, "profiles", "Secondary branch"),
    ProfileField("graduating_year", FieldOwner.ADMIN, "profiles", "Graduating year"),
    ProfileField("cpi", FieldOwner.ADMIN, "profiles", "CPI"),
    ProfileField("active_backlogs", FieldOwner.ADMIN, "profiles", "Active backlog count"),
    ProfileField("total_backlogs", FieldOwner.ADMIN, "profiles", "Total backlog count"),
    ProfileField("gender", FieldOwner.ADMIN, "profiles", "Gender"),
    ProfileField("personal_email", FieldOwner.STUDENT, "profiles", "Personal email"),
    ProfileField("contact_number", FieldOwner.STUDENT, "profiles", "Contact number"),
    ProfileField("nationality", FieldOwner.STUDENT, "profiles", "Nationality"),
    ProfileField("tenth_percent", FieldOwner.STUDENT, "profiles", "10th percentage"),
    ProfileField("tenth_year", FieldOwner.STUDENT, "profiles", "10th year"),
    ProfileField("twelfth_percent", FieldOwner.STUDENT, "profiles", "12th percentage"),
    ProfileField("twelfth_year", FieldOwner.STUDENT, "profiles", "12th year"),
    ProfileField("minor1_id", FieldOwner.STUDENT, "profiles", "Minor 1"),
    ProfileField("minor2_id", FieldOwner.STUDENT, "profiles", "Minor 2"),
    ProfileField("github_url", FieldOwner.STUDENT, "profiles", "GitHub URL"),
    ProfileField("linkedin_url", FieldOwner.STUDENT, "profiles", "LinkedIn URL"),
    ProfileField("portfolio_url", FieldOwner.STUDENT, "profiles", "Portfolio URL"),
)

FIELDS_BY_KEY: dict[str, ProfileField] = {field.key: field for field in FIELDS}
STUDENT_FIELDS: frozenset[str] = frozenset(
    field.key for field in FIELDS if field.owner is FieldOwner.STUDENT
)
ADMIN_FIELDS: frozenset[str] = frozenset(
    field.key for field in FIELDS if field.owner is FieldOwner.ADMIN
)
PROFILE_COLUMNS: tuple[str, ...] = tuple(
    field.key for field in FIELDS if field.home == "profiles"
)
# Full name is seeded from Google at first sign-in (PRO-1), never self-declared.
DECLARABLE_FIELDS: frozenset[str] = frozenset(
    field.key for field in FIELDS if field.key != "full_name"
)
# Admin-managed columns a spreadsheet may carry (PRO-2); roll_number is additionally
# the cross-check key handled by the upsert command itself.
# The official roster may populate contact number initially, but bulk upsert
# must not overwrite a value subsequently maintained by the student.
BULK_FIELDS: frozenset[str] = ADMIN_FIELDS | {"contact_number"}
BULK_INITIAL_ONLY_FIELDS: frozenset[str] = frozenset({"contact_number"})
#: Profile fields stored as booleans; the rule engine treats these as
#: equality-only (LLD section 9.1 via `domain/rule_schema.BOOLEAN_FIELDS`).
BOOLEAN_FIELDS: frozenset[str] = frozenset({"is_dual_major", "is_dual_degree"})
TAXONOMY_FIELDS: dict[str, str] = {
    "program_id": "programs",
    "secondary_program_id": "programs",
    "primary_branch_id": "branches",
    "secondary_branch_id": "branches",
    "minor1_id": "minors",
    "minor2_id": "minors",
}
# SPEC-GAP: PRO-1 marks the institute email "System (admin can correct)" but no card
# specifies what a key change does to live sessions, staged rows, or notification
# history, so the conservative path rejects it (the design review 4.15 ruling 4).
UNEDITABLE_FIELDS: frozenset[str] = frozenset({"institute_email", "email"})
#: Admin-managed fields the student may never supply, whatever their value.
#: ``full_name`` is seeded from Google at first sign-in (PRO-1) and the profile
#: form has never offered it.
NEVER_UNLOCKED_FIELDS: frozenset[str] = frozenset({"full_name"})

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$")
_PHONE = re.compile(r"^\+?[0-9][0-9 \-]{5,19}$")
_HTTPS_URL = re.compile(r"^https://[^\s/$.?#][^\s]*$")
_ROLL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-/]{0,31}$")


class FieldValueError(ValueError):
    """A single field value that failed pure validation."""

    def __init__(self, key: str, human: str) -> None:
        super().__init__(human)
        self.key = key
        self.human = human


def _text(key: str, value: object, *, maximum: int) -> str | None:
    if not isinstance(value, str):
        raise FieldValueError(key, f"{FIELDS_BY_KEY[key].label} must be text")
    stripped = value.strip()
    if not stripped:
        return None
    if len(stripped) > maximum:
        raise FieldValueError(
            key, f"{FIELDS_BY_KEY[key].label} must be at most {maximum} characters"
        )
    return stripped


def _integer(key: str, value: object, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise FieldValueError(key, f"{FIELDS_BY_KEY[key].label} must be a whole number")
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate.lstrip("-").isdigit():
            raise FieldValueError(
                key, f"{FIELDS_BY_KEY[key].label} must be a whole number"
            )
        number = int(candidate)
    elif isinstance(value, int):
        number = value
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    else:
        raise FieldValueError(key, f"{FIELDS_BY_KEY[key].label} must be a whole number")
    if not minimum <= number <= maximum:
        raise FieldValueError(
            key,
            f"{FIELDS_BY_KEY[key].label} must be between {minimum} and {maximum}",
        )
    return number


def _decimal(key: str, value: object, *, maximum: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, (dict, list)):
        raise FieldValueError(key, f"{FIELDS_BY_KEY[key].label} must be a number")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as error:
        raise FieldValueError(
            key, f"{FIELDS_BY_KEY[key].label} must be a number"
        ) from error
    if not number.is_finite():
        raise FieldValueError(key, f"{FIELDS_BY_KEY[key].label} must be a number")
    exponent = number.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2:
        raise FieldValueError(
            key, f"{FIELDS_BY_KEY[key].label} allows at most two decimal places"
        )
    if not Decimal("0") <= number <= Decimal(maximum):
        raise FieldValueError(
            key, f"{FIELDS_BY_KEY[key].label} must be between 0 and {maximum}"
        )
    return number


#: What a spreadsheet may write in a yes/no column (PRO-2).  Listed rather than
#: guessed at, because "0" and "no" have to mean false and `bool("0")` does not.
_TRUE = frozenset({"true", "t", "yes", "y", "1"})
_FALSE = frozenset({"false", "f", "no", "n", "0"})


def _boolean(key: str, value: object) -> bool:
    if isinstance(value, bool):
        return value
    candidate = str(value).strip().casefold()
    if candidate in _TRUE:
        return True
    if candidate in _FALSE:
        return False
    raise FieldValueError(key, f"{FIELDS_BY_KEY[key].label} must be yes or no")


def _uuid(key: str, value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value.strip())
        except ValueError as error:
            raise FieldValueError(
                key, f"{FIELDS_BY_KEY[key].label} must be a valid identifier"
            ) from error
    raise FieldValueError(key, f"{FIELDS_BY_KEY[key].label} must be a valid identifier")


def coerce_field(key: str, value: object) -> object:
    """Validate one provided field value; ``None`` and blanks clear the column."""
    if key not in FIELDS_BY_KEY:
        raise FieldValueError(key, "Unknown profile field")
    field = FIELDS_BY_KEY[key]
    if value is None:
        if key == "full_name":
            raise FieldValueError(key, "Full name is required")
        # The column is NOT NULL: a blank yes/no cell clears the fact to
        # "no", where clearing every other column means "unknown".
        if key in BOOLEAN_FIELDS:
            return False
        return None
    if isinstance(value, str) and not value.strip() and key != "full_name":
        return False if key in BOOLEAN_FIELDS else None

    if key in BOOLEAN_FIELDS:
        return _boolean(key, value)
    if key in TAXONOMY_FIELDS:
        return _uuid(key, value)
    if key == "gender":
        candidate = str(value).strip().casefold()
        if candidate not in {item.value for item in Gender}:
            raise FieldValueError(key, "Gender must be male, female, or other")
        return candidate
    if key == "cpi":
        return _decimal(key, value, maximum="10")
    if key in {"tenth_percent", "twelfth_percent"}:
        return _decimal(key, value, maximum="100")
    if key in {"graduating_year", "tenth_year", "twelfth_year"}:
        return _integer(key, value, minimum=1900, maximum=2100)
    if key in {"active_backlogs", "total_backlogs"}:
        return _integer(key, value, minimum=0, maximum=99)
    if key == "personal_email":
        text = _text(key, value, maximum=254)
        if text is not None and not EMAIL_PATTERN.match(text):
            raise FieldValueError(key, "Personal email must be a valid address")
        return text
    if key == "contact_number":
        text = _text(key, value, maximum=20)
        if text is not None and not _PHONE.match(text):
            raise FieldValueError(key, "Contact number must be a valid phone number")
        return text
    if key in {"github_url", "linkedin_url", "portfolio_url"}:
        text = _text(key, value, maximum=2048)
        if text is not None and not _HTTPS_URL.match(text):
            raise FieldValueError(key, f"{field.label} must be an https link")
        return text
    if key == "roll_number":
        text = _text(key, value, maximum=32)
        if text is not None and not _ROLL.match(text):
            raise FieldValueError(key, "Roll number contains unsupported characters")
        return text
    if key == "full_name":
        text = _text(key, value, maximum=200)
        if text is None:
            raise FieldValueError(key, "Full name is required")
        return text
    if key == "nationality":
        return _text(key, value, maximum=64)
    raise FieldValueError(key, "Unknown profile field")


def jsonable(value: object) -> object:
    """Render a coerced field value for audit details and screen payloads."""
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    return value


def unlocked_admin_fields(
    current: Mapping[str, object], *, roll_number: object = None
) -> frozenset[str]:
    """Admin-managed fields that have not yet accepted an initial value.

    PRO-1 locks an admin-managed field once it "accepts the student's initial
    value".  the design review section 4.33 rules that the lock therefore follows the
    *value*, not ``declared_at``: a column still blank has accepted nothing, so
    its intended source may still supply it.  Pure -- the caller passes the
    profile row it loaded.

    ``roll_number`` lives on ``enrollments`` rather than ``profiles`` (the design review
    section 4.1), so it arrives separately.  ``is_dual_major`` is NOT NULL and
    can never read blank, which would leave it the one PRO-1 field a student
    could never state; it is unlocked exactly while ``secondary_branch_id`` is,
    since 4.32 made the two inseparable.
    """
    unlocked = {
        key
        for key in ADMIN_FIELDS - NEVER_UNLOCKED_FIELDS
        - {"roll_number", "is_dual_major", "is_dual_degree"}
        if is_blank(current.get(key))
    }
    if is_blank(roll_number):
        unlocked.add("roll_number")
    if is_blank(current.get("secondary_branch_id")):
        unlocked.add("is_dual_major")
        unlocked.add("is_dual_degree")
    return frozenset(unlocked)
