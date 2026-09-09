"""Identity administration contracts for Behavior IDN-1, IDN-2, and IDN-3."""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.authz import Authorizer
from app.core.db import create_engine
from app.core.errors import LAST_ACTIVE_ADMIN, DomainRejection
from app.core.executor import Executor
from app.core.plan import ActorContext, Result
from app.core.registry import Registry
from app.domain.shared import Role
from app.modules.identity.admin_commands import (
    DeactivateUserInput,
    SetUserRoleInput,
    StartNewEnrollmentInput,
    register_identity_admin_commands,
)


@pytest_asyncio.fixture(autouse=True)
async def clean_identity_admin_tables() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "TRUNCATE audit_log, cycle_coordinators, profiles, sessions, "
                    "enrollments, users CASCADE"
                )
            )
    finally:
        await engine.dispose()


async def _seed_user(
    connection: object, *, email: str, role: str = "student", active: bool = True
) -> tuple[UUID, UUID, UUID]:
    user_id, enrollment_id, session_id = uuid4(), uuid4(), uuid4()
    await connection.execute(  # type: ignore[attr-defined]
        sa.text(
            "INSERT INTO users (id, email, full_name, role, is_active) "
            "VALUES (:id, :email, :name, CAST(:role AS role_t), :active)"
        ),
        {"id": user_id, "email": email, "name": email, "role": role, "active": active},
    )
    await connection.execute(  # type: ignore[attr-defined]
        sa.text(
            "INSERT INTO enrollments (id, user_id, is_current) "
            "VALUES (:id, :user_id, true)"
        ),
        {"id": enrollment_id, "user_id": user_id},
    )
    await connection.execute(  # type: ignore[attr-defined]
        sa.text(
            "INSERT INTO sessions (id, token_hash, user_id, expires_at) "
            "VALUES (:id, :token, :user_id, now() + interval '1 day')"
        ),
        {"id": session_id, "token": str(session_id), "user_id": user_id},
    )
    return user_id, enrollment_id, session_id


def _actor(user_id: UUID, session_id: UUID) -> ActorContext:
    return ActorContext(
        principal_id=str(user_id), user_id=user_id, role="admin", session_id=session_id
    )


def _executor(registry: Registry | None = None) -> tuple[Executor, object, Registry]:
    resolved = registry or Registry()
    if not resolved.commands:
        register_identity_admin_commands(resolved)
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker[AsyncSession](
        engine, expire_on_commit=False, autobegin=False
    )
    return (
        Executor(
            registry=resolved,
            session_factory=factory,
            authorizer=Authorizer(),
        ),
        engine,
        resolved,
    )


@pytest.mark.asyncio
async def test_IDN2_start_new_enrollment_preserves_history_and_changes_current() -> None:
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin_id, _, admin_session = await _seed_user(
                connection, email="admin@example.edu", role="admin"
            )
            student_id, old_enrollment, _ = await _seed_user(
                connection, email="student@example.edu"
            )
        executor, engine, _ = _executor()
        try:
            result = await executor.run(
                "start_new_enrollment",
                StartNewEnrollmentInput(user_id=student_id),
                _actor(admin_id, admin_session),
            )
        finally:
            await engine.dispose()  # type: ignore[union-attr]
        assert isinstance(result, Result)
        async with migration.connect() as connection:
            rows = (
                await connection.execute(
                    sa.text(
                        "SELECT id, is_current FROM enrollments "
                        "WHERE user_id = :user_id ORDER BY created_at, id"
                    ),
                    {"user_id": student_id},
                )
            ).mappings().all()
    finally:
        await migration.dispose()

    assert len(rows) == 2
    assert next(row for row in rows if row["id"] == old_enrollment)["is_current"] is False
    assert sum(bool(row["is_current"]) for row in rows) == 1
    assert result.summary["new_enrollment_id"] in {str(row["id"]) for row in rows}


