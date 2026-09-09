"""Staged bulk rows applied at the arriving student's sign-in (Behavior PRO-2).

A staged row is terminal once it has been applied (``applied_at``) or has failed
validation (``error``): a permanently invalid row must never retry on every
future login (the design review 4.15 ruling 9).  Rows for one address apply in
``created_at`` order, later values overwriting earlier ones (the design review 4.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    STAGED_ROW_ALREADY_APPLIED,
    STAGED_ROW_NOT_FOUND,
)
from app.core.plan import ActorContext, Plan, Reason, Rejection, ScopeIds, StateOp
from app.core.registry import Registry
from app.modules.identity.commands import (
    LoginInput,
    LoginState,
    PostLoginHooks,
    post_login_hooks,
)
from app.modules.profiles.commands import program_branch_reasons
from app.modules.profiles.fields import (
    BULK_FIELDS,
    FIELDS_BY_KEY,
    PROFILE_COLUMNS,
    TAXONOMY_FIELDS,
    FieldValueError,
    coerce_field,
    jsonable,
)

HOOK_NAME = "staged_profile_rows"
ROW_AUDIT_ACTION = "staged_profile_row.applied"


@dataclass(frozen=True, slots=True)
class StagedRow:
    id: UUID
    fields: dict[str, object]
    uploaded_by: UUID | None
    batch_key: str | None


@dataclass(frozen=True, slots=True)
class StagedLoginState:
    now: datetime
    email: str
    rows: tuple[StagedRow, ...]
    user_exists: bool
    user_id: UUID | None
    full_name: str | None
    enrollment_id: UUID | None
    roll_number: str | None
    profile_exists: bool
    values: dict[str, object]
    known_ids: frozenset[UUID]
    active_ids: frozenset[UUID]
    program_branch_pairs: frozenset[tuple[UUID, UUID]]
    roll_conflicts: frozenset[str]


async def load_staged_rows(
    tx: AsyncSession, email: str, *, lock: bool
) -> StagedLoginState:
    """Load pending staged rows and the profile they would land on."""
    now = datetime.now(UTC)
    lock_clause = " FOR UPDATE" if lock else ""
    staged = (
        await tx.execute(
            sa.text(
                "SELECT id, payload, uploaded_by FROM staged_profile_rows "
                "WHERE institute_email = :email AND applied_at IS NULL AND error IS NULL "
                "ORDER BY created_at, id" + lock_clause
            ),
            {"email": email},
        )
    ).mappings().all()
    rows: list[StagedRow] = []
    for row in staged:
        payload = cast(dict[str, object], row["payload"] or {})
        stored = payload.get("fields")
        batch_key = payload.get("batch_key")
        rows.append(
            StagedRow(
                id=row["id"],
                fields=cast(dict[str, object], stored) if isinstance(stored, dict) else {},
                uploaded_by=row["uploaded_by"],
                batch_key=str(batch_key) if isinstance(batch_key, str) else None,
            )
        )

    user = (
        await tx.execute(
            sa.text("SELECT id, full_name FROM users WHERE email = :email"),
            {"email": email},
        )
    ).mappings().one_or_none()
    enrollment = None
    profile = None
    if user is not None:
        enrollment = (
            await tx.execute(
                sa.text(
                    "SELECT id, roll_number FROM enrollments "
                    "WHERE user_id = :user_id AND is_current" + lock_clause
                ),
                {"user_id": user["id"]},
            )
        ).mappings().one_or_none()
        if enrollment is not None:
            profile = (
                await tx.execute(
                    sa.text(
                        "SELECT " + ", ".join(PROFILE_COLUMNS) + " FROM profiles "
                        "WHERE enrollment_id = :enrollment_id" + lock_clause
                    ),
                    {"enrollment_id": enrollment["id"]},
                )
            ).mappings().one_or_none()

    values: dict[str, object] = {column: None for column in PROFILE_COLUMNS}
    if profile is not None:
        values.update({column: profile[column] for column in PROFILE_COLUMNS})

    known: set[UUID] = set()
    active: set[UUID] = set()
    pairs: set[tuple[UUID, UUID]] = set()
    roll_conflicts: set[str] = set()
    if rows:
        for table in ("programs", "branches", "minors"):
            taxonomy = (
                await tx.execute(
                    sa.text(f"SELECT id, is_active FROM {table}")  # noqa: S608
                )
            ).mappings().all()
            for item in taxonomy:
                known.add(item["id"])
                if item["is_active"]:
                    active.add(item["id"])
        pair_rows = (
            await tx.execute(sa.text("SELECT program_id, branch_id FROM program_branches"))
        ).mappings().all()
        pairs = {(item["program_id"], item["branch_id"]) for item in pair_rows}

        candidate_rolls = sorted(
            {
                str(row.fields["roll_number"]).strip()
                for row in rows
                if isinstance(row.fields.get("roll_number"), str)
                and str(row.fields["roll_number"]).strip()
            }
        )
        if candidate_rolls:
            if lock:
                for roll in candidate_rolls:
                    await tx.execute(
                        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                        {"key": f"roll:{roll.casefold()}"},
                    )
            conflicts = (
                await tx.execute(
                    sa.text(
                        "SELECT roll_number FROM enrollments WHERE is_current "
                        "AND roll_number = ANY(CAST(:rolls AS citext[])) "
                        "AND (CAST(:enrollment_id AS uuid) IS NULL "
                        "OR id <> CAST(:enrollment_id AS uuid))"
                    ),
                    {
                        "rolls": candidate_rolls,
                        "enrollment_id": enrollment["id"] if enrollment is not None else None,
                    },
                )
            ).scalars()
            roll_conflicts = {str(value).casefold() for value in conflicts}

    return StagedLoginState(
        now=now,
        email=email,
        rows=tuple(rows),
        user_exists=user is not None,
        user_id=user["id"] if user is not None else None,
        full_name=str(user["full_name"]) if user is not None else None,
        enrollment_id=enrollment["id"] if enrollment is not None else None,
        roll_number=enrollment["roll_number"] if enrollment is not None else None,
        profile_exists=profile is not None,
        values=values,
        known_ids=frozenset(known),
        active_ids=frozenset(active),
        program_branch_pairs=frozenset(pairs),
        roll_conflicts=frozenset(roll_conflicts),
    )


def _row_problems(
    row: StagedRow,
    state: StagedLoginState,
    effective: dict[str, object],
    roll_number: str | None,
) -> tuple[dict[str, object], str | None, str | None]:
    """Validate one staged row against the running effective profile (pure)."""
    problems: list[str] = []
    resolved: dict[str, object] = {}
    for key, value in row.fields.items():
        if key not in BULK_FIELDS:
            problems.append(f"{key} is not an admin-managed field")
            continue
        try:
            resolved[key] = coerce_field(key, value)
        except FieldValueError as error:
            problems.append(error.human)
    for key in TAXONOMY_FIELDS:
        identifier = resolved.get(key)
        if isinstance(identifier, UUID) and identifier not in state.active_ids:
            problems.append(
                f"{FIELDS_BY_KEY[key].label} is no longer available"
                if identifier in state.known_ids
                else f"{FIELDS_BY_KEY[key].label} does not exist"
            )

    next_roll = roll_number
    provided = resolved.get("roll_number")
    provided_text = str(provided).strip() if isinstance(provided, str) and provided else None
    if "roll_number" in resolved:
        if roll_number is None:
            if provided_text is None:
                problems.append("The roll number is blank")
            elif provided_text.casefold() in state.roll_conflicts:
                problems.append(
                    "Another current enrollment already uses this roll number"
                )
            else:
                next_roll = provided_text
        elif provided_text is None or provided_text.casefold() != roll_number.casefold():
            problems.append(
                "The roll number does not match this student's current enrollment"
            )

    merged = dict(effective)
    merged.update({key: value for key, value in resolved.items() if key in PROFILE_COLUMNS})
    problems.extend(
        reason.human
        for reason in program_branch_reasons(merged, state.program_branch_pairs)
    )
    if problems:
        return {}, "; ".join(problems), roll_number
    return resolved, None, next_roll


def plan_staged_rows(
    input_value: LoginInput, state: LoginState, actor: ActorContext
) -> list[StateOp]:
    """Apply this address's staged rows inside the login transaction (PRO-2)."""
    staged = state.hook(HOOK_NAME)
    if not isinstance(staged, StagedLoginState) or not staged.rows:
        return []

    enrollment_id = staged.enrollment_id
    if enrollment_id is None:
        if staged.user_exists:
            # An existing user without a current enrollment has nowhere to land.
            return [
                StateOp(
                    op="update",
                    model="staged_profile_rows",
                    values={"error": "The user has no current enrollment"},
                    where={"id": row.id},
                )
                for row in staged.rows
            ]
        enrollment_id = input_value._new_enrollment_id

    operations: list[StateOp] = []
    effective = dict(staged.values)
    roll_number = staged.roll_number
    full_name = staged.full_name if staged.user_exists else input_value._full_name
    applied_profile: dict[str, object] = {}
    applied_roll: str | None = None
    applied_full_name: str | None = None

    for row in staged.rows:
        resolved, error, next_roll = _row_problems(row, staged, effective, roll_number)
        if error is not None:
            operations.append(
                StateOp(
                    op="update",
                    model="staged_profile_rows",
                    values={"error": error},
                    where={"id": row.id},
                )
            )
            continue
        before: dict[str, object] = {}
        after: dict[str, object] = {}
        for key, value in resolved.items():
            if key == "roll_number":
                if next_roll == roll_number:
                    continue
                before[key] = jsonable(roll_number)
                after[key] = jsonable(next_roll)
                applied_roll = next_roll
                roll_number = next_roll
                continue
            if key == "full_name":
                if value == full_name:
                    continue
                before[key] = full_name
                after[key] = jsonable(value)
                applied_full_name = cast(str, value)
                full_name = cast(str, value)
                continue
            if effective.get(key) == value:
                continue
            before[key] = jsonable(effective.get(key))
            after[key] = jsonable(value)
            effective[key] = value
            applied_profile[key] = value
        operations.append(
            StateOp(
                op="update",
                model="staged_profile_rows",
                values={"applied_at": staged.now},
                where={"id": row.id},
            )
        )
        operations.append(
            StateOp(
                op="insert",
                model="audit_log",
                values={
                    "actor_user_id": actor.user_id,
                    "action": ROW_AUDIT_ACTION,
                    "subject_type": "enrollment",
                    "subject_id": enrollment_id,
                    "details": {
                        "institute_email": staged.email,
                        "staged_row_id": str(row.id),
                        "batch_key": row.batch_key,
                        "uploaded_by": str(row.uploaded_by) if row.uploaded_by else None,
                        "before": before,
                        "after": after,
                    },
                },
            )
        )

    if applied_profile:
        if staged.profile_exists:
            operations.append(
                StateOp(
                    op="update",
                    model="profiles",
                    values=dict(applied_profile),
                    where={"enrollment_id": enrollment_id},
                )
            )
        else:
            operations.append(
                StateOp(
                    op="insert",
                    model="profiles",
                    values={"enrollment_id": enrollment_id, **applied_profile},
                )
            )
    if applied_roll is not None:
        operations.append(
            StateOp(
                op="update",
                model="enrollments",
                values={"roll_number": applied_roll},
                where={"id": enrollment_id},
            )
        )
    if applied_full_name is not None:
        operations.append(
            StateOp(
                op="update",
                model="users",
                values={"full_name": applied_full_name},
                where={"id": staged.user_id or input_value._new_user_id},
            )
        )
    return operations


