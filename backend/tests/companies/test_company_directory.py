"""Directory CRUD, contacts, and the active flag (Behavior section 4, CMP)."""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import create_engine
from app.core.errors import (
    COMPANY_NAME_CONFLICT,
    COMPANY_NAME_CONFLICT_INACTIVE,
    COMPANY_NOT_FOUND,
    CONTACT_EMAIL_CONFLICT,
    CONTACT_NOT_FOUND,
    INVALID_FIELD_VALUE,
    UNKNOWN_TAXONOMY_VALUE,
    AuthorizationDenied,
    DomainRejection,
)
from app.core.executor import Executor
from app.core.plan import ActorContext, Result
from app.modules.companies.commands import UpdateCompanyInput
from app.modules.companies.queries import staff_companies
from tests.companies.conftest import (
    WEBSITE,
    build_test_executor,
    seed_admin,
    seed_company,
    seed_contact,
    seed_coordinator,
    seed_sector,
)

pytestmark = pytest.mark.usefixtures("clean_companies")


async def _run(
    executor: Executor, name: str, payload: dict[str, object], actor: ActorContext
) -> Result:
    spec = executor.registry.commands[name]
    result = await executor.run(name, spec.input_model.model_validate(payload), actor)
    assert isinstance(result, Result)
    return result


async def _reasons(
    executor: Executor, name: str, payload: dict[str, object], actor: ActorContext
) -> list[tuple[str, str | None]]:
    with pytest.raises(DomainRejection) as rejection:
        await _run(executor, name, payload, actor)
    return [(reason.code, reason.path) for reason in rejection.value.rejection.reasons]


@pytest.mark.asyncio
async def test_CMP_company_names_are_unique_case_insensitively() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            other = await seed_company(connection, "Globex")
        created = await _run(executor, "create_company", {"name": "  Acme   Corp "}, admin.actor)
        duplicate = await _reasons(executor, "create_company", {"name": "ACME CORP"}, admin.actor)
        renamed = await _reasons(
            executor,
            "update_company",
            {"company_id": str(other), "name": "acme corp"},
            admin.actor,
        )
        self_rename = await _run(
            executor,
            "update_company",
            {"company_id": cast(str, created.summary["company_id"]), "name": "Acme Corp"},
            admin.actor,
        )
        async with migration.connect() as connection:
            names = (
                await connection.execute(sa.text("SELECT name FROM companies ORDER BY name"))
            ).scalars().all()
    finally:
        await engine.dispose()
        await migration.dispose()

    assert created.summary["name"] == "Acme Corp"
    assert duplicate == [(COMPANY_NAME_CONFLICT, "name")]
    assert renamed == [(COMPANY_NAME_CONFLICT, "name")]
    assert self_rename.summary["changed"] is False
    assert names == ["Acme Corp", "Globex"]


@pytest.mark.asyncio
async def test_CMP_a_name_clash_with_a_deactivated_company_names_the_way_forward() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            coordinator = await seed_coordinator(connection)
            await seed_company(connection, "Retired Corp", is_active=False)
            live = await seed_company(connection, "Live Corp")
        with pytest.raises(DomainRejection) as rejection:
            await _run(
                executor, "create_company", {"name": "retired corp"}, coordinator.actor
            )
        renamed = await _reasons(
            executor,
            "update_company",
            {"company_id": str(live), "name": "RETIRED CORP"},
            admin.actor,
        )
    finally:
        await engine.dispose()
        await migration.dispose()

    reason = rejection.value.rejection.reasons[0]
    assert reason.code == COMPANY_NAME_CONFLICT_INACTIVE
    assert "deactivated" in reason.human
    assert "reactivate" in reason.human
    assert "Retired Corp" in reason.human
    assert renamed == [(COMPANY_NAME_CONFLICT_INACTIVE, "name")]


@pytest.mark.asyncio
async def test_CMP_parallel_creates_of_one_name_serialize() -> None:
    executor, engine = build_test_executor()
    spec = executor.registry.commands["create_company"]
    original_loader = spec.loader
    barrier = asyncio.Barrier(2)

    async def synchronized_loader(
        tx: AsyncSession, input_value: object, *, lock: bool
    ) -> object:
        await barrier.wait()
        return await original_loader(tx, input_value, lock=lock)

    executor.registry.commands["create_company"] = replace(spec, loader=synchronized_loader)
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
        results = await asyncio.gather(
            _run(executor, "create_company", {"name": "Race Corp"}, admin.actor),
            _run(executor, "create_company", {"name": "race corp"}, admin.actor),
            return_exceptions=True,
        )
        async with migration.connect() as connection:
            count = await connection.scalar(
                sa.text("SELECT count(*) FROM companies WHERE name = 'Race Corp'")
            )
    finally:
        await engine.dispose()
        await migration.dispose()

    rejections = [item for item in results if isinstance(item, DomainRejection)]
    assert len(rejections) == 1
    assert [reason.code for reason in rejections[0].rejection.reasons] == [
        COMPANY_NAME_CONFLICT
    ]
    assert count == 1


