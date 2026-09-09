"""Pure eligibility-rule evaluation for ELG-1/2.

The tree schema lives in :mod:`app.domain.rule_schema` and every human string
in :mod:`app.domain.rule_text`; this module is the evaluator that joins them.
All three are re-exported here, so ``app.domain.rules`` remains the one import
site for eligibility rules.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import InvalidOperation
from typing import cast

from pydantic import BaseModel, ConfigDict

from app.core.errors import NOT_ELIGIBLE
from app.core.plan import Reason
from app.domain.rule_schema import (
    BOOLEAN_FIELDS,
    DECIMAL_FIELDS,
    INTEGER_FIELDS,
    ORDERED_FIELDS,
    TAXONOMY_OF_FIELD,
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
    Scalar,
    is_rule_node,
    normalize_actual,
    normalize_expected,
    ordered_compare,
    parse_rule,
)
from app.domain.rule_text import (
    NO_RULE_SUMMARY,
    Labels,
    Shortfall,
    alternatives_shortfall,
    criterion_shortfall,
    field_shortfall,
    negation_shortfall,
    profile_taxonomy_ids,
    requirement,
    summarize,
    taxonomy_ids,
)

__all__ = [
    "BOOLEAN_FIELDS",
    "DECIMAL_FIELDS",
    "INTEGER_FIELDS",
    "NO_RULE_SUMMARY",
    "ORDERED_FIELDS",
    "TAXONOMY_OF_FIELD",
    "UUID_FIELDS",
    "AllNode",
    "AnyNode",
    "ComparisonOp",
    "Criterion",
    "CriterionNode",
    "EvaluationResult",
    "FieldNode",
    "Labels",
    "NotNode",
    "RuleContext",
    "RuleField",
    "RuleNode",
    "Scalar",
    "Shortfall",
    "evaluate",
    "field_shortfall",
    "is_rule_node",
    "normalize_actual",
    "normalize_expected",
    "ordered_compare",
    "parse_rule",
    "requirement",
    "summarize",
    "profile_taxonomy_ids",
    "taxonomy_ids",
]


@dataclass(frozen=True, slots=True)
class _Failure:
    """One unmet requirement and the rule path it sits at."""

    path: str
    shortfall: Shortfall


class RuleContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    not_placement_placed: bool


class EvaluationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    verdict: bool
    failures: tuple[Reason, ...]


def evaluate(
    tree: RuleNode | Mapping[str, object],
    profile: Mapping[str, object],
    context: RuleContext,
    *,
    labels: Labels | None = None,
) -> EvaluationResult:
    """Evaluate ELG-2 against one live profile and return path-addressed failures.

    ``labels`` resolves the taxonomy ids a rule names to their display names.
    Omitting it renders raw UUIDs, which is fine for a machine reader and wrong
    for anything a person sees -- pass the mapping from
    :func:`app.domain.rules.taxonomy_ids` for every student- or staff-facing call.
    """
    node = tree if is_rule_node(tree) else parse_rule(tree)
    verdict, failures = _evaluate_node(
        cast(RuleNode, node), profile, context, "$", labels or {}
    )
    reasons = tuple(
        Reason(
            code=NOT_ELIGIBLE,
            human=failure.shortfall.standalone,
            path=failure.path,
        )
        for failure in failures
    )
    if not verdict and not reasons:
        reasons = (
            Reason(
                code=NOT_ELIGIBLE,
                human="The eligibility rule was not satisfied",
                path="$",
            ),
        )
    return EvaluationResult(verdict=verdict, failures=reasons)


def _evaluate_node(
    node: RuleNode,
    profile: Mapping[str, object],
    context: RuleContext,
    path: str,
    labels: Labels,
) -> tuple[bool, tuple[_Failure, ...]]:
    if isinstance(node, AllNode):
        failures: list[_Failure] = []
        for index, child in enumerate(node.all):
            child_ok, child_failures = _evaluate_node(
                child, profile, context, f"{path}.all[{index}]", labels
            )
            if not child_ok:
                failures.extend(child_failures)
        return not failures, tuple(failures)
    if isinstance(node, AnyNode):
        # Reported as one choice at this node's path, never as its branches'
        # leaves side by side: a student who satisfies one branch's leaves but
        # not another's would otherwise be told a requirement they already meet
        # is the thing blocking them (the design review section 4.19).
        alternatives: list[str] = []
        for index, child in enumerate(node.any):
            child_ok, child_failures = _evaluate_node(
                child, profile, context, f"{path}.any[{index}]", labels
            )
            if child_ok:
                return True, ()
            alternatives.append(
                " and ".join(failure.shortfall.inline for failure in child_failures)
                or requirement_of(child, labels)
            )
        return False, (_Failure(path, alternatives_shortfall(alternatives)),)
    if isinstance(node, NotNode):
        child_ok, _child_failures = _evaluate_node(
            node.not_, profile, context, f"{path}.not", labels
        )
        if not child_ok:
            return True, ()
        return False, (_Failure(path, negation_shortfall(node, labels)),)
    if isinstance(node, CriterionNode):
        if node.criterion is Criterion.NOT_PLACEMENT_PLACED and context.not_placement_placed:
            return True, ()
        return False, (_Failure(path, criterion_shortfall(node)),)
    return _evaluate_field(node, profile, path, labels)


def requirement_of(node: RuleNode, labels: Labels) -> str:
    """The positive clause for a node that failed without naming a shortfall.

    Only reachable for a node type that yields no failure detail; stating what
    it asked for still beats an empty alternative.
    """
    return requirement(node, labels) if isinstance(node, FieldNode) else "this condition"


def _evaluate_field(
    node: FieldNode, profile: Mapping[str, object], path: str, labels: Labels
) -> tuple[bool, tuple[_Failure, ...]]:
    raw_actual = profile.get(node.field.value)
    passed = False
    if raw_actual is not None:
        try:
            actual = normalize_actual(node.field, raw_actual)
            passed = _compare(actual, node.value, node.op)
        except (InvalidOperation, TypeError, ValueError):
            passed = False
    if passed:
        return True, ()
    return False, (_Failure(path, field_shortfall(node, profile, labels)),)


def _compare(actual: Scalar, expected: object, op: ComparisonOp) -> bool:
    if op is ComparisonOp.EQ:
        return actual == expected
    if op is ComparisonOp.NE:
        return actual != expected
    if op in {ComparisonOp.IN, ComparisonOp.NOT_IN}:
        values = cast(tuple[Scalar, ...], expected)
        contained = actual in values
        return contained if op is ComparisonOp.IN else not contained
    if op in {ComparisonOp.GTE, ComparisonOp.LTE}:
        expected_scalar = cast(Scalar, expected)
        return ordered_compare(actual, expected_scalar, op)
    lower, upper = cast(tuple[Scalar, Scalar], expected)
    return ordered_compare(lower, actual, ComparisonOp.LTE) and ordered_compare(
        actual, upper, ComparisonOp.LTE
    )
