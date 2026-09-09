"""Audited taxonomy and global-setting commands for Behavior TAX."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    INVALID_REQUEST,
    TAXONOMY_ITEM_NOT_FOUND,
    TAXONOMY_NAME_CONFLICT,
)
from app.core.plan import ActorContext, Plan, Reason, Rejection, ScopeIds, StateOp
from app.core.registry import Registry


class TaxonomyKind(StrEnum):
    PROGRAM = "programs"
    BRANCH = "branches"
    MINOR = "minors"
    SECTOR = "sectors"
    ROUND_TYPE = "round_types"


class SettingKey(StrEnum):
    STRIKES_PER_PENALTY = "strikes_per_penalty"
    SESSION_HOURS = "session_hours"
    SES_SENDER = "ses_sender"


class UpsertTaxonomyItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: TaxonomyKind
    item_id: UUID | None = None
    name: str | None = None
    is_active: bool = True
    action: Literal["upsert", "delete"] = "upsert"
    branch_ids: list[UUID] | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized

    @field_validator("branch_ids")
    @classmethod
    def unique_branch_ids(cls, value: list[UUID] | None) -> list[UUID] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("branch_ids must not contain duplicates")
        return value

    @model_validator(mode="after")
    def validate_action_shape(self) -> UpsertTaxonomyItemInput:
        if self.action == "delete":
            if self.item_id is None:
                raise ValueError("item_id is required when deleting")
            if self.name is not None or self.branch_ids is not None:
                raise ValueError("delete accepts only kind and item_id")
        elif self.item_id is None and self.name is None:
            raise ValueError("name is required when creating an item")
        if self.branch_ids is not None and self.kind is not TaxonomyKind.PROGRAM:
            raise ValueError("branch_ids is valid only for programs")
        return self


class UpsertTaxonomyItemSummary(BaseModel):
    item_id: UUID
    kind: TaxonomyKind
    action: Literal["created", "updated", "deleted", "deactivated", "unchanged"]
    is_active: bool | None
    branch_ids: list[UUID] | None = None


class SetSettingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: SettingKey
    value: object

    @model_validator(mode="after")
    def validate_typed_value(self) -> SetSettingInput:
        value = self.value
        if self.key is SettingKey.STRIKES_PER_PENALTY:
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 1
            ):
                raise ValueError("strikes_per_penalty must be at least 1 or null")
        elif self.key is SettingKey.SESSION_HOURS:
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError("session_hours must be a positive integer")
        elif not isinstance(value, str):
            raise ValueError("ses_sender must be a string")
        return self


class SetSettingSummary(BaseModel):
    key: SettingKey
    value: object
    changed: bool


@dataclass(frozen=True, slots=True)
class TaxonomyState:
    scope_ids: ScopeIds
    item_id: UUID
    existing_name: str | None
    existing_active: bool | None
    name_conflict: bool
    reference_count: int
    existing_branch_ids: tuple[UUID, ...]
    requested_branch_ids: tuple[UUID, ...] | None
    missing_branch_ids: tuple[UUID, ...]
    inactive_branch_ids: tuple[UUID, ...]
    new_map_ids: tuple[tuple[UUID, UUID], ...]


@dataclass(frozen=True, slots=True)
class SettingState:
    scope_ids: ScopeIds
    exists: bool
    value: object


_REFERENCE_QUERIES: dict[TaxonomyKind, str] = {
    TaxonomyKind.PROGRAM: """
        SELECT
            (SELECT count(*) FROM profiles
             WHERE program_id = :item_id OR secondary_program_id = :item_id) +
            (SELECT count(*) FROM job_program_ctc WHERE program_id = :item_id) +
            (SELECT count(*) FROM program_branches WHERE program_id = :item_id)
    """,
    TaxonomyKind.BRANCH: """
        SELECT
            (SELECT count(*) FROM profiles
             WHERE primary_branch_id = :item_id OR secondary_branch_id = :item_id) +
            (SELECT count(*) FROM program_branches WHERE branch_id = :item_id)
    """,
    TaxonomyKind.MINOR: """
        SELECT count(*) FROM profiles
        WHERE minor1_id = :item_id OR minor2_id = :item_id
    """,
    TaxonomyKind.SECTOR: """
        SELECT
            (SELECT count(*) FROM companies WHERE sector_id = :item_id) +
            (SELECT count(*) FROM jobs WHERE sector_id = :item_id)
    """,
    TaxonomyKind.ROUND_TYPE: """
        SELECT count(*) FROM job_rounds WHERE round_type_id = :item_id
    """,
}


async def _load_taxonomy(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> TaxonomyState:
    if not isinstance(input_value, UpsertTaxonomyItemInput):
        raise TypeError("upsert_taxonomy_item requires UpsertTaxonomyItemInput")
    table_name = input_value.kind.value
    if lock:
        lock_key = f"taxonomy:{table_name}:{input_value.item_id or input_value.name}"
        await tx.execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": lock_key},
        )
    lock_clause = " FOR UPDATE" if lock else ""
    columns = "id, name, is_active"
    if input_value.item_id is not None:
        existing = (
            await tx.execute(
                sa.text(
                    f"SELECT {columns} FROM {table_name} "  # noqa: S608
                    "WHERE id = :item_id" + lock_clause
                ),
                {"item_id": input_value.item_id},
            )
        ).mappings().one_or_none()
    else:
        existing = (
            await tx.execute(
                sa.text(
                    f"SELECT {columns} FROM {table_name} "  # noqa: S608
                    "WHERE name = :name" + lock_clause
                ),
                {"name": input_value.name},
            )
        ).mappings().one_or_none()

    item_id = existing["id"] if existing is not None else uuid4()
    name_conflict = False
    if input_value.name is not None:
        conflict_id = await tx.scalar(
            sa.text(
                f"SELECT id FROM {table_name} "  # noqa: S608
                "WHERE name = :name AND id <> :item_id" + lock_clause
            ),
            {"name": input_value.name, "item_id": item_id},
        )
        name_conflict = conflict_id is not None

    reference_count = 0
    existing_branch_ids: tuple[UUID, ...] = ()
    if existing is not None:
        reference_count = int(
            await tx.scalar(
                sa.text(_REFERENCE_QUERIES[input_value.kind]), {"item_id": item_id}
            )
            or 0
        )
        if input_value.kind is TaxonomyKind.PROGRAM:
            existing_branch_ids = tuple(
                (
                    await tx.execute(
                        sa.text(
                            "SELECT branch_id FROM program_branches "
                            "WHERE program_id = :program_id ORDER BY branch_id"
                            + lock_clause
                        ),
                        {"program_id": item_id},
                    )
                ).scalars()
            )

    requested = (
        tuple(sorted(input_value.branch_ids))
        if input_value.branch_ids is not None
        else None
    )
    missing: tuple[UUID, ...] = ()
    inactive: tuple[UUID, ...] = ()
    new_map_ids: tuple[tuple[UUID, UUID], ...] = ()
    if requested is not None:
        branch_rows = (
            await tx.execute(
                sa.text(
                    "SELECT id, is_active FROM branches "
                    "WHERE id = ANY(CAST(:branch_ids AS uuid[])) ORDER BY id"
                    + lock_clause
                ),
                {"branch_ids": list(requested)},
            )
        ).mappings().all()
        found = {row["id"]: bool(row["is_active"]) for row in branch_rows}
        missing = tuple(branch_id for branch_id in requested if branch_id not in found)
        inactive = tuple(
            branch_id for branch_id in requested if found.get(branch_id) is False
        )
        new_map_ids = tuple(
            (branch_id, uuid4())
            for branch_id in requested
            if branch_id not in existing_branch_ids
        )

    return TaxonomyState(
        scope_ids=ScopeIds(),
        item_id=item_id,
        existing_name=str(existing["name"]) if existing is not None else None,
        existing_active=bool(existing["is_active"]) if existing is not None else None,
        name_conflict=name_conflict,
        reference_count=reference_count,
        existing_branch_ids=existing_branch_ids,
        requested_branch_ids=requested,
        missing_branch_ids=missing,
        inactive_branch_ids=inactive,
        new_map_ids=new_map_ids,
    )


async def _load_setting(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> SettingState:
    if not isinstance(input_value, SetSettingInput):
        raise TypeError("set_setting requires SetSettingInput")
    row = (
        await tx.execute(
            sa.text(
                "SELECT value FROM settings WHERE key = :key"
                + (" FOR UPDATE" if lock else "")
            ),
            {"key": input_value.key.value},
        )
    ).mappings().one_or_none()
    return SettingState(
        scope_ids=ScopeIds(),
        exists=row is not None,
        value=row["value"] if row is not None else None,
    )


def _item_snapshot(
    *,
    item_id: UUID,
    name: str,
    is_active: bool,
    branch_ids: tuple[UUID, ...] | None,
) -> dict[str, object]:
    snapshot: dict[str, object] = {
        "id": str(item_id),
        "name": name,
        "is_active": is_active,
    }
    if branch_ids is not None:
        snapshot["branch_ids"] = [str(branch_id) for branch_id in branch_ids]
    return snapshot


def _decide_taxonomy(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Create, rename, map, deactivate, or delete vocabulary per TAX."""
    if not isinstance(input_value, UpsertTaxonomyItemInput) or not isinstance(
        state, TaxonomyState
    ):
        raise TypeError("Invalid upsert_taxonomy_item decision input")
    if input_value.item_id is not None and state.existing_name is None:
        return Rejection(
            reasons=[
                Reason(
                    code=TAXONOMY_ITEM_NOT_FOUND,
                    human="The taxonomy item does not exist",
                    path="item_id",
                )
            ]
        )
    if state.name_conflict:
        return Rejection(
            reasons=[
                Reason(
                    code=TAXONOMY_NAME_CONFLICT,
                    human="A taxonomy item with this name already exists",
                    path="name",
                )
            ]
        )
    if state.missing_branch_ids or state.inactive_branch_ids:
        return Rejection(
            reasons=[
                Reason(
                    code=INVALID_REQUEST,
                    human="Program mappings require existing active branches",
                    path="branch_ids",
                )
            ]
        )

    before_branches = (
        state.existing_branch_ids
        if input_value.kind is TaxonomyKind.PROGRAM
        else None
    )
    before = (
        _item_snapshot(
            item_id=state.item_id,
            name=state.existing_name,
            is_active=bool(state.existing_active),
            branch_ids=before_branches,
        )
        if state.existing_name is not None
        else None
    )
    operations: list[StateOp] = []
    action: Literal["created", "updated", "deleted", "deactivated", "unchanged"]

    if input_value.action == "delete":
        assert state.existing_name is not None
        if state.reference_count:
            changed = state.existing_active is True
            if changed:
                operations.append(
                    StateOp(
                        op="update",
                        model=input_value.kind.value,
                        values={"is_active": False},
                        where={"id": state.item_id},
                    )
                )
            action = "deactivated" if changed else "unchanged"
            after = _item_snapshot(
                item_id=state.item_id,
                name=state.existing_name,
                is_active=False,
                branch_ids=before_branches,
            )
            active_after: bool | None = False
        else:
            changed = True
            action = "deleted"
            operations.append(
                StateOp(
                    op="delete",
                    model=input_value.kind.value,
                    values={},
                    where={"id": state.item_id},
                )
            )
            after = None
            active_after = None
        branch_ids_after = before_branches
    else:
        creating = state.existing_name is None
        name_after = input_value.name or state.existing_name
        assert name_after is not None
        active_after = input_value.is_active
        branch_ids_after = (
            state.requested_branch_ids
            if state.requested_branch_ids is not None
            else state.existing_branch_ids
        ) if input_value.kind is TaxonomyKind.PROGRAM else None
        if creating:
            values: dict[str, object] = {
                "id": state.item_id,
                "name": name_after,
                "is_active": active_after,
            }
            operations.append(
                StateOp(op="insert", model=input_value.kind.value, values=values)
            )
        elif state.existing_name != name_after or state.existing_active != active_after:
            values = {"name": name_after, "is_active": active_after}
            operations.append(
                StateOp(
                    op="update",
                    model=input_value.kind.value,
                    values=values,
                    where={"id": state.item_id},
                )
            )
        if state.requested_branch_ids is not None:
            requested_set = set(state.requested_branch_ids)
            operations.extend(
                StateOp(
                    op="delete",
                    model="program_branches",
                    values={},
                    where={"program_id": state.item_id, "branch_id": branch_id},
                )
                for branch_id in state.existing_branch_ids
                if branch_id not in requested_set
            )
            operations.extend(
                StateOp(
                    op="insert",
                    model="program_branches",
                    values={
                        "id": map_id,
                        "program_id": state.item_id,
                        "branch_id": branch_id,
                    },
                )
                for branch_id, map_id in state.new_map_ids
            )
        after = _item_snapshot(
            item_id=state.item_id,
            name=name_after,
            is_active=active_after,
            branch_ids=branch_ids_after,
        )
        changed = before != after
        action = "created" if creating else ("updated" if changed else "unchanged")

    audit = (
        {
            "subject_type": input_value.kind.value,
            "subject_id": state.item_id,
            "details": {"before": before, "after": after},
        }
        if changed
        else None
    )
    return Plan(
        state_ops=operations,
        events=[],
        deferred=[],
        audit=audit,
        summary={
            "item_id": str(state.item_id),
            "kind": input_value.kind.value,
            "action": action,
            "is_active": active_after,
            "branch_ids": (
                [str(branch_id) for branch_id in branch_ids_after]
                if branch_ids_after is not None
                else None
            ),
        },
    )


