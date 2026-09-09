"""Merging duplicate companies: preview parity, repointing, audit (CMP)."""

from __future__ import annotations

import os
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import (
    COMPANY_INACTIVE,
    COMPANY_NOT_FOUND,
    MERGE_INTO_SELF,
    DomainRejection,
)
from app.core.executor import Executor
from app.core.plan import ActorContext, Preview, Result
from app.modules.companies.commands import MERGE_AUDIT_ACTION
from tests.companies.conftest import (
    build_test_executor,
    seed_admin,
    seed_company,
    seed_contact,
    seed_external_offer,
    seed_job,
)

pytestmark = pytest.mark.usefixtures("clean_companies")


async def _merge(
    executor: Executor,
    actor: ActorContext,
    survivor: UUID,
    duplicate: UUID,
    *,
    dry_run: bool = False,
) -> Preview | Result:
    spec = executor.registry.commands["merge_companies"]
    return await executor.run(
        "merge_companies",
        spec.input_model.model_validate(
            {"survivor_id": str(survivor), "duplicate_id": str(duplicate)}
        ),
        actor,
        dry_run=dry_run,
    )


@pytest.mark.asyncio
async def test_CMP_merge_preview_counts_match_what_execution_repoints() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            survivor = await seed_company(connection, "Acme Corporation")
            duplicate = await seed_company(connection, "Acme Corp")
            await seed_contact(
                connection, survivor, name="Survivor", email="hr@acme.example", is_primary=True
            )
            await seed_contact(connection, duplicate, name="Campus", email="campus@acme.example")
            await seed_job(connection, duplicate, title="Duplicate Job One")
            await seed_job(connection, duplicate, title="Duplicate Job Two")
            await seed_external_offer(connection, duplicate, created_by=admin.user_id)

        preview = await _merge(executor, admin.actor, survivor, duplicate, dry_run=True)
        async with migration.connect() as connection:
            untouched_jobs = await connection.scalar(
                sa.text("SELECT count(*) FROM jobs WHERE company_id = :id"),
                {"id": duplicate},
            )
            still_active = await connection.scalar(
                sa.text("SELECT is_active FROM companies WHERE id = :id"), {"id": duplicate}
            )
        executed = await _merge(executor, admin.actor, survivor, duplicate)
        async with migration.connect() as connection:
            moved_jobs = await connection.scalar(
                sa.text("SELECT count(*) FROM jobs WHERE company_id = :id"), {"id": survivor}
            )
            moved_offers = await connection.scalar(
                sa.text("SELECT count(*) FROM external_offers WHERE company_id = :id"),
                {"id": survivor},
            )
            moved_contacts = await connection.scalar(
                sa.text("SELECT count(*) FROM company_contacts WHERE company_id = :id"),
                {"id": survivor},
            )
            duplicate_active = await connection.scalar(
                sa.text("SELECT is_active FROM companies WHERE id = :id"), {"id": duplicate}
            )
    finally:
        await engine.dispose()
        await migration.dispose()

    assert isinstance(preview, Preview)
    assert preview.summary == executed.summary
    assert untouched_jobs == 2
    assert still_active is True
    assert preview.summary["jobs"] == moved_jobs == 2
    assert preview.summary["external_offers"] == moved_offers == 1
    assert preview.summary["contacts_repointed"] == 1
    assert moved_contacts == 2
    assert duplicate_active is False


