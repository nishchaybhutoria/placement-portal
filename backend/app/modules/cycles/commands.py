"""Cycle configuration, policy, and coordinators (Behavior CYC-1, CYC-2).

A cycle's kind fixes its behaviour permanently, so it is set at creation and
never edited.  Creation writes the ``cycle_policies`` row in the same plan:
every downstream reader (gates, joins, offers) assumes it exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    COORDINATOR_ALREADY_ASSIGNED,
    COORDINATOR_NOT_FOUND,
    CYCLE_NAME_CONFLICT,
    CYCLE_NOT_FOUND,
    FIELD_NOT_EDITABLE,
    INACTIVE_USER,
    INVALID_FIELD_VALUE,
    USER_NOT_FOUND,
)
from app.core.plan import (
    ActorContext,
    Deferred,
    Plan,
    Reason,
    Rejection,
    ScopeIds,
    StateOp,
)
from app.core.registry import Registry
from app.domain.policy import Policy, resolve_policy
from app.domain.rules import parse_rule
from app.domain.shared import CycleKind, OfferExpiry

POLICY_COLUMNS: tuple[str, ...] = (
    "membership_requires_approval",
    "join_rule",
    "max_accepted_offers",
    "penalty_blocks_applications",
    "allow_withdrawal_after_deadline",
    "allow_edit_after_deadline",
    "strike_on_absence",
    "offer_expiry_behavior",
    "deadline_reminder_hours",
    "round_reminder_hours",
)


def normalize_name(value: str) -> str:
    return " ".join(value.split())


def _validated_name(value: str) -> str:
    normalized = normalize_name(value)
    if not normalized:
        raise ValueError("name must not be blank")
    if len(normalized) > 200:
        raise ValueError("name must be at most 200 characters")
    return normalized


class CreateCycleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: CycleKind
    description: str | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    registration_opens_at: datetime | None = None
    registration_closes_at: datetime | None = None
    is_active: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _validated_name(value)


class UpdateCycleInput(BaseModel):
    # kind is accepted so a client may echo the object back unchanged; decide
    # rejects only an actual change, which is what CYC-1 immutability means.
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    name: str | None = None
    kind: CycleKind | None = None
    description: str | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    registration_opens_at: datetime | None = None
    registration_closes_at: datetime | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return None if value is None else _validated_name(value)


class SetCycleActiveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    is_active: bool


class UpdateCyclePolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    membership_requires_approval: bool | None = None
    join_rule: dict[str, object] | None = None
    max_accepted_offers: int | None = None
    penalty_blocks_applications: bool | None = None
    allow_withdrawal_after_deadline: bool | None = None
    allow_edit_after_deadline: bool | None = None
    strike_on_absence: bool | None = None
    offer_expiry_behavior: OfferExpiry | None = None
    deadline_reminder_hours: int | None = None
    round_reminder_hours: int | None = None

    @field_validator("join_rule")
    @classmethod
    def validate_join_rule(cls, value: dict[str, object] | None) -> dict[str, object] | None:
        """Unknown field or operator is a 422 at save (LLD section 9.1)."""
        if value is not None:
            parse_rule(value)
        return value

    @field_validator("max_accepted_offers")
    @classmethod
    def validate_cap(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("max_accepted_offers must be at least 1, or null for uncapped")
        return value

    @field_validator("deadline_reminder_hours", "round_reminder_hours")
    @classmethod
    def validate_offset(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("reminder offsets must be at least one hour")
        return value


class CoordinatorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    user_id: UUID


class CycleSummary(BaseModel):
    cycle_id: UUID
    name: str
    kind: CycleKind
    is_active: bool
    archived_at: datetime | None
    changed: bool


class CyclePolicySummary(BaseModel):
    cycle_id: UUID
    policy: dict[str, object]
    changed: bool


class CoordinatorSummary(BaseModel):
    cycle_id: UUID
    user_id: UUID
    assigned: bool
    changed: bool


@dataclass(frozen=True, slots=True)
class CycleRow:
    id: UUID
    name: str
    kind: CycleKind
    description: str | None
    starts_on: date | None
    ends_on: date | None
    registration_opens_at: datetime | None
    registration_closes_at: datetime | None
    is_active: bool
    archived_at: datetime | None

    def snapshot(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "name": self.name,
            "kind": self.kind.value,
            "description": self.description,
            "starts_on": self.starts_on.isoformat() if self.starts_on else None,
            "ends_on": self.ends_on.isoformat() if self.ends_on else None,
            "registration_opens_at": (
                self.registration_opens_at.isoformat()
                if self.registration_opens_at
                else None
            ),
            "registration_closes_at": (
                self.registration_closes_at.isoformat()
                if self.registration_closes_at
                else None
            ),
            "is_active": self.is_active,
            "archived_at": self.archived_at.isoformat() if self.archived_at else None,
        }


CYCLE_COLUMNS = (
    "id, name, kind, description, starts_on, ends_on, registration_opens_at, "
    "registration_closes_at, is_active, archived_at"
)


def cycle_row(row: sa.RowMapping) -> CycleRow:
    return CycleRow(
        id=row["id"],
        name=str(row["name"]),
        kind=CycleKind(row["kind"]),
        description=row["description"],
        starts_on=row["starts_on"],
        ends_on=row["ends_on"],
        registration_opens_at=row["registration_opens_at"],
        registration_closes_at=row["registration_closes_at"],
        is_active=bool(row["is_active"]),
        archived_at=row["archived_at"],
    )


async def fetch_cycle(
    tx: AsyncSession, cycle_id: UUID, *, lock: bool
) -> CycleRow | None:
    row = (
        await tx.execute(
            sa.text(
                f"SELECT {CYCLE_COLUMNS} FROM cycles WHERE id = :id"  # noqa: S608
                + (" FOR UPDATE" if lock else "")
            ),
            {"id": cycle_id},
        )
    ).mappings().one_or_none()
    return cycle_row(row) if row is not None else None


async def fetch_policy(tx: AsyncSession, cycle_id: UUID) -> dict[str, object] | None:
    row = (
        await tx.execute(
            sa.text(
                f"SELECT {', '.join(POLICY_COLUMNS)} FROM cycle_policies "  # noqa: S608
                "WHERE cycle_id = :cycle_id"
            ),
            {"cycle_id": cycle_id},
        )
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


def policy_values(policy: Policy) -> dict[str, object]:
    """The persisted column values behind a resolved CYC-2 policy."""
    return {
        "membership_requires_approval": policy.membership_requires_approval.value,
        "join_rule": policy.join_rule.value,
        "max_accepted_offers": policy.max_accepted_offers.value,
        "penalty_blocks_applications": policy.penalty_blocks_applications.value,
        "allow_withdrawal_after_deadline": policy.allow_withdrawal_after_deadline.value,
        "allow_edit_after_deadline": policy.allow_edit_after_deadline.value,
        "strike_on_absence": policy.strike_on_absence.value,
        "offer_expiry_behavior": policy.offer_expiry_behavior.value.value,
        "deadline_reminder_hours": policy.deadline_reminder_hours.value,
        "round_reminder_hours": policy.round_reminder_hours.value,
    }


def jsonable_policy(values: dict[str, object]) -> dict[str, object]:
    """Render policy column values for summaries and audit details."""
    return {
        key: (value.value if isinstance(value, OfferExpiry) else value)
        for key, value in values.items()
    }


@dataclass(frozen=True, slots=True)
class CycleCreateState:
    scope_ids: ScopeIds
    cycle_id: UUID
    policy_id: UUID
    conflict: CycleRow | None


@dataclass(frozen=True, slots=True)
class CycleState:
    scope_ids: ScopeIds
    cycle_archived: bool
    cycle: CycleRow | None
    conflict: CycleRow | None


@dataclass(frozen=True, slots=True)
class CyclePolicyState:
    scope_ids: ScopeIds
    cycle_archived: bool
    cycle: CycleRow | None
    policy: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class CoordinatorState:
    scope_ids: ScopeIds
    cycle_archived: bool
    cycle: CycleRow | None
    user_email: str | None
    user_is_active: bool
    assigned: bool


async def _name_conflict(
    tx: AsyncSession, name: str | None, cycle_id: UUID | None, *, lock: bool
) -> CycleRow | None:
    if name is None:
        return None
    if lock:
        await tx.execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"cycle:{name.casefold()}"},
        )
    row = (
        await tx.execute(
            sa.text(
                f"SELECT {CYCLE_COLUMNS} FROM cycles "  # noqa: S608
                "WHERE name = :name AND (CAST(:id AS uuid) IS NULL "
                "OR id <> CAST(:id AS uuid))"
            ),
            {"name": name, "id": cycle_id},
        )
    ).mappings().one_or_none()
    return cycle_row(row) if row is not None else None


async def _load_create(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> CycleCreateState:
    if not isinstance(input_value, CreateCycleInput):
        raise TypeError("create_cycle requires CreateCycleInput")
    return CycleCreateState(
        scope_ids=ScopeIds(),
        cycle_id=uuid4(),
        policy_id=uuid4(),
        conflict=await _name_conflict(tx, input_value.name, None, lock=lock),
    )


async def _load_update(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> CycleState:
    if not isinstance(input_value, UpdateCycleInput):
        raise TypeError("update_cycle requires UpdateCycleInput")
    cycle = await fetch_cycle(tx, input_value.cycle_id, lock=lock)
    return CycleState(
        scope_ids=ScopeIds(cycle_id=input_value.cycle_id),
        cycle_archived=cycle is not None and cycle.archived_at is not None,
        cycle=cycle,
        conflict=await _name_conflict(
            tx, input_value.name, input_value.cycle_id, lock=lock
        ),
    )


async def _load_set_active(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> CycleState:
    if not isinstance(input_value, SetCycleActiveInput):
        raise TypeError("set_cycle_active requires SetCycleActiveInput")
    cycle = await fetch_cycle(tx, input_value.cycle_id, lock=lock)
    return CycleState(
        scope_ids=ScopeIds(cycle_id=input_value.cycle_id),
        cycle_archived=cycle is not None and cycle.archived_at is not None,
        cycle=cycle,
        conflict=None,
    )


async def _load_policy(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> CyclePolicyState:
    if not isinstance(input_value, UpdateCyclePolicyInput):
        raise TypeError("update_cycle_policy requires UpdateCyclePolicyInput")
    cycle = await fetch_cycle(tx, input_value.cycle_id, lock=lock)
    return CyclePolicyState(
        scope_ids=ScopeIds(cycle_id=input_value.cycle_id),
        cycle_archived=cycle is not None and cycle.archived_at is not None,
        cycle=cycle,
        policy=await fetch_policy(tx, input_value.cycle_id),
    )


async def _load_coordinator(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> CoordinatorState:
    if not isinstance(input_value, CoordinatorInput):
        raise TypeError("Coordinator commands require CoordinatorInput")
    cycle = await fetch_cycle(tx, input_value.cycle_id, lock=lock)
    user = (
        await tx.execute(
            sa.text("SELECT email, is_active FROM users WHERE id = :id"),
            {"id": input_value.user_id},
        )
    ).mappings().one_or_none()
    assigned = await tx.scalar(
        sa.text(
            "SELECT count(*) FROM cycle_coordinators "
            "WHERE cycle_id = :cycle_id AND user_id = :user_id"
        ),
        {"cycle_id": input_value.cycle_id, "user_id": input_value.user_id},
    )
    return CoordinatorState(
        scope_ids=ScopeIds(cycle_id=input_value.cycle_id),
        cycle_archived=cycle is not None and cycle.archived_at is not None,
        cycle=cycle,
        user_email=str(user["email"]) if user is not None else None,
        user_is_active=user is not None and bool(user["is_active"]),
        assigned=bool(assigned),
    )


def _cycle_not_found() -> Rejection:
    return Rejection(
        reasons=[Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")]
    )


def _name_conflict_reason(conflict: CycleRow) -> Reason:
    return Reason(
        code=CYCLE_NAME_CONFLICT,
        human=f"'{conflict.name}' is already the name of another cycle",
        path="name",
    )


def _date_order_reasons(starts_on: date | None, ends_on: date | None) -> list[Reason]:
    """Dates are informational (CYC-1); the order check only keeps them sane."""
    if starts_on is not None and ends_on is not None and starts_on > ends_on:
        return [
            Reason(
                code=INVALID_FIELD_VALUE,
                human="The start date must not fall after the end date",
                path="starts_on",
            )
        ]
    return []


def _window_order_reasons(
    opens_at: datetime | None, closes_at: datetime | None
) -> list[Reason]:
    """The registration window is not informational -- it gates joining.

    ``_window_reasons`` in ``modules/cycles/memberships`` reads the pair as
    ``now < opens or now >= closes``, so a window whose close precedes its open
    is satisfied by no instant at all: the cycle silently accepts nobody, and
    the students who try are told only that registration "is not open".  Both
    dates being nullable is deliberate (either end may be left unbounded); only
    the inverted pair is refused.
    """
    if opens_at is not None and closes_at is not None and opens_at >= closes_at:
        return [
            Reason(
                code=INVALID_FIELD_VALUE,
                human="Registration must open before it closes",
                path="registration_closes_at",
            )
        ]
    return []


def _decide_create_cycle(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Create a cycle and its CYC-2 policy row together (Behavior CYC-1)."""
    if not isinstance(input_value, CreateCycleInput) or not isinstance(
        state, CycleCreateState
    ):
        raise TypeError("Invalid create_cycle decision input")
    reasons: list[Reason] = []
    if state.conflict is not None:
        reasons.append(_name_conflict_reason(state.conflict))
    reasons.extend(_date_order_reasons(input_value.starts_on, input_value.ends_on))
    reasons.extend(
        _window_order_reasons(
            input_value.registration_opens_at, input_value.registration_closes_at
        )
    )
    if reasons:
        return Rejection(reasons=reasons)

    cycle = CycleRow(
        id=state.cycle_id,
        name=input_value.name,
        kind=input_value.kind,
        description=input_value.description,
        starts_on=input_value.starts_on,
        ends_on=input_value.ends_on,
        registration_opens_at=input_value.registration_opens_at,
        registration_closes_at=input_value.registration_closes_at,
        is_active=input_value.is_active,
        archived_at=None,
    )
    # The defaults come from the resolver itself, so a freshly created cycle
    # can never disagree with what every reader would have resolved for it.
    defaults = policy_values(resolve_policy(input_value.kind))
    return Plan(
        state_ops=[
            StateOp(
                op="insert",
                model="cycles",
                values={
                    "id": cycle.id,
                    "name": cycle.name,
                    "kind": cycle.kind.value,
                    "description": cycle.description,
                    "starts_on": cycle.starts_on,
                    "ends_on": cycle.ends_on,
                    "registration_opens_at": cycle.registration_opens_at,
                    "registration_closes_at": cycle.registration_closes_at,
                    "is_active": cycle.is_active,
                },
            ),
            StateOp(
                op="insert",
                model="cycle_policies",
                values={"id": state.policy_id, "cycle_id": cycle.id, **defaults},
            ),
        ],
        events=[],
        deferred=[],
        audit={
            "subject_type": "cycle",
            "subject_id": cycle.id,
            "details": {
                "before": None,
                "after": cycle.snapshot(),
                "policy": jsonable_policy(defaults),
            },
        },
        summary={
            "cycle_id": str(cycle.id),
            "name": cycle.name,
            "kind": cycle.kind.value,
            "is_active": cycle.is_active,
            "archived_at": None,
            "changed": True,
        },
    )


