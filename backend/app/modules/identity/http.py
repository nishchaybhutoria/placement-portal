"""Google OIDC and /me HTTP endpoints for Behavior IDN-1/2/3."""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from dataclasses import asdict
from typing import Protocol, cast

import httpx
from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.core.errors import (
    OAUTH_CLAIMS_INVALID,
    OAUTH_PROVIDER_ERROR,
    OAUTH_STATE_EXPIRED,
    OAUTH_STATE_INVALID,
    DomainRejection,
)
from app.core.executor import Executor
from app.core.plan import ActorContext, Reason, Result
from app.core.rate_limit import InProcessRateLimiter
from app.modules.identity.commands import (
    OAUTH_STATE_PREFIX,
    ConsumeOAuthStateSummary,
    email_matches_domain,
    new_login_input,
    new_oauth_state_input,
    oauth_state_key,
)
from app.modules.identity.session import SessionManager
from app.settings import Settings

# Google's token and JWKS endpoints are a hard dependency of the login flow, so
# bound them explicitly rather than inheriting httpx's 5s default for every
# phase. Connect stays tight because a stalled TCP/TLS handshake to Google is a
# network fault, not slowness; the read budget is looser to absorb a slow but
# healthy response.
OAUTH_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class GoogleOAuthClient(Protocol):
    async def authorize_redirect(
        self, request: Request, redirect_uri: str, **kwargs: object
    ) -> Response: ...

    async def authorize_access_token(
        self, request: Request, **kwargs: object
    ) -> Mapping[str, object]: ...


def build_google_oauth_client(settings: Settings) -> GoogleOAuthClient:
    oauth = OAuth()
    oauth.register(
        "google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile", "timeout": OAUTH_TIMEOUT},
    )
    client = oauth.create_client("google")
    if client is None:
        raise RuntimeError("Google OAuth client registration failed")
    return cast(GoogleOAuthClient, client)


def _oauth_rejection(reasons: list[Reason]) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        media_type="application/problem+json",
        content={
            "type": "/problems/oauth-login",
            "title": "Google login rejected",
            "status": 403,
            "reasons": [asdict(reason) for reason in reasons],
        },
    )


def _claims(token: Mapping[str, object], settings: Settings) -> tuple[str, str] | None:
    userinfo = token.get("userinfo")
    if not isinstance(userinfo, Mapping):
        return None
    email = userinfo.get("email")
    full_name = userinfo.get("name")
    if (
        userinfo.get("email_verified") is not True
        or userinfo.get("hd") != settings.allowed_domain
        or not isinstance(email, str)
        or not email_matches_domain(email, settings.allowed_domain)
        or not isinstance(full_name, str)
        or not full_name.strip()
    ):
        return None
    return email, full_name.strip()