@pytest.mark.asyncio
async def test_CMP_sector_must_exist_and_be_active_and_websites_must_be_https() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            sector_id = await seed_sector(connection)
            retired_sector = await seed_sector(connection, "Retired")
            await connection.execute(
                sa.text("UPDATE sectors SET is_active = false WHERE id = :id"),
                {"id": retired_sector},
            )
        unknown = await _reasons(
            executor,
            "create_company",
            {"name": "Unknown Sector", "sector_id": str(uuid4())},
            admin.actor,
        )
        inactive = await _reasons(
            executor,
            "create_company",
            {"name": "Inactive Sector", "sector_id": str(retired_sector)},
            admin.actor,
        )
        plain_http = await _reasons(
            executor,
            "create_company",
            {"name": "Insecure", "website_url": "http://acme.example"},
            admin.actor,
        )
        accepted = await _run(
            executor,
            "create_company",
            {"name": "Acme", "sector_id": str(sector_id), "website_url": WEBSITE},
            admin.actor,
        )
    finally:
        await engine.dispose()
        await migration.dispose()

    assert unknown == [(UNKNOWN_TAXONOMY_VALUE, "sector_id")]
    assert inactive == [(UNKNOWN_TAXONOMY_VALUE, "sector_id")]
    assert plain_http == [(INVALID_FIELD_VALUE, "website_url")]
    assert accepted.summary["changed"] is True


@pytest.mark.asyncio
async def test_CMP_update_company_cannot_flip_the_active_flag() -> None:
    with pytest.raises(ValidationError):
        UpdateCompanyInput.model_validate(
            {"company_id": str(uuid4()), "is_active": False}
        )


@pytest.mark.asyncio
async def test_CMP_coordinators_edit_the_directory_but_only_admins_retire_it() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            coordinator = await seed_coordinator(connection)
            company_id = await seed_company(connection, "Shared Corp")
        await _run(
            executor,
            "update_company",
            {"company_id": str(company_id), "description": "Edited by a coordinator"},
            coordinator.actor,
        )
        with pytest.raises(AuthorizationDenied):
            await _run(
                executor, "deactivate_company", {"company_id": str(company_id)}, coordinator.actor
            )
        deactivated = await _run(
            executor, "deactivate_company", {"company_id": str(company_id)}, admin.actor
        )
        hidden = await staff_companies(engine)
        visible = await staff_companies(engine, include_inactive=True)
        reactivated = await _run(
            executor, "activate_company", {"company_id": str(company_id)}, admin.actor
        )
        restored = await staff_companies(engine)
        unchanged = await _run(
            executor, "activate_company", {"company_id": str(company_id)}, admin.actor
        )
        missing = await _reasons(
            executor, "activate_company", {"company_id": str(uuid4())}, admin.actor
        )
    finally:
        await engine.dispose()
        await migration.dispose()

    assert deactivated.summary["is_active"] is False
    assert cast(list[object], hidden["companies"]) == []
    assert len(cast(list[object], visible["companies"])) == 1
    assert reactivated.summary["is_active"] is True
    assert len(cast(list[object], restored["companies"])) == 1
    assert unchanged.summary["changed"] is False
    assert missing == [(COMPANY_NOT_FOUND, None)]


@pytest.mark.asyncio
async def test_CMP_the_first_contact_becomes_primary_and_the_flip_is_atomic() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            company_id = await seed_company(connection, "Acme")
        first = await _run(
            executor,
            "contact_create",
            {"company_id": str(company_id), "name": "First", "email": "first@acme.example"},
            admin.actor,
        )
        second = await _run(
            executor,
            "contact_create",
            {"company_id": str(company_id), "name": "Second", "email": "second@acme.example"},
            admin.actor,
        )
        promoted = await _run(
            executor,
            "contact_update",
            {
                "company_id": str(company_id),
                "contact_id": cast(str, second.summary["contact_id"]),
                "is_primary": True,
            },
            admin.actor,
        )
        async with migration.connect() as connection:
            rows = (
                await connection.execute(
                    sa.text(
                        "SELECT id, is_primary FROM company_contacts ORDER BY created_at, id"
                    )
                )
            ).mappings().all()
    finally:
        await engine.dispose()
        await migration.dispose()

    assert first.summary["is_primary"] is True
    assert second.summary["is_primary"] is False
    assert promoted.summary["is_primary"] is True
    assert [(str(row["id"]), row["is_primary"]) for row in rows] == [
        (cast(str, first.summary["contact_id"]), False),
        (cast(str, second.summary["contact_id"]), True),
    ]


