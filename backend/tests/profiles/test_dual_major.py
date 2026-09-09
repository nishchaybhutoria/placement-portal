"""Dual majors (Behavior PRO-1, ELG-2; the design review sections 4.19, 4.32).

A dual major is a **student** completing two majors at once, one primary and
one secondary -- not a kind of program.  Section 4.18 originally put the flag
on the ``programs`` taxonomy row; section 4.32 reverses that and moves it to
``profiles.is_dual_major``, beside the two branch columns it governs.  These
tests pin the three things that follow: PRO-1 asks the secondary branch of
exactly the students who hold one, the pair cannot contradict itself, and
ELG-2 rules keep reading the same field name they always have.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.domain.memberships import check_profile_completeness, required_join_fields
from app.domain.rules import RuleContext, RuleField, evaluate, parse_rule
from app.modules.profiles.commands import program_branch_reasons
from app.modules.profiles.fields import (
    BULK_FIELDS,
    FIELDS_BY_KEY,
    PROFILE_COLUMNS,
    FieldOwner,
    FieldValueError,
    coerce_field,
)


def _profile(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "full_name": "Asha Rao",
        "roll_number": "21110001",
        "program_id": uuid4(),
        "primary_branch_id": uuid4(),
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
    return base | overrides


def test_PRO1_a_dual_major_must_name_a_secondary_branch() -> None:
    reasons = check_profile_completeness(
        _profile(is_dual_major=True), resume_count=1, declared=True
    )

    assert [reason.path for reason in reasons] == ["secondary_branch_id"]
    assert reasons[0].human == "Secondary branch is required to join a cycle"


def test_PRO1_a_single_major_is_complete_without_a_secondary_branch() -> None:
    assert (
        check_profile_completeness(
            _profile(is_dual_major=False), resume_count=1, declared=True
        )
        == ()
    )
    # A profile that does not state the fact is treated as single-major rather
    # than blocking: the column defaults to false and says so.
    assert check_profile_completeness(_profile(), resume_count=1, declared=True) == ()


def test_PRO1_a_dual_major_with_a_secondary_branch_is_complete() -> None:
    assert (
        check_profile_completeness(
            _profile(is_dual_major=True, secondary_branch_id=uuid4()),
            resume_count=1,
            declared=True,
        )
        == ()
    )


def test_PRO1_the_required_field_list_depends_on_the_student() -> None:
    single = required_join_fields(dual_major=False)
    dual = required_join_fields(dual_major=True)
    assert "secondary_branch_id" not in single
    assert set(dual) - set(single) == {"secondary_branch_id"}


def test_ELG2_a_rule_can_target_dual_majors() -> None:
    tree = parse_rule({"field": "is_dual_major", "op": "eq", "value": True})
    context = RuleContext(not_placement_placed=True)

    assert evaluate(tree, {"is_dual_major": True}, context).verdict is True
    failed = evaluate(tree, {"is_dual_major": False}, context)
    assert failed.verdict is False
    assert failed.failures[0].human == (
        "Requires a dual major; you are not one."
    )


def test_ELG2_the_dual_major_field_is_in_the_rule_registry() -> None:
    assert RuleField.IS_DUAL_MAJOR.value == "is_dual_major"


@pytest.mark.parametrize(
    "node",
    [
        {"field": "is_dual_major", "op": "eq", "value": "yes"},
        {"field": "is_dual_major", "op": "gte", "value": True},
        {"field": "is_dual_major", "op": "in", "value": [True, False]},
    ],
)
def test_ELG2_a_true_false_field_rejects_nonsensical_operators(
    node: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        parse_rule(node)


def test_PRO1_the_flag_is_an_admin_managed_profile_field() -> None:
    """It is a PRO-1 field, which is what carries it everywhere else.

    Registering it in the field registry is the whole mechanism: `PROFILE_COLUMNS`,
    the PRO-2 bulk columns, `me/profile`, the ANA-4 export registry and the INT-2
    snapshot diff all derive from `FIELDS`, so this one assertion is what stops
    the column being visible to some of them and not others.
    """
    field = FIELDS_BY_KEY["is_dual_major"]
    assert field.owner is FieldOwner.ADMIN
    assert field.home == "profiles"
    assert "is_dual_major" in PROFILE_COLUMNS
    assert "is_dual_major" in BULK_FIELDS


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        ("yes", True),
        ("Y", True),
        ("1", True),
        ("no", False),
        ("FALSE", False),
        ("0", False),
        # A blank cell clears the fact to "no": the column is NOT NULL, so
        # unlike every other field there is no "unknown" to clear it to.
        ("", False),
        (None, False),
    ],
)
def test_PRO2_a_spreadsheet_yes_or_no_becomes_the_flag(
    value: object, expected: bool
) -> None:
    assert coerce_field("is_dual_major", value) is expected


def test_PRO2_an_unreadable_yes_or_no_is_a_row_error() -> None:
    with pytest.raises(FieldValueError, match="must be yes or no"):
        coerce_field("is_dual_major", "maybe")


def test_PRO1_a_secondary_branch_requires_the_student_to_be_a_dual_major() -> None:
    """The pair cannot contradict itself.

    A second major named by somebody who has not got one is not a harmless
    extra field -- it is the same fact stated two ways, disagreeing.
    """
    program, primary, secondary = uuid4(), uuid4(), uuid4()
    pairs = frozenset({(program, primary), (program, secondary)})

    reasons = program_branch_reasons(
        {
            "program_id": program,
            "primary_branch_id": primary,
            "secondary_branch_id": secondary,
            "is_dual_major": False,
        },
        pairs,
    )

    assert [reason.path for reason in reasons] == ["secondary_branch_id"]
    assert reasons[0].human == "Only a dual major or dual degree has a secondary branch"


def test_PRO1_a_dual_degree_uses_its_secondary_program_for_its_second_branch() -> None:
    btech, mtech, primary, secondary = uuid4(), uuid4(), uuid4(), uuid4()
    pairs = frozenset({(btech, primary), (mtech, secondary)})

    assert program_branch_reasons(
        {
            "program_id": btech,
            "primary_branch_id": primary,
            "is_dual_major": False,
            "is_dual_degree": True,
            "secondary_program_id": mtech,
            "secondary_branch_id": secondary,
        },
        pairs,
    ) == []
    reasons = check_profile_completeness(
        _profile(
            is_dual_degree=True,
            secondary_program_id=mtech,
            secondary_branch_id=None,
        ),
        resume_count=1,
        declared=True,
    )
    assert [reason.path for reason in reasons] == ["secondary_branch_id"]


def test_PRO1_a_dual_major_may_be_recorded_before_the_second_branch_is_known() -> None:
    """The flag alone is not an error: PRO-1 makes the branch a *join* rule.

    The office learns that a student is a dual major before it learns which
    second branch, and refusing the first fact until the second arrives would
    make the pair unrecordable in the order they actually arrive.
    """
    program, primary = uuid4(), uuid4()

    assert (
        program_branch_reasons(
            {
                "program_id": program,
                "primary_branch_id": primary,
                "is_dual_major": True,
            },
            frozenset({(program, primary)}),
        )
        == []
    )
