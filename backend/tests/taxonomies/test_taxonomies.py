"""Taxonomy and global-configuration contracts for Behavior TAX."""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.authz import Authorizer
from app.core.db import create_engine
from app.core.errors import INVALID_REQUEST, DomainRejection
from app.core.executor import Executor
from app.core.plan import ActorContext, Result
from app.core.registry import Registry
from app.main import create_app
from app.modules.identity.session import hash_session_token
from app.modules.taxonomies.commands import (
    SetSettingInput,
    SettingKey,
    TaxonomyKind,
    UpsertTaxonomyItemInput,
    register_taxonomy_commands,
)
from app.seed import BRANCHES, PROGRAMS, ROUND_TYPES, SECTORS, STUDENTS, run_seed
from app.settings import Settings


@pytest_asyncio.fixture(autouse=True)
async def clean_taxonomy_tables() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "TRUNCATE audit_log, settings, program_branches, programs, "
                    "branches, minors, sectors, round_types, sessions, enrollments, "
                    "users CASCADE"
                )
            )
    finally:
        await engine.dispose()


async def _seed_admin(connection: object) -> tuple[UUID, UUID]:
    user_id, session_id = uuid4(), uuid4()
    await connection.execute(  # type: ignore[attr-defined]
        sa.text(
            "INSERT INTO users (id, email, full_name, role) "
            "VALUES (:id, 'admin@example.edu', 'Admin', 'admin')"
        ),
        {"id": user_id},
    )
    await connection.execute(  # type: ignore[attr-defined]
        sa.text(
            "INSERT INTO sessions (id, token_hash, user_id, expires_at) "
            "VALUES (:id, :token, :user_id, now() + interval '1 day')"
        ),
        {"id": session_id, "token": str(session_id), "user_id": user_id},
    )
    return user_id, session_id


def _actor(user_id: UUID, session_id: UUID) -> ActorContext:
    return ActorContext(
        principal_id=str(user_id),
        user_id=user_id,
        role="admin",
        session_id=session_id,
    )


def _executor() -> tuple[Executor, object]:
    registry = Registry()
    register_taxonomy_commands(registry)
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker[AsyncSession](
        engine, expire_on_commit=False, autobegin=False
    )
    return (
        Executor(
            registry=registry,
            session_factory=factory,
            authorizer=Authorizer(),
        ),
        engine,
    )


async def _upsert(
    executor: Executor,
    actor: ActorContext,
    kind: TaxonomyKind,
    name: str,
    *,
    item_id: UUID | None = None,
    branch_ids: list[UUID] | None = None,
    is_active: bool = True,
) -> Result:
    result = await executor.run(
        "upsert_taxonomy_item",
        UpsertTaxonomyItemInput(
            kind=kind,
            item_id=item_id,
            name=name,
            branch_ids=branch_ids,
            is_active=is_active,
        ),
        actor,
    )
    assert isinstance(result, Result)
    return result


