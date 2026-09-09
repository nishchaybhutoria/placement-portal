"""Plain-language rendering of an eligibility rule (Behavior ELG-2, JOB-4).

ELG-2 requires two things of a rule beyond evaluating it: every stored rule
carries an auto-generated plain-language summary, and an ineligible student is
shown "the exact failing reasons" (JOB-4).  Both are generated here from one
requirement clause per leaf, so the summary a student reads on the builder and
the reason they read on a card can never drift apart -- they are the same
string in two sentences.

A failing leaf renders two ways.  Standalone -- "Requires CPI at least 8.0;
yours is 7.6." -- when it is a requirement in its own right.  Inline -- "CPI at
least 8.0 (yours is 7.6)" -- when it is one part of an alternative under an
``any``, which must be reported as a group.  Listing an ``any``'s leaves flat
states falsehoods: for ``any[all[branch CSE, cpi>=8.0], all[branch EE,
cpi>=7.5]]`` a CSE student with a 7.6 would be told "requires primary branch
EE", when their branch is fine and only their CPI is short.  Grouped, they are
told the truth -- raise the CPI or be in EE (the design review section 4.19).

Rules address taxonomy rows by id.  A raw UUID is unreadable, so every renderer
takes a ``labels`` mapping from id to display name; an id the caller did not
resolve falls back to its UUID rather than failing, because a rule that names a
deleted program must still render.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import cast
from uuid import UUID

from app.domain.rule_schema import (
    UUID_FIELDS,
    AllNode,
    AnyNode,
    ComparisonOp,
    Criterion,
    CriterionNode,
    FieldNode,
    NotNode,
    RuleField,
    RuleNode,
    is_rule_node,
    normalize_actual,
    parse_rule,
)

type Labels = Mapping[UUID, str]

# The noun each field reads as inside a requirement clause: "Requires <noun>
# at least 8.0".  Deliberately not reused from ``profiles.fields`` -- these are
# clause fragments, not form labels, and ``domain`` may not import a module.
_FIELD_NOUNS: dict[RuleField, str] = {
    RuleField.PROGRAM_ID: "program",
    RuleField.SECONDARY_PROGRAM_ID: "secondary program",
    RuleField.PRIMARY_BRANCH_ID: "primary branch",
    RuleField.SECONDARY_BRANCH_ID: "secondary branch",
    RuleField.GRADUATING_YEAR: "graduating year",
    RuleField.CPI: "CPI",
    RuleField.ACTIVE_BACKLOGS: "active backlogs",
    RuleField.TOTAL_BACKLOGS: "total backlogs",
    RuleField.GENDER: "gender",
    RuleField.TENTH_PERCENT: "10th percentage",
    RuleField.TENTH_YEAR: "10th year",
    RuleField.TWELFTH_PERCENT: "12th percentage",
    RuleField.TWELFTH_YEAR: "12th year",
    RuleField.MINOR1_ID: "minor 1",
    RuleField.MINOR2_ID: "minor 2",
    RuleField.NATIONALITY: "nationality",
    RuleField.IS_DUAL_MAJOR: "dual major",
    RuleField.IS_DUAL_DEGREE: "dual degree",
}

_CRITERION_CLAUSES: dict[Criterion, str] = {
    Criterion.NOT_PLACEMENT_PLACED: "no accepted placement offer",
}

NO_RULE_SUMMARY = "Open to every active member of the cycle."


def field_noun(field: RuleField) -> str:
    return _FIELD_NOUNS[field]


def render_value(value: object, labels: Labels) -> str:
    """Render one comparison value, resolving taxonomy ids to their names."""
    if isinstance(value, UUID):
        return labels.get(value, str(value))
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, Decimal):
        # Rendered exactly as the rule stores it: a CPI floor entered as 8.0
        # must not display as "8", which reads like a different threshold.
        return format(value, "f")
    return str(value)


def _render_list(values: Sequence[object], labels: Labels) -> str:
    return ", ".join(render_value(item, labels) for item in values)


def requirement(node: FieldNode, labels: Labels) -> str:
    """The positive clause a student must satisfy, e.g. "CPI at least 8.0"."""
    noun = _FIELD_NOUNS[node.field]
    value: object = node.value
    if node.field in {RuleField.IS_DUAL_MAJOR, RuleField.IS_DUAL_DEGREE}:
        wants = bool(value) if node.op is ComparisonOp.EQ else not bool(value)
        if node.field is RuleField.IS_DUAL_MAJOR:
            return "a dual major" if wants else "not a dual major"
        return "a dual degree" if wants else "not a dual degree"
    if node.op is ComparisonOp.EQ:
        return f"{noun} {render_value(value, labels)}"
    if node.op is ComparisonOp.NE:
        return f"{noun} other than {render_value(value, labels)}"
    if node.op in {ComparisonOp.IN, ComparisonOp.NOT_IN}:
        # "one of"/"none of" rather than a bare "a or b": an inlined "or" inside
        # a leaf would read as a connector joining it to its siblings.
        quantifier = "one of" if node.op is ComparisonOp.IN else "none of"
        listed = _render_list(cast(Sequence[object], value), labels)
        return f"{noun} {quantifier} {listed}"
    if node.op is ComparisonOp.GTE:
        return f"{noun} at least {render_value(value, labels)}"
    if node.op is ComparisonOp.LTE:
        return f"{noun} at most {render_value(value, labels)}"
    lower, upper = cast(tuple[object, object], value)
    return f"{noun} between {render_value(lower, labels)} and {render_value(upper, labels)}"


@dataclass(frozen=True, slots=True)
class Shortfall:
    """One unmet requirement, rendered for both of the places it can appear.

    ``standalone`` is a sentence; ``inline`` is a fragment that reads correctly
    joined by "and" inside one alternative of an ``any`` group.
    """

    standalone: str
    inline: str


def field_shortfall(
    node: FieldNode, profile: Mapping[str, object], labels: Labels
) -> Shortfall:
    """A failing profile leaf, naming what the student's own profile says (JOB-4).

    Naming the actual value is what turns "you are not eligible" into something
    a student can act on -- they learn whether to fix their profile or move on.
    """
    clause = requirement(node, labels)
    raw = profile.get(node.field.value)
    if raw is None:
        return Shortfall(
            standalone=f"Requires {clause}; your profile does not record this yet.",
            inline=f"{clause} (not recorded in your profile)",
        )
    if node.field in {RuleField.IS_DUAL_MAJOR, RuleField.IS_DUAL_DEGREE}:
        held = "are" if bool(raw) else "are not"
        return Shortfall(
            standalone=f"Requires {clause}; you {held} one.",
            inline=f"{clause} (you {held} one)",
        )
    try:
        actual = render_value(normalize_actual(node.field, raw), labels)
    except (TypeError, ValueError):
        actual = render_value(raw, labels)
    return Shortfall(
        standalone=f"Requires {clause}; yours is {actual}.",
        inline=f"{clause} (yours is {actual})",
    )


def criterion_shortfall(node: CriterionNode) -> Shortfall:
    """A failing context leaf (ELG-2 context leaves, DER-1)."""
    del node  # only one criterion exists; the schema admits no other
    return Shortfall(
        standalone="You have already accepted a placement offer.",
        inline="no accepted placement offer (you have already accepted one)",
    )


def negation_shortfall(node: NotNode, labels: Labels) -> Shortfall:
    """Why a satisfied ``not{...}`` blocked a student.

    A negated leaf is rare in practice (ELG-3 already gates placement), so the
    reason states the excluded condition rather than inventing a positive one.
    """
    if isinstance(node.not_, CriterionNode):
        sentence = (
            "This job is open only to students who have already accepted a "
            "placement offer."
        )
        return Shortfall(standalone=sentence, inline="an accepted placement offer")
    inner, _ = _describe(node.not_, labels)
    return Shortfall(standalone=f"Excluded: {inner}.", inline=f"not {inner}")


def alternatives_shortfall(alternatives: Sequence[str]) -> Shortfall:
    """Every branch of a failed ``any``, reported as the choice it really is."""
    listed = "; or ".join(alternatives)
    return Shortfall(
        standalone=f"Must satisfy one of: {listed}.",
        inline=f"one of: {listed}",
    )


def summarize(tree: RuleNode | Mapping[str, object] | None, labels: Labels) -> str:
    """The stored ELG-2 plain-language summary for one rule tree."""
    if tree is None:
        return NO_RULE_SUMMARY
    node = tree if is_rule_node(tree) else parse_rule(tree)
    body, _ = _describe(cast(RuleNode, node), labels)
    return f"Eligible when {body}."


def _describe(node: RuleNode, labels: Labels) -> tuple[str, str]:
    """Return the clause and the connector that joined it, for parenthesising.

    A child joined by a different connector than its parent has to be bracketed
    or the sentence changes meaning: ``all[a, any[b, c]]`` is "a and (b or c)",
    never "a and b or c".
    """
    if isinstance(node, AllNode):
        return _join(node.all, " and ", "and", labels), "and"
    if isinstance(node, AnyNode):
        return _join(node.any, " or ", "or", labels), "or"
    if isinstance(node, NotNode):
        inner, _ = _describe(node.not_, labels)
        return f"not ({inner})", "leaf"
    if isinstance(node, CriterionNode):
        return _CRITERION_CLAUSES[node.criterion], "leaf"
    return requirement(node, labels), "leaf"


def _join(
    children: Iterable[RuleNode], separator: str, connector: str, labels: Labels
) -> str:
    parts: list[str] = []
    for child in children:
        clause, child_connector = _describe(child, labels)
        if child_connector not in {"leaf", connector}:
            clause = f"({clause})"
        parts.append(clause)
    return separator.join(parts)


def profile_taxonomy_ids(profile: Mapping[str, object]) -> frozenset[UUID]:
    """Every taxonomy id a *profile* holds, so a shortfall can name it.

    A rule's own ids come from :func:`taxonomy_ids`, but a failing leaf also
    renders the student's actual value, and that id is not in the rule -- a CSE
    student failing a rule that names only EE would otherwise be told "yours is
    bfdd47ee-...".  the design review 4.19 requires taxonomy values to render by name
    wherever they appear, which includes the half that came from the profile.
    """
    found: set[UUID] = set()
    for field in UUID_FIELDS:
        value = profile.get(field.value)
        if isinstance(value, UUID):
            found.add(value)
    return frozenset(found)


def taxonomy_ids(tree: RuleNode | Mapping[str, object] | None) -> frozenset[UUID]:
    """Every taxonomy id a rule names, so a caller can resolve their labels."""
    if tree is None:
        return frozenset()
    node = tree if is_rule_node(tree) else parse_rule(tree)
    found: set[UUID] = set()
    _collect(cast(RuleNode, node), found)
    return frozenset(found)


def _collect(node: RuleNode, found: set[UUID]) -> None:
    if isinstance(node, AllNode):
        for child in node.all:
            _collect(child, found)
    elif isinstance(node, AnyNode):
        for child in node.any:
            _collect(child, found)
    elif isinstance(node, NotNode):
        _collect(node.not_, found)
    elif isinstance(node, FieldNode):
        value: object = node.value
        candidates: tuple[object, ...] = (
            cast(tuple[object, ...], value) if isinstance(value, tuple) else (value,)
        )
        found.update(item for item in candidates if isinstance(item, UUID))
