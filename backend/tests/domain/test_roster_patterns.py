"""Every eligibility shape the CDS internship roster asks for (ELG-2).

``docs/ELIGIBILITY-COVERAGE.md`` certifies the roster workbook row by row: each
company's eligibility is one of a handful of structures, and every one of them
compiles from the visual rule editor.  The workbook itself is private
operational material, so what is fixed here is the *shape* -- the pathway
fan-out, the conditional minor, per-discipline CPI floors, the identity and
school-marks clauses, and the study-year cohorts -- against profiles built the
way production builds them.

These are the rules the office will actually write.  A change that keeps
``test_rules.py`` green while breaking one of these has broken the roster.
"""

from collections.abc import Mapping
from decimal import Decimal
from uuid import UUID

from app.domain.pathways import derived_rule_facts
from app.domain.rules import RuleContext, evaluate, parse_rule, summarize, taxonomy_ids
from app.domain.shared import Outcome, ProgramStructure

CONTEXT = RuleContext(not_placement_placed=True)
CURRENT_SESSION = 2026

BTECH = UUID("00000000-0000-0000-0000-0000000000b7")
BTECH_DUAL_MAJOR = UUID("00000000-0000-0000-0000-0000000000dd")
BTECH_MTECH = UUID("00000000-0000-0000-0000-0000000000de")
MTECH = UUID("00000000-0000-0000-0000-0000000000a7")
CSE = UUID("00000000-0000-0000-0000-000000000c5e")
EE = UUID("00000000-0000-0000-0000-0000000000ee")
ME = UUID("00000000-0000-0000-0000-0000000000e3")
MSE = UUID("00000000-0000-0000-0000-0000000000e4")
MINOR_CSE = UUID("00000000-0000-0000-0000-00000000c500")


def _ids(field: str, *values: UUID) -> dict[str, object]:
    return {"field": field, "op": "in", "value": [str(value) for value in values]}


def _all(*clauses: dict[str, object]) -> dict[str, object]:
    return {"all": list(clauses)}


def _year(field: str, *values: int) -> dict[str, object]:
    if len(values) == 1:
        return {"field": field, "op": "eq", "value": values[0]}
    return {"field": field, "op": "in", "value": list(values)}


def _minor(*values: UUID) -> dict[str, object]:
    return {"any": [_ids("minor1_id", *values), _ids("minor2_id", *values)]}


def _btech(
    branch: UUID,
    *,
    year: int = 3,
    session: int = CURRENT_SESSION,
    structure: ProgramStructure = ProgramStructure.SINGLE,
    secondary: UUID | None = None,
    **columns: object,
) -> dict[str, object]:
    program = BTECH if structure is ProgramStructure.SINGLE else BTECH_DUAL_MAJOR
    return {
        "program_id": program,
        "program_structure": structure.value,
        "program_primary_degree_id": BTECH,
        "program_secondary_degree_id": BTECH,
        "primary_branch_id": branch,
        "secondary_branch_id": secondary,
        "study_year": year,
        "study_year_session": session,
        "graduating_year": 2027,
        "active_backlogs": 0,
        **columns,
    }


def _dual_degree(undergraduate: UUID, postgraduate: UUID, **columns: object) -> dict[str, object]:
    return {
        "program_id": BTECH_MTECH,
        "program_structure": ProgramStructure.DUAL_DEGREE.value,
        "program_primary_degree_id": BTECH,
        "program_secondary_degree_id": MTECH,
        "primary_branch_id": undergraduate,
        "secondary_branch_id": postgraduate,
        "graduating_year": 2027,
        "active_backlogs": 0,
        **columns,
    }


def _mtech(branch: UUID, **columns: object) -> dict[str, object]:
    return {
        "program_id": MTECH,
        "program_structure": ProgramStructure.SINGLE.value,
        "primary_branch_id": branch,
        "graduating_year": 2027,
        "active_backlogs": 0,
        **columns,
    }


def _eligible(
    rule: Mapping[str, object],
    profile: Mapping[str, object],
    *,
    outcome: Outcome = Outcome.INTERNSHIP,
    session: int | None = CURRENT_SESSION,
) -> bool:
    evaluated = dict(profile)
    evaluated.update(
        derived_rule_facts(evaluated, outcome=outcome, current_session=session)
    )
    return evaluate(parse_rule(rule), evaluated, CONTEXT).verdict


#: The roster's central shape: one column group per programme, each opening its
#: own disciplines and graduating years.
FAN_OUT = _all(
    {"field": "active_backlogs", "op": "lte", "value": 0},
    {
        "any": [
            _all(_ids("program_id", MTECH), _ids("discipline_id", CSE, EE)),
            _all(
                _ids("program_id", BTECH_MTECH),
                _ids("discipline_id", CSE, EE),
                _year("graduating_year", 2027),
            ),
            _all(
                _ids("program_id", BTECH, BTECH_DUAL_MAJOR),
                _ids("discipline_id", CSE, EE),
                _year("study_year", 3, 4),
                _year("graduating_year", 2027),
            ),
        ]
    },
)