@pytest.mark.asyncio
async def test_TAX_referenced_item_delete_deactivates_and_unreferenced_deletes() -> None:
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    executor, engine = _executor()
    try:
        async with migration.begin() as connection:
            admin_id, session_id = await _seed_admin(connection)
        actor = _actor(admin_id, session_id)
        sector = await _upsert(executor, actor, TaxonomyKind.SECTOR, "Technology")
        sector_id = UUID(str(sector.summary["item_id"]))
        minor = await _upsert(executor, actor, TaxonomyKind.MINOR, "Robotics")
        minor_id = UUID(str(minor.summary["item_id"]))
        async with migration.begin() as connection:
            await connection.execute(
                sa.text(
                    "INSERT INTO companies (name, sector_id, is_active) "
                    "VALUES ('Example Co', :sector_id, true)"
                ),
                {"sector_id": sector_id},
            )

        referenced = await executor.run(
            "upsert_taxonomy_item",
            UpsertTaxonomyItemInput(
                kind=TaxonomyKind.SECTOR,
                item_id=sector_id,
                action="delete",
            ),
            actor,
        )
        unreferenced = await executor.run(
            "upsert_taxonomy_item",
            UpsertTaxonomyItemInput(
                kind=TaxonomyKind.MINOR,
                item_id=minor_id,
                action="delete",
            ),
            actor,
        )
        async with migration.connect() as connection:
            sector_active = await connection.scalar(
                sa.text("SELECT is_active FROM sectors WHERE id = :id"),
                {"id": sector_id},
            )
            minor_count = await connection.scalar(
                sa.text("SELECT count(*) FROM minors WHERE id = :id"),
                {"id": minor_id},
            )
    finally:
        await engine.dispose()  # type: ignore[union-attr]
        await migration.dispose()

    assert referenced.summary["action"] == "deactivated"
    assert referenced.summary["is_active"] is False
    assert unreferenced.summary["action"] == "deleted"
    assert sector_active is False
    assert minor_count == 0


@pytest.mark.asyncio
async def test_TAX_program_branch_map_edits_are_exact_and_integrity_checked() -> None:
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    executor, engine = _executor()
    try:
        async with migration.begin() as connection:
            admin_id, session_id = await _seed_admin(connection)
        actor = _actor(admin_id, session_id)
        first = await _upsert(executor, actor, TaxonomyKind.BRANCH, "CSE")
        second = await _upsert(executor, actor, TaxonomyKind.BRANCH, "EE")
        first_id = UUID(str(first.summary["item_id"]))
        second_id = UUID(str(second.summary["item_id"]))
        program = await _upsert(
            executor,
            actor,
            TaxonomyKind.PROGRAM,
            "BTech",
            branch_ids=[first_id, second_id],
        )
        program_id = UUID(str(program.summary["item_id"]))
        changed = await _upsert(
            executor,
            actor,
            TaxonomyKind.PROGRAM,
            "BTech",
            item_id=program_id,
            branch_ids=[second_id],
        )
        with pytest.raises(DomainRejection) as error:
            await _upsert(
                executor,
                actor,
                TaxonomyKind.PROGRAM,
                "BTech",
                item_id=program_id,
                branch_ids=[uuid4()],
            )
        async with migration.connect() as connection:
            mappings = tuple(
                (
                    await connection.execute(
                        sa.text(
                            "SELECT branch_id FROM program_branches "
                            "WHERE program_id = :id"
                        ),
                        {"id": program_id},
                    )
                ).scalars()
            )
    finally:
        await engine.dispose()  # type: ignore[union-attr]
        await migration.dispose()

    assert changed.summary["branch_ids"] == [str(second_id)]
    assert mappings == (second_id,)
    assert [reason.code for reason in error.value.rejection.reasons] == [
        INVALID_REQUEST
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"key": "strikes_per_penalty", "value": True},
        {"key": "strikes_per_penalty", "value": "2"},
        {"key": "strikes_per_penalty", "value": 0},
        {"key": "strikes_per_penalty", "value": -1},
        {"key": "session_hours", "value": None},
        {"key": "session_hours", "value": "24"},
        {"key": "ses_sender", "value": 42},
        {"key": "unknown", "value": "anything"},
    ],
)
def test_TAX_settings_reject_values_outside_each_key_type(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        SetSettingInput.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"key": "strikes_per_penalty", "value": None},
        {"key": "strikes_per_penalty", "value": 1},
        {"key": "strikes_per_penalty", "value": 2},
        {"key": "session_hours", "value": 24},
        {"key": "ses_sender", "value": "placements@example.edu"},
    ],
)
def test_TAX_settings_accept_the_documented_typed_values(
    payload: dict[str, object],
) -> None:
    assert SetSettingInput.model_validate(payload).value == payload["value"]


