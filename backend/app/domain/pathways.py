"""Which disciplines a student may be matched on (ELG-2, the eligibility roster).

The institute states the dual-major rule once, for every company at once, in
the heading of the eligibility roster itself:

    The students enrolled in dual major programs will become eligible for
    internship in the second discipline only at the beginning of fourth year.
    It should be noted that they are eligible for internship in their primary
    discipline starting third year.

So it belongs to the enrollment, not to any one job: a rule names the
disciplines a role recruits in, and this decides which of the student's own
disciplines are allowed to answer.  A dual degree answers with its
postgraduate discipline alone, because that is the degree it recruits into.

Keeping the decision here is what lets a rule outlive a change in how the
enrollment is stored.  A rule says "discipline is one of EE, ICDT"; it never
says "primary branch or, if a dual major in fourth year, secondary branch".

Not to be confused with :mod:`app.domain.discipline`, which is the
*disciplinary* strike and penalty ledger.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from app.domain.shared import Outcome, ProgramStructure

#: A dual major's primary internship discipline opens in third year and the
#: second at the start of fourth year.
PRIMARY_DISCIPLINE_YEAR = 3
SECOND_DISCIPLINE_YEAR = 4

#: How a combined programme is named.  One place decides it, so the registrar
#: parser, the seeds and migration 0017 cannot drift into naming the same
#: enrollment two different things and minting a duplicate programme.
DUAL_MAJOR_SUFFIX = " Dual Major"
DUAL_DEGREE_SUFFIX = " Dual Degree"


def dual_major_name(base: str) -> str:
    return f"{base}{DUAL_MAJOR_SUFFIX}"


def dual_degree_name(undergraduate: str, postgraduate: str) -> str:
    return f"{undergraduate}\N{EN DASH}{postgraduate}{DUAL_DEGREE_SUFFIX}"


def _identifier(value: object) -> UUID | None:
    return value if isinstance(value, UUID) else None


def _study_year(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


@dataclass(frozen=True, slots=True)
class ProgramPathway:
    """One programme's shape, and where each of its disciplines comes from.

    ``primary_degree_id`` and ``secondary_degree_id`` name the programmes whose
    discipline lists each slot draws on.  A dual major draws both from the same
    degree; a dual degree draws its second from the postgraduate one.  A single
    programme offers its own disciplines and leaves both unset.
    """

    structure: ProgramStructure
    primary_degree_id: UUID | None = None
    secondary_degree_id: UUID | None = None

    @property
    def holds_second_discipline(self) -> bool:
        return self.structure is not ProgramStructure.SINGLE

    def discipline_source(self, *, secondary: bool) -> UUID | None:
        return self.secondary_degree_id if secondary else self.primary_degree_id


def program_structure(value: object) -> ProgramStructure | None:
    """Read a stored structure conservatively; an unknown one is not assumed."""
    if isinstance(value, ProgramStructure):
        return value
    try:
        return ProgramStructure(value) if isinstance(value, str) else None
    except ValueError:
        return None


def eligible_disciplines(
    profile: Mapping[str, object],
    *,
    outcome: Outcome | None,
    current_session: int | None,
) -> frozenset[UUID] | None:
    """The disciplines this student may be matched on, or ``None`` if unknowable.

    ``None`` is not "no disciplines".  It means the profile does not yet say
    enough to decide, and the caller must reject naming what is missing rather
    than quietly excluding the student -- a dual major whose year of study is
    blank has an answer, and the portal simply has not been told it yet.

    A discipline the student holds but the profile has not recorded is not
    inferred.  The returned set is what is *known* to be theirs, so a student
    whose primary discipline already matches is never held up waiting for a
    second one to be filled in.
    """
    primary = _identifier(profile.get("primary_branch_id"))
    secondary = _identifier(profile.get("secondary_branch_id"))
    structure = program_structure(profile.get("program_structure"))
    if structure is None:
        # No programme recorded, or one whose shape this build does not know.
        return None

    if structure is ProgramStructure.DUAL_DEGREE:
        # The postgraduate half is the degree a dual degree recruits into.
        return frozenset({secondary}) if secondary is not None else None

    if structure is ProgramStructure.DUAL_MAJOR:
        if primary is None:
            return None
        if outcome is Outcome.PLACEMENT:
            return frozenset(
                discipline
                for discipline in (primary, secondary)
                if discipline is not None
            )
        if outcome is not Outcome.INTERNSHIP:
            return None
        year = _study_year(profile.get("study_year"))
        recorded_session = _study_year(profile.get("study_year_session"))
        if (
            year is None
            or current_session is None
            or recorded_session != current_session
        ):
            return None
        if year < PRIMARY_DISCIPLINE_YEAR:
            return frozenset()
        if year < SECOND_DISCIPLINE_YEAR or secondary is None:
            return frozenset({primary})
        return frozenset({primary, secondary})

    return frozenset({primary}) if primary is not None else None


def derived_rule_facts(
    profile: Mapping[str, object],
    *,
    outcome: Outcome | None,
    current_session: int | None,
) -> dict[str, object]:
    """The facts a rule reads that no profile column holds any more (ELG-2).

    ``is_dual_major``, ``is_dual_degree`` and ``secondary_program_id`` were
    profile columns before the programme carried its own structure.  Rules
    saved while they were keep evaluating, because a rule naming a fact the
    portal still knows must not start failing on the day the fact moves house.

    New rules should say ``discipline_id`` instead: it is the question those
    three were being combined to ask, and it does not need the author to know
    how an enrollment happens to be stored.
    """
    structure = program_structure(profile.get("program_structure"))
    program = _identifier(profile.get("program_id"))
    return {
        # Every programme the student counts as being in: the one they declared
        # and the degrees it is built from.  A rule naming BTech keeps matching
        # a BTech dual major, which is what its author meant.  Kept beside the
        # declared programme rather than over it, because the per-programme CTC
        # and the record screens still want the one they are actually in.
        "eligible_program_ids": frozenset(
            identifier
            for identifier in (
                program,
                _identifier(profile.get("program_primary_degree_id")),
                _identifier(profile.get("program_secondary_degree_id")),
            )
            if identifier is not None
        ),
        "discipline_id": eligible_disciplines(
            profile, outcome=outcome, current_session=current_session
        ),
        "is_dual_major": structure is ProgramStructure.DUAL_MAJOR,
        "is_dual_degree": structure is ProgramStructure.DUAL_DEGREE,
        "secondary_program_id": profile.get("program_secondary_degree_id"),
    }