@pytest.mark.asyncio
async def test_IDN3_second_admin_demotion_is_rejected_as_last_active_admin() -> None:
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            first_id, _, first_session = await _seed_user(
                connection, email="first.admin@example.edu", role="admin"
            )
            second_id, _, _ = await _seed_user(
                connection, email="second.admin@example.edu", role="admin"
            )
        executor, engine, _ = _executor()
        actor = _actor(first_id, first_session)
        try:
            await executor.run(
                "set_user_role",
                SetUserRoleInput(user_id=second_id, role=Role.STUDENT),
                actor,
            )
            with pytest.raises(DomainRejection) as error:
                await executor.run(
                    "set_user_role",
                    SetUserRoleInput(user_id=first_id, role=Role.STUDENT),
                    actor,
                )
        finally:
            await engine.dispose()  # type: ignore[union-attr]
    finally:
        await migration.dispose()

    assert [reason.code for reason in error.value.rejection.reasons] == [
        LAST_ACTIVE_ADMIN
    ]


@pytest.mark.asyncio
async def test_IDN3_deactivate_user_revokes_sessions_and_protects_last_admin() -> None:
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin_id, _, admin_session = await _seed_user(
                connection, email="admin@example.edu", role="admin"
            )
            student_id, _, student_session = await _seed_user(
                connection, email="student@example.edu"
            )
        executor, engine, _ = _executor()
        actor = _actor(admin_id, admin_session)
        try:
            await executor.run(
                "deactivate_user", DeactivateUserInput(user_id=student_id), actor
            )
            with pytest.raises(DomainRejection) as error:
                await executor.run(
                    "deactivate_user", DeactivateUserInput(user_id=admin_id), actor
                )
        finally:
            await engine.dispose()  # type: ignore[union-attr]
        async with migration.connect() as connection:
            student = (
                await connection.execute(
                    sa.text("SELECT is_active FROM users WHERE id = :id"),
                    {"id": student_id},
                )
            ).mappings().one()
            revoked = await connection.scalar(
                sa.text("SELECT revoked_at IS NOT NULL FROM sessions WHERE id = :id"),
                {"id": student_session},
            )
    finally:
        await migration.dispose()

    assert student["is_active"] is False
    assert revoked is True
    assert [reason.code for reason in error.value.rejection.reasons] == [
        LAST_ACTIVE_ADMIN
    ]


@pytest.mark.asyncio
async def test_IDN3_parallel_admin_demotions_leave_one_active_admin() -> None:
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            first_id, _, first_session = await _seed_user(
                connection, email="first.admin@example.edu", role="admin"
            )
            second_id, _, second_session = await _seed_user(
                connection, email="second.admin@example.edu", role="admin"
            )

        registry = Registry()
        register_identity_admin_commands(registry)
        spec = registry.commands["set_user_role"]
        original_loader = spec.loader
        barrier = asyncio.Barrier(2)
        backend_pids: set[int] = set()

        async def parallel_loader(
            tx: AsyncSession, input_value: object, *, lock: bool
        ) -> object:
            pid = await tx.scalar(sa.text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            backend_pids.add(pid)
            await barrier.wait()
            return await original_loader(tx, input_value, lock=lock)

        registry.commands["set_user_role"] = replace(spec, loader=parallel_loader)
        executor, engine, _ = _executor(registry)
        try:
            outcomes = await asyncio.wait_for(
                asyncio.gather(
                    executor.run(
                        "set_user_role",
                        SetUserRoleInput(user_id=second_id, role=Role.STUDENT),
                        _actor(first_id, first_session),
                    ),
                    executor.run(
                        "set_user_role",
                        SetUserRoleInput(user_id=first_id, role=Role.STUDENT),
                        _actor(second_id, second_session),
                    ),
                    return_exceptions=True,
                ),
                timeout=5,
            )
        finally:
            await engine.dispose()  # type: ignore[union-attr]
        async with migration.connect() as connection:
            active_admins = await connection.scalar(
                sa.text("SELECT count(*) FROM users WHERE role = 'admin' AND is_active")
            )
    finally:
        await migration.dispose()

    assert len(backend_pids) == 2
    assert sum(isinstance(outcome, Result) for outcome in outcomes) == 1
    rejection = next(
        outcome for outcome in outcomes if isinstance(outcome, DomainRejection)
    )
    assert [reason.code for reason in rejection.rejection.reasons] == [
        LAST_ACTIVE_ADMIN
    ]
    assert active_admins == 1