def mount_identity_routes(
    app: FastAPI,
    *,
    settings: Settings,
    oauth_client: GoogleOAuthClient,
    executor: Executor,
    sessions: SessionManager,
    limiter: InProcessRateLimiter,
) -> None:
    actor_dependency = Depends(sessions.current_actor)

    def system_actor(actor: ActorContext | None = None) -> ActorContext:
        request_actor = actor or ActorContext(principal_id="anonymous")
        return ActorContext(
            principal_id="oauth-system",
            user_id=request_actor.user_id,
            role=request_actor.role,
            session_id=request_actor.session_id,
            current_enrollment_id=request_actor.current_enrollment_id,
            coordinated_cycle_ids=request_actor.coordinated_cycle_ids,
            email=request_actor.email,
            full_name=request_actor.full_name,
            profile_declared=request_actor.profile_declared,
            is_system=True,
        )

    @app.get("/auth/google/login")
    async def google_login(request: Request) -> Response:
        client_address = request.client.host if request.client is not None else "unknown"
        await limiter.check(client_address, "google_login", "10/min")
        superseded_keys = tuple(
            key for key in request.session if key.startswith(OAUTH_STATE_PREFIX)
        )
        for key in tuple(request.session):
            if key.startswith(OAUTH_STATE_PREFIX) or key.startswith("_state_google_"):
                request.session.pop(key)
        state = secrets.token_urlsafe(32)
        try:
            await executor.run(
                "issue_oauth_state",
                new_oauth_state_input(
                    state=state,
                    settings=settings,
                    superseded_keys=superseded_keys,
                ),
                system_actor(),
            )
        except DomainRejection as error:
            return _oauth_rejection(error.rejection.reasons)
        request.session[oauth_state_key(state, settings.session_secret)] = True
        callback_url = f"{settings.base_url.rstrip('/')}/auth/google/callback"
        try:
            return await oauth_client.authorize_redirect(
                request,
                callback_url,
                hd=settings.allowed_domain,
                state=state,
            )
        except (OAuthError, httpx.HTTPError):
            # Discovery metadata is fetched lazily on the first redirect, so an
            # unreachable provider fails here rather than at the callback. The
            # state issued above is left to expire; the next attempt supersedes
            # it through the same prefix sweep that opens this handler.
            return _oauth_rejection(
                [
                    Reason(
                        code=OAUTH_PROVIDER_ERROR,
                        human="Google OAuth provider is unreachable",
                    )
                ]
            )

    @app.get("/auth/google/callback", name="google_callback")
    async def google_callback(
        request: Request, actor: ActorContext = actor_dependency
    ) -> Response:
        try:
            state = request.query_params.get("state", "")
            marker = oauth_state_key(state, settings.session_secret) if state else ""
            if not marker or request.session.get(marker) is not True:
                return _oauth_rejection(
                    [
                        Reason(
                            code=OAUTH_STATE_INVALID,
                            human="OAuth state marker is missing or invalid",
                        )
                    ]
                )
            oauth_actor = system_actor(actor)
            try:
                consume_result = await executor.run(
                    "consume_oauth_state",
                    new_oauth_state_input(state=state, settings=settings),
                    oauth_actor,
                )
            except DomainRejection as error:
                return _oauth_rejection(error.rejection.reasons)
            consume_summary = ConsumeOAuthStateSummary.model_validate(
                consume_result.summary
            )
            if not consume_summary.consumed:
                code = consume_summary.reason or OAUTH_STATE_INVALID
                human = (
                    "OAuth state has expired"
                    if code == OAUTH_STATE_EXPIRED
                    else "OAuth state is invalid"
                )
                return _oauth_rejection([Reason(code=code, human=human)])
            token = await oauth_client.authorize_access_token(request)
            claims = _claims(token, settings)
            if claims is None:
                return _oauth_rejection(
                    [
                        Reason(
                            code=OAUTH_CLAIMS_INVALID,
                            human="Google identity claims are not accepted",
                        )
                    ]
                )
            email, full_name = claims
            input_value = new_login_input(
                email=email,
                full_name=full_name,
                settings=settings,
                prior_session_id=oauth_actor.session_id,
            )
            result = await executor.run("google_login", input_value, oauth_actor)
            if not isinstance(result, Result):
                raise RuntimeError("Google callback cannot preview login")
            response = RedirectResponse(f"{settings.base_url.rstrip('/')}/")
            sessions.set_login_cookies(response, input_value.session_token)
            return response
        except (OAuthError, httpx.HTTPError, KeyError, TypeError, ValueError):
            return _oauth_rejection(
                [
                    Reason(
                        code=OAUTH_PROVIDER_ERROR,
                        human="Google OAuth exchange failed",
                    )
                ]
            )
        finally:
            request.session.clear()

    @app.get("/me")
    async def me(actor: ActorContext = actor_dependency) -> JSONResponse:
        if actor.user_id is None:
            content: dict[str, object] = {
                "authenticated": False,
                "dev_login_enabled": settings.dev_login,
            }
        else:
            content = {
                "authenticated": True,
                "dev_login_enabled": settings.dev_login,
                "user": {
                    "id": str(actor.user_id),
                    "email": actor.email,
                    "full_name": actor.full_name,
                    "role": actor.role,
                },
                "current_enrollment_id": str(actor.current_enrollment_id)
                if actor.current_enrollment_id is not None
                else None,
                "profile_declared": actor.profile_declared,
                "coordinated_cycle_ids": [
                    str(cycle_id) for cycle_id in actor.coordinated_cycle_ids
                ],
            }
        response = JSONResponse(content=content)
        sessions.refresh_csrf(response)
        return response
