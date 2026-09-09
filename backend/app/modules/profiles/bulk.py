"""Admin bulk upsert of profiles from a spreadsheet (Behavior PRO-2).

Match key is the institute email, resolved to the user and applied to that
user's *current* enrollment.  Rows for unknown addresses are staged and applied
at that user's next sign-in (``staged.py``).  Each changed row writes its own
``audit_log`` entry so the batch stays reconstructable per student.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    DUPLICATE_ROW,
    ENROLLMENT_NOT_FOUND,
    INVALID_FIELD_VALUE,
    ROLL_MISMATCH,
    ROLL_NUMBER_TAKEN,
    UNKNOWN_TAXONOMY_VALUE,
)
from app.core.plan import ActorContext, Plan, Rejection, ScopeIds, StateOp
from app.core.registry import Registry
from app.modules.profiles.commands import program_branch_reasons
from app.modules.profiles.fields import (
    BULK_FIELDS,
    BULK_INITIAL_ONLY_FIELDS,
    EMAIL_PATTERN,
    FIELDS_BY_KEY,
    PROFILE_COLUMNS,
    TAXONOMY_FIELDS,
    FieldValueError,
    coerce_field,
    jsonable,
)

ROW_AUDIT_ACTION = "bulk_upsert_profiles.row"


class BulkProfileRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_number: int
    institute_email: str
    fields: dict[str, object] = {}


class BulkUpsertProfilesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[BulkProfileRow]
    batch_key: str


class BulkUpsertProfilesSummary(BaseModel):
    rows: list[dict[str, object]]


@dataclass(frozen=True, slots=True)
class TargetRecord:
    user_id: UUID
    full_name: str
    enrollment_id: UUID | None
    roll_number: str | None
    profile_exists: bool
    values: dict[str, object]


@dataclass(frozen=True, slots=True)
class BulkState:
    scope_ids: ScopeIds
    now: datetime
    targets: dict[str, TargetRecord]
    staged_fingerprints: dict[str, set[str]]
    names: dict[str, dict[str, UUID]] = field(default_factory=dict)
    known_ids: frozenset[UUID] = frozenset()
    active_ids: frozenset[UUID] = frozenset()
    program_branch_pairs: frozenset[tuple[UUID, UUID]] = frozenset()
    roll_conflicts: frozenset[str] = frozenset()


def _normalize_email(value: str) -> str:
    return value.strip().casefold()


def _fingerprint(values: dict[str, object]) -> str:
    return "|".join(f"{key}={values[key]!r}" for key in sorted(values))


async def _load_bulk(tx: AsyncSession, input_value: BaseModel, *, lock: bool) -> BulkState:
    if not isinstance(input_value, BulkUpsertProfilesInput):
        raise TypeError("bulk_upsert_profiles requires BulkUpsertProfilesInput")
    now = datetime.now(UTC)
    emails = sorted({_normalize_email(row.institute_email) for row in input_value.rows})
    rolls = sorted(
        {
            str(row.fields["roll_number"]).strip()
            for row in input_value.rows
            if isinstance(row.fields.get("roll_number"), str)
            and str(row.fields["roll_number"]).strip()
        }
    )
    if lock:
        for key in [f"email:{email}" for email in emails] + [
            f"roll:{roll.casefold()}" for roll in rolls
        ]:
            await tx.execute(
                sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": key},
            )

    user_rows = (
        await tx.execute(
            sa.text(
                "SELECT id, email, full_name FROM users "
                "WHERE email = ANY(CAST(:emails AS citext[])) ORDER BY id"
                + (" FOR UPDATE" if lock else "")
            ),
            {"emails": emails},
        )
    ).mappings().all()
    user_ids = [row["id"] for row in user_rows]
    enrollment_rows = (
        (
            await tx.execute(
                sa.text(
                    "SELECT id, user_id, roll_number FROM enrollments "
                    "WHERE user_id = ANY(CAST(:user_ids AS uuid[])) AND is_current "
                    "ORDER BY id" + (" FOR UPDATE" if lock else "")
                ),
                {"user_ids": user_ids},
            )
        ).mappings().all()
        if user_ids
        else []
    )
    enrollment_by_user = {row["user_id"]: row for row in enrollment_rows}
    enrollment_ids = [row["id"] for row in enrollment_rows]
    profile_rows = (
        (
            await tx.execute(
                sa.text(
                    "SELECT enrollment_id, " + ", ".join(PROFILE_COLUMNS) + " FROM profiles "
                    "WHERE enrollment_id = ANY(CAST(:ids AS uuid[])) ORDER BY enrollment_id"
                    + (" FOR UPDATE" if lock else "")
                ),
                {"ids": enrollment_ids},
            )
        ).mappings().all()
        if enrollment_ids
        else []
    )
    profile_by_enrollment = {row["enrollment_id"]: row for row in profile_rows}

    targets: dict[str, TargetRecord] = {}
    for row in user_rows:
        enrollment = enrollment_by_user.get(row["id"])
        enrollment_id = enrollment["id"] if enrollment is not None else None
        profile = profile_by_enrollment.get(enrollment_id) if enrollment_id else None
        values: dict[str, object] = {column: None for column in PROFILE_COLUMNS}
        if profile is not None:
            values.update({column: profile[column] for column in PROFILE_COLUMNS})
        targets[_normalize_email(str(row["email"]))] = TargetRecord(
            user_id=row["id"],
            full_name=str(row["full_name"]),
            enrollment_id=enrollment_id,
            roll_number=enrollment["roll_number"] if enrollment is not None else None,
            profile_exists=profile is not None,
            values=values,
        )

    staged_rows = (
        await tx.execute(
            sa.text(
                "SELECT institute_email, payload FROM staged_profile_rows "
                "WHERE institute_email = ANY(CAST(:emails AS citext[])) "
                "AND applied_at IS NULL AND error IS NULL"
            ),
            {"emails": emails},
        )
    ).mappings().all()
    staged_fingerprints: dict[str, set[str]] = {}
    for row in staged_rows:
        payload = cast(dict[str, object], row["payload"] or {})
        stored_fields = payload.get("fields")
        stored = cast(dict[str, object], stored_fields) if isinstance(stored_fields, dict) else {}
        staged_fingerprints.setdefault(
            _normalize_email(str(row["institute_email"])), set()
        ).add(_fingerprint(stored))

    names: dict[str, dict[str, UUID]] = {}
    known: set[UUID] = set()
    active: set[UUID] = set()
    for table in ("programs", "branches", "minors"):
        rows = (
            await tx.execute(
                sa.text(f"SELECT id, name, is_active FROM {table} ORDER BY name")  # noqa: S608
            )
        ).mappings().all()
        mapping: dict[str, UUID] = {}
        for row in rows:
            known.add(row["id"])
            if row["is_active"]:
                active.add(row["id"])
                mapping[str(row["name"]).strip().casefold()] = row["id"]
        names[table] = mapping
    pair_rows = (
        await tx.execute(sa.text("SELECT program_id, branch_id FROM program_branches"))
    ).mappings().all()

    roll_conflicts: set[str] = set()
    if rolls:
        conflict_rows = (
            await tx.execute(
                sa.text(
                    "SELECT roll_number FROM enrollments "
                    "WHERE is_current AND roll_number = ANY(CAST(:rolls AS citext[]))"
                ),
                {"rolls": rolls},
            )
        ).scalars()
        roll_conflicts = {str(value).casefold() for value in conflict_rows}

    return BulkState(
        scope_ids=ScopeIds(),
        now=now,
        targets=targets,
        staged_fingerprints=staged_fingerprints,
        names=names,
        known_ids=frozenset(known),
        active_ids=frozenset(active),
        program_branch_pairs=frozenset(
            (row["program_id"], row["branch_id"]) for row in pair_rows
        ),
        roll_conflicts=frozenset(roll_conflicts),
    )


def _reason(code: str, human: str, path: str | None = None) -> dict[str, object]:
    return {"code": code, "human": human, "path": path}


def resolve_row_fields(
    fields: dict[str, object], state: BulkState
) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    """Resolve taxonomy names to ids and validate values for one row (pure)."""
    reasons: list[dict[str, object]] = []
    raw: dict[str, object] = {}
    resolved: dict[str, object] = {}
    for key, value in fields.items():
        raw[key] = jsonable(value)
        if key not in BULK_FIELDS:
            label = FIELDS_BY_KEY[key].label if key in FIELDS_BY_KEY else key
            reasons.append(
                _reason(
                    "field_not_editable",
                    f"{label} is not an admin-managed field",
                    key,
                )
            )
            continue
        candidate = value
        if key in TAXONOMY_FIELDS and isinstance(value, str) and value.strip():
            text = value.strip()
            table = TAXONOMY_FIELDS[key]
            try:
                identifier = UUID(text)
            except ValueError:
                identifier = state.names[table].get(text.casefold())
                if identifier is None:
                    reasons.append(
                        _reason(
                            UNKNOWN_TAXONOMY_VALUE,
                            f"{FIELDS_BY_KEY[key].label} '{text}' is not an active option",
                            key,
                        )
                    )
                    continue
            candidate = identifier
        try:
            resolved[key] = coerce_field(key, candidate)
        except FieldValueError as error:
            reasons.append(_reason(INVALID_FIELD_VALUE, error.human, error.key))
            continue
        identifier = resolved[key]
        if key in TAXONOMY_FIELDS and isinstance(identifier, UUID):
            if identifier not in state.known_ids:
                reasons.append(
                    _reason(
                        UNKNOWN_TAXONOMY_VALUE,
                        f"{FIELDS_BY_KEY[key].label} does not exist",
                        key,
                    )
                )
            elif identifier not in state.active_ids:
                reasons.append(
                    _reason(
                        UNKNOWN_TAXONOMY_VALUE,
                        f"{FIELDS_BY_KEY[key].label} is no longer active",
                        key,
                    )
                )
    return resolved, raw, reasons


def _pair_reasons(
    effective: dict[str, object], pairs: frozenset[tuple[UUID, UUID]]
) -> list[dict[str, object]]:
    return [
        _reason(reason.code, reason.human, reason.path)
        for reason in program_branch_reasons(effective, pairs)
    ]


def _decide_bulk(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """Apply, stage, or reject each spreadsheet row per Behavior PRO-2."""
    if not isinstance(input_value, BulkUpsertProfilesInput) or not isinstance(state, BulkState):
        raise TypeError("Invalid bulk_upsert_profiles decision input")

    counts: dict[str, int] = {}
    for row in input_value.rows:
        key = _normalize_email(row.institute_email)
        counts[key] = counts.get(key, 0) + 1

    operations: list[StateOp] = []
    results: list[dict[str, object]] = []
    for row in input_value.rows:
        email = _normalize_email(row.institute_email)
        result: dict[str, object] = {
            "row_number": row.row_number,
            "institute_email": email,
            "result": "error",
            "changed_fields": [],
            "reasons": [],
        }
        reasons: list[dict[str, object]] = []
        if not EMAIL_PATTERN.match(email):
            reasons.append(
                _reason(INVALID_FIELD_VALUE, "Not a valid email address", "institute_email")
            )
        elif counts[email] > 1:
            reasons.append(
                _reason(DUPLICATE_ROW, "This address appears more than once", "institute_email")
            )
        if reasons:
            result["reasons"] = reasons
            results.append(result)
            continue

        resolved, raw, reasons = resolve_row_fields(row.fields, state)
        target = state.targets.get(email)
        if target is None:
            if reasons:
                result["reasons"] = reasons
                results.append(result)
                continue
            if _fingerprint({key: jsonable(value) for key, value in resolved.items()}) in (
                state.staged_fingerprints.get(email, set())
            ):
                result["result"] = "unchanged"
                results.append(result)
                continue
            operations.append(
                StateOp(
                    op="insert",
                    model="staged_profile_rows",
                    values={
                        "institute_email": email,
                        "uploaded_by": actor.user_id,
                        "payload": {
                            "fields": {
                                key: jsonable(value) for key, value in resolved.items()
                            },
                            "raw": raw,
                            "batch_key": input_value.batch_key,
                            "row_number": row.row_number,
                        },
                    },
                )
            )
            result["result"] = "staged"
            result["changed_fields"] = sorted(resolved)
            results.append(result)
            continue

        if target.enrollment_id is None:
            reasons.append(
                _reason(ENROLLMENT_NOT_FOUND, "The user has no current enrollment", None)
            )

        adopt_roll = False
        if "roll_number" in resolved:
            provided = resolved["roll_number"]
            provided_text = str(provided) if provided is not None else None
            if target.roll_number is None:
                if provided_text is not None:
                    if provided_text.casefold() in state.roll_conflicts:
                        reasons.append(
                            _reason(
                                ROLL_NUMBER_TAKEN,
                                "Another current enrollment already uses this roll number",
                                "roll_number",
                            )
                        )
                    else:
                        adopt_roll = True
            elif (
                provided_text is None
                or provided_text.casefold() != target.roll_number.casefold()
            ):
                # PRO-2 cross-check: a stale file can never write onto a newer enrollment.
                reasons.append(
                    _reason(
                        ROLL_MISMATCH,
                        "The roll number does not match this student's current enrollment",
                        "roll_number",
                    )
                )

        effective = dict(target.values)
        for key in BULK_INITIAL_ONLY_FIELDS:
            incoming = resolved.get(key)
            existing = target.values.get(key)
            if key in resolved and existing not in (None, "") and incoming != existing:
                reasons.append(_reason(
                    INVALID_FIELD_VALUE,
                    f"{FIELDS_BY_KEY[key].label} was already set and was not overwritten",
                    key,
                ))
        effective.update({key: value for key, value in resolved.items() if key in PROFILE_COLUMNS})
        reasons.extend(_pair_reasons(effective, state.program_branch_pairs))
        if reasons:
            result["reasons"] = reasons
            results.append(result)
            continue

        before: dict[str, object] = {}
        after: dict[str, object] = {}
        profile_changes: dict[str, object] = {}
        for key, value in resolved.items():
            if key == "roll_number":
                if not adopt_roll:
                    continue
                before[key] = jsonable(target.roll_number)
                after[key] = jsonable(value)
                continue
            if key == "full_name":
                if value == target.full_name:
                    continue
                before[key] = target.full_name
                after[key] = jsonable(value)
                continue
            if target.values.get(key) == value:
                continue
            profile_changes[key] = value
            before[key] = jsonable(target.values.get(key))
            after[key] = jsonable(value)

        if not before:
            result["result"] = "unchanged"
            results.append(result)
            continue

        if profile_changes:
            if target.profile_exists:
                operations.append(
                    StateOp(
                        op="update",
                        model="profiles",
                        values=dict(profile_changes),
                        where={"enrollment_id": target.enrollment_id},
                    )
                )
            else:
                operations.append(
                    StateOp(
                        op="insert",
                        model="profiles",
                        values={"enrollment_id": target.enrollment_id, **profile_changes},
                    )
                )
        if adopt_roll:
            operations.append(
                StateOp(
                    op="update",
                    model="enrollments",
                    values={"roll_number": resolved["roll_number"]},
                    where={"id": target.enrollment_id},
                )
            )
        if "full_name" in after:
            operations.append(
                StateOp(
                    op="update",
                    model="users",
                    values={"full_name": resolved["full_name"]},
                    where={"id": target.user_id},
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
                    "subject_id": target.enrollment_id,
                    "details": {
                        "batch_key": input_value.batch_key,
                        "row_number": row.row_number,
                        "institute_email": email,
                        "before": before,
                        "after": after,
                    },
                },
            )
        )
        result["result"] = "updated"
        result["changed_fields"] = sorted(after)
        results.append(result)

    return Plan(
        state_ops=operations,
        events=[],
        deferred=[],
        audit=None,
        summary={"rows": results},
    )


def register_bulk_commands(registry: Registry) -> None:
    registry.command(
        name="bulk_upsert_profiles",
        input_model=BulkUpsertProfilesInput,
        output_model=BulkUpsertProfilesSummary,
        actor="admin",
        scope="none",
        loader=_load_bulk,
        rule_domains=(),
        spec_ids=("PRO-2",),
        rate_limit="10/min",
        execution_mode="bulk",
    )(_decide_bulk)
