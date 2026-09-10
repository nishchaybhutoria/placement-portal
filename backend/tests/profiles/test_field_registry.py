"""The PRO-1 field inventory as code: ownership, locking, and value validation."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from app.modules.profiles.fields import (
    ADMIN_FIELDS,
    BULK_FIELDS,
    BULK_INITIAL_ONLY_FIELDS,
    DECLARABLE_FIELDS,
    FIELDS,
    FIELDS_BY_KEY,
    STUDENT_FIELDS,
    STUDENT_MAINTAINED_ADMIN_FIELDS,
    UNEDITABLE_FIELDS,
    FieldValueError,
    coerce_field,
    unlocked_admin_fields,
)

# Transcribed from docs/BEHAVIOR.md PRO-1 "Field inventory (confirmed)".
# Owner is the column "After initial declaration"; columns are this system's
# storage names for that row (the design review 4.1 puts roll_number on enrollments).
PRO1_INVENTORY: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Full name", "admin", ("full_name",)),
    ("Institute email", "system", ()),
    ("Roll number", "admin", ("roll_number",)),
    ("Program", "admin", ("program_id",)),
    ("Primary branch", "admin", ("primary_branch_id",)),
    # PRO-1 states the secondary branch as belonging to dual majors and asks it
    # of them conditionally. The condition needs somewhere to live, so the
    # inventory row covers the pair: the flag that says a student holds a second
    # major, and the branch it names (the design review 4.32).
    (
        "Secondary branch (dual majors)",
        "admin",
        (
            "is_dual_major",
            "is_dual_degree",
            "secondary_program_id",
            "secondary_branch_id",
        ),
    ),
    ("Graduating year", "admin", ("graduating_year",)),
    ("CPI (0-10, 2 dp)", "admin", ("cpi",)),
    ("Active backlog count", "admin", ("active_backlogs",)),
    ("Total (ever) backlog count", "admin", ("total_backlogs",)),
    ("Gender", "admin", ("gender",)),
    ("Personal email", "student", ("personal_email",)),
    ("Contact number", "student", ("contact_number",)),
    ("Nationality", "student", ("nationality",)),
    (
        "10th %, 10th year, 12th %, 12th year",
        "student",
        ("tenth_percent", "tenth_year", "twelfth_percent", "twelfth_year"),
    ),
    ("Minor 1 / Minor 2", "student", ("minor1_id", "minor2_id")),
    (
        "GitHub / LinkedIn / portfolio URLs",
        "student",
        ("github_url", "linkedin_url", "portfolio_url"),
    ),
    ("Resume library (PRO-3)", "student", ()),
)


def _inventory(owner: str) -> frozenset[str]:
    return frozenset(
        column for _, row_owner, columns in PRO1_INVENTORY if row_owner == owner
        for column in columns
    )


def test_PRO1_student_whitelist_equals_the_specification_table() -> None:
    assert STUDENT_FIELDS == _inventory("student")


def test_PRO1_admin_whitelist_equals_the_specification_table() -> None:
    assert ADMIN_FIELDS == _inventory("admin")


def test_PRO1_registry_holds_exactly_the_inventory_and_nothing_else() -> None:
    assert {field.key for field in FIELDS} == _inventory("student") | _inventory("admin")
    assert STUDENT_FIELDS.isdisjoint(ADMIN_FIELDS)
    # The institute email is the system's key: no whitelist may carry it.
    assert UNEDITABLE_FIELDS.isdisjoint(STUDENT_FIELDS | ADMIN_FIELDS)


def test_PRO1_declaration_covers_every_field_except_the_google_seeded_name() -> None:
    assert DECLARABLE_FIELDS == (STUDENT_FIELDS | ADMIN_FIELDS) - {"full_name"}


def test_PRO2_bulk_columns_include_admin_fields_and_initial_roster_contact() -> None:
    assert BULK_FIELDS == ADMIN_FIELDS | {"contact_number"}


def test_PRO1_the_semesterly_academic_fields_never_lock() -> None:
    """CPI, backlogs, and the graduating year move mid-degree (PRO-1).

    They stay admin-owned -- the roster is still authoritative and PRO-2 still
    writes them -- but the student may restate them at any time, so the lock
    that closes on every other admin field never closes on these four.
    """
    assert STUDENT_MAINTAINED_ADMIN_FIELDS <= ADMIN_FIELDS
    filled = {key: "set" for key in ADMIN_FIELDS}

    assert (
        unlocked_admin_fields(filled, roll_number="21110001")
        == STUDENT_MAINTAINED_ADMIN_FIELDS
    )


def test_PRO2_a_roster_upload_still_refreshes_the_student_maintained_fields() -> None:
    """The office's semesterly numbers overwrite whatever the student entered."""
    assert STUDENT_MAINTAINED_ADMIN_FIELDS <= BULK_FIELDS
    assert STUDENT_MAINTAINED_ADMIN_FIELDS.isdisjoint(BULK_INITIAL_ONLY_FIELDS)


def test_PRO1_field_homes_match_the_schema() -> None:
    assert FIELDS_BY_KEY["roll_number"].home == "enrollments"
    assert FIELDS_BY_KEY["full_name"].home == "users"
    assert all(
        FIELDS_BY_KEY[key].home == "profiles"
        for key in (STUDENT_FIELDS | ADMIN_FIELDS) - {"roll_number", "full_name"}
    )


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("cpi", "8.5", Decimal("8.5")),
        ("cpi", 10, Decimal("10")),
        ("cpi", "0", Decimal("0")),
        ("tenth_percent", "92.75", Decimal("92.75")),
        ("graduating_year", "2026", 2026),
        ("active_backlogs", 0, 0),
        ("gender", "Female", "female"),
        ("nationality", " IN ", "IN"),
        ("personal_email", "a.b@example.com", "a.b@example.com"),
        ("contact_number", "+1 202-555-0100", "+1 202-555-0100"),
        ("github_url", "https://github.com/example", "https://github.com/example"),
        ("roll_number", " 21110001 ", "21110001"),
        ("linkedin_url", "", None),
        ("minor1_id", None, None),
    ],
)
def test_PRO1_field_coercion_accepts_documented_values(
    key: str, value: object, expected: object
) -> None:
    assert coerce_field(key, value) == expected


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("cpi", "10.5"),
        ("cpi", "-1"),
        ("cpi", "8.555"),
        ("cpi", "not-a-number"),
        ("tenth_percent", "120"),
        ("graduating_year", "20xx"),
        ("active_backlogs", -1),
        ("active_backlogs", True),
        ("gender", "unspecified"),
        ("personal_email", "not-an-email"),
        ("contact_number", "phone"),
        ("github_url", "javascript:alert(1)"),
        ("github_url", "http://github.com/example"),
        ("program_id", "not-a-uuid"),
        ("full_name", None),
        ("roll_number", "roll number!"),
    ],
)
def test_PRO1_field_coercion_rejects_out_of_contract_values(key: str, value: object) -> None:
    with pytest.raises(FieldValueError):
        coerce_field(key, value)


def test_PRO1_uuid_fields_round_trip_identifiers() -> None:
    identifier = UUID("11111111-2222-3333-4444-555555555555")
    assert coerce_field("program_id", str(identifier)) == identifier
    assert coerce_field("program_id", identifier) == identifier