def _decide_update_cycle(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Edit a cycle's descriptive fields; the kind never moves (Behavior CYC-1)."""
    if not isinstance(input_value, UpdateCycleInput) or not isinstance(state, CycleState):
        raise TypeError("Invalid update_cycle decision input")
    if state.cycle is None:
        return _cycle_not_found()
    before = state.cycle
    provided = input_value.model_fields_set

    reasons: list[Reason] = []
    if (
        "kind" in provided
        and input_value.kind is not None
        and input_value.kind is not before.kind
    ):
        reasons.append(
            Reason(
                code=FIELD_NOT_EDITABLE,
                human=(
                    "A cycle's kind fixes how its jobs, offers, and gates behave "
                    "and cannot be changed after creation"
                ),
                path="kind",
            )
        )
    if state.conflict is not None:
        reasons.append(_name_conflict_reason(state.conflict))

    def field[T](key: str, current: T) -> T:
        return getattr(input_value, key) if key in provided else current

    after = CycleRow(
        id=before.id,
        name=input_value.name if "name" in provided and input_value.name else before.name,
        kind=before.kind,
        description=field("description", before.description),
        starts_on=field("starts_on", before.starts_on),
        ends_on=field("ends_on", before.ends_on),
        registration_opens_at=field(
            "registration_opens_at", before.registration_opens_at
        ),
        registration_closes_at=field(
            "registration_closes_at", before.registration_closes_at
        ),
        is_active=before.is_active,
        archived_at=before.archived_at,
    )
    reasons.extend(_date_order_reasons(after.starts_on, after.ends_on))
    reasons.extend(
        _window_order_reasons(
            after.registration_opens_at, after.registration_closes_at
        )
    )
    if reasons:
        return Rejection(reasons=reasons)

    changed = after != before
    return Plan(
        state_ops=(
            [
                StateOp(
                    op="update",
                    model="cycles",
                    values={
                        "name": after.name,
                        "description": after.description,
                        "starts_on": after.starts_on,
                        "ends_on": after.ends_on,
                        "registration_opens_at": after.registration_opens_at,
                        "registration_closes_at": after.registration_closes_at,
                    },
                    where={"id": before.id},
                )
            ]
            if changed
            else []
        ),
        events=[],
        deferred=[],
        audit={
            "subject_type": "cycle",
            "subject_id": before.id,
            "details": {"before": before.snapshot(), "after": after.snapshot()},
        },
        summary={
            "cycle_id": str(after.id),
            "name": after.name,
            "kind": after.kind.value,
            "is_active": after.is_active,
            "archived_at": None,
            "changed": changed,
        },
    )


def _decide_set_cycle_active(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Open or close a cycle for joining (Behavior CYC-1, the design review section 4.9)."""
    if not isinstance(input_value, SetCycleActiveInput) or not isinstance(
        state, CycleState
    ):
        raise TypeError("Invalid set_cycle_active decision input")
    if state.cycle is None:
        return _cycle_not_found()
    before = state.cycle
    changed = before.is_active is not input_value.is_active
    return Plan(
        state_ops=(
            [
                StateOp(
                    op="update",
                    model="cycles",
                    values={"is_active": input_value.is_active},
                    where={"id": before.id},
                )
            ]
            if changed
            else []
        ),
        events=[],
        deferred=[],
        audit={
            "subject_type": "cycle",
            "subject_id": before.id,
            "details": {
                "before": {"is_active": before.is_active},
                "after": {"is_active": input_value.is_active},
            },
        },
        summary={
            "cycle_id": str(before.id),
            "name": before.name,
            "kind": before.kind.value,
            "is_active": input_value.is_active,
            "archived_at": None,
            "changed": changed,
        },
    )


def _decide_update_cycle_policy(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Edit the CYC-2 knob list; absent keys keep their stored value."""
    if not isinstance(input_value, UpdateCyclePolicyInput) or not isinstance(
        state, CyclePolicyState
    ):
        raise TypeError("Invalid update_cycle_policy decision input")
    if state.cycle is None:
        return _cycle_not_found()
    if state.policy is None:
        raise RuntimeError(f"Cycle {state.cycle.id} has no policy row")

    provided = input_value.model_fields_set
    before = dict(state.policy)
    after = dict(before)
    for column in POLICY_COLUMNS:
        if column in provided:
            value = getattr(input_value, column)
            after[column] = value.value if isinstance(value, OfferExpiry) else value

    changed = after != before
    return Plan(
        state_ops=(
            [
                StateOp(
                    op="update",
                    model="cycle_policies",
                    values=after,
                    where={"cycle_id": state.cycle.id},
                )
            ]
            if changed
            else []
        ),
        events=[],
        deferred=[],
        audit={
            "subject_type": "cycle_policy",
            "subject_id": state.cycle.id,
            "details": {
                "before": jsonable_policy(before),
                "after": jsonable_policy(after),
            },
        },
        summary={
            "cycle_id": str(state.cycle.id),
            "policy": jsonable_policy(after),
            "changed": changed,
        },
    )


def _coordinator_notification(
    state: CoordinatorState, cycle: CycleRow, event_key: str
) -> list[Deferred]:
    if state.user_email is None:
        return []
    return [
        Deferred(
            task="deliver_notification",
            args={
                "event_key": event_key,
                "recipient": state.user_email,
                "context": {"cycle": cycle.name, "cycle_id": str(cycle.id)},
            },
        )
    ]


def _decide_assign_coordinator(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Grant staff-of-cycle capability to one user (Behavior CYC-1, IDN-3)."""
    if not isinstance(input_value, CoordinatorInput) or not isinstance(
        state, CoordinatorState
    ):
        raise TypeError("Invalid assign_coordinator decision input")
    if state.cycle is None:
        return _cycle_not_found()
    if state.user_email is None:
        return Rejection(
            reasons=[
                Reason(code=USER_NOT_FOUND, human="The user does not exist", path="user_id")
            ]
        )
    if not state.user_is_active:
        return Rejection(
            reasons=[
                Reason(
                    code=INACTIVE_USER,
                    human="A deactivated user cannot coordinate a cycle",
                    path="user_id",
                )
            ]
        )
    if state.assigned:
        return Rejection(
            reasons=[
                Reason(
                    code=COORDINATOR_ALREADY_ASSIGNED,
                    human="The user already coordinates this cycle",
                    path="user_id",
                )
            ]
        )

    return Plan(
        state_ops=[
            StateOp(
                op="insert",
                model="cycle_coordinators",
                values={
                    "id": uuid4(),
                    "cycle_id": state.cycle.id,
                    "user_id": input_value.user_id,
                },
            )
        ],
        events=[],
        deferred=_coordinator_notification(state, state.cycle, "coordinator_assigned"),
        audit={
            "subject_type": "cycle",
            "subject_id": state.cycle.id,
            "details": {"assigned_user_id": str(input_value.user_id)},
        },
        summary={
            "cycle_id": str(state.cycle.id),
            "user_id": str(input_value.user_id),
            "assigned": True,
            "changed": True,
        },
    )


def _decide_remove_coordinator(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Revoke staff-of-cycle capability (Behavior CYC-1, IDN-3)."""
    if not isinstance(input_value, CoordinatorInput) or not isinstance(
        state, CoordinatorState
    ):
        raise TypeError("Invalid remove_coordinator decision input")
    if state.cycle is None:
        return _cycle_not_found()
    if not state.assigned:
        return Rejection(
            reasons=[
                Reason(
                    code=COORDINATOR_NOT_FOUND,
                    human="The user does not coordinate this cycle",
                    path="user_id",
                )
            ]
        )

    return Plan(
        state_ops=[
            StateOp(
                op="delete",
                model="cycle_coordinators",
                values={},
                where={"cycle_id": state.cycle.id, "user_id": input_value.user_id},
            )
        ],
        events=[],
        deferred=_coordinator_notification(state, state.cycle, "coordinator_removed"),
        audit={
            "subject_type": "cycle",
            "subject_id": state.cycle.id,
            "details": {"removed_user_id": str(input_value.user_id)},
        },
        summary={
            "cycle_id": str(state.cycle.id),
            "user_id": str(input_value.user_id),
            "assigned": False,
            "changed": True,
        },
    )


def register_cycle_commands(registry: Registry) -> None:
    registry.command(
        name="create_cycle",
        input_model=CreateCycleInput,
        output_model=CycleSummary,
        actor="admin",
        scope="none",
        loader=_load_create,
        rule_domains=(),
        spec_ids=("CYC-1", "CYC-2"),
    )(_decide_create_cycle)
    registry.command(
        name="update_cycle",
        input_model=UpdateCycleInput,
        output_model=CycleSummary,
        actor="admin",
        scope="cycle",
        loader=_load_update,
        rule_domains=(),
        spec_ids=("CYC-1",),
    )(_decide_update_cycle)
    registry.command(
        name="set_cycle_active",
        input_model=SetCycleActiveInput,
        output_model=CycleSummary,
        actor="admin",
        scope="cycle",
        loader=_load_set_active,
        rule_domains=(),
        spec_ids=("CYC-1",),
    )(_decide_set_cycle_active)
    registry.command(
        name="update_cycle_policy",
        input_model=UpdateCyclePolicyInput,
        output_model=CyclePolicySummary,
        actor="admin",
        scope="cycle",
        loader=_load_policy,
        rule_domains=(),
        spec_ids=("CYC-2",),
    )(_decide_update_cycle_policy)
    registry.command(
        name="assign_coordinator",
        input_model=CoordinatorInput,
        output_model=CoordinatorSummary,
        actor="admin",
        scope="cycle",
        loader=_load_coordinator,
        rule_domains=(),
        spec_ids=("CYC-1", "IDN-3"),
    )(_decide_assign_coordinator)
    registry.command(
        name="remove_coordinator",
        input_model=CoordinatorInput,
        output_model=CoordinatorSummary,
        actor="admin",
        scope="cycle",
        loader=_load_coordinator,
        rule_domains=(),
        spec_ids=("CYC-1", "IDN-3"),
    )(_decide_remove_coordinator)
