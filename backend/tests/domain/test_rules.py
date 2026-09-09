"""Pure ELG-1/2 eligibility-rule contracts."""

from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.rules import RuleContext, RuleField, evaluate, parse_rule

CONTEXT = RuleContext(not_placement_placed=True)
PROGRAM = UUID("00000000-0000-0000-0000-000000000101")
OTHER_PROGRAM = UUID("00000000-0000-0000-0000-000000000102")


def _verdict(field: str, op: str, expected: object, actual: object) -> bool:
    rule = parse_rule({"field": field, "op": op, "value": expected})
    return evaluate(rule, {field: actual}, CONTEXT).verdict


@pytest.mark.parametrize(
    ("field", "op", "expected", "actual", "verdict"),
    [
        ("program_id", "eq", str(PROGRAM), PROGRAM, True),
        ("program_id", "eq", str(PROGRAM), OTHER_PROGRAM, False),
        ("nationality", "ne", "US", "IN", True),
        ("nationality", "ne", "IN", "IN", False),
        ("gender", "in", ["female", "other"], "female", True),
        ("gender", "in", ["female", "other"], "male", False),
        ("program_id", "not_in", [str(OTHER_PROGRAM)], PROGRAM, True),
        ("program_id", "not_in", [str(PROGRAM)], PROGRAM, False),
        ("active_backlogs", "gte", 1, 1, True),
        ("active_backlogs", "gte", 1, 0, False),
        ("cpi", "lte", 8.0, Decimal("8.0"), True),
        ("cpi", "lte", 8.0, Decimal("8.1"), False),
        ("graduating_year", "between", [2025, 2027], 2025, True),
        ("graduating_year", "between", [2025, 2027], 2027, True),
        ("graduating_year", "between", [2025, 2027], 2028, False),
        ("tenth_percent", "between", [80, 90], Decimal("85.5"), True),
    ],
)
def test_ELG2_operator_table_covers_types_and_edges(
    field: str, op: str, expected: object, actual: object, verdict: bool
) -> None:
    assert _verdict(field, op, expected, actual) is verdict


@pytest.mark.parametrize(
    "op,expected",
    [
        ("eq", 0),
        ("ne", 0),
        ("in", [0]),
        ("not_in", [0]),
        ("gte", 0),
        ("lte", 0),
        ("between", [0, 1]),
    ],
)
def test_ELG2_null_profile_values_fail_every_comparison(op: str, expected: object) -> None:
    result = evaluate(
        parse_rule({"field": "active_backlogs", "op": op, "value": expected}),
        {"active_backlogs": None},
        CONTEXT,
    )
    assert result.verdict is False
    assert len(result.failures) == 1
    assert result.failures[0].path == "$"


def test_ELG2_CPI_round_half_up_contract() -> None:
    rule = parse_rule({"field": "cpi", "op": "gte", "value": 8.0})
    assert evaluate(rule, {"cpi": Decimal("7.95")}, CONTEXT).verdict is True
    assert evaluate(rule, {"cpi": Decimal("7.94")}, CONTEXT).verdict is False


def test_ELG2_a_failed_any_is_reported_as_one_choice_at_its_own_path() -> None:
    """An ``any``'s branches are alternatives, so they are reported together.

    Listing them separately would assert each branch as its own requirement,
    which is false: the student has to meet one of them, not all
    (the design review section 4.19).
    """
    rule = parse_rule(
        {
            "all": [
                {
                    "any": [
                        {"field": "cpi", "op": "gte", "value": 9},
                        {"field": "active_backlogs", "op": "lte", "value": 0},
                    ]
                },
                {"not": {"field": "nationality", "op": "eq", "value": "IN"}},
            ]
        }
    )
    result = evaluate(
        rule,
        {"cpi": 8, "active_backlogs": 2, "nationality": "IN"},
        CONTEXT,
    )
    assert result.verdict is False
    assert [failure.path for failure in result.failures] == ["$.all[0]", "$.all[1]"]
    assert result.failures[0].human == (
        "Must satisfy one of: CPI at least 9 (yours is 8.0); "
        "or active backlogs at most 0 (yours is 2)."
    )
    assert all(failure.human for failure in result.failures)


