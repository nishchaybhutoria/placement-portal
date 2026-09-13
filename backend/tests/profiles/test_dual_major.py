"""Dual majors and dual degrees (PRO-1, ELG-2; the design review 4.19, 4.32).

Section 4.18 put the dual-major flag on the ``programs`` row; 4.32 moved it to
``profiles.is_dual_major`` beside the branch columns it governed.  Both readings
made the *profile* carry the shape of the enrollment, and a pair of booleans
beside a secondary programme id can disagree with itself: both set at once, a
secondary programme with no dual degree, a second discipline on neither.

The programme carries it instead.  "BTech Dual Major" and "BTech-MTech Dual
Degree" are programmes the office admits students into, a student is in one
programme, and the contradictions above cannot be written down.  These tests
pin what follows: PRO-1 asks the second discipline of exactly the programmes
that enrol one, each discipline is checked against the degree it comes from,
and rules written against the old field names keep evaluating.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.domain.memberships import check_profile_completeness, required_join_fields
from app.domain.pathways import ProgramPathway, derived_rule_facts
from app.domain.rules import RuleContext, RuleField, evaluate, parse_rule
from app.domain.shared import Outcome, ProgramStructure
from app.modules.profiles.commands import program_branch_reasons
from app.modules.profiles.fields import (
    BULK_FIELDS,
    FIELDS_BY_KEY,
    PROFILE_COLUMNS,
    FieldOwner,
)

CONTEXT = RuleContext(not_placement_placed=True)


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


def _pathways(
    program: UUID, structure: ProgramStructure, primary: UUID, secondary: UUID
) -> dict[UUID, ProgramPathway]:
    return {
        program: ProgramPathway(
            structure=structure,
            primary_degree_id=primary,
            secondary_degree_id=secondary,
        )
    }


def test_PRO1_a_programme_with_a_second_discipline_must_name_it() -> None:
    reasons = check_profile_completeness(
        _profile(), resume_count=1, declared=True, second_discipline=True
    )

    assert [reason.path for reason in reasons] == ["secondary_branch_id"]
    assert reasons[0].human == "Secondary branch is required to join a cycle"


def test_PRO1_a_single_programme_is_complete_without_a_second_discipline() -> None:
    assert check_profile_completeness(_profile(), resume_count=1, declared=True) == ()


def test_PRO1_a_second_discipline_named_completes_the_profile() -> None:
    assert (
        check_profile_completeness(
            _profile(secondary_branch_id=uuid4()),
            resume_count=1,
            declared=True,
            second_discipline=True,
        )
        == ()
    )


def test_PRO1_the_required_field_list_depends_on_the_programme() -> None:
    single = required_join_fields(second_discipline=False)
    dual = required_join_fields(second_discipline=True)
    assert "secondary_branch_id" not in single
    assert set(dual) - set(single) == {"secondary_branch_id"}
    # The combined programme names the postgraduate degree, so the profile
    # never has to -- and the join checklist stops asking for it.
    assert "secondary_program_id" not in dual


def test_PRO1_a_second_discipline_on_a_single_programme_is_a_contradiction() -> None:
    """Not a harmless extra field: the programme says there is no second slot."""
    program, primary, secondary = uuid4(), uuid4(), uuid4()
    pairs = frozenset({(program, primary), (program, secondary)})

    reasons = program_branch_reasons(
        {
            "program_id": program,
            "primary_branch_id": primary,
            "secondary_branch_id": secondary,
        },
        pairs,
        {program: ProgramPathway(ProgramStructure.SINGLE)},
    )

    assert [reason.path for reason in reasons] == ["secondary_branch_id"]
    assert reasons[0].human == "Only a dual major or dual degree has a secondary branch"


def test_PRO1_both_disciplines_may_name_the_same_branch() -> None:
    """One discipline, two qualifications: the pair repeating is not an error.

    A BTech continued into an MTech in the same discipline is the ordinary dual
    degree, and the office records dual majors that read the same way.
    """
    combined, btech, mtech, branch = uuid4(), uuid4(), uuid4(), uuid4()
    pairs = frozenset({(combined, branch), (btech, branch), (mtech, branch)})

    assert program_branch_reasons(
        {
            "program_id": combined,
            "primary_branch_id": branch,
            "secondary_branch_id": branch,
        },
        pairs,
        _pathways(combined, ProgramStructure.DUAL_DEGREE, btech, mtech),
    ) == []
    assert program_branch_reasons(
        {
            "program_id": combined,
            "primary_branch_id": branch,
            "secondary_branch_id": branch,
        },
        pairs,
        _pathways(combined, ProgramStructure.DUAL_MAJOR, btech, btech),
    ) == []


def test_PRO1_a_dual_degree_checks_its_second_discipline_against_the_pg_degree() -> None:
    combined, btech, mtech = uuid4(), uuid4(), uuid4()
    primary, secondary = uuid4(), uuid4()
    pairs = frozenset({(combined, primary), (btech, primary), (mtech, secondary)})
    pathways = _pathways(combined, ProgramStructure.DUAL_DEGREE, btech, mtech)

    assert program_branch_reasons(
        {
            "program_id": combined,
            "primary_branch_id": primary,
            "secondary_branch_id": secondary,
        },
        pairs,
        pathways,
    ) == []

    # A discipline the postgraduate degree does not offer is refused, even when
    # the undergraduate half does offer it.
    reasons = program_branch_reasons(
        {
            "program_id": combined,
            "primary_branch_id": primary,
            "secondary_branch_id": primary,
        },
        pairs,
        pathways,
    )
    assert [reason.path for reason in reasons] == ["secondary_branch_id"]
    assert reasons[0].human == (
        "Secondary branch is not offered by the postgraduate degree"
    )


def test_PRO1_a_dual_programme_may_be_recorded_before_the_second_branch() -> None:
    """PRO-1 makes the second discipline a *join* rule, not a declaration one.

    The office learns which programme a student is in before it learns their
    second discipline, and refusing the first until the second arrives would
    make the pair unrecordable in the order they actually arrive.
    """
    combined, btech, primary = uuid4(), uuid4(), uuid4()

    assert program_branch_reasons(
        {"program_id": combined, "primary_branch_id": primary},
        frozenset({(btech, primary)}),
        _pathways(combined, ProgramStructure.DUAL_MAJOR, btech, btech),
    ) == []


def test_PRO1_the_profile_no_longer_carries_the_shape_of_the_enrollment() -> None:
    """The three columns that could disagree are gone from the registry.

    Registering a field is the whole mechanism -- `PROFILE_COLUMNS`, the PRO-2
    bulk columns, `me/profile`, the ANA-4 export registry and the INT-2 snapshot
    diff all derive from `FIELDS` -- so their absence here is their absence
    everywhere.
    """
    for key in ("is_dual_major", "is_dual_degree", "secondary_program_id"):
        assert key not in FIELDS_BY_KEY
        assert key not in PROFILE_COLUMNS
        assert key not in BULK_FIELDS
    secondary = FIELDS_BY_KEY["secondary_branch_id"]
    assert secondary.owner is FieldOwner.ADMIN
    assert secondary.home == "profiles"


@pytest.mark.parametrize("structure, dual_major, dual_degree", [
    (ProgramStructure.SINGLE, False, False),
    (ProgramStructure.DUAL_MAJOR, True, False),
    (ProgramStructure.DUAL_DEGREE, False, True),
])
def test_ELG2_a_rule_written_against_the_old_field_names_still_evaluates(
    structure: ProgramStructure, dual_major: bool, dual_degree: bool,
) -> None:
    """A fact that moves house must not start failing the rules that named it."""
    facts = derived_rule_facts(
        {"program_structure": structure.value},
        outcome=Outcome.PLACEMENT,
        current_session=None,
    )
    assert facts["is_dual_major"] is dual_major
    assert facts["is_dual_degree"] is dual_degree

    tree = parse_rule({"field": "is_dual_major", "op": "eq", "value": True})
    assert evaluate(tree, facts, CONTEXT).verdict is dual_major


def test_ELG2_the_old_boolean_fields_remain_in_the_rule_registry() -> None:
    assert RuleField.IS_DUAL_MAJOR.value == "is_dual_major"
    assert RuleField.IS_DUAL_DEGREE.value == "is_dual_degree"


@pytest.mark.parametrize("node", [
    {"field": "is_dual_major", "op": "eq", "value": "yes"},
    {"field": "is_dual_major", "op": "gte", "value": True},
    {"field": "is_dual_major", "op": "in", "value": [True, False]},
])
def test_ELG2_a_true_false_field_rejects_nonsensical_operators(
    node: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        parse_rule(node)
