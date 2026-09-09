"""Administrative strikes and penalties (Behavior DIS).

Four admin commands over the enrollment, not the cycle: strikes and penalties
attach to an enrollment and persist across every cycle it joins, so a fresh
enrollment starts clean and none of these is cycle-scoped.

Conversion and its recomputation are M5's (``domain/discipline``); this module
loads the enrollment's standing record, hands it over, and writes the rows the
pure functions ask for.  The penalty *gate* is not here at all -- it has always
been live in ``domain/gates``, correct by emptiness until these commands gave
the ``penalties`` table a write path (the design review section 4.25).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ENROLLMENT_NOT_FOUND,
    PENALTY_NOT_FOUND,
    STRIKE_NOT_FOUND,
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
from app.domain.discipline import recompute_after_revoke
from app.domain.shared import StrikeSource
from app.modules.discipline.awards import (
    EnrollmentDiscipline,
    StrikeIntent,
    award_direct_penalty,
    award_strikes,
    load_discipline,
    lock_enrollments,
    penalty_revocable,
    resolve_threshold,
    strike_revocable,
)


def _required_text(value: str) -> str:
    if not value.strip():
        raise ValueError("a reason is required")
    return value.strip()


class AwardStrikeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enrollment_id: UUID
    reason: str

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return _required_text(value)


class RevokeStrikeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strike_id: UUID
    #: INT-1: every intervention carries a mandatory reason.  A strike row has
    #: nowhere to store it, so it lands in the audit log (the design review 4.25).
    reason: str

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return _required_text(value)


class AwardPenaltyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enrollment_id: UUID
    reasons: str

    @field_validator("reasons")
    @classmethod
    def validate_reasons(cls, value: str) -> str:
        return _required_text(value)


class RevokePenaltyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    penalty_id: UUID
    reason: str

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return _required_text(value)


class StrikeSummary(BaseModel):
    enrollment_id: UUID
    full_name: str
    strike_total: int
    penalties_created: int


class RevokeStrikeSummary(BaseModel):
    enrollment_id: UUID
    full_name: str
    strike_total: int
    penalties_dissolved: int
    penalties_created: int


class PenaltySummary(BaseModel):
    enrollment_id: UUID
    full_name: str
    penalty_active: bool


@dataclass(frozen=True, slots=True)
class DisciplineState:
    scope_ids: ScopeIds
    now: datetime
    threshold: int | None
    record: EnrollmentDiscipline | None
    #: The strike or penalty the command names, when it names one.
    target_strike_id: UUID | None = None
    target_penalty_id: UUID | None = None


async def _load_for_enrollment(
    tx: AsyncSession, enrollment_id: UUID, *, lock: bool
) -> DisciplineState:
    if lock:
        await lock_enrollments(tx, [enrollment_id])
    records = await load_discipline(tx, [enrollment_id])
    return DisciplineState(
        scope_ids=ScopeIds(enrollment_id=enrollment_id),
        now=cast(datetime, await tx.scalar(sa.select(sa.func.now()))),
        threshold=await resolve_threshold(tx),
        record=records.get(enrollment_id),
    )


async def _load_award_strike(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> DisciplineState:
    if not isinstance(input_value, AwardStrikeInput):
        raise TypeError("award_strike requires AwardStrikeInput")
    return await _load_for_enrollment(tx, input_value.enrollment_id, lock=lock)


async def _load_award_penalty(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> DisciplineState:
    if not isinstance(input_value, AwardPenaltyInput):
        raise TypeError("award_penalty requires AwardPenaltyInput")
    return await _load_for_enrollment(tx, input_value.enrollment_id, lock=lock)


async def _owner_of(tx: AsyncSession, table: str, row_id: UUID) -> UUID | None:
    return cast(
        "UUID | None",
        await tx.scalar(
            sa.text(f"SELECT enrollment_id FROM {table} WHERE id = :id"),  # noqa: S608
            {"id": row_id},
        ),
    )


async def _load_revoke_strike(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> DisciplineState:
    if not isinstance(input_value, RevokeStrikeInput):
        raise TypeError("revoke_strike requires RevokeStrikeInput")
    enrollment_id = await _owner_of(tx, "strikes", input_value.strike_id)
    if enrollment_id is None:
        return DisciplineState(
            scope_ids=ScopeIds(),
            now=cast(datetime, await tx.scalar(sa.select(sa.func.now()))),
            threshold=await resolve_threshold(tx),
            record=None,
            target_strike_id=input_value.strike_id,
        )
    state = await _load_for_enrollment(tx, enrollment_id, lock=lock)
    return DisciplineState(
        scope_ids=state.scope_ids,
        now=state.now,
        threshold=state.threshold,
        record=state.record,
        target_strike_id=input_value.strike_id,
    )


async def _load_revoke_penalty(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> DisciplineState:
    if not isinstance(input_value, RevokePenaltyInput):
        raise TypeError("revoke_penalty requires RevokePenaltyInput")
    enrollment_id = await _owner_of(tx, "penalties", input_value.penalty_id)
    if enrollment_id is None:
        return DisciplineState(
            scope_ids=ScopeIds(),
            now=cast(datetime, await tx.scalar(sa.select(sa.func.now()))),
            threshold=await resolve_threshold(tx),
            record=None,
            target_penalty_id=input_value.penalty_id,
        )
    state = await _load_for_enrollment(tx, enrollment_id, lock=lock)
    return DisciplineState(
        scope_ids=state.scope_ids,
        now=state.now,
        threshold=state.threshold,
        record=state.record,
        target_penalty_id=input_value.penalty_id,
    )


def _no_enrollment() -> Rejection:
    return Rejection(
        reasons=[
            Reason(
                code=ENROLLMENT_NOT_FOUND,
                human="The enrollment does not exist",
                path="enrollment_id",
            )
        ]
    )


def _decide_award_strike(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """Award one strike by hand, converting if it completes a threshold (DIS)."""
    if not isinstance(input_value, AwardStrikeInput) or not isinstance(
        state, DisciplineState
    ):
        raise TypeError("Invalid award_strike decision input")
    if state.record is None:
        return _no_enrollment()

    outcome = award_strikes(
        [
            StrikeIntent(
                enrollment_id=input_value.enrollment_id,
                reason=input_value.reason,
                source=StrikeSource.MANUAL,
            )
        ],
        {input_value.enrollment_id: state.record},
        threshold=state.threshold,
        now=state.now,
        actor_user_id=actor.user_id,
    )
    reported = outcome.rows[0]
    return Plan(
        state_ops=outcome.state_ops,
        events=[],
        deferred=outcome.deferred,
        audit={
            "subject_type": "enrollment",
            "subject_id": input_value.enrollment_id,
            "details": {
                "action": "award_strike",
                "reason": input_value.reason,
                "source": StrikeSource.MANUAL.value,
                "strike_total": reported["strike_total"],
                "penalties_created": reported["penalties_created"],
            },
        },
        summary={
            "enrollment_id": str(input_value.enrollment_id),
            "full_name": state.record.full_name,
            "strike_total": reported["strike_total"],
            "penalties_created": reported["penalties_created"],
        },
    )


def _decide_revoke_strike(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """Revoke a strike and recompute conversion against the threshold (DIS)."""
    if not isinstance(input_value, RevokeStrikeInput) or not isinstance(
        state, DisciplineState
    ):
        raise TypeError("Invalid revoke_strike decision input")
    if state.record is None:
        return Rejection(
            reasons=[
                Reason(
                    code=STRIKE_NOT_FOUND,
                    human="The strike does not exist",
                    path="strike_id",
                )
            ]
        )
    target = next(
        (item for item in state.record.strikes if item.id == input_value.strike_id), None
    )
    if target is None:
        return Rejection(
            reasons=[
                Reason(
                    code=STRIKE_NOT_FOUND,
                    human="The strike does not exist",
                    path="strike_id",
                )
            ]
        )
    blocked = strike_revocable(target)
    if blocked is not None:
        return Rejection(reasons=[blocked])

    result = recompute_after_revoke(
        strikes=tuple(strike.state() for strike in state.record.strikes),
        penalties=tuple(penalty.state() for penalty in state.record.penalties),
        revoked_strike_id=input_value.strike_id,
        threshold=state.threshold,
    )

    operations: list[StateOp] = [
        StateOp(
            op="update",
            model="strikes",
            values={"is_active": False},
            where={"id": input_value.strike_id},
        )
    ]
    deferred: list[Deferred] = []
    for dissolution in result.dissolutions:
        # An automatic penalty with nothing left supporting it stops standing,
        # and its strikes go back to being unconsumed so they can regroup.
        operations.append(
            StateOp(
                op="update",
                model="penalties",
                values={
                    "is_active": False,
                    "revoked_at": state.now,
                    "revoked_by": actor.user_id,
                },
                where={"id": dissolution.penalty_id},
            )
        )
        for strike_id in dissolution.unconsume_strike_ids:
            operations.append(
                StateOp(
                    op="update",
                    model="strikes",
                    values={"consumed_by_penalty_id": None},
                    where={"id": strike_id},
                )
            )
        deferred.append(
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": "penalty_revoked",
                    "recipient": state.record.email,
                    "context": {
                        "student": state.record.full_name,
                        "reason": input_value.reason,
                    },
                },
            )
        )

    for group in result.conversions:
        penalty_id = uuid4()
        operations.append(
            StateOp(
                op="insert",
                model="penalties",
                values={
                    "id": penalty_id,
                    "enrollment_id": state.record.enrollment_id,
                    "reasons": group.reasons,
                    "from_strikes": True,
                    "is_active": True,
                    "created_by": actor.user_id,
                },
            )
        )
        for strike_id in group.strike_ids:
            operations.append(
                StateOp(
                    op="update",
                    model="strikes",
                    values={"consumed_by_penalty_id": penalty_id},
                    where={"id": strike_id},
                )
            )
        deferred.append(
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": "penalty_added",
                    "recipient": state.record.email,
                    "context": {
                        "student": state.record.full_name,
                        "reasons": group.reasons,
                    },
                },
            )
        )

    total = state.record.active_strikes() - 1
    deferred.append(
        Deferred(
            task="deliver_notification",
            args={
                "event_key": "strike_revoked",
                "recipient": state.record.email,
                "context": {"student": state.record.full_name, "total": total},
            },
        )
    )
    return Plan(
        state_ops=operations,
        events=[],
        deferred=deferred,
        audit={
            "subject_type": "strike",
            "subject_id": input_value.strike_id,
            # The strikes table has no revoked_by column (LLD section 8), so
            # this row is the only record of who revoked it and why.  M14's
            # drill-down reads it (the design review section 4.25).
            "details": {
                "action": "revoke_strike",
                "reason": input_value.reason,
                "enrollment_id": str(state.record.enrollment_id),
                "actor_user_id": str(actor.user_id) if actor.user_id else None,
                "penalties_dissolved": [
                    str(item.penalty_id) for item in result.dissolutions
                ],
            },
        },
        summary={
            "enrollment_id": str(state.record.enrollment_id),
            "full_name": state.record.full_name,
            "strike_total": total,
            "penalties_dissolved": len(result.dissolutions),
            "penalties_created": len(result.conversions),
        },
    )


def _decide_award_penalty(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """Award a penalty directly, consuming no strikes (DIS)."""
    if not isinstance(input_value, AwardPenaltyInput) or not isinstance(
        state, DisciplineState
    ):
        raise TypeError("Invalid award_penalty decision input")
    if state.record is None:
        return _no_enrollment()
    outcome = award_direct_penalty(
        state.record,
        reasons=input_value.reasons,
        actor_user_id=actor.user_id,
    )
    return Plan(
        state_ops=outcome.state_ops,
        events=[],
        deferred=outcome.deferred,
        audit={
            "subject_type": "enrollment",
            "subject_id": input_value.enrollment_id,
            "details": {"action": "award_penalty", "reasons": input_value.reasons},
        },
        summary={
            "enrollment_id": str(input_value.enrollment_id),
            "full_name": state.record.full_name,
            "penalty_active": True,
        },
    )


def _decide_revoke_penalty(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """Deactivate a penalty; its consumed strikes stay consumed (DIS)."""
    if not isinstance(input_value, RevokePenaltyInput) or not isinstance(
        state, DisciplineState
    ):
        raise TypeError("Invalid revoke_penalty decision input")
    if state.record is None:
        return Rejection(
            reasons=[
                Reason(
                    code=PENALTY_NOT_FOUND,
                    human="The penalty does not exist",
                    path="penalty_id",
                )
            ]
        )
    target = next(
        (item for item in state.record.penalties if item.id == input_value.penalty_id),
        None,
    )
    if target is None:
        return Rejection(
            reasons=[
                Reason(
                    code=PENALTY_NOT_FOUND,
                    human="The penalty does not exist",
                    path="penalty_id",
                )
            ]
        )
    blocked = penalty_revocable(target)
    if blocked is not None:
        return Rejection(reasons=[blocked])
    return Plan(
        state_ops=[
            StateOp(
                op="update",
                model="penalties",
                values={
                    "is_active": False,
                    "revoked_at": state.now,
                    "revoked_by": actor.user_id,
                },
                where={"id": input_value.penalty_id},
            )
        ],
        events=[],
        deferred=[
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": "penalty_revoked",
                    "recipient": state.record.email,
                    "context": {
                        "student": state.record.full_name,
                        "reason": input_value.reason,
                    },
                },
            )
        ],
        audit={
            "subject_type": "penalty",
            "subject_id": input_value.penalty_id,
            "details": {
                "action": "revoke_penalty",
                "reason": input_value.reason,
                "enrollment_id": str(state.record.enrollment_id),
                # DIS is explicit: revoking a penalty leaves the strikes it
                # consumed consumed, unless they are revoked too.
                "strikes_unconsumed": False,
            },
        },
        summary={
            "enrollment_id": str(state.record.enrollment_id),
            "full_name": state.record.full_name,
            "penalty_active": False,
        },
    )


def register_discipline_commands(registry: Registry) -> None:
    registry.command(
        name="award_strike",
        input_model=AwardStrikeInput,
        output_model=StrikeSummary,
        actor="admin",
        scope="none",
        loader=_load_award_strike,
        rule_domains=(),
        spec_ids=("DIS",),
        rate_limit="10/min",
    )(_decide_award_strike)
    registry.command(
        name="revoke_strike",
        input_model=RevokeStrikeInput,
        output_model=RevokeStrikeSummary,
        actor="admin",
        scope="none",
        loader=_load_revoke_strike,
        rule_domains=(),
        spec_ids=("DIS",),
        rate_limit="10/min",
    )(_decide_revoke_strike)
    registry.command(
        name="award_penalty",
        input_model=AwardPenaltyInput,
        output_model=PenaltySummary,
        actor="admin",
        scope="none",
        loader=_load_award_penalty,
        rule_domains=(),
        spec_ids=("DIS",),
        rate_limit="10/min",
    )(_decide_award_penalty)
    registry.command(
        name="revoke_penalty",
        input_model=RevokePenaltyInput,
        output_model=PenaltySummary,
        actor="admin",
        scope="none",
        loader=_load_revoke_penalty,
        rule_domains=(),
        spec_ids=("DIS",),
        rate_limit="10/min",
    )(_decide_revoke_penalty)
