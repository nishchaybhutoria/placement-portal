"""Server-side session command contracts for Behavior IDN-1 and IDN-2."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import create_engine
from app.core.errors import (
    INACTIVE_USER,
    OUTSIDE_ALLOWED_DOMAIN,
    SESSION_EFFECT_IDEMPOTENCY,
    DomainRejection,
)
from app.core.executor import Executor, ExecutorHooks
from app.core.plan import ActorContext, ScopeIds, StateOp
from app.core.registry import Registry
from app.modules.identity.commands import (
    LoginState,
    OAuthStateInput,
    PostLoginHooks,
    hash_session_token,
    new_login_input,
    new_oauth_state_input,
    oauth_state_key,
    register_identity_commands,
)
from app.modules.identity.session import SessionManager
from app.settings import Settings

FIXED_NOW = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
SESSION_SECRET = "command-test-session-secret-32-chars"


def _settings() -> Settings:
    return Settings(
        session_secret=SESSION_SECRET,
        google_client_id="google-client",
        google_client_secret="google-secret",
        allowed_domain="example.edu",
        dev_login=True,
        base_url="http://test",
        session_cookie_secure=False,
    )


@pytest_asyncio.fixture(autouse=True)
async def clean_identity_tables() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "TRUNCATE audit_log, cycle_coordinators, profiles, sessions, "
                    "enrollments, users, settings, idempotency_keys CASCADE"
                )
            )
    finally:
        await engine.dispose()


def _executor(*, hooks: PostLoginHooks | None = None) -> tuple[Executor, object]:
    registry = Registry()
    register_identity_commands(registry, settings=_settings(), hooks=hooks)
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker[AsyncSession](
        engine, expire_on_commit=False, autobegin=False
    )
    return Executor(registry=registry, session_factory=factory), engine


async def _row(
    statement: str, params: dict[str, object] | None = None
) -> RowMapping:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            return (await connection.execute(sa.text(statement), params or {})).mappings().one()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_IDN1_distinct_expired_restarts_overlap_without_lock_inversion() -> None:
    """Two restarts, each holding the row the other would purge, must not block.

    `_load_oauth_state_issue` takes locks in one order: this run's own
    superseded key with a plain `FOR UPDATE`, then the expired-key purge with
    `FOR UPDATE SKIP LOCKED`. The skip is what keeps the second stage from
    waiting on a row another restart already owns, so the two overlapping
    transactions here must both reach commit rather than deadlock.
    """
    first_old_state = "first-expired-oauth-state"
    second_old_state = "second-expired-oauth-state"
    first_old_key = oauth_state_key(first_old_state, SESSION_SECRET)
    second_old_key = oauth_state_key(second_old_state, SESSION_SECRET)
    migration_engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration_engine.begin() as connection:
            for key in (first_old_key, second_old_key):
                await connection.execute(
                    sa.text(
                        "INSERT INTO idempotency_keys (key, command, result) "
                        "VALUES (:key, 'issue_oauth_state', CAST(:result AS jsonb))"
                    ),
                    {
                        "key": key,
                        "result": json.dumps(
                            {
                                "kind": "oauth_state",
                                "expires_at": "2020-01-01T00:00:00+00:00",
                            }
                        ),
                    },
                )
    finally:
        await migration_engine.dispose()

    registry = Registry()
    register_identity_commands(registry, settings=_settings())
    issue_spec = registry.commands["issue_oauth_state"]
    original_loader = issue_spec.loader
    backend_pids: set[int] = set()
    # Both transactions must own their own superseded key before either runs
    # the purge; otherwise whichever transaction gets there first locks the
    # other's row before the other has claimed it, and the loser blocks on a
    # lock the winner will not release until a barrier the loser will never
    # reach. That race is an artefact of driving both runs from one event
    # loop, not the inversion under test, and it is what made this test flaky.
    load_barrier = asyncio.Barrier(2)

    async def tracking_loader(
        tx: AsyncSession, input_value: object, *, lock: bool
    ) -> object:
        backend_pid = await tx.scalar(sa.text("SELECT pg_backend_pid()"))
        assert isinstance(backend_pid, int)
        backend_pids.add(backend_pid)
        # The loader's own first statement, replayed: the lock it takes here
        # is the lock the loader would take a moment later, on this same
        # transaction, so nothing about the purge stage changes.
        await tx.execute(
            sa.text(
                "SELECT key FROM idempotency_keys "
                "WHERE command = 'issue_oauth_state' "
                "AND key = ANY(CAST(:keys AS text[])) ORDER BY key FOR UPDATE"
            ),
            {"keys": list(cast(OAuthStateInput, input_value)._superseded_keys)},
        )
        await load_barrier.wait()
        return await original_loader(tx, input_value, lock=lock)

    registry.commands["issue_oauth_state"] = replace(
        issue_spec, loader=tracking_loader
    )
    commit_barrier = asyncio.Barrier(2)

    async def overlap_before_commit() -> None:
        await commit_barrier.wait()

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker[AsyncSession](
        engine, expire_on_commit=False, autobegin=False
    )
    executor = Executor(
        registry=registry,
        session_factory=factory,
        hooks=ExecutorHooks(before_commit=overlap_before_commit),
    )
    actor = ActorContext(principal_id="oauth-system", is_system=True)
    first_new_state = "first-replacement-oauth-state"
    second_new_state = "second-replacement-oauth-state"
    try:
        await asyncio.wait_for(
            asyncio.gather(
                executor.run(
                    "issue_oauth_state",
                    new_oauth_state_input(
                        state=first_new_state,
                        settings=_settings(),
                        now=FIXED_NOW,
                        superseded_keys=(first_old_key,),
                    ),
                    actor,
                ),
                executor.run(
                    "issue_oauth_state",
                    new_oauth_state_input(
                        state=second_new_state,
                        settings=_settings(),
                        now=FIXED_NOW,
                        superseded_keys=(second_old_key,),
                    ),
                    actor,
                ),
            ),
            timeout=5,
        )
    finally:
        await engine.dispose()

    migration_engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration_engine.connect() as connection:
            stored_keys = (
                await connection.execute(
                    sa.text(
                        "SELECT key FROM idempotency_keys "
                        "WHERE command = 'issue_oauth_state' ORDER BY key"
                    )
                )
            ).scalars().all()
    finally:
        await migration_engine.dispose()

    assert len(backend_pids) == 2
    assert stored_keys == sorted(
        [
            oauth_state_key(first_new_state, SESSION_SECRET),
            oauth_state_key(second_new_state, SESSION_SECRET),
        ]
    )


@pytest.mark.asyncio
async def test_IDN1_login_rejects_an_email_outside_the_configured_domain() -> None:
    executor, engine = _executor()
    input_value = new_login_input(
        email="student@example.com",
        full_name="Outside Student",
        settings=_settings(),
        issued_at=FIXED_NOW,
    )
    try:
        with pytest.raises(DomainRejection) as error:
            await executor.run(
                "google_login", input_value, ActorContext(principal_id="anonymous")
            )
    finally:
        await engine.dispose()  # type: ignore[union-attr]

    assert [reason.code for reason in error.value.rejection.reasons] == [
        OUTSIDE_ALLOWED_DOMAIN
    ]


@pytest.mark.asyncio
async def test_IDN1_login_stores_only_hmac_token_and_uses_default_lifetime() -> None:
    executor, engine = _executor()
    input_value = new_login_input(
        email="student@example.edu",
        full_name="Student Name",
        settings=_settings(),
        issued_at=FIXED_NOW,
    )
    raw_token = input_value.session_token
    try:
        await executor.run(
            "google_login", input_value, ActorContext(principal_id="anonymous")
        )
    finally:
        await engine.dispose()  # type: ignore[union-attr]

    session = await _row("SELECT token_hash, expires_at FROM sessions")
    audit = await _row("SELECT details FROM audit_log WHERE action = 'google_login'")
    assert session["token_hash"] == hash_session_token(raw_token, SESSION_SECRET)
    assert session["token_hash"] != raw_token
    assert session["expires_at"] == FIXED_NOW + timedelta(hours=24)
    assert raw_token not in json.dumps(input_value.model_dump(mode="json"))
    assert raw_token not in json.dumps(audit["details"])


@pytest.mark.asyncio
async def test_IDN1_login_reads_session_hours_setting() -> None:
    migration_engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration_engine.begin() as connection:
            await connection.execute(
                sa.text("INSERT INTO settings (key, value) VALUES ('session_hours', '3')")
            )
    finally:
        await migration_engine.dispose()
    executor, engine = _executor()
    input_value = new_login_input(
        email="student@example.edu",
        full_name="Student Name",
        settings=_settings(),
        issued_at=FIXED_NOW,
    )
    try:
        await executor.run(
            "google_login", input_value, ActorContext(principal_id="anonymous")
        )
    finally:
        await engine.dispose()  # type: ignore[union-attr]

    session = await _row("SELECT expires_at FROM sessions")
    assert session["expires_at"] == FIXED_NOW + timedelta(hours=3)


@pytest.mark.asyncio
async def test_IDN1_present_json_null_session_hours_fails_closed() -> None:
    migration_engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration_engine.begin() as connection:
            await connection.execute(
                sa.text("INSERT INTO settings (key, value) VALUES ('session_hours', 'null')")
            )
    finally:
        await migration_engine.dispose()
    executor, engine = _executor()
    input_value = new_login_input(
        email="student@example.edu",
        full_name="Student Name",
        settings=_settings(),
        issued_at=FIXED_NOW,
    )
    try:
        with pytest.raises(ValueError, match="settings.session_hours"):
            await executor.run(
                "google_login", input_value, ActorContext(principal_id="anonymous")
            )
    finally:
        await engine.dispose()  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_IDN1_login_rejects_idempotency_keys() -> None:
    executor, engine = _executor()
    input_value = new_login_input(
        email="student@example.edu",
        full_name="Student Name",
        settings=_settings(),
        issued_at=FIXED_NOW,
    )
    try:
        with pytest.raises(DomainRejection) as error:
            await executor.run(
                "google_login",
                input_value,
                ActorContext(principal_id="anonymous"),
                idempotency_key="forbidden-login-key",
            )
    finally:
        await engine.dispose()  # type: ignore[union-attr]

    assert [reason.code for reason in error.value.rejection.reasons] == [
        SESSION_EFFECT_IDEMPOTENCY
    ]


@pytest.mark.asyncio
async def test_IDN1_login_revokes_only_the_requests_prior_valid_session() -> None:
    executor, engine = _executor()
    actor = ActorContext(principal_id="anonymous")
    first = new_login_input(
        email="student@example.edu",
        full_name="Original Name",
        settings=_settings(),
        issued_at=FIXED_NOW,
    )
    other_device = new_login_input(
        email="student@example.edu",
        full_name="Ignored Replacement",
        settings=_settings(),
        issued_at=FIXED_NOW + timedelta(minutes=1),
    )
    try:
        await executor.run("google_login", first, actor)
        first_row = await _row(
            "SELECT id FROM sessions WHERE token_hash = :token_hash",
            {"token_hash": hash_session_token(first.session_token, SESSION_SECRET)},
        )
        await executor.run("google_login", other_device, actor)
        other_row = await _row(
            "SELECT id FROM sessions WHERE token_hash = :token_hash",
            {
                "token_hash": hash_session_token(
                    other_device.session_token, SESSION_SECRET
                )
            },
        )
        replacement = new_login_input(
            email="student@example.edu",
            full_name="Still Ignored",
            settings=_settings(),
            prior_session_id=first_row["id"],
            issued_at=FIXED_NOW + timedelta(minutes=2),
        )
        await executor.run("google_login", replacement, actor)
    finally:
        await engine.dispose()  # type: ignore[union-attr]

    prior = await _row("SELECT revoked_at FROM sessions WHERE id = :id", {"id": first_row["id"]})
    untouched = await _row(
        "SELECT revoked_at FROM sessions WHERE id = :id", {"id": other_row["id"]}
    )
    user = await _row("SELECT full_name FROM users WHERE email = 'student@example.edu'")
    assert prior["revoked_at"] == FIXED_NOW + timedelta(minutes=2)
    assert untouched["revoked_at"] is None
    assert user["full_name"] == "Original Name"
    assert len({first.session_token, other_device.session_token, replacement.session_token}) == 3


@pytest.mark.asyncio
async def test_IDN1_inactive_existing_user_is_refused_a_session() -> None:
    user_id = uuid4()
    migration_engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration_engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "INSERT INTO users (id, email, full_name, is_active) "
                    "VALUES (:id, 'inactive@example.edu', 'Inactive', false)"
                ),
                {"id": user_id},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO enrollments (user_id, is_current) VALUES (:id, true)"
                ),
                {"id": user_id},
            )
    finally:
        await migration_engine.dispose()
    executor, engine = _executor()
    input_value = new_login_input(
        email="inactive@example.edu",
        full_name="Different Name",
        settings=_settings(),
        issued_at=FIXED_NOW,
    )
    try:
        with pytest.raises(DomainRejection) as error:
            await executor.run(
                "google_login", input_value, ActorContext(principal_id="anonymous")
            )
    finally:
        await engine.dispose()  # type: ignore[union-attr]

    assert [reason.code for reason in error.value.rejection.reasons] == [INACTIVE_USER]


def test_IDN2_post_login_planner_hooks_are_invoked_in_registration_order() -> None:
    hooks = PostLoginHooks()
    observed: list[str] = []

    def first(*_: object) -> list[StateOp]:
        observed.append("first")
        return []

    def second(*_: object) -> list[StateOp]:
        observed.append("second")
        return []

    hooks.register(first)
    hooks.register(second)
    input_value = new_login_input(
        email="student@example.edu",
        full_name="Student",
        settings=_settings(),
        issued_at=FIXED_NOW,
    )
    hooks.plan(
        input_value,
        LoginState(
            scope_ids=ScopeIds(),
            user_id=UUID("00000000-0000-0000-0000-000000000001"),
            user_is_active=True,
            prior_session_id=None,
            session_hours=24,
        ),
        ActorContext(principal_id="student"),
    )

    assert observed == ["first", "second"]


@pytest.mark.asyncio
async def test_IDN1_configured_secure_flag_applies_to_both_login_cookies() -> None:
    from fastapi import Response

    settings = _settings().model_copy(update={"session_cookie_secure": True})
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        sessions = SessionManager(settings=settings, engine=engine)
        response = Response()
        sessions.set_login_cookies(response, "opaque-session-token")
    finally:
        await engine.dispose()

    cookies = [
        value.decode()
        for name, value in response.raw_headers
        if name == b"set-cookie"
    ]
    session_cookie = next(item for item in cookies if item.startswith("cds_session="))
    csrf_cookie = next(item for item in cookies if item.startswith("cds_csrf="))
    assert "Secure" in session_cookie
    assert "Secure" in csrf_cookie
