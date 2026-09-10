"""HTTP, CSRF, cookie, /me, and OAuth contracts for Behavior IDN-1/2/3."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.starlette_client import OAuth
from fastapi import FastAPI

from app.core.db import create_engine
from app.main import create_app
from app.modules.identity.http import build_google_oauth_client
from app.settings import Settings


def _settings(*, dev_login: bool = True, secure: bool = False) -> Settings:
    return Settings(
        session_secret="http-session-secret-at-least-32-chars",
        google_client_id="google-client",
        google_client_secret="google-secret",
        allowed_domain="example.edu",
        dev_login=dev_login,
        base_url="http://test",
        session_cookie_secure=secure,
    )


@pytest_asyncio.fixture(autouse=True)
async def clean_identity_tables() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "TRUNCATE audit_log, cycle_coordinators, profiles, sessions, "
                    "enrollments, users, settings, cycles, idempotency_keys CASCADE"
                )
            )
    finally:
        await engine.dispose()


def _oauth_client(userinfo: dict[str, object]) -> tuple[object, AsyncMock]:
    oauth = OAuth()
    oauth.register(
        "google",
        client_id="google-client",
        client_secret="google-secret",
        authorize_url="https://accounts.google.test/o/oauth2/auth",
        access_token_url="https://accounts.google.test/o/oauth2/token",
        client_kwargs={"scope": "openid email profile"},
    )
    client = oauth.create_client("google")
    assert client is not None
    fetch = AsyncMock(return_value={"access_token": "fake", "userinfo": userinfo})
    client.fetch_access_token = fetch
    return client, fetch


def _oauth_client_with_failing_redirect(error: Exception) -> tuple[object, AsyncMock]:
    oauth = OAuth()
    oauth.register(
        "google",
        client_id="google-client",
        client_secret="google-secret",
        authorize_url="https://accounts.google.test/o/oauth2/auth",
        access_token_url="https://accounts.google.test/o/oauth2/token",
        client_kwargs={"scope": "openid email profile"},
    )
    client = oauth.create_client("google")
    assert client is not None
    redirect = AsyncMock(side_effect=error)
    client.authorize_redirect = redirect
    return client, redirect


async def _client(
    *, settings: Settings | None = None, oauth_client: object | None = None
) -> tuple[FastAPI, httpx.AsyncClient]:
    application = create_app(
        os.environ["TEST_DATABASE_URL"],
        settings=settings or _settings(),
        oauth_client=oauth_client,
    )
    transport = httpx.ASGITransport(app=application)
    client = httpx.AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=False
    )
    return application, client


async def _close(application: FastAPI, client: httpx.AsyncClient) -> None:
    await client.aclose()
    await application.state.database_engine.dispose()


async def _csrf(client: httpx.AsyncClient) -> str:
    response = await client.get("/me")
    assert response.status_code == 200
    token = client.cookies.get("cds_csrf")
    assert token
    return token


def _oauth_cookie_payload(cookie: str) -> dict[str, object]:
    encoded, _signature = cookie.rsplit(".", 1)
    payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    decoded = json.loads(payload)
    assert isinstance(decoded, dict)
    return decoded


@pytest.mark.asyncio
async def test_IDN1_dev_login_route_is_absent_when_disabled() -> None:
    application = create_app(
        os.environ["TEST_DATABASE_URL"], settings=_settings(dev_login=False, secure=True)
    )

    paths = application.openapi()["paths"]

    assert "/api/v1/commands/dev_login" not in paths


@pytest.mark.asyncio
async def test_IDN1_me_bootstraps_csrf_and_reports_anonymous_capabilities() -> None:
    application, client = await _client()
    try:
        response = await client.get("/me")
    finally:
        await _close(application, client)

    assert response.json() == {"authenticated": False, "dev_login_enabled": True}
    csrf_cookie = next(
        header
        for header in response.headers.get_list("set-cookie")
        if header.startswith("cds_csrf=")
    )
    assert "HttpOnly" not in csrf_cookie
    assert "SameSite=lax" in csrf_cookie


@pytest.mark.asyncio
@pytest.mark.parametrize("header", [None, "", "mismatch"])
async def test_IDN1_csrf_rejects_every_post_without_a_nonempty_constant_time_match(
    header: str | None,
) -> None:
    application, client = await _client()
    try:
        token = await _csrf(client)
        headers = {} if header is None else {"X-CSRF": header}
        if header == "":
            headers["X-CSRF"] = ""
        response = await client.post(
            "/api/v1/commands/dev_login",
            json={"input": {"email": "student@example.edu"}, "dry_run": True},
            headers=headers,
        )
    finally:
        await _close(application, client)

    assert token
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_IDN1_preview_post_requires_csrf_and_never_sets_session_cookies() -> None:
    application, client = await _client()
    try:
        token = await _csrf(client)
        response = await client.post(
            "/api/v1/commands/dev_login",
            json={"input": {"email": "preview@example.edu"}, "dry_run": True},
            headers={"X-CSRF": token},
        )
    finally:
        await _close(application, client)

    assert response.status_code == 200
    assert response.json()["summary"] == {
        "authenticated": True,
        "email": "preview@example.edu",
    }
    assert not any(
        header.startswith("cds_session=")
        for header in response.headers.get_list("set-cookie")
    )


@pytest.mark.asyncio
async def test_IDN1_dev_login_sets_securely_shaped_session_and_csrf_cookies_after_commit() -> None:
    application, client = await _client()
    try:
        csrf = await _csrf(client)
        response = await client.post(
            "/api/v1/commands/dev_login",
            json={"input": {"email": "first.last@EXAMPLE.EDU"}},
            headers={"X-CSRF": csrf},
        )
        session_token = client.cookies.get("cds_session")
        me = await client.get("/me")
    finally:
        await _close(application, client)

    session_cookie = next(
        header
        for header in response.headers.get_list("set-cookie")
        if header.startswith("cds_session=")
    )
    csrf_cookie = next(
        header
        for header in response.headers.get_list("set-cookie")
        if header.startswith("cds_csrf=")
    )
    assert response.status_code == 200
    assert session_token
    assert "HttpOnly" in session_cookie
    assert "SameSite=lax" in session_cookie
    assert "HttpOnly" not in csrf_cookie
    assert "SameSite=lax" in csrf_cookie
    assert me.json()["authenticated"] is True
    assert me.json()["user"]["full_name"] == "First Last"


@pytest.mark.asyncio
async def test_IDN1_me_treats_expired_revoked_and_inactive_sessions_as_anonymous() -> None:
    for invalidation in ("expired", "revoked", "inactive"):
        application, client = await _client()
        try:
            csrf = await _csrf(client)
            await client.post(
                "/api/v1/commands/dev_login",
                json={"input": {"email": f"{invalidation}@example.edu"}},
                headers={"X-CSRF": csrf},
            )
            engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
            try:
                async with engine.begin() as connection:
                    if invalidation == "expired":
                        await connection.execute(
                            sa.text(
                                "UPDATE sessions SET expires_at = now() - interval '1 second' "
                                "WHERE token_hash IS NOT NULL"
                            )
                        )
                    elif invalidation == "revoked":
                        await connection.execute(
                            sa.text("UPDATE sessions SET revoked_at = now()")
                        )
                    else:
                        await connection.execute(
                            sa.text(
                                "UPDATE users SET is_active = false "
                                "WHERE email = :email"
                            ),
                            {"email": f"{invalidation}@example.edu"},
                        )
            finally:
                await engine.dispose()
            response = await client.get("/me")
        finally:
            await _close(application, client)

        assert response.json() == {
            "authenticated": False,
            "dev_login_enabled": True,
        }


@pytest.mark.asyncio
async def test_IDN2_IDN3_me_returns_identity_current_enrollment_profile_and_cycles() -> None:
    application, client = await _client()
    try:
        csrf = await _csrf(client)
        await client.post(
            "/api/v1/commands/dev_login",
            json={"input": {"email": "coordinator@example.edu"}},
            headers={"X-CSRF": csrf},
        )
        engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
        try:
            async with engine.begin() as connection:
                identity = (
                    await connection.execute(
                        sa.text(
                            "SELECT u.id AS user_id, e.id AS enrollment_id "
                            "FROM users u JOIN enrollments e ON e.user_id = u.id "
                            "WHERE u.email = 'coordinator@example.edu' AND e.is_current"
                        )
                    )
                ).mappings().one()
                cycle_id = await connection.scalar(
                    sa.text(
                        "INSERT INTO cycles (name, kind) VALUES ('Placement 2026', 'placement') "
                        "RETURNING id"
                    )
                )
                await connection.execute(
                    sa.text(
                        "INSERT INTO profiles (enrollment_id, declared_at) "
                        "VALUES (:enrollment_id, now())"
                    ),
                    {"enrollment_id": identity["enrollment_id"]},
                )
                await connection.execute(
                    sa.text(
                        "INSERT INTO cycle_coordinators (cycle_id, user_id) "
                        "VALUES (:cycle_id, :user_id)"
                    ),
                    {"cycle_id": cycle_id, "user_id": identity["user_id"]},
                )
        finally:
            await engine.dispose()
        response = await client.get("/me")
    finally:
        await _close(application, client)

    assert response.json() == {
        "authenticated": True,
        "dev_login_enabled": True,
        "user": {
            "id": str(identity["user_id"]),
            "email": "coordinator@example.edu",
            "full_name": "Coordinator",
            "role": "student",
        },
        "current_enrollment_id": str(identity["enrollment_id"]),
        "profile_declared": True,
        "coordinated_cycle_ids": [str(cycle_id)],
    }


@pytest.mark.asyncio
async def test_IDN1_google_oidc_uses_hd_consumes_state_rejects_replay_and_redirects_root() -> None:
    oauth_client, fetch = _oauth_client(
        {
            "email": "Google.Student@EXAMPLE.EDU",
            "email_verified": True,
            "hd": "example.edu",
            "name": "Google Student",
        }
    )
    application, client = await _client(oauth_client=oauth_client)
    replay_client: httpx.AsyncClient | None = None
    try:
        login = await client.get("/auth/google/login")
        query = parse_qs(urlparse(login.headers["location"]).query)
        state = query["state"][0]
        original_oauth_cookie = client.cookies.get("cds_oauth")
        assert original_oauth_cookie
        callback = await client.get(
            "/auth/google/callback", params={"code": "valid-code", "state": state}
        )
        replay_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://test",
            cookies={"cds_oauth": original_oauth_cookie},
            follow_redirects=False,
        )
        replay = await replay_client.get(
            "/auth/google/callback", params={"code": "valid-code", "state": state}
        )
    finally:
        if replay_client is not None:
            await replay_client.aclose()
        await _close(application, client)

    assert query["hd"] == ["example.edu"]
    assert callback.status_code == 307
    assert callback.headers["location"] == "http://test/"
    assert client.cookies.get("cds_session")
    assert client.cookies.get("cds_oauth") is None
    assert replay.status_code == 403
    assert fetch.await_count == 1


@pytest.mark.asyncio
async def test_IDN1_oauth_state_is_stored_server_side_only_as_a_hash() -> None:
    oauth_client, _fetch = _oauth_client(
        {
            "email": "state@example.edu",
            "email_verified": True,
            "hd": "example.edu",
            "name": "State Student",
        }
    )
    application, client = await _client(oauth_client=oauth_client)
    try:
        login = await client.get("/auth/google/login")
        raw_state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
        try:
            async with engine.connect() as connection:
                stored = (
                    await connection.execute(
                        sa.text(
                            "SELECT key, command, result FROM idempotency_keys "
                            "WHERE command = 'issue_oauth_state'"
                        )
                    )
                ).mappings().one()
        finally:
            await engine.dispose()
    finally:
        await _close(application, client)

    assert stored["key"].startswith("oauth-state:v1:")
    assert raw_state not in stored["key"]
    assert raw_state not in json.dumps(stored["result"])


@pytest.mark.asyncio
async def test_IDN1_restarting_oauth_replaces_server_and_cookie_state() -> None:
    oauth_client, _fetch = _oauth_client(
        {
            "email": "restart@example.edu",
            "email_verified": True,
            "hd": "example.edu",
            "name": "Restart Student",
        }
    )
    application, client = await _client(oauth_client=oauth_client)
    try:
        first = await client.get("/auth/google/login")
        second = await client.get("/auth/google/login")
        oauth_cookie = client.cookies.get("cds_oauth")
        assert oauth_cookie
        payload = _oauth_cookie_payload(oauth_cookie)
        engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
        try:
            async with engine.connect() as connection:
                stored_keys = (
                    await connection.execute(
                        sa.text(
                            "SELECT key FROM idempotency_keys "
                            "WHERE command = 'issue_oauth_state' ORDER BY key"
                        )
                    )
                ).scalars().all()
        finally:
            await engine.dispose()
    finally:
        await _close(application, client)

    assert first.is_redirect
    assert second.is_redirect
    custom_markers = [key for key in payload if key.startswith("oauth-state:v1:")]
    authlib_states = [key for key in payload if key.startswith("_state_google_")]
    assert stored_keys == custom_markers
    assert len(custom_markers) == 1
    assert len(authlib_states) == 1


@pytest.mark.asyncio
async def test_IDN1_concurrent_restarts_from_one_signed_session_issue_one_flow() -> None:
    oauth_client, fetch = _oauth_client(
        {
            "email": "concurrent.restart@example.edu",
            "email_verified": True,
            "hd": "example.edu",
            "name": "Concurrent Restart",
        }
    )
    application, bootstrap_client = await _client(oauth_client=oauth_client)
    first_client: httpx.AsyncClient | None = None
    second_client: httpx.AsyncClient | None = None
    try:
        initial = await bootstrap_client.get("/auth/google/login")
        initial_cookie = bootstrap_client.cookies.get("cds_oauth")
        assert initial.is_redirect
        assert initial_cookie

        executor = application.state.command_executor
        original_run = executor.run
        start_barrier = asyncio.Barrier(2)

        async def overlapping_run(
            name: str, *args: object, **kwargs: object
        ) -> object:
            if name == "issue_oauth_state":
                await start_barrier.wait()
            return await original_run(name, *args, **kwargs)

        executor.run = overlapping_run
        client_kwargs = {
            "base_url": "http://test",
            "cookies": {"cds_oauth": initial_cookie},
            "follow_redirects": False,
        }
        first_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), **client_kwargs
        )
        second_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), **client_kwargs
        )
        first, second = await asyncio.wait_for(
            asyncio.gather(
                first_client.get("/auth/google/login"),
                second_client.get("/auth/google/login"),
            ),
            timeout=5,
        )
        executor.run = original_run

        assert sorted((first.status_code, second.status_code)) == [302, 403]
        response_clients = ((first, first_client), (second, second_client))
        winner, winner_client = next(
            pair for pair in response_clients if pair[0].is_redirect
        )
        loser, loser_client = next(
            pair for pair in response_clients if not pair[0].is_redirect
        )
        winner_cookie = winner.cookies.get("cds_oauth")
        assert winner_cookie
        winner_payload = _oauth_cookie_payload(winner_cookie)
        loser_cookie_header = next(
            header
            for header in loser.headers.get_list("set-cookie")
            if header.startswith('cds_oauth=""')
        )

        engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
        try:
            async with engine.connect() as connection:
                stored_keys = (
                    await connection.execute(
                        sa.text(
                            "SELECT key FROM idempotency_keys "
                            "WHERE command = 'issue_oauth_state' ORDER BY key"
                        )
                    )
                ).scalars().all()
        finally:
            await engine.dispose()

        winning_state = parse_qs(urlparse(winner.headers["location"]).query)[
            "state"
        ][0]
        callback = await winner_client.get(
            "/auth/google/callback",
            params={"code": "winner", "state": winning_state},
        )
        loser_client.cookies.clear()
        retry = await loser_client.get("/auth/google/login")
    finally:
        if first_client is not None:
            await first_client.aclose()
        if second_client is not None:
            await second_client.aclose()
        await _close(application, bootstrap_client)

    assert loser.headers["content-type"].startswith("application/problem+json")
    assert loser.json()["reasons"] == [
        {
            "code": "oauth_state_invalid",
            "human": "OAuth state was superseded by another login start",
            "path": None,
        }
    ]
    assert "Max-Age=0" in loser_cookie_header
    assert stored_keys == [
        key for key in winner_payload if key.startswith("oauth-state:v1:")
    ]
    assert len(stored_keys) == 1
    assert callback.status_code == 307
    assert fetch.await_count == 1
    assert retry.is_redirect


@pytest.mark.asyncio
async def test_IDN1_superseded_captured_cookie_is_rejected_before_fetch() -> None:
    oauth_client, fetch = _oauth_client(
        {
            "email": "superseded@example.edu",
            "email_verified": True,
            "hd": "example.edu",
            "name": "Superseded Student",
        }
    )
    application, client = await _client(oauth_client=oauth_client)
    replay_client: httpx.AsyncClient | None = None
    try:
        first = await client.get("/auth/google/login")
        old_state = parse_qs(urlparse(first.headers["location"]).query)["state"][0]
        old_cookie = client.cookies.get("cds_oauth")
        assert old_cookie
        await client.get("/auth/google/login")
        replay_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://test",
            cookies={"cds_oauth": old_cookie},
            follow_redirects=False,
        )
        replay = await replay_client.get(
            "/auth/google/callback", params={"code": "old", "state": old_state}
        )
    finally:
        if replay_client is not None:
            await replay_client.aclose()
        await _close(application, client)

    assert replay.status_code == 403
    assert fetch.await_count == 0


@pytest.mark.asyncio
async def test_IDN1_new_oauth_start_purges_expired_abandoned_states() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            for suffix in range(3):
                await connection.execute(
                    sa.text(
                        "INSERT INTO idempotency_keys (key, command, result) "
                        "VALUES (:key, 'issue_oauth_state', CAST(:result AS jsonb))"
                    ),
                    {
                        "key": f"oauth-state:v1:abandoned-{suffix}",
                        "result": json.dumps(
                            {
                                "kind": "oauth_state",
                                "expires_at": "2020-01-01T00:00:00+00:00",
                            }
                        ),
                    },
                )
    finally:
        await engine.dispose()

    oauth_client, _fetch = _oauth_client(
        {
            "email": "purge@example.edu",
            "email_verified": True,
            "hd": "example.edu",
            "name": "Purge Student",
        }
    )
    application, client = await _client(oauth_client=oauth_client)
    try:
        response = await client.get("/auth/google/login")
        engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
        try:
            async with engine.connect() as connection:
                stored = (
                    await connection.execute(
                        sa.text(
                            "SELECT key FROM idempotency_keys "
                            "WHERE command = 'issue_oauth_state'"
                        )
                    )
                ).scalars().all()
        finally:
            await engine.dispose()
    finally:
        await _close(application, client)

    assert response.is_redirect
    assert len(stored) == 1
    assert stored[0].startswith("oauth-state:v1:")
    assert "abandoned" not in stored[0]


@pytest.mark.asyncio
async def test_IDN1_google_login_start_is_limited_to_ten_per_client_minute() -> None:
    oauth_client, _fetch = _oauth_client(
        {
            "email": "limited@example.edu",
            "email_verified": True,
            "hd": "example.edu",
            "name": "Limited Student",
        }
    )
    application, client = await _client(oauth_client=oauth_client)
    try:
        responses = [
            await client.get("/auth/google/login") for _attempt in range(11)
        ]
        engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
        try:
            async with engine.connect() as connection:
                stored_count = await connection.scalar(
                    sa.text(
                        "SELECT count(*) FROM idempotency_keys "
                        "WHERE command = 'issue_oauth_state'"
                    )
                )
        finally:
            await engine.dispose()
    finally:
        await _close(application, client)

    assert all(response.is_redirect for response in responses[:10])
    assert responses[10].status_code == 429
    assert stored_count == 1


@pytest.mark.asyncio
async def test_IDN1_concurrent_oauth_callbacks_atomically_fetch_once() -> None:
    oauth_client, fetch = _oauth_client(
        {
            "email": "parallel.oauth@example.edu",
            "email_verified": True,
            "hd": "example.edu",
            "name": "Parallel OAuth",
        }
    )
    application, client = await _client(oauth_client=oauth_client)
    first_client: httpx.AsyncClient | None = None
    second_client: httpx.AsyncClient | None = None
    try:
        login = await client.get("/auth/google/login")
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        original_oauth_cookie = client.cookies.get("cds_oauth")
        assert original_oauth_cookie
        client_kwargs = {
            "base_url": "http://test",
            "cookies": {"cds_oauth": original_oauth_cookie},
            "follow_redirects": False,
        }
        first_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), **client_kwargs
        )
        second_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), **client_kwargs
        )
        first, second = await asyncio.gather(
            first_client.get(
                "/auth/google/callback", params={"code": "first", "state": state}
            ),
            second_client.get(
                "/auth/google/callback", params={"code": "second", "state": state}
            ),
        )
    finally:
        if first_client is not None:
            await first_client.aclose()
        if second_client is not None:
            await second_client.aclose()
        await _close(application, client)

    assert sorted((first.status_code, second.status_code)) == [307, 403]
    assert fetch.await_count == 1


@pytest.mark.asyncio
async def test_IDN1_failed_oauth_exchange_still_consumes_server_state() -> None:
    oauth_client, fetch = _oauth_client(
        {
            "email": "failure@example.edu",
            "email_verified": True,
            "hd": "example.edu",
            "name": "Failure Student",
        }
    )
    fetch.side_effect = OAuthError(error="provider_error")
    application, client = await _client(oauth_client=oauth_client)
    replay_client: httpx.AsyncClient | None = None
    try:
        login = await client.get("/auth/google/login")
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        original_oauth_cookie = client.cookies.get("cds_oauth")
        assert original_oauth_cookie
        failed = await client.get(
            "/auth/google/callback", params={"code": "failure", "state": state}
        )
        replay_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://test",
            cookies={"cds_oauth": original_oauth_cookie},
            follow_redirects=False,
        )
        replay = await replay_client.get(
            "/auth/google/callback", params={"code": "replay", "state": state}
        )
    finally:
        if replay_client is not None:
            await replay_client.aclose()
        await _close(application, client)

    assert failed.status_code == 403
    assert replay.status_code == 403
    assert fetch.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "timeout_error",
    [
        httpx.ConnectTimeout("connection to Google timed out"),
        httpx.ReadTimeout("Google did not answer in time"),
    ],
    ids=["connect", "read"],
)
async def test_IDN1_provider_timeout_is_rejected_not_raised(
    timeout_error: httpx.TimeoutException,
) -> None:
    """A slow Google token endpoint is a provider rejection, never a 500.

    httpx timeouts are not OAuthError, so they used to escape the callback and
    surface as an unhandled ASGI exception after the one-time state had already
    been consumed.
    """

    oauth_client, fetch = _oauth_client(
        {
            "email": "timeout@example.edu",
            "email_verified": True,
            "hd": "example.edu",
            "name": "Timeout Student",
        }
    )
    fetch.side_effect = timeout_error
    application, client = await _client(oauth_client=oauth_client)
    try:
        login = await client.get("/auth/google/login")
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        timed_out = await client.get(
            "/auth/google/callback", params={"code": "slow", "state": state}
        )
        replay = await client.get(
            "/auth/google/callback", params={"code": "slow", "state": state}
        )
    finally:
        await _close(application, client)

    assert timed_out.status_code == 403
    assert timed_out.headers["content-type"].startswith("application/problem+json")
    assert [reason["code"] for reason in timed_out.json()["reasons"]] == [
        "oauth_provider_error"
    ]
    # The state is spent even on failure, so a retry must restart the flow.
    assert replay.status_code == 403
    assert fetch.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_error",
    [
        httpx.ConnectTimeout("connection to Google timed out"),
        httpx.ReadTimeout("Google did not answer in time"),
    ],
    ids=["connect", "read"],
)
async def test_IDN1_login_provider_timeout_is_rejected_not_raised(
    provider_error: httpx.TimeoutException,
) -> None:
    """Discovery metadata is fetched lazily, so the redirect is a network call."""

    oauth_client, redirect = _oauth_client_with_failing_redirect(provider_error)
    application, client = await _client(oauth_client=oauth_client)
    try:
        login = await client.get("/auth/google/login")
    finally:
        await _close(application, client)

    assert login.status_code == 403
    assert login.headers["content-type"].startswith("application/problem+json")
    assert [reason["code"] for reason in login.json()["reasons"]] == [
        "oauth_provider_error"
    ]
    assert redirect.await_count == 1


def test_IDN1_google_oauth_client_bounds_provider_timeouts() -> None:
    """The provider client must not inherit httpx's implicit 5s default."""

    client = build_google_oauth_client(_settings())
    timeout = getattr(client, "client_kwargs", {}).get("timeout")

    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 5.0
    assert timeout.read == 10.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "userinfo",
    [
        {
            "email": "student@example.edu",
            "email_verified": False,
            "hd": "example.edu",
            "name": "Student",
        },
        {
            "email": "student@example.edu",
            "email_verified": True,
            "hd": "EXAMPLE.EDU",
            "name": "Student",
        },
        {
            "email": "student@example.com",
            "email_verified": True,
            "hd": "example.edu",
            "name": "Student",
        },
    ],
)
async def test_IDN1_google_callback_requires_verified_email_exact_hd_and_domain(
    userinfo: dict[str, object],
) -> None:
    oauth_client, _fetch = _oauth_client(userinfo)
    application, client = await _client(oauth_client=oauth_client)
    try:
        login = await client.get("/auth/google/login")
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        callback = await client.get(
            "/auth/google/callback", params={"code": "invalid-claims", "state": state}
        )
    finally:
        await _close(application, client)

    assert callback.status_code == 403
    assert client.cookies.get("cds_session") is None
    assert client.cookies.get("cds_oauth") is None