def test_ELG2_a_satisfied_any_branch_is_never_reported_as_a_failure() -> None:
    """The regression the grouping exists to prevent (the design review section 4.19).

    This student's branch matches the first alternative and only their CPI is
    short.  Flattened, they were told the *other* alternative's branch
    requirement -- a requirement they do not need and cannot act on.
    """
    cse = UUID("22222222-2222-2222-2222-222222222222")
    ee = UUID("33333333-3333-3333-3333-333333333333")
    rule = parse_rule(
        {
            "any": [
                {
                    "all": [
                        {"field": "primary_branch_id", "op": "eq", "value": str(cse)},
                        {"field": "cpi", "op": "gte", "value": 8.0},
                    ]
                },
                {
                    "all": [
                        {"field": "primary_branch_id", "op": "eq", "value": str(ee)},
                        {"field": "cpi", "op": "gte", "value": 7.5},
                    ]
                },
            ]
        }
    )
    result = evaluate(
        rule,
        {"primary_branch_id": cse, "cpi": Decimal("7.62")},
        CONTEXT,
        labels={cse: "Computer Science", ee: "Electrical Engineering"},
    )

    assert result.verdict is False
    assert len(result.failures) == 1
    assert result.failures[0].human == (
        "Must satisfy one of: CPI at least 8.0 (yours is 7.6); "
        "or primary branch Electrical Engineering (yours is Computer Science)."
    )
    # The branch the student already satisfies is never stated as unmet.
    assert "primary branch Computer Science" not in result.failures[0].human


def test_ELG2_failing_not_never_returns_an_empty_failure_list() -> None:
    result = evaluate(
        parse_rule({"not": {"field": "cpi", "op": "gte", "value": 8}}),
        {"cpi": 8.5},
        CONTEXT,
    )
    assert result.verdict is False
    assert len(result.failures) == 1
    assert result.failures[0].path == "$"


def test_ELG2_not_wrapping_placement_criterion_has_a_readable_reason() -> None:
    result = evaluate(
        parse_rule({"not": {"criterion": "not_placement_placed"}}),
        {},
        RuleContext(not_placement_placed=True),
    )
    assert result.verdict is False
    assert result.failures[0].human == (
        "This job is open only to students who have already accepted a "
        "placement offer."
    )
    assert "not not" not in result.failures[0].human.casefold()


def test_ELG1_evaluation_uses_the_live_profile_each_time() -> None:
    rule = parse_rule({"field": "cpi", "op": "gte", "value": 8})
    assert evaluate(rule, {"cpi": 7}, CONTEXT).verdict is False
    assert evaluate(rule, {"cpi": 9}, CONTEXT).verdict is True


def test_DER1_context_criterion_is_precomputed_and_pure() -> None:
    rule = parse_rule({"criterion": "not_placement_placed"})
    assert evaluate(rule, {}, RuleContext(not_placement_placed=True)).verdict is True
    failed = evaluate(rule, {}, RuleContext(not_placement_placed=False))
    assert failed.verdict is False
    assert failed.failures[0].path == "$"


def test_ELG2_field_registry_is_exactly_the_approved_academic_set() -> None:
    assert {field.value for field in RuleField} == {
        "program_id",
        "secondary_program_id",
        "primary_branch_id",
        "secondary_branch_id",
        "graduating_year",
        "cpi",
        "active_backlogs",
        "total_backlogs",
        "gender",
        "tenth_percent",
        "tenth_year",
        "twelfth_percent",
        "twelfth_year",
        "minor1_id",
        "minor2_id",
        "nationality",
        # Added by the M9 amendment closing the design review section 4.18: a rule can
        # target dual majors, which the schema previously could not express.
        "is_dual_major",
        "is_dual_degree",
    }
    with pytest.raises(ValidationError):
        parse_rule({"field": "personal_email", "op": "eq", "value": "x@example.com"})


@pytest.mark.parametrize(
    "rule",
    [
        {"all": []},
        {"any": []},
        {"field": "nationality", "op": "gte", "value": "IN"},
        {"field": "cpi", "op": "between", "value": [9, 8]},
        {"field": "cpi", "op": "eq", "value": None},
        {"unknown": []},
    ],
)
def test_ELG2_invalid_rule_shapes_fail_closed(rule: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        parse_rule(rule)
