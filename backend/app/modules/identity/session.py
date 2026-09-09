"""Session authentication, cookie effects, and CSRF helpers for IDN-1/2/3."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from fastapi import Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from app.core.plan import ActorContext
from app.core.registry import CommandSpec
from app.modules.identity.commands import (
    DevLoginInput,
    SessionEstablishInput,
    hash_session_token,
    prepare_dev_login_input,
)
from app.settings import Settings

SESSION_COOKIE = "cds_session"
CSRF_COOKIE = "cds_csrf"
CSRF_HEADER = "X-CSRF"
OAUTH_COOKIE = "cds_oauth"


class OAuthSessionMiddleware(BaseHTTPMiddleware):
    """Expose a signed transient session mapping for Authlib OAuth state."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        secret: str,
        secure: bool,
    ) -> None:
        super().__init__(app)
        self._secret = secret.encode()
        self._secure = secure

    def _decode(self, value: str | None) -> dict[str, object]:
        if not value:
            return {}
        try:
            encoded, signature = value.rsplit(".", 1)
            expected = hmac.new(self._secret, encoded.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                return {}
            padding = "=" * (-len(encoded) % 4)
            payload = base64.urlsafe_b64decode(encoded + padding)
            decoded = json.loads(payload)
        except (binascii.Error, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}

    def _encode(self, value: dict[str, object]) -> str:
        payload = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        encoded = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
        signature = hmac.new(self._secret, encoded.encode(), hashlib.sha256).hexdigest()
        return f"{encoded}.{signature}"

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        original_cookie = request.cookies.get(OAUTH_COOKIE)
        oauth_session = self._decode(original_cookie)
        request.scope["session"] = oauth_session
        response = await call_next(request)
        if oauth_session:
            response.set_cookie(
                OAUTH_COOKIE,
                self._encode(oauth_session),
                httponly=True,
                secure=self._secure,
                samesite="lax",
            )
        elif original_cookie is not None:
            response.delete_cookie(
                OAUTH_COOKIE,
                httponly=True,
                secure=self._secure,
                samesite="lax",
            )
        return response


def _record_actor_context(request: Request, actor: ActorContext) -> ActorContext:
    """Expose only non-PII actor fields to the request telemetry middleware."""

    request.scope["actor_kind"] = (
        "authenticated" if actor.user_id is not None else "anonymous"
    )
    if actor.user_id is not None:
        request.scope["actor_user_id"] = str(actor.user_id)
    if actor.role is not None:
        request.scope["actor_role"] = actor.role
    return actor


class SessionManager:
    def __init__(self, *, settings: Settings, engine: AsyncEngine) -> None:
        self.settings = settings
        self.engine = engine

    async def current_actor(self, request: Request) -> ActorContext:
        raw_token = request.cookies.get(SESSION_COOKIE)
        if not raw_token:
            return _record_actor_context(
                request, ActorContext(principal_id="anonymous")
            )
        token_hash = hash_session_token(raw_token, self.settings.session_secret)
        statement = sa.text(
            """
            SELECT
                s.id AS session_id,
                u.id AS user_id,
                u.email,
                u.full_name,
                u.role,
                e.id AS current_enrollment_id,
                COALESCE(p.declared_at IS NOT NULL, false) AS profile_declared,
                ARRAY(
                    SELECT cc.cycle_id
                    FROM cycle_coordinators cc
                    WHERE cc.user_id = u.id
                    ORDER BY cc.cycle_id
                ) AS coordinated_cycle_ids
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            LEFT JOIN enrollments e ON e.user_id = u.id AND e.is_current
            LEFT JOIN profiles p ON p.enrollment_id = e.id
            WHERE s.token_hash = :token_hash
              AND s.revoked_at IS NULL
              AND s.expires_at > now()
              AND u.is_active
            """
        )
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(statement, {"token_hash": token_hash})
            ).mappings().one_or_none()
        if row is None:
            return _record_actor_context(
                request, ActorContext(principal_id="anonymous")
            )
        cycle_ids = tuple(cast(list[UUID], row["coordinated_cycle_ids"]))
        actor = ActorContext(
            principal_id=str(row["user_id"]),
            user_id=row["user_id"],
            role=row["role"],
            session_id=row["session_id"],
            current_enrollment_id=row["current_enrollment_id"],
            coordinated_cycle_ids=cycle_ids,
            email=str(row["email"]),
            full_name=row["full_name"],
            profile_declared=row["profile_declared"],
        )
        return _record_actor_context(request, actor)

    def prepare_input(
        self, spec: CommandSpec, input_value: BaseModel, actor: ActorContext
    ) -> BaseModel:
        if spec.session_effect != "establish":
            return input_value
        if isinstance(input_value, DevLoginInput):
            return prepare_dev_login_input(
                input_value,
                settings=self.settings,
                prior_session_id=actor.session_id,
            )
        if isinstance(input_value, SessionEstablishInput):
            return input_value
        raise TypeError("Session establishment requires SessionEstablishInput")

    def apply_effect(
        self, response: Response, spec: CommandSpec, input_value: BaseModel
    ) -> None:
        if spec.session_effect == "establish":
            if not isinstance(input_value, SessionEstablishInput):
                raise TypeError("Session establishment requires SessionEstablishInput")
            self.set_login_cookies(response, input_value.session_token)
        elif spec.session_effect == "clear":
            self.clear_login_cookies(response)

    def set_login_cookies(self, response: Response, session_token: str) -> None:
        response.set_cookie(
            SESSION_COOKIE,
            session_token,
            httponly=True,
            secure=self.settings.session_cookie_secure,
            samesite="lax",
        )
        self.refresh_csrf(response)

    def refresh_csrf(self, response: Response) -> str:
        token = secrets.token_urlsafe(32)
        response.set_cookie(
            CSRF_COOKIE,
            token,
            httponly=False,
            secure=self.settings.session_cookie_secure,
            samesite="lax",
        )
        return token

    def clear_login_cookies(self, response: Response) -> None:
        for cookie in (SESSION_COOKIE, CSRF_COOKIE):
            response.delete_cookie(
                cookie,
                secure=self.settings.session_cookie_secure,
                httponly=cookie == SESSION_COOKIE,
                samesite="lax",
            )


def csrf_matches(request: Request) -> bool:
    cookie = request.cookies.get(CSRF_COOKIE, "")
    header = request.headers.get(CSRF_HEADER, "")
    return bool(cookie and header and hmac.compare_digest(cookie, header))
