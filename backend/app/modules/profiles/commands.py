"""Profile declaration, field edits, and the resume library (PRO-1, PRO-3).

Field ownership comes from ``fields.py``; every write is audited with the exact
before/after pair the specification asks for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ENROLLMENT_NOT_FOUND,
    FIELD_NOT_EDITABLE,
    INVALID_DRIVE_URL,
    INVALID_FIELD_VALUE,
    LAST_RESUME,
    PROFILE_ALREADY_DECLARED,
    PROFILE_NOT_DECLARED,
    PROGRAM_BRANCH_MISMATCH,
    RESUME_NOT_FOUND,
    ROLL_NUMBER_TAKEN,
    UNKNOWN_TAXONOMY_VALUE,
)
from app.core.plan import ActorContext, Plan, Reason, Rejection, ScopeIds, StateOp
from app.core.registry import Registry
from app.modules.profiles.fields import (
    ADMIN_FIELDS,
    DECLARABLE_FIELDS,
    FIELDS_BY_KEY,
    PROFILE_COLUMNS,
    STUDENT_FIELDS,
    TAXONOMY_FIELDS,
    UNEDITABLE_FIELDS,
    FieldValueError,
    coerce_field,
    jsonable,
    unlocked_admin_fields,
)

_DRIVE_URL_PATTERNS = (
    re.compile(
        r"^https://drive\.google\.com/file/d/[A-Za-z0-9_-]{10,}(?:/[^\s?#]*)?"
        r"(?:\?[^\s#]*)?(?:#[^\s]*)?$"
    ),
    re.compile(r"^https://drive\.google\.com/open\?id=[A-Za-z0-9_-]{10,}(?:&[^\s#]*)?$"),
    re.compile(
        r"^https://docs\.google\.com/(?:document|spreadsheets|presentation)/d/"
        r"[A-Za-z0-9_-]{10,}(?:/[^\s?#]*)?(?:\?[^\s#]*)?(?:#[^\s]*)?$"
    ),
)


def is_drive_file_url(url: str) -> bool:
    """PRO-3 shape check: a Drive or Docs *file* link, never a folder or probe."""
    return any(pattern.match(url) for pattern in _DRIVE_URL_PATTERNS)


class DeclareProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enrollment_id: UUID
    fields: dict[str, object]


class DeclareProfileSummary(BaseModel):
    enrollment_id: UUID
    declared_at: str
    applied_fields: list[str]
    retained_fields: list[str]


class UpdateStudentFieldsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enrollment_id: UUID
    fields: dict[str, object]


class UpdateProfileSummary(BaseModel):
    enrollment_id: UUID
    changed_fields: list[str]


class AdminUpdateProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enrollment_id: UUID
    fields: dict[str, object]


class AddResumeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enrollment_id: UUID
    label: str
    drive_url: str
    is_default: bool = False

    @field_validator("label", "drive_url")
    @classmethod
    def strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class UpdateResumeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enrollment_id: UUID
    resume_id: UUID
    label: str | None = None
    drive_url: str | None = None


class ResumeIdInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enrollment_id: UUID
    resume_id: UUID


class ResumeSummary(BaseModel):
    resume_id: UUID
    is_default: bool
    changed: bool


class DeleteResumeSummary(BaseModel):
    deleted_resume_id: UUID
    promoted_resume_id: UUID | None
    memberships_default_cleared: int


@dataclass(frozen=True, slots=True)
class ProfileState:
    scope_ids: ScopeIds
    now: datetime
    enrollment_exists: bool
    is_current: bool
    user_id: UUID | None
    full_name: str | None
    roll_number: str | None
    profile_exists: bool
    declared_at: datetime | None
    values: tuple[tuple[str, object], ...]
    known_taxonomy_ids: frozenset[UUID]
    active_taxonomy_ids: frozenset[UUID]
    program_branch_pairs: frozenset[tuple[UUID, UUID]]
    roll_conflict: bool

    @property
    def current(self) -> dict[str, object]:
        return dict(self.values)


@dataclass(frozen=True, slots=True)
class ResumeRow:
    id: UUID
    label: str
    drive_url: str
    is_default: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ResumeState:
    scope_ids: ScopeIds
    now: datetime
    enrollment_exists: bool
    resumes: tuple[ResumeRow, ...]
    target: ResumeRow | None
    membership_refs: int
    new_resume_id: UUID


def _candidate_uuids(fields: dict[str, object]) -> tuple[UUID, ...]:
    candidates: list[UUID] = []
    for key in TAXONOMY_FIELDS:
        raw = fields.get(key)
        if raw is None:
            continue
        try:
            candidates.append(raw if isinstance(raw, UUID) else UUID(str(raw).strip()))
        except (ValueError, AttributeError):
            continue
    return tuple(candidates)


async def _load_profile_state(
    tx: AsyncSession,
    enrollment_id: UUID,
    fields: dict[str, object],
    *,
    lock: bool,
) -> ProfileState:
    now = datetime.now(UTC)
    lock_clause = " FOR UPDATE" if lock else ""
    roll_value = fields.get("roll_number")
    normalized_roll = (
        str(roll_value).strip() if isinstance(roll_value, str) and roll_value.strip() else None
    )
    if lock and normalized_roll is not None:
        await tx.execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"roll:{normalized_roll.casefold()}"},
        )
    enrollment = (
        await tx.execute(
            sa.text(
                "SELECT e.id, e.user_id, e.is_current, e.roll_number, u.full_name "
                "FROM enrollments e JOIN users u ON u.id = e.user_id "
                "WHERE e.id = :enrollment_id" + lock_clause
            ),
            {"enrollment_id": enrollment_id},
        )
    ).mappings().one_or_none()
    profile = None
    if enrollment is not None:
        profile = (
            await tx.execute(
                sa.text(
                    "SELECT " + ", ".join(PROFILE_COLUMNS) + ", declared_at "
                    "FROM profiles WHERE enrollment_id = :enrollment_id" + lock_clause
                ),
                {"enrollment_id": enrollment_id},
            )
        ).mappings().one_or_none()

    current: dict[str, object] = {column: None for column in PROFILE_COLUMNS}
    if profile is not None:
        current.update({column: profile[column] for column in PROFILE_COLUMNS})

    candidates = set(_candidate_uuids(fields))
    for key in (
        "program_id",
        "secondary_program_id",
        "primary_branch_id",
        "secondary_branch_id",
    ):
        existing = current.get(key)
        if isinstance(existing, UUID):
            candidates.add(existing)
    known: set[UUID] = set()
    active: set[UUID] = set()
    pairs: set[tuple[UUID, UUID]] = set()
    if candidates:
        rows = (
            await tx.execute(
                sa.text(
                    "SELECT id, is_active FROM programs WHERE id = ANY(CAST(:ids AS uuid[])) "
                    "UNION ALL "
                    "SELECT id, is_active FROM branches WHERE id = ANY(CAST(:ids AS uuid[])) "
                    "UNION ALL "
                    "SELECT id, is_active FROM minors WHERE id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": list(candidates)},
            )
        ).mappings().all()
        for row in rows:
            known.add(row["id"])
            if row["is_active"]:
                active.add(row["id"])
        pair_rows = (
            await tx.execute(
                sa.text(
                    "SELECT program_id, branch_id FROM program_branches "
                    "WHERE program_id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": list(candidates)},
            )
        ).mappings().all()
        pairs = {(row["program_id"], row["branch_id"]) for row in pair_rows}

    roll_conflict = False
    if normalized_roll is not None and enrollment is not None and enrollment["is_current"]:
        conflict = await tx.scalar(
            sa.text(
                "SELECT 1 FROM enrollments WHERE roll_number = :roll AND is_current "
                "AND id <> :enrollment_id"
            ),
            {"roll": normalized_roll, "enrollment_id": enrollment_id},
        )
        roll_conflict = conflict is not None

    return ProfileState(
        scope_ids=ScopeIds(enrollment_id=enrollment_id),
        now=now,
        enrollment_exists=enrollment is not None,
        is_current=bool(enrollment["is_current"]) if enrollment is not None else False,
        user_id=enrollment["user_id"] if enrollment is not None else None,
        full_name=enrollment["full_name"] if enrollment is not None else None,
        roll_number=enrollment["roll_number"] if enrollment is not None else None,
        profile_exists=profile is not None,
        declared_at=profile["declared_at"] if profile is not None else None,
        values=tuple(current.items()),
        known_taxonomy_ids=frozenset(known),
        active_taxonomy_ids=frozenset(active),
        program_branch_pairs=frozenset(pairs),
        roll_conflict=roll_conflict,
    )


async def _load_declare(tx: AsyncSession, input_value: BaseModel, *, lock: bool) -> ProfileState:
    if not isinstance(input_value, DeclareProfileInput):
        raise TypeError("declare_profile requires DeclareProfileInput")
    return await _load_profile_state(tx, input_value.enrollment_id, input_value.fields, lock=lock)


async def _load_student_update(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> ProfileState:
    if not isinstance(input_value, UpdateStudentFieldsInput):
        raise TypeError("update_student_fields requires UpdateStudentFieldsInput")
    return await _load_profile_state(tx, input_value.enrollment_id, input_value.fields, lock=lock)


async def _load_admin_update(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> ProfileState:
    if not isinstance(input_value, AdminUpdateProfileInput):
        raise TypeError("admin_update_profile requires AdminUpdateProfileInput")
    return await _load_profile_state(tx, input_value.enrollment_id, input_value.fields, lock=lock)


def coerce_fields(
    fields: dict[str, object], allowed: frozenset[str]
) -> tuple[dict[str, object], list[Reason]]:
    """Validate provided values against the ownership whitelist (pure)."""
    reasons: list[Reason] = []
    coerced: dict[str, object] = {}
    for key, value in fields.items():
        if key in UNEDITABLE_FIELDS:
            reasons.append(
                Reason(
                    code=FIELD_NOT_EDITABLE,
                    human="The institute email is managed by the system",
                    path=key,
                )
            )
            continue
        if key not in allowed:
            label = FIELDS_BY_KEY[key].label if key in FIELDS_BY_KEY else key
            reasons.append(
                Reason(
                    code=FIELD_NOT_EDITABLE,
                    human=f"{label} is not editable here",
                    path=key,
                )
            )
            continue
        try:
            coerced[key] = coerce_field(key, value)
        except FieldValueError as error:
            reasons.append(
                Reason(code=INVALID_FIELD_VALUE, human=error.human, path=error.key)
            )
    return coerced, reasons


def taxonomy_reasons(coerced: dict[str, object], state: ProfileState) -> list[Reason]:
    reasons: list[Reason] = []
    for key in TAXONOMY_FIELDS:
        value = coerced.get(key)
        if not isinstance(value, UUID):
            continue
        if value not in state.known_taxonomy_ids:
            reasons.append(
                Reason(
                    code=UNKNOWN_TAXONOMY_VALUE,
                    human=f"{FIELDS_BY_KEY[key].label} does not exist",
                    path=key,
                )
            )
        elif value not in state.active_taxonomy_ids:
            reasons.append(
                Reason(
                    code=UNKNOWN_TAXONOMY_VALUE,
                    human=f"{FIELDS_BY_KEY[key].label} is no longer active",
                    path=key,
                )
            )
    return reasons


def program_branch_reasons(
    effective: dict[str, object], pairs: frozenset[tuple[UUID, UUID]]
) -> list[Reason]:
    """PRO-1: a declared branch must belong to the declared program.

    Also the one cross-field rule the dual-major flag brings with it: a second
    major is what being a dual major *means* (the design review section 4.32), so a
    secondary branch on a student who is not one is a contradiction rather than
    a harmless extra.  Requiring the converse -- a dual major who has named no
    secondary branch yet -- is deliberately *not* done here: PRO-1 makes that a
    requirement for joining a cycle, which `check_profile_completeness` already
    enforces, so the office can record the fact before the branch is settled.
    """
    program = effective.get("program_id")
    secondary_program = effective.get("secondary_program_id")
    dual_major = bool(effective.get("is_dual_major"))
    dual_degree = bool(effective.get("is_dual_degree"))
    reasons: list[Reason] = []

    if dual_major and dual_degree:
        reasons.append(Reason(
            code=INVALID_FIELD_VALUE,
            human="A student cannot be both a dual major and a dual degree",
            path="is_dual_degree",
        ))
    if dual_degree != isinstance(secondary_program, UUID):
        reasons.append(Reason(
            code=INVALID_FIELD_VALUE,
            human="A dual degree must name its secondary program",
            path="secondary_program_id",
        ))
    if dual_major and isinstance(secondary_program, UUID):
        reasons.append(Reason(
            code=INVALID_FIELD_VALUE,
            human="A dual major does not have a secondary program",
            path="secondary_program_id",
        ))

    primary = effective.get("primary_branch_id")
    secondary = effective.get("secondary_branch_id")
    if isinstance(program, UUID) and isinstance(primary, UUID) and (program, primary) not in pairs:
        reasons.append(Reason(
            code=PROGRAM_BRANCH_MISMATCH,
            human="Primary branch is not offered by the declared program",
            path="primary_branch_id",
        ))
    branch_program = secondary_program if dual_degree else program
    if (isinstance(branch_program, UUID) and isinstance(secondary, UUID)
            and (branch_program, secondary) not in pairs):
        reasons.append(Reason(
            code=PROGRAM_BRANCH_MISMATCH,
            human=("Secondary branch is not offered by the secondary program"
                   if dual_degree else
                   "Secondary branch is not offered by the declared program"),
            path="secondary_branch_id",
        ))
    if isinstance(primary, UUID) and primary == secondary:
        reasons.append(Reason(
            code=PROGRAM_BRANCH_MISMATCH,
            human="Secondary branch must differ from the primary branch",
            path="secondary_branch_id",
        ))
    if isinstance(secondary, UUID) and not (dual_major or dual_degree):
        reasons.append(Reason(
            code=INVALID_FIELD_VALUE,
            human="Only a dual major or dual degree has a secondary branch",
            path="secondary_branch_id",
        ))
    return reasons


def _profile_ops(
    state: ProfileState, changes: dict[str, object], *, declared_at: datetime | None
) -> list[StateOp]:
    values = {key: value for key, value in changes.items() if key in PROFILE_COLUMNS}
    if declared_at is not None:
        values["declared_at"] = declared_at
    if not values:
        return []
    if state.profile_exists:
        return [
            StateOp(
                op="update",
                model="profiles",
                values=values,
                where={"enrollment_id": state.scope_ids.enrollment_id},
            )
        ]
    return [
        StateOp(
            op="insert",
            model="profiles",
            values={"enrollment_id": state.scope_ids.enrollment_id, **values},
        )
    ]


def _decide_declare(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Declare one profile per enrollment, once, per Behavior PRO-1 and IDN-2."""
    if not isinstance(input_value, DeclareProfileInput) or not isinstance(state, ProfileState):
        raise TypeError("Invalid declare_profile decision input")
    if not state.enrollment_exists:
        return Rejection(
            reasons=[Reason(code=ENROLLMENT_NOT_FOUND, human="The enrollment does not exist")]
        )
    if state.declared_at is not None:
        return Rejection(
            reasons=[
                Reason(
                    code=PROFILE_ALREADY_DECLARED,
                    human="This profile has already been declared",
                )
            ]
        )
    coerced, reasons = coerce_fields(input_value.fields, DECLARABLE_FIELDS)
    reasons.extend(taxonomy_reasons(coerced, state))

    current = state.current
    # PRO-1: admin-managed fields the administration already populated stay theirs;
    # the student's declaration fills only what is still empty.
    retained: list[str] = []
    applied: dict[str, object] = {}
    for key, value in coerced.items():
        if key == "roll_number":
            if state.roll_number is not None:
                retained.append(key)
            elif value is not None:
                applied[key] = value
            continue
        if key in ADMIN_FIELDS and current.get(key) is not None:
            retained.append(key)
            continue
        applied[key] = value

    effective = dict(current)
    effective.update({key: value for key, value in applied.items() if key in PROFILE_COLUMNS})
    reasons.extend(program_branch_reasons(effective, state.program_branch_pairs))
    if "roll_number" in applied and state.roll_conflict:
        reasons.append(
            Reason(
                code=ROLL_NUMBER_TAKEN,
                human="Another current enrollment already uses this roll number",
                path="roll_number",
            )
        )
    if reasons:
        return Rejection(reasons=reasons)

    before = {key: jsonable(value) for key, value in current.items()}
    before["roll_number"] = jsonable(state.roll_number)
    after = dict(before)
    after.update({key: jsonable(value) for key, value in applied.items()})

    operations = _profile_ops(state, applied, declared_at=state.now)
    if "roll_number" in applied:
        operations.append(
            StateOp(
                op="update",
                model="enrollments",
                values={"roll_number": applied["roll_number"]},
                where={"id": input_value.enrollment_id},
            )
        )
    return Plan(
        state_ops=operations,
        events=[],
        deferred=[],
        audit={
            "subject_type": "enrollment",
            "subject_id": input_value.enrollment_id,
            "details": {"before": before, "after": after, "retained": sorted(retained)},
        },
        summary={
            "enrollment_id": str(input_value.enrollment_id),
            "declared_at": state.now.isoformat(),
            "applied_fields": sorted(applied),
            "retained_fields": sorted(retained),
        },
    )


