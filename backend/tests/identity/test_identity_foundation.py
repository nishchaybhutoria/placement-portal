"""Identity/session foundation contracts for Behavior IDN-1, IDN-2, and IDN-3."""

from __future__ import annotations

import asyncio
import importlib
import os
from dataclasses import replace
from uuid import UUID

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import create_engine
from app.core.executor import Executor
from app.core.plan import ActorContext
from app.core.registry import Registry


def test_IDN1_settings_reject_insecure_session_cookie_outside_dev_login() -> None:
    settings_module = importlib.import_module("app.settings")
    settings_type = settings_module.Settings

    with pytest.raises(ValueError, match="SESSION_COOKIE_SECURE"):
        settings_type(
            session_secret="test-session-secret-at-least-32-chars",
            google_client_id="google-client",
            google_client_secret="google-secret",
            allowed_domain="example.edu",
            dev_login=False,
            base_url="https://portal.example",
            session_cookie_secure=False,
        )


@pytest.mark.parametrize("secret", [None, "short-secret"])
def test_IDN1_settings_require_an_explicit_long_session_secret(
    secret: str | None,
) -> None:
    settings_module = importlib.import_module("app.settings")
    values: dict[str, object] = {
        "dev_login": True,
        "session_cookie_secure": False,
    }
    if secret is not None:
        values["session_secret"] = secret

    with pytest.raises(ValidationError):
        settings_module.Settings(**values)


@pytest.mark.asyncio
async def test_IDN2_parallel_first_login_creates_one_user_and_current_enrollment() -> None:
    settings_module = importlib.import_module("app.settings")
    identity_commands = importlib.import_module("app.modules.identity.commands")
    settings = settings_module.Settings(
        session_secret="parallel-login-session-secret-32-chars",
        google_client_id="google-client",
        google_client_secret="google-secret",
        allowed_domain="example.edu",
        dev_login=True,
        base_url="http://test",
        session_cookie_secure=False,
    )
    registry = Registry()
    identity_commands.register_identity_commands(registry, settings=settings)
    spec = registry.commands["google_login"]
    original_loader = spec.loader
    barrier = asyncio.Barrier(2)
    backend_pids: set[int] = set()

    async def synchronized_loader(
        tx: AsyncSession, input_value: object, *, lock: bool
    ) -> object:
        backend_pid = await tx.scalar(sa.text("SELECT pg_backend_pid()"))
        assert isinstance(backend_pid, int)
        backend_pids.add(backend_pid)
        await barrier.wait()
        return await original_loader(tx, input_value, lock=lock)

    registry.commands["google_login"] = replace(spec, loader=synchronized_loader)
    migration_engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    app_engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with migration_engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "TRUNCATE audit_log, cycle_coordinators, profiles, sessions, "
                    "enrollments, users CASCADE"
                )
            )
        session_factory = async_sessionmaker[AsyncSession](
            app_engine, expire_on_commit=False, autobegin=False
        )
        executor = Executor(registry=registry, session_factory=session_factory)
        first_input = identity_commands.new_login_input(
            email="New.Student@EXAMPLE.EDU",
            full_name="First Name",
            settings=settings,
        )
        second_input = identity_commands.new_login_input(
            email="new.student@example.edu",
            full_name="Second Name",
            settings=settings,
        )

        await asyncio.gather(
            executor.run("google_login", first_input, ActorContext(principal_id="anonymous")),
            executor.run("google_login", second_input, ActorContext(principal_id="anonymous")),
        )

        async with migration_engine.connect() as connection:
            user_count = await connection.scalar(
                sa.text("SELECT count(*) FROM users WHERE email = 'new.student@example.edu'")
            )
            enrollment_count = await connection.scalar(
                sa.text(
                    "SELECT count(*) FROM enrollments e JOIN users u ON u.id = e.user_id "
                    "WHERE u.email = 'new.student@example.edu' AND e.is_current"
                )
            )
            stored_name = await connection.scalar(
                sa.text("SELECT full_name FROM users WHERE email = 'new.student@example.edu'")
            )
    finally:
        await app_engine.dispose()
        await migration_engine.dispose()

    assert len(backend_pids) == 2
    assert user_count == 1
    assert enrollment_count == 1
    assert stored_name in {"First Name", "Second Name"}


def test_IDN3_actor_context_keeps_coordinator_capability_separate_from_role() -> None:
    session_id = UUID("00000000-0000-0000-0000-000000000101")
    enrollment_id = UUID("00000000-0000-0000-0000-000000000102")
    cycle_id = UUID("00000000-0000-0000-0000-000000000103")

    actor = ActorContext(
        principal_id="student@example.edu",
        role="student",
        session_id=session_id,
        current_enrollment_id=enrollment_id,
        coordinated_cycle_ids=(cycle_id,),
    )

    assert actor.role == "student"
    assert actor.session_id == session_id
    assert actor.current_enrollment_id == enrollment_id
    assert actor.coordinated_cycle_ids == (cycle_id,)
