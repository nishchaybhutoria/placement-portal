"""Executor-backed identity administration commands for IDN-1/2/3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    INACTIVE_USER,
    LAST_ACTIVE_ADMIN,
    SELF_ADMIN_MUTATION,
    USER_NOT_FOUND,
)
from app.core.plan import ActorContext, Plan, Reason, Rejection, ScopeIds, StateOp
from app.core.registry import Registry
from app.domain.shared import Role


class LogoutInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pass


class LogoutSummary(BaseModel):
    logged_out: bool


class StartNewEnrollmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID


class StartNewEnrollmentSummary(BaseModel):
    new_enrollment_id: UUID


class SetUserRoleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    role: Role


class SetUserRoleSummary(BaseModel):
    changed: bool
    role: Role


class DeactivateUserInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID


class DeactivateUserSummary(BaseModel):
    changed: bool
    revoked_sessions: int


@dataclass(frozen=True, slots=True)
class LogoutState:
    scope_ids: ScopeIds
    now: datetime


@dataclass(frozen=True, slots=True)
class EnrollmentState:
    scope_ids: ScopeIds
    user_exists: bool
    user_active: bool
    current_ids: tuple[UUID, ...]
    new_enrollment_id: UUID


@dataclass(frozen=True, slots=True)
class AdminTargetState:
    scope_ids: ScopeIds
    target_exists: bool
    target_role: str | None
    target_active: bool
    active_admin_ids: tuple[UUID, ...]
    active_session_ids: tuple[UUID, ...]
    now: datetime


async def _load_logout(
    _tx: AsyncSession, _input: BaseModel, *, lock: bool
) -> LogoutState:
    del lock
    return LogoutState(scope_ids=ScopeIds(), now=datetime.now(UTC))


async def _load_enrollment(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> EnrollmentState:
    if not isinstance(input_value, StartNewEnrollmentInput):
        raise TypeError("start_new_enrollment requires StartNewEnrollmentInput")
    lock_clause = " FOR UPDATE" if lock else ""
    user = (
        await tx.execute(
            sa.text("SELECT is_active FROM users WHERE id = :id" + lock_clause),
            {"id": input_value.user_id},
        )
    ).mappings().one_or_none()
    current_ids: tuple[UUID, ...] = ()
    if user is not None:
        current_ids = tuple(
            (
                await tx.execute(
                    sa.text(
                        "SELECT id FROM enrollments WHERE user_id = :user_id "
                        "AND is_current ORDER BY id" + lock_clause
                    ),
                    {"user_id": input_value.user_id},
                )
            ).scalars()
        )
    return EnrollmentState(
        scope_ids=ScopeIds(enrollment_id=current_ids[0] if current_ids else None),
        user_exists=user is not None,
        user_active=bool(user["is_active"]) if user is not None else False,
        current_ids=current_ids,
        new_enrollment_id=uuid4(),
    )


async def _load_admin_target(
    tx: AsyncSession, user_id: UUID, *, lock: bool, include_sessions: bool
) -> AdminTargetState:
    lock_clause = " FOR UPDATE" if lock else ""
    active_admin_ids = tuple(
        (
            await tx.execute(
                sa.text(
                    "SELECT id FROM users WHERE role = 'admin' AND is_active "
                    "ORDER BY id" + lock_clause
                )
            )
        ).scalars()
    )
    target = (
        await tx.execute(
            sa.text(
                "SELECT role, is_active FROM users WHERE id = :id" + lock_clause
            ),
            {"id": user_id},
        )
    ).mappings().one_or_none()
    session_ids: tuple[UUID, ...] = ()
    if target is not None and include_sessions:
        session_ids = tuple(
            (
                await tx.execute(
                    sa.text(
                        "SELECT id FROM sessions WHERE user_id = :user_id "
                        "AND revoked_at IS NULL ORDER BY id" + lock_clause
                    ),
                    {"user_id": user_id},
                )
            ).scalars()
        )
    return AdminTargetState(
        scope_ids=ScopeIds(),
        target_exists=target is not None,
        target_role=str(target["role"]) if target is not None else None,
        target_active=bool(target["is_active"]) if target is not None else False,
        active_admin_ids=active_admin_ids,
        active_session_ids=session_ids,
        now=datetime.now(UTC),
    )


async def _load_role(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> AdminTargetState:
    if not isinstance(input_value, SetUserRoleInput):
        raise TypeError("set_user_role requires SetUserRoleInput")
    return await _load_admin_target(
        tx, input_value.user_id, lock=lock, include_sessions=False
    )


async def _load_deactivate(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> AdminTargetState:
    if not isinstance(input_value, DeactivateUserInput):
        raise TypeError("deactivate_user requires DeactivateUserInput")
    return await _load_admin_target(
        tx, input_value.user_id, lock=lock, include_sessions=True
    )


def _missing_user() -> Rejection:
    return Rejection(
        reasons=[Reason(code=USER_NOT_FOUND, human="The target user does not exist")]
    )


def _admin_removal_rejection(
    *, target_id: UUID, state: AdminTargetState, actor: ActorContext
) -> Rejection | None:
    if state.target_role != Role.ADMIN.value or not state.target_active:
        return None
    if len(state.active_admin_ids) <= 1:
        return Rejection(
            reasons=[
                Reason(
                    code=LAST_ACTIVE_ADMIN,
                    human="At least one active administrator must remain",
                )
            ]
        )
    if actor.user_id == target_id:
        return Rejection(
            reasons=[
                Reason(
                    code=SELF_ADMIN_MUTATION,
                    human="Administrators cannot remove their own access",
                )
            ]
        )
    return None


def _decide_logout(
    _input: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """Revoke the caller session for IDN-1."""
    if not isinstance(state, LogoutState) or actor.session_id is None:
        return Rejection(reasons=[Reason(code=INACTIVE_USER, human="No active session")])
    return Plan(
        state_ops=[
            StateOp(
                op="update",
                model="sessions",
                values={"revoked_at": state.now},
                where={"id": actor.session_id},
            )
        ],
        events=[],
        deferred=[],
        audit={"subject_type": "session", "subject_id": actor.session_id, "details": {}},
        summary={"logged_out": True},
    )


def _decide_enrollment(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Start a fresh current enrollment while retaining history for IDN-2."""
    if not isinstance(input_value, StartNewEnrollmentInput) or not isinstance(
        state, EnrollmentState
    ):
        raise TypeError("Invalid start_new_enrollment decision input")
    if not state.user_exists:
        return _missing_user()
    if not state.user_active:
        return Rejection(
            reasons=[Reason(code=INACTIVE_USER, human="The target user is inactive")]
        )
    operations = [
        StateOp(
            op="update",
            model="enrollments",
            values={"is_current": False},
            where={"id": enrollment_id},
        )
        for enrollment_id in state.current_ids
    ]
    operations.append(
        StateOp(
            op="insert",
            model="enrollments",
            values={
                "id": state.new_enrollment_id,
                "user_id": input_value.user_id,
                "is_current": True,
                "roll_number": None,
            },
        )
    )
    return Plan(
        state_ops=operations,
        events=[],
        deferred=[],
        audit={
            "subject_type": "user",
            "subject_id": input_value.user_id,
            "details": {"new_enrollment_id": str(state.new_enrollment_id)},
        },
        summary={"new_enrollment_id": str(state.new_enrollment_id)},
    )