def _decide_field_update(
    enrollment_id: UUID,
    fields: dict[str, object],
    state: ProfileState,
    *,
    allowed: frozenset[str],
    require_declared: bool,
) -> Plan | Rejection:
    if not state.enrollment_exists:
        return Rejection(
            reasons=[Reason(code=ENROLLMENT_NOT_FOUND, human="The enrollment does not exist")]
        )
    if require_declared and state.declared_at is None:
        return Rejection(
            reasons=[
                Reason(
                    code=PROFILE_NOT_DECLARED,
                    human="Declare your profile before editing it",
                )
            ]
        )
    coerced, reasons = coerce_fields(fields, allowed)
    reasons.extend(taxonomy_reasons(coerced, state))

    current = state.current
    effective = dict(current)
    effective.update({key: value for key, value in coerced.items() if key in PROFILE_COLUMNS})
    reasons.extend(program_branch_reasons(effective, state.program_branch_pairs))
    if "roll_number" in coerced and coerced["roll_number"] is not None and state.roll_conflict:
        reasons.append(
            Reason(
                code=ROLL_NUMBER_TAKEN,
                human="Another current enrollment already uses this roll number",
                path="roll_number",
            )
        )
    if reasons:
        return Rejection(reasons=reasons)

    changes: dict[str, object] = {}
    before: dict[str, object] = {}
    after: dict[str, object] = {}
    for key, value in coerced.items():
        existing = (
            state.roll_number
            if key == "roll_number"
            else state.full_name
            if key == "full_name"
            else current.get(key)
        )
        if existing == value:
            continue
        changes[key] = value
        before[key] = jsonable(existing)
        after[key] = jsonable(value)

    operations = _profile_ops(state, changes, declared_at=None)
    if "roll_number" in changes:
        operations.append(
            StateOp(
                op="update",
                model="enrollments",
                values={"roll_number": changes["roll_number"]},
                where={"id": enrollment_id},
            )
        )
    if "full_name" in changes:
        operations.append(
            StateOp(
                op="update",
                model="users",
                values={"full_name": changes["full_name"]},
                where={"id": state.user_id},
            )
        )
    return Plan(
        state_ops=operations,
        events=[],
        deferred=[],
        audit={
            "subject_type": "enrollment",
            "subject_id": enrollment_id,
            "details": {"before": before, "after": after},
        }
        if changes
        else None,
        summary={
            "enrollment_id": str(enrollment_id),
            "changed_fields": sorted(changes),
        },
    )


