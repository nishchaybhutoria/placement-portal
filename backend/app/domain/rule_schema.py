"""The canonical eligibility-rule tree and its value normalisation (ELG-2).

Split from the evaluator so that the plain-language renderer
(:mod:`app.domain.rule_text`) and the evaluator (:mod:`app.domain.rules`) can
both build on the schema without importing each other.  ``app.domain.rules``
re-exports everything here, so the rest of the codebase keeps one import site.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated, cast
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    TypeAdapter,
    model_validator,
)

from app.domain.shared import Gender


class RuleField(StrEnum):
    PROGRAM_ID = "program_id"
    SECONDARY_PROGRAM_ID = "secondary_program_id"
    PRIMARY_BRANCH_ID = "primary_branch_id"
    SECONDARY_BRANCH_ID = "secondary_branch_id"
    GRADUATING_YEAR = "graduating_year"
    CPI = "cpi"
    ACTIVE_BACKLOGS = "active_backlogs"
    TOTAL_BACKLOGS = "total_backlogs"
    GENDER = "gender"
    TENTH_PERCENT = "tenth_percent"
    TENTH_YEAR = "tenth_year"
    TWELFTH_PERCENT = "twelfth_percent"
    TWELFTH_YEAR = "twelfth_year"
    MINOR1_ID = "minor1_id"
    MINOR2_ID = "minor2_id"
    NATIONALITY = "nationality"
    IS_DUAL_MAJOR = "is_dual_major"
    IS_DUAL_DEGREE = "is_dual_degree"


class ComparisonOp(StrEnum):
    EQ = "eq"
    NE = "ne"
    IN = "in"
    NOT_IN = "not_in"
    GTE = "gte"
    LTE = "lte"
    BETWEEN = "between"


class Criterion(StrEnum):
    NOT_PLACEMENT_PLACED = "not_placement_placed"


UUID_FIELDS = frozenset(
    {
        RuleField.PROGRAM_ID,
        RuleField.SECONDARY_PROGRAM_ID,
        RuleField.PRIMARY_BRANCH_ID,
        RuleField.SECONDARY_BRANCH_ID,
        RuleField.MINOR1_ID,
        RuleField.MINOR2_ID,
    }
)
INTEGER_FIELDS = frozenset(
    {
        RuleField.GRADUATING_YEAR,
        RuleField.ACTIVE_BACKLOGS,
        RuleField.TOTAL_BACKLOGS,
        RuleField.TENTH_YEAR,
        RuleField.TWELFTH_YEAR,
    }
)
DECIMAL_FIELDS = frozenset(
    {RuleField.CPI, RuleField.TENTH_PERCENT, RuleField.TWELFTH_PERCENT}
)
# A profile column like every other rule field, so a rule can say "dual majors
# only" (Behavior ELG-2, the design review section 4.32).
BOOLEAN_FIELDS = frozenset({RuleField.IS_DUAL_MAJOR, RuleField.IS_DUAL_DEGREE})
ORDERED_FIELDS = INTEGER_FIELDS | DECIMAL_FIELDS
# The taxonomy each id-valued field draws from, so a caller can resolve the
# display names a rule's UUIDs stand for.
TAXONOMY_OF_FIELD: dict[RuleField, str] = {
    RuleField.PROGRAM_ID: "programs",
    RuleField.SECONDARY_PROGRAM_ID: "programs",
    RuleField.PRIMARY_BRANCH_ID: "branches",
    RuleField.SECONDARY_BRANCH_ID: "branches",
    RuleField.MINOR1_ID: "minors",
    RuleField.MINOR2_ID: "minors",
}


class _RuleModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AllNode(_RuleModel):
    all: Annotated[tuple[RuleNode, ...], Field(min_length=1)]


class AnyNode(_RuleModel):
    any: Annotated[tuple[RuleNode, ...], Field(min_length=1)]


class NotNode(_RuleModel):
    not_: RuleNode = Field(alias="not")


class FieldNode(_RuleModel):
    field: RuleField
    op: ComparisonOp
    value: object

    @model_validator(mode="after")
    def validate_value_for_field(self) -> FieldNode:
        raw_value: object = self.value
        if self.op in {ComparisonOp.GTE, ComparisonOp.LTE, ComparisonOp.BETWEEN}:
            if self.field not in ORDERED_FIELDS:
                raise ValueError(f"{self.op.value} is valid only for numeric fields")
        if self.op in {ComparisonOp.IN, ComparisonOp.NOT_IN} and (
            self.field in BOOLEAN_FIELDS
        ):
            raise ValueError(f"{self.op.value} is not valid for a true/false field")
        if self.op in {ComparisonOp.IN, ComparisonOp.NOT_IN}:
            if not isinstance(raw_value, (list, tuple)) or not raw_value:
                raise ValueError(f"{self.op.value} requires a non-empty list")
            values = cast(Sequence[object], raw_value)
            self.value = tuple(normalize_expected(self.field, item) for item in values)
        elif self.op is ComparisonOp.BETWEEN:
            if not isinstance(raw_value, (list, tuple)):
                raise ValueError("between requires exactly two bounds")
            values = cast(Sequence[object], raw_value)
            if len(values) != 2:
                raise ValueError("between requires exactly two bounds")
            lower = normalize_expected(self.field, values[0])
            upper = normalize_expected(self.field, values[1])
            if not ordered_compare(lower, upper, ComparisonOp.LTE):
                raise ValueError("between lower bound must not exceed upper bound")
            self.value = (lower, upper)
        else:
            if isinstance(raw_value, (list, tuple, dict)):
                raise ValueError(f"{self.op.value} requires one scalar value")
            self.value = normalize_expected(self.field, raw_value)
        return self


class CriterionNode(_RuleModel):
    criterion: Criterion


def _node_discriminator(value: object) -> str:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        keys = set(mapping)
        for key in ("all", "any", "not", "field", "criterion"):
            if key in keys:
                return key
    if isinstance(value, AllNode):
        return "all"
    if isinstance(value, AnyNode):
        return "any"
    if isinstance(value, NotNode):
        return "not"
    if isinstance(value, FieldNode):
        return "field"
    if isinstance(value, CriterionNode):
        return "criterion"
    return "invalid"


type RuleNode = Annotated[
    Annotated[AllNode, Tag("all")]
    | Annotated[AnyNode, Tag("any")]
    | Annotated[NotNode, Tag("not")]
    | Annotated[FieldNode, Tag("field")]
    | Annotated[CriterionNode, Tag("criterion")],
    Discriminator(_node_discriminator),
]

AllNode.model_rebuild()
AnyNode.model_rebuild()
NotNode.model_rebuild()
_RULE_ADAPTER: TypeAdapter[RuleNode] = TypeAdapter(RuleNode)

type Scalar = UUID | int | Decimal | str | bool


def parse_rule(value: object) -> RuleNode:
    """Validate canonical stored rule JSON without adding an artificial type key."""
    return _RULE_ADAPTER.validate_python(value)


def is_rule_node(value: object) -> bool:
    return isinstance(value, (AllNode, AnyNode, NotNode, FieldNode, CriterionNode))


def normalize_expected(field: RuleField, value: object) -> Scalar:
    if value is None:
        raise ValueError("null comparisons are not supported")
    if field in UUID_FIELDS:
        if isinstance(value, UUID):
            return value
        if not isinstance(value, str):
            raise ValueError(f"{field.value} requires a UUID")
        return UUID(value)
    if field in INTEGER_FIELDS:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{field.value} requires an integer")
        return value
    if field in DECIMAL_FIELDS:
        if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
            raise ValueError(f"{field.value} requires a number")
        return Decimal(str(value))
    if field in BOOLEAN_FIELDS:
        if not isinstance(value, bool):
            raise ValueError(f"{field.value} requires true or false")
        return value
    if field is RuleField.GENDER:
        if not isinstance(value, str):
            raise ValueError("gender requires a string")
        return Gender(value).value
    if not isinstance(value, str):
        raise ValueError(f"{field.value} requires a string")
    return value


def normalize_actual(field: RuleField, value: object) -> Scalar:
    """Normalise a live profile value, applying the ELG-2 CPI rounding contract."""
    normalized = normalize_expected(field, value)
    if field is RuleField.CPI:
        return Decimal(str(normalized)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return normalized


def ordered_compare(left: Scalar, right: Scalar, op: ComparisonOp) -> bool:
    if not isinstance(left, (int, Decimal)) or not isinstance(right, (int, Decimal)):
        raise TypeError("ordered comparison requires numbers")
    return left <= right if op is ComparisonOp.LTE else left >= right