def _decide_role(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """Set the global student/admin role without permitting lockout for IDN-3."""
    if not isinstance(input_value, SetUserRoleInput) or not isinstance(
        state, AdminTargetState
    ):
        raise TypeError("Invalid set_user_role decision input")
    if not state.target_exists:
        return _missing_user()
    changed = state.target_role != input_value.role.value
    if changed and input_value.role is Role.STUDENT:
        rejection = _admin_removal_rejection(
            target_id=input_value.user_id, state=state, actor=actor
        )
        if rejection is not None:
            return rejection
    operations = (
        [
            StateOp(
                op="update",
                model="users",
                values={"role": input_value.role.value},
                where={"id": input_value.user_id},
            )
        ]
        if changed
        else []
    )
    return Plan(
        state_ops=operations,
        events=[],
        deferred=[],
        audit={
            "subject_type": "user",
            "subject_id": input_value.user_id,
            "details": {"from_role": state.target_role, "to_role": input_value.role.value},
        }
        if changed
        else None,
        summary={"changed": changed, "role": input_value.role.value},
    )


def _decide_deactivate(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """Deactivate a user and revoke every active session for IDN-1/3."""
    if not isinstance(input_value, DeactivateUserInput) or not isinstance(
        state, AdminTargetState
    ):
        raise TypeError("Invalid deactivate_user decision input")
    if not state.target_exists:
        return _missing_user()
    if not state.target_active:
        return Plan(
            state_ops=[], events=[], deferred=[], audit=None,
            summary={"changed": False, "revoked_sessions": 0},
        )
    rejection = _admin_removal_rejection(
        target_id=input_value.user_id, state=state, actor=actor
    )
    if rejection is not None:
        return rejection
    operations = [
        StateOp(
            op="update",
            model="users",
            values={"is_active": False},
            where={"id": input_value.user_id},
        )
    ]
    operations.extend(
        StateOp(
            op="update",
            model="sessions",
            values={"revoked_at": state.now},
            where={"id": session_id},
        )
        for session_id in state.active_session_ids
    )
    return Plan(
        state_ops=operations,
        events=[],
        deferred=[],
        audit={
            "subject_type": "user",
            "subject_id": input_value.user_id,
            "details": {"revoked_sessions": len(state.active_session_ids)},
        },
        summary={"changed": True, "revoked_sessions": len(state.active_session_ids)},
    )


def register_identity_admin_commands(registry: Registry) -> None:
    registry.command(
        name="logout", input_model=LogoutInput, output_model=LogoutSummary,
        actor="authenticated", scope="none", loader=_load_logout,
        rule_domains=(), spec_ids=("IDN-1",), session_effect="clear",
    )(_decide_logout)
    registry.command(
        name="start_new_enrollment", input_model=StartNewEnrollmentInput,
        output_model=StartNewEnrollmentSummary, actor="admin", scope="none",
        loader=_load_enrollment, rule_domains=(), spec_ids=("IDN-2",),
    )(_decide_enrollment)
    registry.command(
        name="set_user_role", input_model=SetUserRoleInput,
        output_model=SetUserRoleSummary, actor="admin", scope="none",
        loader=_load_role, rule_domains=(), spec_ids=("IDN-3",),
    )(_decide_role)
    registry.command(
        name="deactivate_user", input_model=DeactivateUserInput,
        output_model=DeactivateUserSummary, actor="admin", scope="none",
        loader=_load_deactivate, rule_domains=(), spec_ids=("IDN-1", "IDN-3"),
    )(_decide_deactivate)
