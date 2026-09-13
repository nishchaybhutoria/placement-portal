"""Pure eligibility-rule evaluation for ELG-1/2.

The tree schema lives in :mod:`app.domain.rule_schema` and every human string
in :mod:`app.domain.rule_text`; this module is the evaluator that joins them.
All three are re-exported here, so ``app.domain.rules`` remains the one import
site for eligibility rules.
"""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from decimal import InvalidOperation
from enum import Enum, auto
from typing import cast

from pydantic import BaseModel, ConfigDict

from app.core.errors import NOT_ELIGIBLE
from app.core.plan import Reason
from app.domain.rule_schema import (
    BOOLEAN_FIELDS,
    DECIMAL_FIELDS,
    INTEGER_FIELDS,
    ORDERED_FIELDS,
    SET_FIELDS,
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
    RuleSemantics,
    Scalar,
    actual_key,
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
    "SET_FIELDS",
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
    "RuleSemantics",
    "Scalar",
    "Shortfall",
    "actual_key",
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


class _Truth(Enum):
    """Internal three-valued result; public eligibility remains pass or deny."""

    FALSE = auto()
    TRUE = auto()
    UNKNOWN = auto()


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
    semantics: RuleSemantics = RuleSemantics.CURRENT,
) -> EvaluationResult:
    """Evaluate ELG-2 against one live profile and return path-addressed failures.

    ``labels`` resolves the taxonomy ids a rule names to their display names.
    Omitting it renders raw UUIDs, which is fine for a machine reader and wrong
    for anything a person sees -- pass the mapping from
    :func:`app.domain.rules.taxonomy_ids` for every student- or staff-facing call.
    """
    node = tree if is_rule_node(tree) else parse_rule(tree)
    truth, failures = _evaluate_node(
        cast(RuleNode, node), profile, context, "$", labels or {}, semantics
    )
    verdict = truth is _Truth.TRUE
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
    semantics: RuleSemantics,
) -> tuple[_Truth, tuple[_Failure, ...]]:
    if isinstance(node, AllNode):
        failures: list[_Failure] = []
        child_truths: list[_Truth] = []
        for index, child in enumerate(node.all):
            child_truth, child_failures = _evaluate_node(
                child, profile, context, f"{path}.all[{index}]", labels, semantics
            )
            child_truths.append(child_truth)
            if child_truth is not _Truth.TRUE:
                failures.extend(child_failures)
        if _Truth.FALSE in child_truths:
            return _Truth.FALSE, tuple(failures)
        if _Truth.UNKNOWN in child_truths:
            return _Truth.UNKNOWN, tuple(failures)
        return _Truth.TRUE, ()
    if isinstance(node, AnyNode):
        # Reported as one choice at this node's path, never as its branches'
        # leaves side by side: a student who satisfies one branch's leaves but
        # not another's would otherwise be told a requirement they already meet
        # is the thing blocking them (the design review section 4.19).
        alternatives: list[str] = []
        saw_unknown = False
        for index, child in enumerate(node.any):
            child_truth, child_failures = _evaluate_node(
                child, profile, context, f"{path}.any[{index}]", labels, semantics
            )
            if child_truth is _Truth.TRUE:
                return _Truth.TRUE, ()
            saw_unknown = saw_unknown or child_truth is _Truth.UNKNOWN
            alternatives.append(
                " and ".join(failure.shortfall.inline for failure in child_failures)
                or requirement_of(child, labels)
            )
        truth = _Truth.UNKNOWN if saw_unknown else _Truth.FALSE
        return truth, (_Failure(path, alternatives_shortfall(alternatives)),)
    if isinstance(node, NotNode):
        child_truth, child_failures = _evaluate_node(
            node.not_, profile, context, f"{path}.not", labels, semantics
        )
        if child_truth is _Truth.FALSE:
            return _Truth.TRUE, ()
        if child_truth is _Truth.UNKNOWN:
            return _Truth.UNKNOWN, child_failures
        return _Truth.FALSE, (_Failure(path, negation_shortfall(node, labels)),)
    if isinstance(node, CriterionNode):
        if node.criterion is Criterion.NOT_PLACEMENT_PLACED and context.not_placement_placed:
            return _Truth.TRUE, ()
        return _Truth.FALSE, (_Failure(path, criterion_shortfall(node)),)
    return _evaluate_field(node, profile, path, labels, semantics)


def requirement_of(node: RuleNode, labels: Labels) -> str:
    """The positive clause for a node that failed without naming a shortfall.

    Only reachable for a node type that yields no failure detail; stating what
    it asked for still beats an empty alternative.
    """
    return requirement(node, labels) if isinstance(node, FieldNode) else "this condition"


def _evaluate_field(
    node: FieldNode,
    profile: Mapping[str, object],
    path: str,
    labels: Labels,
    semantics: RuleSemantics,
) -> tuple[_Truth, tuple[_Failure, ...]]:
    raw_actual = profile.get(actual_key(node.field, semantics))
    if node.field in SET_FIELDS:
        if not isinstance(raw_actual, AbstractSet) or not raw_actual:
            truth = (
                _Truth.FALSE
                if semantics is RuleSemantics.LEGACY
                else _Truth.UNKNOWN
            )
            return truth, (_Failure(path, field_shortfall(node, profile, labels)),)
        if _compare_set(cast(AbstractSet[object], raw_actual), node.value, node.op):
            return _Truth.TRUE, ()
        return _Truth.FALSE, (_Failure(path, field_shortfall(node, profile, labels)),)
    if raw_actual is None:
        truth = (
            _Truth.FALSE if semantics is RuleSemantics.LEGACY else _Truth.UNKNOWN
        )
        return truth, (_Failure(path, field_shortfall(node, profile, labels)),)
    try:
        actual = normalize_actual(node.field, raw_actual)
        passed = _compare(actual, node.value, node.op)
    except (InvalidOperation, TypeError, ValueError):
        truth = (
            _Truth.FALSE if semantics is RuleSemantics.LEGACY else _Truth.UNKNOWN
        )
        return truth, (_Failure(path, field_shortfall(node, profile, labels)),)
    if passed:
        return _Truth.TRUE, ()
    return _Truth.FALSE, (_Failure(path, field_shortfall(node, profile, labels)),)


def _compare_set(raw_actual: object, expected: object, op: ComparisonOp) -> bool:
    """Answer a rule from the set of values the student is allowed to use.

    Unknown and empty sets are classified before this comparison so negation
    cannot turn missing facts into a pass.  This helper receives known values.
    """
    if not isinstance(raw_actual, AbstractSet):
        return False
    actual = cast(AbstractSet[object], raw_actual)
    if op is ComparisonOp.IN:
        values = cast(tuple[Scalar, ...], expected)
        return any(value in values for value in actual)
    if op is ComparisonOp.NOT_IN:
        values = cast(tuple[Scalar, ...], expected)
        return all(value not in values for value in actual)
    if op is ComparisonOp.EQ:
        return expected in actual
    if op is ComparisonOp.NE:
        return expected not in actual
    return False


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
