"""Granting and revoking scoped rule overrides (Behavior INT-2).

An override is the standing exception every gate consults before it enforces:
``modules/overrides/service.applicable`` resolves it and ``domain/gates`` acts
on it, both since M2.  What was missing until now is the write path -- there
was no way to create one, so the whole mechanism was correct by emptiness.

An override scope is one of six target combinations (the design review section 4.52),
from a whole cycle through one student-plus-job to an existing application.  A
job or application request still carries ``cycle_id`` on the wire so the route
stage can authorize a coordinator before loading (CONTRIBUTING.md invariant 8), but
that carrier is not persisted beside either target.  Without a job or
application, ``cycle_id`` is a real target and can be paired with an enrollment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    APPLICATION_NOT_FOUND,
    CYCLE_NOT_FOUND,
    ENROLLMENT_NOT_FOUND,
    INVALID_FIELD_VALUE,
    INVALID_REQUEST,
    JOB_NOT_FOUND,
    OVERRIDE_ALREADY_INACTIVE,
    OVERRIDE_NOT_FOUND,
)
from app.core.plan import (
    ActorContext,
    Plan,
    Reason,
    Rejection,
    ScopeIds,
    StateOp,
)
from app.core.registry import Registry
from app.domain.shared import (
    APPLICATION_SCOPE,
    CYCLE_ENROLLMENT_SCOPE,
    CYCLE_SCOPE,
    DOMAIN_SCOPES,
    ENROLLMENT_SCOPE,
    JOB_ENROLLMENT_SCOPE,
    JOB_SCOPE,
    RuleDomain,
    ScopeCombination,
    override_scope_combination,
    scope_name,
)

_TARGET_CYCLE = {
    "application_id": (
        "SELECT j.cycle_id FROM applications a JOIN jobs j ON j.id = a.job_id "
        "WHERE a.id = :id"
    ),
    "job_id": "SELECT cycle_id FROM jobs WHERE id = :id",
    "cycle_id": "SELECT id FROM cycles WHERE id = :id",
}
_TARGET_MISSING = {
    "application_id": (APPLICATION_NOT_FOUND, "The application does not exist"),
    "job_id": (JOB_NOT_FOUND, "The job does not exist"),
    "cycle_id": (CYCLE_NOT_FOUND, "The cycle does not exist"),
    "enrollment_id": (ENROLLMENT_NOT_FOUND, "The enrollment does not exist"),
}


def _required_text(value: str) -> str:
    if not value.strip():
        raise ValueError("a reason is required")
    return value.strip()


class CreateOverrideInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_domain: RuleDomain
    #: INT-2's allow flag.  ``False`` is a standing *block*, which the gates
    #: report as ``blocked_by_override`` and which wins over an equally
    #: specific allow (the design review section 4.14).
    allow: bool = True
    reason: str
    expires_at: datetime | None = None
    cycle_id: UUID | None = None
    job_id: UUID | None = None
    enrollment_id: UUID | None = None
    application_id: UUID | None = None

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return _required_text(value)

    @model_validator(mode="after")
    def validate_scope(self) -> CreateOverrideInput:
        if self.application_id is not None:
            if self.cycle_id is None:
                raise ValueError(
                    "an application-scoped override must also name the cycle_id "
                    "it belongs to"
                )
            if self.job_id is not None or self.enrollment_id is not None:
                raise ValueError(
                    "application_id cannot be combined with job_id or enrollment_id"
                )
            return self
        if self.job_id is not None:
            if self.cycle_id is None:
                raise ValueError(
                    "a job-scoped override must also name the cycle_id it belongs to"
                )
            return self
        if self.cycle_id is None and self.enrollment_id is None:
            raise ValueError(
                "name a legal scope target: cycle_id, job_id, enrollment_id, "
                "or application_id"
            )
        return self

    @property
    def target_combination(self) -> ScopeCombination:
        """The persisted target columns, excluding an authorization carrier."""
        if self.application_id is not None:
            return APPLICATION_SCOPE
        if self.job_id is not None:
            return (
                JOB_ENROLLMENT_SCOPE
                if self.enrollment_id is not None
                else JOB_SCOPE
            )
        if self.cycle_id is not None and self.enrollment_id is not None:
            return CYCLE_ENROLLMENT_SCOPE
        if self.enrollment_id is not None:
            return ENROLLMENT_SCOPE
        return CYCLE_SCOPE


class DeactivateOverrideInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    override_id: UUID
    #: Optional by ruling: INT-2 asks for "one-click deactivation" and the
    #: mandatory-reason table in INT-1 does not list overrides.  When one is
    #: given it is audited like every other intervention reason.
    reason: str | None = None

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str | None) -> str | None:
        return None if value is None else _required_text(value)


class OverrideSummary(BaseModel):
    override_id: UUID
    rule_domain: RuleDomain
    allow: bool
    scope: str
    subject_id: UUID
    is_active: bool
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class CreateOverrideState:
    scope_ids: ScopeIds
    cycle_archived: bool
    now: datetime
    #: The target row's cycle, or None for an enrollment-only target.
    target_cycle_id: UUID | None
    #: First target column whose row does not exist, in combination order.
    missing_target: str | None


@dataclass(frozen=True, slots=True)
class DeactivateOverrideState:
    scope_ids: ScopeIds
    cycle_archived: bool
    row: sa.RowMapping | None


async def _load_create_override(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> CreateOverrideState:
    # Nothing here is mutated between load and insert, and the target's
    # existence has its own DB-level backstop: every scope column is a
    # RESTRICT foreign key, so a target that vanishes concurrently fails the
    # insert rather than producing an override pointing at nothing.
    del lock
    if not isinstance(input_value, CreateOverrideInput):
        raise TypeError("create_override requires CreateOverrideInput")

    combination = input_value.target_combination
    cycle_target = input_value.cycle_id if "cycle" in combination else None
    target_cycle_id: UUID | None = None
    missing_target: str | None = None

    for target in combination:
        field = f"{target}_id"
        target_id = cast(UUID, getattr(input_value, field))
        if target == "enrollment":
            exists = bool(
                await tx.scalar(
                    sa.text("SELECT 1 FROM enrollments WHERE id = :id"),
                    {"id": target_id},
                )
            )
        else:
            found_cycle = cast(
                "UUID | None",
                await tx.scalar(sa.text(_TARGET_CYCLE[field]), {"id": target_id}),
            )
            exists = found_cycle is not None
            if target in {"cycle", "job", "application"}:
                target_cycle_id = found_cycle
        if not exists and missing_target is None:
            missing_target = field

    # The scope the executor re-checks is the cycle the target really sits in,
    # never the one the request claimed.  For cycle+enrollment the cycle itself
    # is the target; for job/application it was resolved through the target.
    if target_cycle_id is None:
        target_cycle_id = cycle_target
    archived = False
    if target_cycle_id is not None:
        archived = bool(
            await tx.scalar(
                sa.text("SELECT archived_at IS NOT NULL FROM cycles WHERE id = :id"),
                {"id": target_cycle_id},
            )
        )
    return CreateOverrideState(
        scope_ids=ScopeIds(
            cycle_id=target_cycle_id,
            job_id=input_value.job_id,
            enrollment_id=input_value.enrollment_id,
            application_id=input_value.application_id,
        ),
        cycle_archived=archived,
        now=cast(datetime, await tx.scalar(sa.select(sa.func.now()))),
        target_cycle_id=target_cycle_id,
        missing_target=missing_target,
    )


async def _load_deactivate_override(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> DeactivateOverrideState:
    if not isinstance(input_value, DeactivateOverrideInput):
        raise TypeError("deactivate_override requires DeactivateOverrideInput")
    row = (
        await tx.execute(
            sa.text(
                "SELECT o.id, o.rule_domain, o.allow, o.is_active, o.expires_at, "
                "o.reason, o.cycle_id, o.job_id, o.enrollment_id, o.application_id, "
                "coalesce(o.cycle_id, j.cycle_id, aj.cycle_id) AS scope_cycle_id, "
                "c.archived_at IS NOT NULL AS cycle_archived "
                "FROM overrides o "
                "LEFT JOIN jobs j ON j.id = o.job_id "
                "LEFT JOIN applications a ON a.id = o.application_id "
                "LEFT JOIN jobs aj ON aj.id = a.job_id "
                "LEFT JOIN cycles c "
                "  ON c.id = coalesce(o.cycle_id, j.cycle_id, aj.cycle_id) "
                "WHERE o.id = :id" + (" FOR UPDATE OF o" if lock else "")
            ),
            {"id": input_value.override_id},
        )
    ).mappings().one_or_none()
    return DeactivateOverrideState(
        scope_ids=ScopeIds(
            cycle_id=(
                cast("UUID | None", row["scope_cycle_id"]) if row is not None else None
            ),
            job_id=cast("UUID | None", row["job_id"]) if row is not None else None,
            enrollment_id=(
                cast("UUID | None", row["enrollment_id"]) if row is not None else None
            ),
            application_id=(
                cast("UUID | None", row["application_id"]) if row is not None else None
            ),
        ),
        cycle_archived=bool(row["cycle_archived"]) if row is not None else False,
        row=row,
    )


def scope_of(row: sa.RowMapping) -> tuple[str, UUID]:
    """Name an override row's combination and its primary subject."""
    combination = override_scope_combination(
        cycle_id=row["cycle_id"],
        job_id=row["job_id"],
        enrollment_id=row["enrollment_id"],
        application_id=row["application_id"],
    )
    if combination is None:
        raise ValueError("Override row names an illegal scope combination")
    for target in ("application", "job", "enrollment", "cycle"):
        field = f"{target}_id"
        if row[field] is not None:
            return scope_name(combination), cast(UUID, row[field])
    raise ValueError("Override row names no scope target")