def test_ELG2_roster_fan_out_admits_each_programme_on_its_own_row() -> None:
    assert _eligible(FAN_OUT, _mtech(CSE)) is True
    assert _eligible(FAN_OUT, _dual_degree(ME, CSE)) is True
    assert _eligible(FAN_OUT, _btech(CSE, year=3)) is True
    # A programme the roster did not open on any row.
    assert _eligible(FAN_OUT, _mtech(ME)) is False


def test_ELG2_roster_dual_degree_row_is_read_as_its_postgraduate_discipline() -> None:
    """The roster lists dual degrees by their MTech discipline, and so does the rule."""
    assert _eligible(FAN_OUT, _dual_degree(CSE, ME)) is False
    assert _eligible(FAN_OUT, _dual_degree(ME, CSE)) is True


def test_ELG2_roster_undergraduate_row_holds_its_study_year_and_batch() -> None:
    assert _eligible(FAN_OUT, _btech(CSE, year=2)) is False
    assert _eligible(FAN_OUT, _btech(CSE, year=3, graduating_year=2028)) is False
    # A year declared for a session that is no longer current is not advanced.
    assert _eligible(FAN_OUT, _btech(CSE, year=3, session=CURRENT_SESSION - 1)) is False


def test_ELG2_roster_dual_major_second_discipline_opens_in_fourth_year() -> None:
    """The roster's own heading, inside a pathway rule rather than beside it."""
    third = _btech(ME, year=3, structure=ProgramStructure.DUAL_MAJOR, secondary=CSE)
    fourth = _btech(ME, year=4, structure=ProgramStructure.DUAL_MAJOR, secondary=CSE)
    assert _eligible(FAN_OUT, third) is False
    assert _eligible(FAN_OUT, fourth) is True
    # Placement reads both disciplines without a year threshold.
    assert _eligible(FAN_OUT, third, outcome=Outcome.PLACEMENT) is True


def test_ELG2_roster_conditional_minor_is_a_pathway_option_not_a_nested_rule() -> None:
    """"Open for ME/CE/CL/MSE also if pursuing Minor in CSE/AI" -- its own option."""
    rule = _all(
        {
            "any": [
                _all(_ids("discipline_id", CSE, EE), _year("study_year", 3, 4)),
                _all(
                    _ids("discipline_id", ME, MSE),
                    _minor(MINOR_CSE),
                    _year("study_year", 3, 4),
                ),
            ]
        }
    )
    assert _eligible(rule, _btech(CSE)) is True
    assert _eligible(rule, _btech(ME)) is False
    assert _eligible(rule, _btech(ME, minor1_id=MINOR_CSE)) is True
    assert _eligible(rule, _btech(ME, minor2_id=MINOR_CSE)) is True
    # The minor opens the extra disciplines only, not the year.
    assert _eligible(rule, _btech(ME, year=2, minor1_id=MINOR_CSE)) is False


def test_ELG2_roster_cpi_floor_may_differ_by_discipline() -> None:
    """"CGPA 7.00 in Computer Science branches and 8.00 in other branches"."""
    rule = {
        "any": [
            _all(_ids("discipline_id", CSE), {"field": "cpi", "op": "gte", "value": 7.0}),
            _all(_ids("discipline_id", ME, MSE), {"field": "cpi", "op": "gte", "value": 8.0}),
        ]
    }
    assert _eligible(rule, _btech(CSE, cpi=Decimal("7.2"))) is True
    assert _eligible(rule, _btech(ME, cpi=Decimal("7.2"))) is False
    assert _eligible(rule, _btech(ME, cpi=Decimal("8.1"))) is True


def test_ELG2_roster_identity_and_school_marks_clauses_evaluate_and_fail_closed() -> None:
    """"Female students graduating in 2027"; "minimum 60% marks in 10th and 12th"."""
    rule = _all(
        {"field": "gender", "op": "eq", "value": "female"},
        {"field": "tenth_percent", "op": "gte", "value": 60},
        {"field": "twelfth_percent", "op": "gte", "value": 60},
        _year("graduating_year", 2027),
    )
    marks: dict[str, object] = {
        "gender": "female",
        "tenth_percent": Decimal("82.0"),
        "twelfth_percent": Decimal("61.5"),
    }
    assert _eligible(rule, _btech(CSE) | marks) is True
    assert _eligible(rule, _btech(CSE) | marks | {"gender": "male"}) is False
    assert _eligible(rule, _btech(CSE) | marks | {"twelfth_percent": Decimal("59.9")}) is False
    # A mark the student has not declared denies rather than passes silently.
    assert _eligible(rule, _btech(CSE) | marks | {"tenth_percent": None}) is False


def test_ELG2_roster_rules_carry_a_readable_summary() -> None:
    labels = {
        MTECH: "MTech",
        BTECH: "BTech",
        BTECH_DUAL_MAJOR: "BTech Dual Major",
        BTECH_MTECH: "BTech–MTech Dual Degree",
        CSE: "Computer Science and Engineering",
        EE: "Electrical Engineering",
    }
    node = parse_rule(FAN_OUT)
    assert taxonomy_ids(node) <= set(labels)
    summary = summarize(node, labels)
    assert "BTech–MTech Dual Degree" in summary
    assert "current study year one of 3, 4" in summary
    assert str(MTECH) not in summary