def _decide_setting(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """Validate and version one global configuration value per TAX."""
    if not isinstance(input_value, SetSettingInput) or not isinstance(
        state, SettingState
    ):
        raise TypeError("Invalid set_setting decision input")
    changed = not state.exists or state.value != input_value.value
    operation = StateOp(
        op="update" if state.exists else "insert",
        model="settings",
        values={
            **({"key": input_value.key.value} if not state.exists else {}),
            "value": input_value.value,
            "updated_by": actor.user_id,
        },
        where={"key": input_value.key.value} if state.exists else None,
    )
    before = (
        {"key": input_value.key.value, "value": state.value}
        if state.exists
        else None
    )
    after = {"key": input_value.key.value, "value": input_value.value}
    return Plan(
        state_ops=[operation] if changed else [],
        events=[],
        deferred=[],
        audit={
            "subject_type": "setting",
            "details": {"before": before, "after": after},
        }
        if changed
        else None,
        summary={
            "key": input_value.key.value,
            "value": input_value.value,
            "changed": changed,
        },
    )


def register_taxonomy_commands(registry: Registry) -> None:
    registry.command(
        name="upsert_taxonomy_item",
        input_model=UpsertTaxonomyItemInput,
        output_model=UpsertTaxonomyItemSummary,
        actor="admin",
        scope="none",
        loader=_load_taxonomy,
        rule_domains=(),
        spec_ids=("TAX",),
    )(_decide_taxonomy)
    registry.command(
        name="set_setting",
        input_model=SetSettingInput,
        output_model=SetSettingSummary,
        actor="admin",
        scope="none",
        loader=_load_setting,
        rule_domains=(),
        spec_ids=("TAX",),
    )(_decide_setting)