def _decide_create_override(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """Grant one standing scoped exception to one rule domain (INT-2)."""
    if not isinstance(input_value, CreateOverrideInput) or not isinstance(
        state, CreateOverrideState
    ):
        raise TypeError("Invalid create_override decision input")

    combination = input_value.target_combination
    if state.missing_target is not None:
        code, human = _TARGET_MISSING[state.missing_target]
        return Rejection(
            reasons=[
                Reason(code=code, human=human, path=state.missing_target)
            ]
        )
    if (
        input_value.cycle_id is not None
        and state.target_cycle_id is not None
        and input_value.cycle_id != state.target_cycle_id
    ):
        return Rejection(
            reasons=[
                Reason(
                    code=INVALID_REQUEST,
                    human="The named cycle is not the one this target belongs to",
                    path="cycle_id",
                )
            ]
        )
    if combination not in DOMAIN_SCOPES[input_value.rule_domain]:
        return Rejection(
            reasons=[
                Reason(
                    code=INVALID_FIELD_VALUE,
                    human=(
                        f"{input_value.rule_domain.value} cannot affect a "
                        f"{scope_name(combination)} target"
                    ),
                    path="rule_domain",
                )
            ]
        )
    if input_value.expires_at is not None and input_value.expires_at <= state.now:
        # An override that is inert on arrival is a mistake, not a grant: the
        # resolver already treats a past expiry as absent, so the row would do
        # nothing and read as though it had.
        return Rejection(
            reasons=[
                Reason(
                    code=INVALID_FIELD_VALUE,
                    human="An expiry in the past would make this override inert immediately",
                    path="expires_at",
                )
            ]
        )
    if actor.user_id is None:
        raise RuntimeError("create_override requires an identified actor")

    override_id = uuid4()
    persisted = {
        "cycle_id": input_value.cycle_id if "cycle" in combination else None,
        "job_id": input_value.job_id if "job" in combination else None,
        "enrollment_id": (
            input_value.enrollment_id if "enrollment" in combination else None
        ),
        "application_id": (
            input_value.application_id if "application" in combination else None
        ),
    }
    target_id = cast(
        UUID,
        persisted["application_id"]
        or persisted["job_id"]
        or persisted["enrollment_id"]
        or persisted["cycle_id"],
    )
    scope = scope_name(combination)
    target_ids = {
        field: str(value)
        for field, value in persisted.items()
        if value is not None
    }
    return Plan(
        state_ops=[
            StateOp(
                op="insert",
                model="overrides",
                values={
                    "id": override_id,
                    "rule_domain": input_value.rule_domain.value,
                    "allow": input_value.allow,
                    **persisted,
                    "reason": input_value.reason,
                    "granted_by": actor.user_id,
                    "expires_at": input_value.expires_at,
                    "is_active": True,
                },
            )
        ],
        events=[],
        deferred=[],
        audit={
            "subject_type": "override",
            "subject_id": override_id,
            "details": {
                "action": "create_override",
                "rule_domain": input_value.rule_domain.value,
                "allow": input_value.allow,
                "scope": scope,
                "subject_id": str(target_id),
                "target_ids": target_ids,
                "cycle_id": (
                    str(state.target_cycle_id) if state.target_cycle_id else None
                ),
                "reason": input_value.reason,
                "expires_at": (
                    input_value.expires_at.isoformat() if input_value.expires_at else None
                ),
            },
        },
        summary={
            "override_id": str(override_id),
            "rule_domain": input_value.rule_domain.value,
            "allow": input_value.allow,
            "scope": scope,
            "subject_id": str(target_id),
            "is_active": True,
            "expires_at": (
                input_value.expires_at.isoformat() if input_value.expires_at else None
            ),
        },
    )


def _decide_deactivate_override(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Make one override inert from now on, keeping the row as history (INT-2)."""
    if not isinstance(input_value, DeactivateOverrideInput) or not isinstance(
        state, DeactivateOverrideState
    ):
        raise TypeError("Invalid deactivate_override decision input")
    if state.row is None:
        return Rejection(
            reasons=[
                Reason(
                    code=OVERRIDE_NOT_FOUND,
                    human="The override does not exist",
                    path="override_id",
                )
            ]
        )
    if not bool(state.row["is_active"]):
        return Rejection(
            reasons=[
                Reason(
                    code=OVERRIDE_ALREADY_INACTIVE,
                    human="This override has already been deactivated",
                    path="override_id",
                )
            ]
        )

    scope, subject_id = scope_of(state.row)
    return Plan(
        state_ops=[
            StateOp(
                op="update",
                model="overrides",
                values={"is_active": False},
                where={"id": input_value.override_id},
            )
        ],
        events=[],
        deferred=[],
        audit={
            "subject_type": "override",
            "subject_id": input_value.override_id,
            "details": {
                "action": "deactivate_override",
                "rule_domain": str(state.row["rule_domain"]),
                "scope": scope,
                "subject_id": str(subject_id),
                "reason": input_value.reason,
            },
        },
        summary={
            "override_id": str(input_value.override_id),
            "rule_domain": str(state.row["rule_domain"]),
            "allow": bool(state.row["allow"]),
            "scope": scope,
            "subject_id": str(subject_id),
            "is_active": False,
            "expires_at": (
                cast(datetime, state.row["expires_at"]).isoformat()
                if state.row["expires_at"] is not None
                else None
            ),
        },
    )


def register_override_commands(registry: Registry) -> None:
    registry.command(
        name="create_override",
        input_model=CreateOverrideInput,
        output_model=OverrideSummary,
        actor="staff",
        scope="cycle",
        loader=_load_create_override,
        # An override is not itself subject to overrides.
        rule_domains=(),
        spec_ids=("INT-2",),
        rate_limit="10/min",
    )(_decide_create_override)
    registry.command(
        name="deactivate_override",
        input_model=DeactivateOverrideInput,
        output_model=OverrideSummary,
        actor="staff",
        scope="cycle",
        loader=_load_deactivate_override,
        rule_domains=(),
        spec_ids=("INT-2",),
        rate_limit="10/min",
    )(_decide_deactivate_override)
