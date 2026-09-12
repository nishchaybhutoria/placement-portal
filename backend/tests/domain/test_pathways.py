"""ELG-2: which disciplines answer a rule, and the roster rule that decides.

The institute's own eligibility roster states the dual-major rule once: the
second discipline opens at the beginning of fourth year, the primary from
third. These prove that rule and the fail-closed behaviour that keeps a
student whose standing is unknown from being silently excluded.
"""

from uuid import UUID

import pytest

from app.domain.pathways import (
    SECOND_DISCIPLINE_YEAR,
    derived_rule_facts,
    eligible_disciplines,
)
from app.domain.rules import RuleContext, evaluate, parse_rule
from app.domain.shared import ProgramStructure

CONTEXT = RuleContext(not_placement_placed=True)
EE = UUID("00000000-0000-0000-0000-0000000000ee")
ICDT = UUID("00000000-0000-0000-0000-000000001cd7")
CSE = UUID("00000000-0000-0000-0000-000000000c5e")
LABELS = {EE: "Electrical Engineering", ICDT: "ICDT", CSE: "Computer Science"}


def _single(branch: UUID | None) -> dict[str, object]:
    return {
        "primary_branch_id": branch,
        "program_structure": ProgramStructure.SINGLE.value,
    }


def _dual_major(
    primary: UUID | None, secondary: UUID | None, year: object
) -> dict[str, object]:
    return {
        "primary_branch_id": primary,
        "secondary_branch_id": secondary,
        "program_structure": ProgramStructure.DUAL_MAJOR.value,
        "study_year": year,
    }


def _dual_degree(primary: UUID, secondary: UUID | None) -> dict[str, object]:
    return {
        "primary_branch_id": primary,
        "secondary_branch_id": secondary,
        "program_structure": ProgramStructure.DUAL_DEGREE.value,
    }


def test_ELG2_single_discipline_student_answers_with_their_own_branch() -> None:
    assert eligible_disciplines(_single(EE)) == frozenset({EE})


def test_ELG2_dual_major_second_discipline_opens_in_the_fourth_year() -> None:
    """The roster rule verbatim: primary from third year, second from fourth."""
    for year in (1, 2, 3):
        assert eligible_disciplines(_dual_major(EE, CSE, year)) == frozenset({EE})
    for year in (SECOND_DISCIPLINE_YEAR, 5, 8):
        assert eligible_disciplines(_dual_major(EE, CSE, year)) == frozenset({EE, CSE})


def test_ELG2_dual_degree_answers_with_its_postgraduate_discipline_alone() -> None:
    assert eligible_disciplines(_dual_degree(EE, CSE)) == frozenset({CSE})
    # The undergraduate half does not qualify it for its own discipline.
    assert EE not in (eligible_disciplines(_dual_degree(EE, CSE)) or frozenset())


@pytest.mark.parametrize("profile", [
    {},
    # A profile naming no programme: the shape of the enrollment is unknown,
    # which is not the same as a single-discipline one.
    {"primary_branch_id": EE},
    {"program_structure": "a shape this build does not know"},
    _single(None),
    _dual_major(EE, CSE, None),
    _dual_major(EE, CSE, True),
    _dual_major(None, CSE, 4),
    _dual_degree(EE, None),
])
def test_ELG2_unknowable_standing_is_none_rather_than_an_empty_answer(
    profile: dict[str, object],
) -> None:
    """None means "not yet knowable", never "this student holds no discipline"."""
    assert eligible_disciplines(profile) is None


def test_ELG2_a_recorded_primary_is_not_withheld_for_a_missing_second() -> None:
    """A fourth-year dual major still answers with the discipline that is known."""
    assert eligible_disciplines(_dual_major(EE, None, 4)) == frozenset({EE})


@pytest.mark.parametrize("op, expected, disciplines, verdict", [
    ("in", [str(EE), str(ICDT)], frozenset({EE}), True),
    ("in", [str(EE), str(ICDT)], frozenset({CSE}), False),
    ("in", [str(EE), str(ICDT)], frozenset({CSE, ICDT}), True),
    ("not_in", [str(EE)], frozenset({CSE}), True),
    ("not_in", [str(EE)], frozenset({CSE, EE}), False),
    ("eq", str(EE), frozenset({EE, CSE}), True),
    ("eq", str(EE), frozenset({CSE}), False),
    ("ne", str(EE), frozenset({CSE}), True),
    ("ne", str(EE), frozenset({EE}), False),
])
def test_ELG2_any_discipline_the_student_may_use_answers_the_rule(
    op: str, expected: object, disciplines: frozenset[UUID], verdict: bool,
) -> None:
    rule = parse_rule({"field": "discipline_id", "op": op, "value": expected})
    assert evaluate(rule, {"discipline_id": disciplines}, CONTEXT).verdict is verdict


