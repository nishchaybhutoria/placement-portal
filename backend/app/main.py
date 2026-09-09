"""FastAPI application assembly."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response
from starlette.routing import Match

from app.bootstrap import build_executor, build_registry
from app.core.authz import Authorizer
from app.core.db import create_engine
from app.core.errors import install_exception_handlers
from app.core.plan import ActorContext
from app.core.rate_limit import InProcessRateLimiter
from app.core.routes import ActorProvider, mount_registry_routes
from app.modules.analytics.http import mount_export_routes
from app.modules.applications.http import mount_venue_upload_route
from app.modules.identity.http import (
    GoogleOAuthClient,
    build_google_oauth_client,
    mount_identity_routes,
)
from app.modules.identity.session import (
    OAuthSessionMiddleware,
    SessionManager,
    csrf_matches,
)
from app.modules.notifications.dev_email import dev_email_output_enabled
from app.modules.profiles.http import mount_profile_upload_route
from app.observability import (
    RequestTelemetryMiddleware,
    configure_logging,
    metrics_payload,
)
from app.settings import Settings


def create_app(
    database_url: str | None = None,
    *,
    enable_test_harness: bool = False,
    settings: Settings | None = None,
    oauth_client: object | None = None,
) -> FastAPI:
    """Build the API app, optionally overriding its database URL for tests."""

    dev_email_output_enabled()
    configure_logging()
    resolved_url = database_url or os.environ.get("DATABASE_URL")
    resolved_settings = settings or Settings.from_env()
    engine = create_engine(resolved_url)
    registry = build_registry(
        settings=resolved_settings, enable_test_harness=enable_test_harness
    )
    authorizer = Authorizer()
    command_executor = build_executor(registry, engine, authorizer=authorizer)
    session_manager = SessionManager(settings=resolved_settings, engine=engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.database_engine = engine
        app.state.command_executor = command_executor
        app.state.command_registry = registry
        try:
            yield
        finally:
            await engine.dispose()

    application = FastAPI(title="CDS Portal API", lifespan=lifespan)
    application.add_middleware(RequestTelemetryMiddleware)
    application.state.database_engine = engine
    application.state.command_executor = command_executor
    application.state.command_registry = registry
    application.state.session_manager = session_manager
    install_exception_handlers(application)

    application.add_middleware(
        OAuthSessionMiddleware,
        secret=resolved_settings.session_secret,
        secure=resolved_settings.session_cookie_secure,
    )

    @application.middleware("http")
    async def csrf_middleware(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        matched_post = any(
            route.matches(request.scope)[0] is Match.FULL
            and "POST" in (getattr(route, "methods", None) or ())
            for route in application.routes
        )
        if (
            request.method == "POST"
            and matched_post
            and not csrf_matches(request)
        ):
            return JSONResponse(
                status_code=403,
                media_type="application/problem+json",
                content={
                    "type": "/problems/csrf",
                    "title": "CSRF validation failed",
                    "status": 403,
                },
            )
        return await call_next(request)

    actor_provider: ActorProvider
    if enable_test_harness:

        async def harness_actor_provider() -> ActorContext:
            return ActorContext(principal_id="harness", is_test_harness=True)

        actor_provider = harness_actor_provider
    else:
        actor_provider = session_manager.current_actor

    limiter = InProcessRateLimiter()
    mount_registry_routes(
        application,
        registry=registry,
        executor=command_executor,
        actor_provider=actor_provider,
        limiter=limiter,
        session_effects=session_manager,
        route_authorizer=authorizer,
    )
    resolved_oauth = (
        cast(GoogleOAuthClient, oauth_client)
        if oauth_client is not None
        else build_google_oauth_client(resolved_settings)
    )
    mount_export_routes(
        application, actor_provider=actor_provider, limiter=limiter
    )
    mount_profile_upload_route(
        application, actor_provider=actor_provider, limiter=limiter
    )
    mount_venue_upload_route(
        application, actor_provider=actor_provider, limiter=limiter
    )
    mount_identity_routes(
        application,
        settings=resolved_settings,
        oauth_client=resolved_oauth,
        executor=command_executor,
        sessions=session_manager,
        limiter=limiter,
    )

    @application.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(
            content=metrics_payload(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @application.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/readyz")
    async def readyz(request: Request) -> JSONResponse:
        engine: AsyncEngine = request.app.state.database_engine
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except (OSError, SQLAlchemyError):
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        return JSONResponse(status_code=200, content={"status": "ready"})

    return application


app = create_app()