def test_TAX_zero_strikes_threshold_is_rejected_because_null_disables_conversion() -> None:
    with pytest.raises(ValidationError):
        SetSettingInput(key=SettingKey.STRIKES_PER_PENALTY, value=0)
    assert SetSettingInput(
        key=SettingKey.STRIKES_PER_PENALTY, value=None
    ).value is None


@pytest.mark.asyncio
async def test_TAX_audit_rows_version_taxonomy_and_setting_before_after() -> None:
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    executor, engine = _executor()
    try:
        async with migration.begin() as connection:
            admin_id, session_id = await _seed_admin(connection)
        actor = _actor(admin_id, session_id)
        created = await _upsert(executor, actor, TaxonomyKind.SECTOR, "Tech")
        sector_id = UUID(str(created.summary["item_id"]))
        await _upsert(
            executor,
            actor,
            TaxonomyKind.SECTOR,
            "Technology",
            item_id=sector_id,
        )
        await executor.run(
            "set_setting",
            SetSettingInput(key=SettingKey.SESSION_HOURS, value=24),
            actor,
        )
        await executor.run(
            "set_setting",
            SetSettingInput(key=SettingKey.SESSION_HOURS, value=12),
            actor,
        )
        async with migration.connect() as connection:
            audits = (
                await connection.execute(
                    sa.text(
                        "SELECT action, details FROM audit_log "
                        "ORDER BY created_at, id"
                    )
                )
            ).mappings().all()
    finally:
        await engine.dispose()  # type: ignore[union-attr]
        await migration.dispose()

    taxonomy_update = [
        row for row in audits if row["action"] == "upsert_taxonomy_item"
    ][-1]["details"]
    setting_update = [row for row in audits if row["action"] == "set_setting"][-1][
        "details"
    ]
    assert taxonomy_update["before"]["name"] == "Tech"
    assert taxonomy_update["after"]["name"] == "Technology"
    assert setting_update == {
        "before": {"key": "session_hours", "value": 24},
        "after": {"key": "session_hours", "value": 12},
    }


@pytest.mark.asyncio
async def test_TAX_admin_screens_are_authorized_and_return_current_configuration() -> None:
    settings = Settings(
        session_secret="taxonomy-screen-test-secret-32-characters",
        dev_login=False,
    )
    raw_token = "admin-screen-token"
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin_id, _ = await _seed_admin(connection)
            await connection.execute(
                sa.text(
                    "UPDATE sessions SET token_hash = :token_hash WHERE user_id = :user_id"
                ),
                {
                    "token_hash": hash_session_token(
                        raw_token, settings.session_secret
                    ),
                    "user_id": admin_id,
                },
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO sectors (name, is_active) "
                    "VALUES ('Technology', true)"
                )
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO settings (key, value, updated_by) "
                    "VALUES ('session_hours', '24'::jsonb, :user_id)"
                ),
                {"user_id": admin_id},
            )
        application = create_app(os.environ["TEST_DATABASE_URL"], settings=settings)
        async with application.router.lifespan_context(application):
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(
                transport=transport, base_url="https://test"
            ) as client:
                denied = await client.get("/api/v1/screens/admin/taxonomies")
                client.cookies.set("cds_session", raw_token)
                taxonomies = await client.get("/api/v1/screens/admin/taxonomies")
                configured = await client.get("/api/v1/screens/admin/settings")
                await client.get("/me")
                csrf = client.cookies.get("cds_csrf")
                assert csrf is not None
                edited = await client.post(
                    "/api/v1/commands/upsert_taxonomy_item",
                    json={
                        "input": {
                            "kind": "sectors",
                            "item_id": taxonomies.json()["sectors"][0]["id"],
                            "name": "Software",
                        }
                    },
                    headers={"X-CSRF": csrf},
                )
                refreshed = await client.get(
                    "/api/v1/screens/admin/taxonomies"
                )
    finally:
        await migration.dispose()

    assert denied.status_code == 401
    assert taxonomies.status_code == 200
    assert taxonomies.json()["sectors"][0]["name"] == "Technology"
    assert configured.status_code == 200
    assert configured.json()["settings"][0]["value"] == 24
    assert edited.status_code == 200
    assert edited.json()["summary"]["action"] == "updated"
    assert refreshed.json()["sectors"][0]["name"] == "Software"


