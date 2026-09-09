"""The global company directory and its contacts (Behavior section 4, CMP).

Coordinators and administrators create and edit; deactivation, reactivation, and
merge are administrator-only.  Inactive companies stay attached to everything
they ever touched and only disappear from pickers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    COMPANY_INACTIVE,
    COMPANY_NAME_CONFLICT,
    COMPANY_NAME_CONFLICT_INACTIVE,
    COMPANY_NOT_FOUND,
    CONTACT_EMAIL_CONFLICT,
    CONTACT_NOT_FOUND,
    INVALID_FIELD_VALUE,
    MERGE_INTO_SELF,
    UNKNOWN_TAXONOMY_VALUE,
)
from app.core.plan import ActorContext, Plan, Reason, Rejection, ScopeIds, StateOp
from app.core.registry import Decider, Registry

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$")
# https only: a directory link handed to students and staff must not downgrade.
WEBSITE_PATTERN = re.compile(r"^https://[^\s/$.?#][^\s]*$")
MERGE_AUDIT_ACTION = "merge_companies.duplicate"


def normalize_name(value: str) -> str:
    return " ".join(value.split())


class CreateCompanyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    website_url: str | None = None
    sector_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = normalize_name(value)
        if not normalized:
            raise ValueError("name must not be blank")
        if len(normalized) > 200:
            raise ValueError("name must be at most 200 characters")
        return normalized


class UpdateCompanyInput(BaseModel):
    # Forbid unknown keys so an attempt to flip is_active here fails loudly:
    # deactivation and reactivation are administrator-only commands.
    model_config = ConfigDict(extra="forbid")

    company_id: UUID
    name: str | None = None
    description: str | None = None
    website_url: str | None = None
    sector_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_name(value)
        if not normalized:
            raise ValueError("name must not be blank")
        if len(normalized) > 200:
            raise ValueError("name must be at most 200 characters")
        return normalized


class CompanySummary(BaseModel):
    company_id: UUID
    name: str
    is_active: bool
    changed: bool


class CompanyIdInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: UUID


class ContactCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: UUID
    name: str
    email: str
    phone: str | None = None
    designation: str | None = None
    is_primary: bool = False

    @field_validator("name", "email")
    @classmethod
    def strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class ContactUpdateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: UUID
    contact_id: UUID
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    designation: str | None = None
    is_primary: bool | None = None


class ContactIdInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: UUID
    contact_id: UUID


class ContactSummary(BaseModel):
    contact_id: UUID
    company_id: UUID
    is_primary: bool
    changed: bool


class MergeCompaniesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    survivor_id: UUID
    duplicate_id: UUID


class MergeCompaniesSummary(BaseModel):
    survivor_id: UUID
    duplicate_id: UUID
    jobs: int
    external_offers: int
    contacts_repointed: int
    contacts_dropped: list[dict[str, object]]
    primary_kept: UUID | None


@dataclass(frozen=True, slots=True)
class ContactRow:
    id: UUID
    company_id: UUID
    name: str
    email: str
    phone: str | None
    designation: str | None
    is_primary: bool

    def payload(self) -> dict[str, object]:
        """The full contact record, as previews and audit details carry it."""
        return {
            "id": str(self.id),
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "designation": self.designation,
            "is_primary": self.is_primary,
        }


@dataclass(frozen=True, slots=True)
class CompanyRow:
    id: UUID
    name: str
    description: str | None
    website_url: str | None
    sector_id: UUID | None
    is_active: bool

    def snapshot(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "website_url": self.website_url,
            "sector_id": str(self.sector_id) if self.sector_id else None,
            "is_active": self.is_active,
        }


@dataclass(frozen=True, slots=True)
class CompanyState:
    scope_ids: ScopeIds
    company_id: UUID
    company: CompanyRow | None
    conflict: CompanyRow | None
    sector_known: bool
    sector_active: bool


@dataclass(frozen=True, slots=True)
class ContactState:
    scope_ids: ScopeIds
    company: CompanyRow | None
    contacts: tuple[ContactRow, ...]
    target: ContactRow | None
    email_conflict: ContactRow | None
    new_contact_id: UUID


@dataclass(frozen=True, slots=True)
class MergeState:
    scope_ids: ScopeIds
    survivor: CompanyRow | None
    duplicate: CompanyRow | None
    survivor_contacts: tuple[ContactRow, ...]
    duplicate_contacts: tuple[ContactRow, ...]
    job_count: int
    external_offer_count: int


_COMPANY_COLUMNS = "id, name, description, website_url, sector_id, is_active"


def _company_row(row: sa.RowMapping) -> CompanyRow:
    return CompanyRow(
        id=row["id"],
        name=str(row["name"]),
        description=row["description"],
        website_url=row["website_url"],
        sector_id=row["sector_id"],
        is_active=bool(row["is_active"]),
    )


def _contact_row(row: sa.RowMapping) -> ContactRow:
    return ContactRow(
        id=row["id"],
        company_id=row["company_id"],
        name=str(row["name"]),
        email=str(row["email"]),
        phone=row["phone"],
        designation=row["designation"],
        is_primary=bool(row["is_primary"]),
    )


async def _load_company(
    tx: AsyncSession,
    *,
    company_id: UUID | None,
    name: str | None,
    sector_id: UUID | None,
    lock: bool,
) -> CompanyState:
    lock_clause = " FOR UPDATE" if lock else ""
    if lock and name is not None:
        await tx.execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"company:{name.casefold()}"},
        )
    company = None
    if company_id is not None:
        row = (
            await tx.execute(
                sa.text(
                    f"SELECT {_COMPANY_COLUMNS} FROM companies WHERE id = :id"  # noqa: S608
                    + lock_clause
                ),
                {"id": company_id},
            )
        ).mappings().one_or_none()
        company = _company_row(row) if row is not None else None

    conflict = None
    if name is not None:
        row = (
            await tx.execute(
                sa.text(
                    f"SELECT {_COMPANY_COLUMNS} FROM companies "  # noqa: S608
                    "WHERE name = :name AND (CAST(:id AS uuid) IS NULL "
                    "OR id <> CAST(:id AS uuid))"
                    + lock_clause
                ),
                {"name": name, "id": company_id},
            )
        ).mappings().one_or_none()
        conflict = _company_row(row) if row is not None else None

    sector_known = sector_id is None
    sector_active = sector_id is None
    if sector_id is not None:
        sector = (
            await tx.execute(
                sa.text("SELECT is_active FROM sectors WHERE id = :id"),
                {"id": sector_id},
            )
        ).mappings().one_or_none()
        sector_known = sector is not None
        sector_active = sector is not None and bool(sector["is_active"])

    return CompanyState(
        scope_ids=ScopeIds(),
        company_id=company_id or uuid4(),
        company=company,
        conflict=conflict,
        sector_known=sector_known,
        sector_active=sector_active,
    )


async def _load_create(tx: AsyncSession, input_value: BaseModel, *, lock: bool) -> CompanyState:
    if not isinstance(input_value, CreateCompanyInput):
        raise TypeError("create_company requires CreateCompanyInput")
    return await _load_company(
        tx,
        company_id=None,
        name=input_value.name,
        sector_id=input_value.sector_id,
        lock=lock,
    )


async def _load_update(tx: AsyncSession, input_value: BaseModel, *, lock: bool) -> CompanyState:
    if not isinstance(input_value, UpdateCompanyInput):
        raise TypeError("update_company requires UpdateCompanyInput")
    return await _load_company(
        tx,
        company_id=input_value.company_id,
        name=input_value.name,
        sector_id=input_value.sector_id,
        lock=lock,
    )


async def _load_company_id(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> CompanyState:
    if not isinstance(input_value, CompanyIdInput):
        raise TypeError("Company activation requires CompanyIdInput")
    return await _load_company(
        tx, company_id=input_value.company_id, name=None, sector_id=None, lock=lock
    )


def _name_conflict_reason(conflict: CompanyRow) -> Reason:
    """A conflict with a deactivated company must name the way forward (CMP)."""
    if conflict.is_active:
        return Reason(
            code=COMPANY_NAME_CONFLICT,
            human=f"'{conflict.name}' is already in the directory",
            path="name",
        )
    return Reason(
        code=COMPANY_NAME_CONFLICT_INACTIVE,
        human=(
            f"'{conflict.name}' already exists but is deactivated, so it is hidden "
            "from pickers; an administrator must reactivate it instead of creating "
            "a second entry"
        ),
        path="name",
    )


def _sector_reasons(state: CompanyState) -> list[Reason]:
    if not state.sector_known:
        return [
            Reason(
                code=UNKNOWN_TAXONOMY_VALUE, human="The sector does not exist", path="sector_id"
            )
        ]
    if not state.sector_active:
        return [
            Reason(
                code=UNKNOWN_TAXONOMY_VALUE,
                human="The sector is no longer active",
                path="sector_id",
            )
        ]
    return []


def _website_reasons(website_url: str | None) -> list[Reason]:
    if website_url is None or WEBSITE_PATTERN.match(website_url):
        return []
    return [
        Reason(
            code=INVALID_FIELD_VALUE,
            human="The website must be an https link",
            path="website_url",
        )
    ]


def _decide_create_company(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Add one company to the global directory per Behavior section 4 (CMP)."""
    if not isinstance(input_value, CreateCompanyInput) or not isinstance(state, CompanyState):
        raise TypeError("Invalid create_company decision input")
    website = input_value.website_url.strip() if input_value.website_url else None
    reasons: list[Reason] = []
    if state.conflict is not None:
        reasons.append(_name_conflict_reason(state.conflict))
    reasons.extend(_sector_reasons(state))
    reasons.extend(_website_reasons(website))
    if reasons:
        return Rejection(reasons=reasons)

    values: dict[str, object] = {
        "id": state.company_id,
        "name": input_value.name,
        "description": input_value.description,
        "website_url": website,
        "sector_id": input_value.sector_id,
        "is_active": True,
    }
    after = CompanyRow(
        id=state.company_id,
        name=input_value.name,
        description=input_value.description,
        website_url=website,
        sector_id=input_value.sector_id,
        is_active=True,
    )
    return Plan(
        state_ops=[StateOp(op="insert", model="companies", values=values)],
        events=[],
        deferred=[],
        audit={
            "subject_type": "company",
            "subject_id": state.company_id,
            "details": {"before": None, "after": after.snapshot()},
        },
        summary={
            "company_id": str(state.company_id),
            "name": input_value.name,
            "is_active": True,
            "changed": True,
        },
    )