def register_staged_login_hook(hooks: PostLoginHooks | None = None) -> None:
    (hooks or post_login_hooks).register(
        plan_staged_rows, name=HOOK_NAME, loader=load_staged_rows
    )


class DeleteStagedRowInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    staged_row_id: UUID


class DeleteStagedRowSummary(BaseModel):
    staged_row_id: UUID
    institute_email: str


@dataclass(frozen=True, slots=True)
class StagedRowState:
    scope_ids: ScopeIds
    exists: bool
    institute_email: str | None
    applied_at: datetime | None


async def _load_staged_row(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> StagedRowState:
    if not isinstance(input_value, DeleteStagedRowInput):
        raise TypeError("delete_staged_row requires DeleteStagedRowInput")
    row = (
        await tx.execute(
            sa.text(
                "SELECT institute_email, applied_at FROM staged_profile_rows "
                "WHERE id = :id" + (" FOR UPDATE" if lock else "")
            ),
            {"id": input_value.staged_row_id},
        )
    ).mappings().one_or_none()
    return StagedRowState(
        scope_ids=ScopeIds(),
        exists=row is not None,
        institute_email=str(row["institute_email"]) if row is not None else None,
        applied_at=row["applied_at"] if row is not None else None,
    )


def _decide_delete_staged_row(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Remove a pending or errored staged row; applied history stays (PRO-2)."""
    if not isinstance(input_value, DeleteStagedRowInput) or not isinstance(
        state, StagedRowState
    ):
        raise TypeError("Invalid delete_staged_row decision input")
    if not state.exists:
        return Rejection(
            reasons=[
                Reason(
                    code=STAGED_ROW_NOT_FOUND,
                    human="The staged row does not exist",
                    path="staged_row_id",
                )
            ]
        )
    if state.applied_at is not None:
        return Rejection(
            reasons=[
                Reason(
                    code=STAGED_ROW_ALREADY_APPLIED,
                    human="Applied staged rows are kept as history",
                    path="staged_row_id",
                )
            ]
        )
    return Plan(
        state_ops=[
            StateOp(
                op="delete",
                model="staged_profile_rows",
                values={},
                where={"id": input_value.staged_row_id},
            )
        ],
        events=[],
        deferred=[],
        audit={
            "subject_type": "staged_profile_row",
            "subject_id": input_value.staged_row_id,
            "details": {"institute_email": state.institute_email},
        },
        summary={
            "staged_row_id": str(input_value.staged_row_id),
            "institute_email": state.institute_email,
        },
    )


def register_staged_commands(registry: Registry) -> None:
    registry.command(
        name="delete_staged_row",
        input_model=DeleteStagedRowInput,
        output_model=DeleteStagedRowSummary,
        actor="admin",
        scope="none",
        loader=_load_staged_row,
        rule_domains=(),
        spec_ids=("PRO-2",),
    )(_decide_delete_staged_row)