@pytest.mark.asyncio
async def test_TAX_seed_v1_is_idempotent_and_builds_the_admin_vocabulary() -> None:
    settings = Settings(
        session_secret="taxonomy-seed-test-secret-32-characters",
        allowed_domain="example.edu",
        dev_login=False,
    )
    await run_seed(
        database_url=os.environ["TEST_DATABASE_URL"],
        settings=settings,
        admin_email="seed.admin@example.edu",
    )
    await run_seed(
        database_url=os.environ["TEST_DATABASE_URL"],
        settings=settings,
        admin_email="seed.admin@example.edu",
    )

    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.connect() as connection:
            counts = {
                table: await connection.scalar(sa.text(f"SELECT count(*) FROM {table}"))
                for table in (
                    "users",
                    "programs",
                    "branches",
                    "program_branches",
                    "sectors",
                    "round_types",
                )
            }
            admin_role = await connection.scalar(
                sa.text("SELECT role FROM users WHERE email = 'seed.admin@example.edu'")
            )
            role_bootstraps = await connection.scalar(
                sa.text(
                    "SELECT count(*) FROM audit_log WHERE action = 'set_user_role'"
                )
            )
    finally:
        await migration.dispose()

    assert counts == {
        # The admin, the coordinator, and one user per seeded student. Running
        # the seed twice adds none of them again, which is what this asserts.
        "users": 2 + len(STUDENTS),
        "programs": len(PROGRAMS),
        "branches": len(BRANCHES),
        "program_branches": sum(len(branches) for branches in PROGRAMS.values()),
        "sectors": len(SECTORS),
        "round_types": len(ROUND_TYPES),
    }
    assert admin_role == "admin"
    assert role_bootstraps == 1


@pytest.mark.asyncio
async def test_TAX_first_admin_bootstrap_is_seed_only_and_skips_when_admin_exists() -> None:
    settings = Settings(
        session_secret="taxonomy-bootstrap-test-secret-32-characters",
        allowed_domain="example.edu",
        dev_login=False,
    )
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            existing_admin_id, _ = await _seed_admin(connection)
        await run_seed(
            database_url=os.environ["TEST_DATABASE_URL"],
            settings=settings,
            admin_email="ignored-because-admin-exists@example.com",
        )
        async with migration.connect() as connection:
            users = (
                await connection.execute(
                    sa.text("SELECT id, email, role FROM users ORDER BY email")
                )
            ).mappings().all()
            role_bootstraps = await connection.scalar(
                sa.text(
                    "SELECT count(*) FROM audit_log WHERE action = 'set_user_role'"
                )
            )
    finally:
        await migration.dispose()

    application = create_app(os.environ["TEST_DATABASE_URL"], settings=settings)
    paths = set(application.openapi()["paths"])
    registry = application.state.command_registry

    # The point of the assertion is the admin: exactly one exists, it is the
    # one that was already there, and the seed did not promote anybody. The
    # seeded students and coordinator are ordinary users and say nothing about
    # bootstrap, so they are counted rather than enumerated.
    admins = [row for row in users if row["role"] == "admin"]
    assert [(row["id"], str(row["email"])) for row in admins] == [
        (existing_admin_id, "admin@example.edu")
    ]
    assert len(users) == 2 + len(STUDENTS)
    assert all(row["role"] == "student" for row in users if row not in admins)
    assert role_bootstraps == 0
    assert registry.commands["set_user_role"].actor == "admin"
    assert registry.commands["google_login"].expose_http is False
    assert "/api/v1/commands/google_login" not in paths
    assert all("seed" not in path and "bootstrap" not in path for path in paths)