def _decide_update_company(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Edit directory fields; the active flag is never touched here (CMP)."""
    if not isinstance(input_value, UpdateCompanyInput) or not isinstance(state, CompanyState):
        raise TypeError("Invalid update_company decision input")
    if state.company is None:
        return Rejection(
            reasons=[Reason(code=COMPANY_NOT_FOUND, human="The company does not exist")]
        )
    provided = input_value.model_fields_set
    website = (
        input_value.website_url.strip()
        if "website_url" in provided and input_value.website_url
        else None if "website_url" in provided else state.company.website_url
    )
    reasons: list[Reason] = []
    if state.conflict is not None:
        reasons.append(_name_conflict_reason(state.conflict))
    if "sector_id" in provided:
        reasons.extend(_sector_reasons(state))
    if "website_url" in provided:
        reasons.extend(_website_reasons(website))
    if reasons:
        return Rejection(reasons=reasons)

    before = state.company
    after = CompanyRow(
        id=before.id,
        name=input_value.name if "name" in provided and input_value.name else before.name,
        description=(
            input_value.description if "description" in provided else before.description
        ),
        website_url=website,
        sector_id=input_value.sector_id if "sector_id" in provided else before.sector_id,
        is_active=before.is_active,
    )
    changed = after != before
    values = {
        "name": after.name,
        "description": after.description,
        "website_url": after.website_url,
        "sector_id": after.sector_id,
    }
    return Plan(
        state_ops=(
            [
                StateOp(
                    op="update", model="companies", values=values, where={"id": before.id}
                )
            ]
            if changed
            else []
        ),
        events=[],
        deferred=[],
        audit={
            "subject_type": "company",
            "subject_id": before.id,
            "details": {"before": before.snapshot(), "after": after.snapshot()},
        }
        if changed
        else None,
        summary={
            "company_id": str(before.id),
            "name": after.name,
            "is_active": after.is_active,
            "changed": changed,
        },
    )


def _decide_set_active(active: bool) -> Decider:
    def decide(
        input_value: BaseModel,
        state: object,
        _policy: object,
        _overrides: object,
        _actor: ActorContext,
    ) -> Plan | Rejection:
        """Hide a company from pickers, or restore it; administrators only (CMP)."""
        if not isinstance(input_value, CompanyIdInput) or not isinstance(state, CompanyState):
            raise TypeError("Invalid company activation decision input")
        if state.company is None:
            return Rejection(
                reasons=[Reason(code=COMPANY_NOT_FOUND, human="The company does not exist")]
            )
        before = state.company
        changed = before.is_active != active
        after = CompanyRow(
            id=before.id,
            name=before.name,
            description=before.description,
            website_url=before.website_url,
            sector_id=before.sector_id,
            is_active=active,
        )
        return Plan(
            state_ops=(
                [
                    StateOp(
                        op="update",
                        model="companies",
                        values={"is_active": active},
                        where={"id": before.id},
                    )
                ]
                if changed
                else []
            ),
            events=[],
            deferred=[],
            audit={
                "subject_type": "company",
                "subject_id": before.id,
                "details": {"before": before.snapshot(), "after": after.snapshot()},
            }
            if changed
            else None,
            summary={
                "company_id": str(before.id),
                "name": before.name,
                "is_active": active,
                "changed": changed,
            },
        )

    return decide


async def _load_contacts(
    tx: AsyncSession,
    *,
    company_id: UUID,
    contact_id: UUID | None,
    email: str | None,
    lock: bool,
) -> ContactState:
    lock_clause = " FOR UPDATE" if lock else ""
    company_row = (
        await tx.execute(
            sa.text(
                f"SELECT {_COMPANY_COLUMNS} FROM companies WHERE id = :id"  # noqa: S608
                + lock_clause
            ),
            {"id": company_id},
        )
    ).mappings().one_or_none()
    rows = (
        await tx.execute(
            sa.text(
                "SELECT id, company_id, name, email, phone, designation, is_primary "
                "FROM company_contacts WHERE company_id = :company_id "
                "ORDER BY created_at, id" + lock_clause
            ),
            {"company_id": company_id},
        )
    ).mappings().all()
    contacts = tuple(_contact_row(row) for row in rows)
    target = next((row for row in contacts if row.id == contact_id), None)
    conflict = None
    if email is not None:
        conflict = next(
            (
                row
                for row in contacts
                if row.email.casefold() == email.casefold() and row.id != contact_id
            ),
            None,
        )
    return ContactState(
        scope_ids=ScopeIds(),
        company=_company_row(company_row) if company_row is not None else None,
        contacts=contacts,
        target=target,
        email_conflict=conflict,
        new_contact_id=uuid4(),
    )


async def _load_contact_create(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> ContactState:
    if not isinstance(input_value, ContactCreateInput):
        raise TypeError("contact_create requires ContactCreateInput")
    return await _load_contacts(
        tx,
        company_id=input_value.company_id,
        contact_id=None,
        email=input_value.email,
        lock=lock,
    )


async def _load_contact_update(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> ContactState:
    if not isinstance(input_value, ContactUpdateInput):
        raise TypeError("contact_update requires ContactUpdateInput")
    return await _load_contacts(
        tx,
        company_id=input_value.company_id,
        contact_id=input_value.contact_id,
        email=input_value.email,
        lock=lock,
    )


async def _load_contact_id(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> ContactState:
    if not isinstance(input_value, ContactIdInput):
        raise TypeError("contact_delete requires ContactIdInput")
    return await _load_contacts(
        tx,
        company_id=input_value.company_id,
        contact_id=input_value.contact_id,
        email=None,
        lock=lock,
    )


def _missing_company() -> Rejection:
    return Rejection(
        reasons=[
            Reason(code=COMPANY_NOT_FOUND, human="The company does not exist", path="company_id")
        ]
    )


def _email_reasons(email: str | None) -> list[Reason]:
    if email is None or EMAIL_PATTERN.match(email):
        return []
    return [
        Reason(
            code=INVALID_FIELD_VALUE, human="The contact email is not valid", path="email"
        )
    ]


def _clear_primary_ops(contacts: tuple[ContactRow, ...], keep: UUID | None) -> list[StateOp]:
    # The single-primary index is not deferrable: clear the old primary first.
    return [
        StateOp(
            op="update",
            model="company_contacts",
            values={"is_primary": False},
            where={"id": contact.id},
        )
        for contact in contacts
        if contact.is_primary and contact.id != keep
    ]


def _decide_contact_create(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Record a company contact; the first one becomes primary (CMP)."""
    if not isinstance(input_value, ContactCreateInput) or not isinstance(state, ContactState):
        raise TypeError("Invalid contact_create decision input")
    if state.company is None:
        return _missing_company()
    reasons = _email_reasons(input_value.email)
    if state.email_conflict is not None:
        reasons.append(
            Reason(
                code=CONTACT_EMAIL_CONFLICT,
                human="This company already has a contact with that email",
                path="email",
            )
        )
    if reasons:
        return Rejection(reasons=reasons)

    is_primary = input_value.is_primary or not state.contacts
    operations = _clear_primary_ops(state.contacts, keep=None) if is_primary else []
    contact = ContactRow(
        id=state.new_contact_id,
        company_id=input_value.company_id,
        name=input_value.name,
        email=input_value.email,
        phone=input_value.phone,
        designation=input_value.designation,
        is_primary=is_primary,
    )
    operations.append(
        StateOp(
            op="insert",
            model="company_contacts",
            values={
                "id": contact.id,
                "company_id": contact.company_id,
                "name": contact.name,
                "email": contact.email,
                "phone": contact.phone,
                "designation": contact.designation,
                "is_primary": contact.is_primary,
            },
        )
    )
    return Plan(
        state_ops=operations,
        events=[],
        deferred=[],
        audit={
            "subject_type": "company_contact",
            "subject_id": contact.id,
            "details": {
                "company_id": str(input_value.company_id),
                "before": None,
                "after": contact.payload(),
            },
        },
        summary={
            "contact_id": str(contact.id),
            "company_id": str(input_value.company_id),
            "is_primary": is_primary,
            "changed": True,
        },
    )


def _decide_contact_update(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Edit a contact; a primary flip moves the single marker atomically (CMP)."""
    if not isinstance(input_value, ContactUpdateInput) or not isinstance(state, ContactState):
        raise TypeError("Invalid contact_update decision input")
    if state.company is None:
        return _missing_company()
    if state.target is None:
        return Rejection(
            reasons=[
                Reason(
                    code=CONTACT_NOT_FOUND, human="The contact does not exist", path="contact_id"
                )
            ]
        )
    provided = input_value.model_fields_set
    email = input_value.email.strip() if "email" in provided and input_value.email else None
    name = input_value.name.strip() if "name" in provided and input_value.name else None
    reasons: list[Reason] = []
    if "email" in provided:
        if not email:
            reasons.append(
                Reason(code=INVALID_FIELD_VALUE, human="Email must not be blank", path="email")
            )
        else:
            reasons.extend(_email_reasons(email))
    if "name" in provided and not name:
        reasons.append(
            Reason(code=INVALID_FIELD_VALUE, human="Name must not be blank", path="name")
        )
    if state.email_conflict is not None:
        reasons.append(
            Reason(
                code=CONTACT_EMAIL_CONFLICT,
                human="This company already has a contact with that email",
                path="email",
            )
        )
    if reasons:
        return Rejection(reasons=reasons)

    before = state.target
    after = ContactRow(
        id=before.id,
        company_id=before.company_id,
        name=name or before.name,
        email=email or before.email,
        phone=input_value.phone if "phone" in provided else before.phone,
        designation=(
            input_value.designation if "designation" in provided else before.designation
        ),
        is_primary=(
            bool(input_value.is_primary) if "is_primary" in provided else before.is_primary
        ),
    )
    changed = after != before
    operations: list[StateOp] = []
    if after.is_primary and not before.is_primary:
        operations.extend(_clear_primary_ops(state.contacts, keep=before.id))
    if changed:
        operations.append(
            StateOp(
                op="update",
                model="company_contacts",
                values={
                    "name": after.name,
                    "email": after.email,
                    "phone": after.phone,
                    "designation": after.designation,
                    "is_primary": after.is_primary,
                },
                where={"id": before.id},
            )
        )
    return Plan(
        state_ops=operations,
        events=[],
        deferred=[],
        audit={
            "subject_type": "company_contact",
            "subject_id": before.id,
            "details": {
                "company_id": str(before.company_id),
                "before": before.payload(),
                "after": after.payload(),
            },
        }
        if changed
        else None,
        summary={
            "contact_id": str(before.id),
            "company_id": str(before.company_id),
            "is_primary": after.is_primary,
            "changed": changed,
        },
    )


def _decide_contact_delete(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Remove a contact; nothing is promoted in its place (CMP)."""
    if not isinstance(input_value, ContactIdInput) or not isinstance(state, ContactState):
        raise TypeError("Invalid contact_delete decision input")
    if state.company is None:
        return _missing_company()
    if state.target is None:
        return Rejection(
            reasons=[
                Reason(
                    code=CONTACT_NOT_FOUND, human="The contact does not exist", path="contact_id"
                )
            ]
        )
    return Plan(
        state_ops=[
            StateOp(
                op="delete",
                model="company_contacts",
                values={},
                where={"id": state.target.id},
            )
        ],
        events=[],
        deferred=[],
        audit={
            "subject_type": "company_contact",
            "subject_id": state.target.id,
            "details": {
                "company_id": str(state.target.company_id),
                "before": state.target.payload(),
                "after": None,
            },
        },
        summary={
            "contact_id": str(state.target.id),
            "company_id": str(state.target.company_id),
            "is_primary": False,
            "changed": True,
        },
    )


async def _load_merge(tx: AsyncSession, input_value: BaseModel, *, lock: bool) -> MergeState:
    if not isinstance(input_value, MergeCompaniesInput):
        raise TypeError("merge_companies requires MergeCompaniesInput")
    lock_clause = " FOR UPDATE" if lock else ""
    # Deterministic lock order keeps a concurrent inverse merge from deadlocking.
    ordered = sorted({input_value.survivor_id, input_value.duplicate_id}, key=str)
    rows = (
        await tx.execute(
            sa.text(
                f"SELECT {_COMPANY_COLUMNS} FROM companies "  # noqa: S608
                "WHERE id = ANY(CAST(:ids AS uuid[])) ORDER BY id::text" + lock_clause
            ),
            {"ids": ordered},
        )
    ).mappings().all()
    companies = {row["id"]: _company_row(row) for row in rows}
    contact_rows = (
        await tx.execute(
            sa.text(
                "SELECT id, company_id, name, email, phone, designation, is_primary "
                "FROM company_contacts WHERE company_id = ANY(CAST(:ids AS uuid[])) "
                "ORDER BY created_at, id" + lock_clause
            ),
            {"ids": ordered},
        )
    ).mappings().all()
    contacts = [_contact_row(row) for row in contact_rows]
    job_count = int(
        await tx.scalar(
            sa.text("SELECT count(*) FROM jobs WHERE company_id = :id"),
            {"id": input_value.duplicate_id},
        )
        or 0
    )
    external_count = int(
        await tx.scalar(
            sa.text("SELECT count(*) FROM external_offers WHERE company_id = :id"),
            {"id": input_value.duplicate_id},
        )
        or 0
    )
    return MergeState(
        scope_ids=ScopeIds(),
        survivor=companies.get(input_value.survivor_id),
        duplicate=companies.get(input_value.duplicate_id),
        survivor_contacts=tuple(
            row for row in contacts if row.company_id == input_value.survivor_id
        ),
        duplicate_contacts=tuple(
            row for row in contacts if row.company_id == input_value.duplicate_id
        ),
        job_count=job_count,
        external_offer_count=external_count,
    )


def _decide_merge(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """Repoint one company's history onto another and retire it (CMP)."""
    if not isinstance(input_value, MergeCompaniesInput) or not isinstance(state, MergeState):
        raise TypeError("Invalid merge_companies decision input")
    if input_value.survivor_id == input_value.duplicate_id:
        return Rejection(
            reasons=[
                Reason(
                    code=MERGE_INTO_SELF,
                    human="Pick two different companies to merge",
                    path="duplicate_id",
                )
            ]
        )
    reasons: list[Reason] = []
    if state.survivor is None:
        reasons.append(
            Reason(
                code=COMPANY_NOT_FOUND, human="The survivor does not exist", path="survivor_id"
            )
        )
    elif not state.survivor.is_active:
        reasons.append(
            Reason(
                code=COMPANY_INACTIVE,
                human=(
                    f"'{state.survivor.name}' is deactivated; reactivate it before merging "
                    "another company into it"
                ),
                path="survivor_id",
            )
        )
    if state.duplicate is None:
        reasons.append(
            Reason(
                code=COMPANY_NOT_FOUND, human="The duplicate does not exist", path="duplicate_id"
            )
        )
    if reasons:
        return Rejection(reasons=reasons)
    assert state.survivor is not None and state.duplicate is not None

    survivor_emails = {contact.email.casefold() for contact in state.survivor_contacts}
    dropped = [
        contact
        for contact in state.duplicate_contacts
        if contact.email.casefold() in survivor_emails
    ]
    repointed = [
        contact
        for contact in state.duplicate_contacts
        if contact.email.casefold() not in survivor_emails
    ]
    survivor_primary = next(
        (contact for contact in state.survivor_contacts if contact.is_primary), None
    )
    incoming_primary = (
        None
        if survivor_primary is not None
        else next((contact for contact in repointed if contact.is_primary), None)
    )
    primary_kept = (
        survivor_primary.id
        if survivor_primary is not None
        else incoming_primary.id
        if incoming_primary is not None
        else None
    )

    operations: list[StateOp] = [
        StateOp(op="delete", model="company_contacts", values={}, where={"id": contact.id})
        for contact in dropped
    ]
    operations.extend(
        StateOp(
            op="update",
            model="company_contacts",
            values={
                "company_id": state.survivor.id,
                "is_primary": incoming_primary is not None and contact.id == incoming_primary.id,
            },
            where={"id": contact.id},
        )
        for contact in repointed
    )
    if state.job_count:
        operations.append(
            StateOp(
                op="update",
                model="jobs",
                values={"company_id": state.survivor.id},
                where={"company_id": state.duplicate.id},
            )
        )
    if state.external_offer_count:
        operations.append(
            StateOp(
                op="update",
                model="external_offers",
                values={"company_id": state.survivor.id},
                where={"company_id": state.duplicate.id},
            )
        )
    operations.append(
        StateOp(
            op="update",
            model="companies",
            values={"is_active": False},
            where={"id": state.duplicate.id},
        )
    )

    details: dict[str, object] = {
        "survivor": state.survivor.snapshot(),
        "duplicate": state.duplicate.snapshot(),
        "jobs": state.job_count,
        "external_offers": state.external_offer_count,
        # Nothing un-merges, so the audit keeps every discarded field verbatim.
        "contacts_repointed": [contact.payload() for contact in repointed],
        "contacts_dropped": [contact.payload() for contact in dropped],
        "primary_kept": str(primary_kept) if primary_kept else None,
    }
    operations.append(
        StateOp(
            op="insert",
            model="audit_log",
            values={
                "actor_user_id": actor.user_id,
                "action": MERGE_AUDIT_ACTION,
                "subject_type": "company",
                "subject_id": state.duplicate.id,
                "details": details,
            },
        )
    )
    return Plan(
        state_ops=operations,
        events=[],
        deferred=[],
        audit={"subject_type": "company", "subject_id": state.survivor.id, "details": details},
        summary={
            "survivor_id": str(state.survivor.id),
            "duplicate_id": str(state.duplicate.id),
            "jobs": state.job_count,
            "external_offers": state.external_offer_count,
            "contacts_repointed": len(repointed),
            "contacts_dropped": [contact.payload() for contact in dropped],
            "primary_kept": str(primary_kept) if primary_kept else None,
        },
    )


def register_company_commands(registry: Registry) -> None:
    registry.command(
        name="create_company",
        input_model=CreateCompanyInput,
        output_model=CompanySummary,
        actor="staff",
        scope="none",
        loader=_load_create,
        rule_domains=(),
        spec_ids=("CMP",),
    )(_decide_create_company)
    registry.command(
        name="update_company",
        input_model=UpdateCompanyInput,
        output_model=CompanySummary,
        actor="staff",
        scope="none",
        loader=_load_update,
        rule_domains=(),
        spec_ids=("CMP",),
    )(_decide_update_company)
    registry.command(
        name="deactivate_company",
        input_model=CompanyIdInput,
        output_model=CompanySummary,
        actor="admin",
        scope="none",
        loader=_load_company_id,
        rule_domains=(),
        spec_ids=("CMP",),
    )(_decide_set_active(False))
    registry.command(
        name="activate_company",
        input_model=CompanyIdInput,
        output_model=CompanySummary,
        actor="admin",
        scope="none",
        loader=_load_company_id,
        rule_domains=(),
        spec_ids=("CMP",),
    )(_decide_set_active(True))
    registry.command(
        name="contact_create",
        input_model=ContactCreateInput,
        output_model=ContactSummary,
        actor="staff",
        scope="none",
        loader=_load_contact_create,
        rule_domains=(),
        spec_ids=("CMP",),
    )(_decide_contact_create)
    registry.command(
        name="contact_update",
        input_model=ContactUpdateInput,
        output_model=ContactSummary,
        actor="staff",
        scope="none",
        loader=_load_contact_update,
        rule_domains=(),
        spec_ids=("CMP",),
    )(_decide_contact_update)
    registry.command(
        name="contact_delete",
        input_model=ContactIdInput,
        output_model=ContactSummary,
        actor="staff",
        scope="none",
        loader=_load_contact_id,
        rule_domains=(),
        spec_ids=("CMP",),
    )(_decide_contact_delete)
    registry.command(
        name="merge_companies",
        input_model=MergeCompaniesInput,
        output_model=MergeCompaniesSummary,
        actor="admin",
        scope="none",
        loader=_load_merge,
        rule_domains=(),
        spec_ids=("CMP",),
    )(_decide_merge)