@pytest.mark.parametrize("op, value", [
    ("in", [str(EE)]), ("not_in", [str(EE)]), ("eq", str(EE)), ("ne", str(EE)),
])
@pytest.mark.parametrize("unknown", [None, frozenset()])
def test_ELG2_unknown_disciplines_fail_closed_in_both_directions(
    op: str, value: object, unknown: object,
) -> None:
    """not_in must not pass a student the portal cannot place in a discipline."""
    rule = parse_rule({"field": "discipline_id", "op": op, "value": value})
    outcome = evaluate(rule, {"discipline_id": unknown}, CONTEXT, labels=LABELS)
    assert outcome.verdict is False
    assert "does not yet say which disciplines" in outcome.failures[0].human


def test_ELG2_shortfall_names_the_disciplines_the_student_may_apply_in() -> None:
    rule = parse_rule({"field": "discipline_id", "op": "in", "value": [str(EE)]})
    one = evaluate(rule, {"discipline_id": frozenset({CSE})}, CONTEXT, labels=LABELS)
    assert one.failures[0].human == (
        "Requires discipline one of Electrical Engineering; yours is Computer Science."
    )
    two = evaluate(
        rule, {"discipline_id": frozenset({CSE, ICDT})}, CONTEXT, labels=LABELS
    )
    assert two.failures[0].human == (
        "Requires discipline one of Electrical Engineering; "
        "yours are Computer Science, ICDT."
    )


def test_ELG2_the_ixana_defect_a_single_discipline_student_is_not_excluded() -> None:
    """The stored rule ANDed both branch columns, so NULL secondary failed everyone.

    Stated as one discipline condition, the same intent admits the students it
    always meant to: single-discipline, dual major and dual degree alike.
    """
    paired = parse_rule({"all": [
        {"field": "primary_branch_id", "op": "in", "value": [str(EE), str(ICDT)]},
        {"field": "secondary_branch_id", "op": "in", "value": [str(EE), str(ICDT)]},
    ]})
    corrected = parse_rule(
        {"field": "discipline_id", "op": "in", "value": [str(EE), str(ICDT)]}
    )
    single = _single(EE)
    single["discipline_id"] = eligible_disciplines(single)
    assert evaluate(paired, single, CONTEXT).verdict is False
    assert evaluate(corrected, single, CONTEXT).verdict is True

    fourth_year = _dual_major(CSE, ICDT, 4)
    fourth_year["discipline_id"] = eligible_disciplines(fourth_year)
    assert evaluate(corrected, fourth_year, CONTEXT).verdict is True

    third_year = _dual_major(CSE, ICDT, 3)
    third_year["discipline_id"] = eligible_disciplines(third_year)
    assert evaluate(corrected, third_year, CONTEXT).verdict is False


def test_ELG2_a_rule_naming_a_degree_still_matches_the_programmes_built_on_it() -> None:
    """The migration must not quietly narrow the rules it carries across.

    "BTech Dual Major" is a new programme, and a saved rule naming BTech was
    written when its dual majors were BTech with a flag. The rule keeps meaning
    what its author meant: enrolled in a programme built on BTech.
    """
    btech = UUID("00000000-0000-0000-0000-0000000b7ec8")
    dual_major = UUID("00000000-0000-0000-0000-00000000d117")
    mtech = UUID("00000000-0000-0000-0000-00000000117e")

    facts = derived_rule_facts({
        "program_id": dual_major,
        "program_primary_degree_id": btech,
        "program_secondary_degree_id": btech,
        "program_structure": ProgramStructure.DUAL_MAJOR.value,
    })
    assert facts["eligible_program_ids"] == frozenset({dual_major, btech})

    rule = parse_rule({"field": "program_id", "op": "in", "value": [str(btech)]})
    assert evaluate(rule, facts, CONTEXT).verdict is True
    # And naming the combined programme alone still selects only it.
    exact = parse_rule({"field": "program_id", "op": "in", "value": [str(dual_major)]})
    assert evaluate(exact, facts, CONTEXT).verdict is True
    assert evaluate(
        parse_rule({"field": "program_id", "op": "in", "value": [str(mtech)]}),
        facts,
        CONTEXT,
    ).verdict is False


def test_ELG2_the_declared_programme_is_kept_beside_the_widened_set() -> None:
    """Per-programme CTC and the record screens read the one they are in."""
    dual_major = UUID("00000000-0000-0000-0000-00000000d117")
    profile: dict[str, object] = {
        "program_id": dual_major,
        "program_structure": ProgramStructure.DUAL_MAJOR.value,
    }
    profile.update(derived_rule_facts(profile))
    assert profile["program_id"] == dual_major