@pytest.mark.asyncio
async def test_CMP_contact_emails_are_unique_per_company_not_globally() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            acme = await seed_company(connection, "Acme")
            globex = await seed_company(connection, "Globex")
            existing = await seed_contact(
                connection, acme, name="Recruiter", email="hire@acme.example", is_primary=True
            )
            other = await seed_contact(
                connection, acme, name="Other", email="other@acme.example"
            )
        duplicate = await _reasons(
            executor,
            "contact_create",
            {"company_id": str(acme), "name": "Copy", "email": "HIRE@acme.example"},
            admin.actor,
        )
        cross_company = await _run(
            executor,
            "contact_create",
            {"company_id": str(globex), "name": "Same Person", "email": "hire@acme.example"},
            admin.actor,
        )
        collide_on_edit = await _reasons(
            executor,
            "contact_update",
            {
                "company_id": str(acme),
                "contact_id": str(other),
                "email": "hire@acme.example",
            },
            admin.actor,
        )
        invalid = await _reasons(
            executor,
            "contact_create",
            {"company_id": str(acme), "name": "Bad", "email": "not-an-email"},
            admin.actor,
        )
        missing_contact = await _reasons(
            executor,
            "contact_update",
            {"company_id": str(acme), "contact_id": str(uuid4()), "name": "Ghost"},
            admin.actor,
        )
        missing_company = await _reasons(
            executor,
            "contact_create",
            {"company_id": str(uuid4()), "name": "Ghost", "email": "ghost@example.com"},
            admin.actor,
        )
    finally:
        await engine.dispose()
        await migration.dispose()

    assert duplicate == [(CONTACT_EMAIL_CONFLICT, "email")]
    assert cross_company.summary["is_primary"] is True
    assert collide_on_edit == [(CONTACT_EMAIL_CONFLICT, "email")]
    assert invalid == [(INVALID_FIELD_VALUE, "email")]
    assert missing_contact == [(CONTACT_NOT_FOUND, "contact_id")]
    assert missing_company == [(COMPANY_NOT_FOUND, "company_id")]
    assert existing is not None


@pytest.mark.asyncio
async def test_CMP_deleting_the_primary_contact_leaves_the_company_without_one() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            company_id = await seed_company(connection, "Acme")
            primary = await seed_contact(
                connection, company_id, name="Primary", email="p@acme.example", is_primary=True
            )
            secondary = await seed_contact(
                connection, company_id, name="Secondary", email="s@acme.example"
            )
        result = await _run(
            executor,
            "contact_delete",
            {"company_id": str(company_id), "contact_id": str(primary)},
            admin.actor,
        )
        async with migration.connect() as connection:
            rows = (
                await connection.execute(
                    sa.text("SELECT id, is_primary FROM company_contacts")
                )
            ).mappings().all()
            audit = (
                await connection.execute(
                    sa.text(
                        "SELECT details FROM audit_log WHERE action = 'contact_delete'"
                    )
                )
            ).mappings().one()
    finally:
        await engine.dispose()
        await migration.dispose()

    assert result.summary["changed"] is True
    assert [(row["id"], row["is_primary"]) for row in rows] == [(secondary, False)]
    assert audit["details"]["before"]["email"] == "p@acme.example"
    assert audit["details"]["after"] is None


@pytest.mark.asyncio
async def test_CMP_directory_edits_are_audited_with_before_and_after() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            sector_id = await seed_sector(connection)
        created = await _run(
            executor, "create_company", {"name": "Acme", "description": "Old"}, admin.actor
        )
        company_id = cast(str, created.summary["company_id"])
        await _run(
            executor,
            "update_company",
            {
                "company_id": company_id,
                "description": "New",
                "sector_id": str(sector_id),
                "website_url": WEBSITE,
            },
            admin.actor,
        )
        async with migration.connect() as connection:
            audits = (
                await connection.execute(
                    sa.text(
                        "SELECT action, subject_type, subject_id, details FROM audit_log "
                        "ORDER BY created_at, action"
                    )
                )
            ).mappings().all()
            stored = (
                await connection.execute(
                    sa.text(
                        "SELECT description, website_url, sector_id FROM companies "
                        "WHERE id = :id"
                    ),
                    {"id": UUID(company_id)},
                )
            ).mappings().one()
    finally:
        await engine.dispose()
        await migration.dispose()

    assert [entry["action"] for entry in audits] == ["create_company", "update_company"]
    assert audits[0]["details"]["before"] is None
    assert audits[0]["details"]["after"]["name"] == "Acme"
    assert audits[1]["details"]["before"]["description"] == "Old"
    assert audits[1]["details"]["after"]["description"] == "New"
    assert audits[1]["details"]["after"]["sector_id"] == str(sector_id)
    assert stored["description"] == "New"
    assert stored["website_url"] == WEBSITE
    assert stored["sector_id"] == sector_id