def _decide_student_update(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Edit the student-managed columns of PRO-1, plus any admin field still blank.

    PRO-1 locks an admin-managed field once it "accepts the student's initial
    value", which the design review section 4.33 reads as the value's property and not
    ``declared_at``'s: a column nobody has filled has accepted nothing, and its
    intended source is the person in front of it.  The allowed set is therefore
    a function of the loaded row, which keeps this decision pure -- the loader
    read ``current`` and ``roll_number`` under the same lock as the write.
    """
    if not isinstance(input_value, UpdateStudentFieldsInput) or not isinstance(
        state, ProfileState
    ):
        raise TypeError("Invalid update_student_fields decision input")
    return _decide_field_update(
        input_value.enrollment_id,
        input_value.fields,
        state,
        allowed=STUDENT_FIELDS
        | unlocked_admin_fields(state.current, roll_number=state.roll_number),
        require_declared=True,
    )


def _decide_admin_update(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Administration owns every field on any enrollment, current or historical (PRO-1)."""
    if not isinstance(input_value, AdminUpdateProfileInput) or not isinstance(
        state, ProfileState
    ):
        raise TypeError("Invalid admin_update_profile decision input")
    return _decide_field_update(
        input_value.enrollment_id,
        input_value.fields,
        state,
        allowed=STUDENT_FIELDS | ADMIN_FIELDS,
        require_declared=False,
    )


async def _load_resumes(
    tx: AsyncSession, enrollment_id: UUID, resume_id: UUID | None, *, lock: bool
) -> ResumeState:
    now = datetime.now(UTC)
    lock_clause = " FOR UPDATE" if lock else ""
    enrollment_exists = (
        await tx.scalar(
            sa.text("SELECT 1 FROM enrollments WHERE id = :id" + lock_clause),
            {"id": enrollment_id},
        )
        is not None
    )
    rows = (
        await tx.execute(
            sa.text(
                "SELECT id, label, drive_url, is_default, created_at FROM resumes "
                "WHERE enrollment_id = :enrollment_id ORDER BY created_at, id" + lock_clause
            ),
            {"enrollment_id": enrollment_id},
        )
    ).mappings().all()
    resumes = tuple(
        ResumeRow(
            id=row["id"],
            label=str(row["label"]),
            drive_url=str(row["drive_url"]),
            is_default=bool(row["is_default"]),
            created_at=row["created_at"],
        )
        for row in rows
    )
    target = next((row for row in resumes if row.id == resume_id), None)
    membership_refs = 0
    if target is not None:
        membership_refs = int(
            await tx.scalar(
                sa.text(
                    "SELECT count(*) FROM cycle_memberships "
                    "WHERE default_resume_id = :resume_id"
                ),
                {"resume_id": target.id},
            )
            or 0
        )
    return ResumeState(
        scope_ids=ScopeIds(enrollment_id=enrollment_id),
        now=now,
        enrollment_exists=enrollment_exists,
        resumes=resumes,
        target=target,
        membership_refs=membership_refs,
        new_resume_id=uuid4(),
    )


async def _load_add_resume(tx: AsyncSession, input_value: BaseModel, *, lock: bool) -> ResumeState:
    if not isinstance(input_value, AddResumeInput):
        raise TypeError("add_resume requires AddResumeInput")
    return await _load_resumes(tx, input_value.enrollment_id, None, lock=lock)


async def _load_update_resume(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> ResumeState:
    if not isinstance(input_value, UpdateResumeInput):
        raise TypeError("update_resume requires UpdateResumeInput")
    return await _load_resumes(tx, input_value.enrollment_id, input_value.resume_id, lock=lock)


async def _load_resume_id(tx: AsyncSession, input_value: BaseModel, *, lock: bool) -> ResumeState:
    if not isinstance(input_value, ResumeIdInput):
        raise TypeError("Resume command requires ResumeIdInput")
    return await _load_resumes(tx, input_value.enrollment_id, input_value.resume_id, lock=lock)


def _missing_enrollment() -> Rejection:
    return Rejection(
        reasons=[Reason(code=ENROLLMENT_NOT_FOUND, human="The enrollment does not exist")]
    )


def _missing_resume() -> Rejection:
    return Rejection(
        reasons=[Reason(code=RESUME_NOT_FOUND, human="The resume does not exist", path="resume_id")]
    )


def _invalid_drive_url() -> Rejection:
    return Rejection(
        reasons=[
            Reason(
                code=INVALID_DRIVE_URL,
                human="Provide a Google Drive or Docs file link",
                path="drive_url",
            )
        ]
    )


def _clear_default_ops(state: ResumeState, keep: UUID | None) -> list[StateOp]:
    return [
        StateOp(
            op="update",
            model="resumes",
            values={"is_default": False},
            where={"id": resume.id},
        )
        for resume in state.resumes
        if resume.is_default and resume.id != keep
    ]


def _decide_add_resume(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Add a Drive link to the enrollment's resume library per Behavior PRO-3."""
    if not isinstance(input_value, AddResumeInput) or not isinstance(state, ResumeState):
        raise TypeError("Invalid add_resume decision input")
    if not state.enrollment_exists:
        return _missing_enrollment()
    if not is_drive_file_url(input_value.drive_url):
        return _invalid_drive_url()
    is_default = input_value.is_default or not state.resumes
    operations = _clear_default_ops(state, keep=None) if is_default else []
    operations.append(
        StateOp(
            op="insert",
            model="resumes",
            values={
                "id": state.new_resume_id,
                "enrollment_id": input_value.enrollment_id,
                "label": input_value.label,
                "drive_url": input_value.drive_url,
                "is_default": is_default,
            },
        )
    )
    return Plan(
        state_ops=operations,
        events=[],
        deferred=[],
        audit={
            "subject_type": "resume",
            "subject_id": state.new_resume_id,
            "details": {
                "before": None,
                "after": {
                    "label": input_value.label,
                    "drive_url": input_value.drive_url,
                    "is_default": is_default,
                },
            },
        },
        summary={
            "resume_id": str(state.new_resume_id),
            "is_default": is_default,
            "changed": True,
        },
    )


def _decide_update_resume(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Edit a resume label or link; URL shape only, never a probe (PRO-3)."""
    if not isinstance(input_value, UpdateResumeInput) or not isinstance(state, ResumeState):
        raise TypeError("Invalid update_resume decision input")
    if not state.enrollment_exists:
        return _missing_enrollment()
    if state.target is None:
        return _missing_resume()
    label = input_value.label.strip() if input_value.label is not None else None
    drive_url = input_value.drive_url.strip() if input_value.drive_url is not None else None
    if label is not None and not label:
        return Rejection(
            reasons=[
                Reason(code=INVALID_FIELD_VALUE, human="Label must not be blank", path="label")
            ]
        )
    if drive_url is not None and not is_drive_file_url(drive_url):
        return _invalid_drive_url()
    values: dict[str, object] = {}
    if label is not None and label != state.target.label:
        values["label"] = label
    if drive_url is not None and drive_url != state.target.drive_url:
        values["drive_url"] = drive_url
    operations = (
        [StateOp(op="update", model="resumes", values=values, where={"id": state.target.id})]
        if values
        else []
    )
    return Plan(
        state_ops=operations,
        events=[],
        deferred=[],
        audit={
            "subject_type": "resume",
            "subject_id": state.target.id,
            "details": {
                "before": {"label": state.target.label, "drive_url": state.target.drive_url},
                "after": {
                    "label": values.get("label", state.target.label),
                    "drive_url": values.get("drive_url", state.target.drive_url),
                },
            },
        }
        if values
        else None,
        summary={
            "resume_id": str(state.target.id),
            "is_default": state.target.is_default,
            "changed": bool(values),
        },
    )


def _decide_set_default_resume(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Move the single default marker inside the library (PRO-3)."""
    if not isinstance(input_value, ResumeIdInput) or not isinstance(state, ResumeState):
        raise TypeError("Invalid set_default_resume decision input")
    if not state.enrollment_exists:
        return _missing_enrollment()
    if state.target is None:
        return _missing_resume()
    if state.target.is_default:
        return Plan(
            state_ops=[],
            events=[],
            deferred=[],
            audit=None,
            summary={"resume_id": str(state.target.id), "is_default": True, "changed": False},
        )
    # The partial unique index is not deferrable: clear the old default first.
    operations = _clear_default_ops(state, keep=state.target.id)
    operations.append(
        StateOp(
            op="update",
            model="resumes",
            values={"is_default": True},
            where={"id": state.target.id},
        )
    )
    return Plan(
        state_ops=operations,
        events=[],
        deferred=[],
        audit={
            "subject_type": "resume",
            "subject_id": state.target.id,
            "details": {
                "before": {"is_default": False},
                "after": {"is_default": True},
            },
        },
        summary={"resume_id": str(state.target.id), "is_default": True, "changed": True},
    )


def _decide_delete_resume(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Delete a resume, keeping the library non-empty and defaulted (PRO-1, PRO-3)."""
    if not isinstance(input_value, ResumeIdInput) or not isinstance(state, ResumeState):
        raise TypeError("Invalid delete_resume decision input")
    if not state.enrollment_exists:
        return _missing_enrollment()
    if state.target is None:
        return _missing_resume()
    if len(state.resumes) == 1:
        return Rejection(
            reasons=[
                Reason(
                    code=LAST_RESUME,
                    human="Joining a cycle needs at least one resume; add another first",
                    path="resume_id",
                )
            ]
        )
    remaining = [resume for resume in state.resumes if resume.id != state.target.id]
    promoted = (
        max(remaining, key=lambda resume: (resume.created_at, resume.id))
        if state.target.is_default
        else None
    )
    operations: list[StateOp] = [
        StateOp(op="delete", model="resumes", values={}, where={"id": state.target.id})
    ]
    if promoted is not None:
        operations.append(
            StateOp(
                op="update",
                model="resumes",
                values={"is_default": True},
                where={"id": promoted.id},
            )
        )
    return Plan(
        state_ops=operations,
        events=[],
        deferred=[],
        audit={
            "subject_type": "resume",
            "subject_id": state.target.id,
            "details": {
                "before": {
                    "label": state.target.label,
                    "drive_url": state.target.drive_url,
                    "is_default": state.target.is_default,
                },
                "after": None,
                "promoted_resume_id": str(promoted.id) if promoted is not None else None,
                "memberships_default_cleared": state.membership_refs,
            },
        },
        summary={
            "deleted_resume_id": str(state.target.id),
            "promoted_resume_id": str(promoted.id) if promoted is not None else None,
            "memberships_default_cleared": state.membership_refs,
        },
    )


def register_profile_commands(registry: Registry) -> None:
    registry.command(
        name="declare_profile",
        input_model=DeclareProfileInput,
        output_model=DeclareProfileSummary,
        actor="student",
        scope="none",
        loader=_load_declare,
        rule_domains=(),
        spec_ids=("PRO-1", "IDN-2"),
    )(_decide_declare)
    registry.command(
        name="update_student_fields",
        input_model=UpdateStudentFieldsInput,
        output_model=UpdateProfileSummary,
        actor="student",
        scope="none",
        loader=_load_student_update,
        rule_domains=(),
        spec_ids=("PRO-1",),
    )(_decide_student_update)
    registry.command(
        name="admin_update_profile",
        input_model=AdminUpdateProfileInput,
        output_model=UpdateProfileSummary,
        actor="admin",
        scope="none",
        loader=_load_admin_update,
        rule_domains=(),
        spec_ids=("PRO-1", "PRO-2"),
    )(_decide_admin_update)
    registry.command(
        name="add_resume",
        input_model=AddResumeInput,
        output_model=ResumeSummary,
        actor="student",
        scope="none",
        loader=_load_add_resume,
        rule_domains=(),
        spec_ids=("PRO-3",),
    )(_decide_add_resume)
    registry.command(
        name="update_resume",
        input_model=UpdateResumeInput,
        output_model=ResumeSummary,
        actor="student",
        scope="none",
        loader=_load_update_resume,
        rule_domains=(),
        spec_ids=("PRO-3",),
    )(_decide_update_resume)
    registry.command(
        name="set_default_resume",
        input_model=ResumeIdInput,
        output_model=ResumeSummary,
        actor="student",
        scope="none",
        loader=_load_resume_id,
        rule_domains=(),
        spec_ids=("PRO-3",),
    )(_decide_set_default_resume)
    registry.command(
        name="delete_resume",
        input_model=ResumeIdInput,
        output_model=DeleteResumeSummary,
        actor="student",
        scope="none",
        loader=_load_resume_id,
        rule_domains=(),
        spec_ids=("PRO-3",),
    )(_decide_delete_resume)