@pytest.mark.asyncio
async def test_CMP_merge_drops_colliding_contacts_with_their_full_details() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            survivor = await seed_company(connection, "Acme Corporation")
            duplicate = await seed_company(connection, "Acme Corp")
            await seed_contact(
                connection,
                survivor,
                name="Stale Name",
                email="hr@acme.example",
                is_primary=True,
            )
            dropped = await seed_contact(
                connection,
                duplicate,
                name="Current Name",
                email="HR@acme.example",
                phone="+1 202-555-0100",
                designation="Head of Campus Hiring",
                is_primary=True,
            )
        executed = await _merge(executor, admin.actor, survivor, duplicate)
        async with migration.connect() as connection:
            remaining = (
                await connection.execute(
                    sa.text(
                        "SELECT email, is_primary, company_id FROM company_contacts"
                    )
                )
            ).mappings().all()
            audits = (
                await connection.execute(
                    sa.text(
                        "SELECT action, subject_id, details FROM audit_log "
                        "ORDER BY action"
                    )
                )
            ).mappings().all()
    finally:
        await engine.dispose()
        await migration.dispose()

    dropped_payloads = cast(list[dict[str, object]], executed.summary["contacts_dropped"])
    assert dropped_payloads == [
        {
            "id": str(dropped),
            "name": "Current Name",
            "email": "HR@acme.example",
            "phone": "+1 202-555-0100",
            "designation": "Head of Campus Hiring",
            "is_primary": True,
        }
    ]
    assert [(row["email"], row["is_primary"], row["company_id"]) for row in remaining] == [
        ("hr@acme.example", True, survivor)
    ]
    # Nothing un-merges, so both audit rows keep every discarded field.
    assert [entry["action"] for entry in audits] == ["merge_companies", MERGE_AUDIT_ACTION]
    assert [entry["subject_id"] for entry in audits] == [survivor, duplicate]
    for entry in audits:
        assert entry["details"]["contacts_dropped"] == dropped_payloads
        assert entry["details"]["survivor"]["id"] == str(survivor)
        assert entry["details"]["duplicate"]["id"] == str(duplicate)


@pytest.mark.asyncio
async def test_CMP_merge_keeps_exactly_one_primary_contact() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            survivor = await seed_company(connection, "Acme Corporation")
            duplicate = await seed_company(connection, "Acme Corp")
            survivor_primary = await seed_contact(
                connection, survivor, name="Kept", email="kept@acme.example", is_primary=True
            )
            incoming = await seed_contact(
                connection,
                duplicate,
                name="Demoted",
                email="other@acme.example",
                is_primary=True,
            )

            headless = await seed_company(connection, "Headless")
            donor = await seed_company(connection, "Donor")
            donor_primary = await seed_contact(
                connection, donor, name="Promoted", email="donor@acme.example", is_primary=True
            )
        with_primary = await _merge(executor, admin.actor, survivor, duplicate)
        without_primary = await _merge(executor, admin.actor, headless, donor)
        async with migration.connect() as connection:
            rows = (
                await connection.execute(
                    sa.text(
                        "SELECT id, company_id, is_primary FROM company_contacts "
                        "ORDER BY email"
                    )
                )
            ).mappings().all()
    finally:
        await engine.dispose()
        await migration.dispose()

    assert with_primary.summary["primary_kept"] == str(survivor_primary)
    assert without_primary.summary["primary_kept"] == str(donor_primary)
    assert {(row["id"], row["company_id"], row["is_primary"]) for row in rows} == {
        (survivor_primary, survivor, True),
        (incoming, survivor, False),
        (donor_primary, headless, True),
    }


@pytest.mark.asyncio
async def test_CMP_merge_rejects_self_merges_and_inactive_survivors() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            active = await seed_company(connection, "Acme Corporation")
            retired = await seed_company(connection, "Retired Corp", is_active=False)

        async def reasons(survivor: UUID, duplicate: UUID) -> list[tuple[str, str | None]]:
            with pytest.raises(DomainRejection) as rejection:
                await _merge(executor, admin.actor, survivor, duplicate)
            return [
                (reason.code, reason.path) for reason in rejection.value.rejection.reasons
            ]

        self_merge = await reasons(active, active)
        inactive_survivor = await reasons(retired, active)
        missing = await reasons(active, uuid4())
        # A duplicate that was already retired may still be merged away.
        allowed = await _merge(executor, admin.actor, active, retired)
    finally:
        await engine.dispose()
        await migration.dispose()

    assert self_merge == [(MERGE_INTO_SELF, "duplicate_id")]
    assert inactive_survivor == [(COMPANY_INACTIVE, "survivor_id")]
    assert missing == [(COMPANY_NOT_FOUND, "duplicate_id")]
    assert allowed.summary["contacts_dropped"] == []
