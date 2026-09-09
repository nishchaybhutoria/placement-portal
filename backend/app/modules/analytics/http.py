"""Delivery for ANA-4 exports: status to poll, bytes to download.

``request_export`` records the request; these two routes hand the file over.
They are reads, so they are routes rather than commands -- but they carry the
same authorization the command did, because an export URL is a link somebody
can forward and a spreadsheet of students is not public.

The sync path re-runs the row query at download time rather than carrying bytes
through the write transaction.  That means a download a minute after the
request reflects the world a minute later, which is the honest behaviour for a
report and is why the file states its own build time.
"""

from __future__ import annotations

from base64 import b64decode
from dataclasses import asdict
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from fastapi import Depends, FastAPI, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.errors import EXPORT_NOT_FOUND, EXPORT_NOT_READY, AuthorizationDenied
from app.core.plan import ActorContext, Reason
from app.core.rate_limit import InProcessRateLimiter
from app.core.routes import ActorProvider
from app.modules.analytics.exports import build_table, render

DOWNLOAD_RATE_LIMIT = "5/min"


async def _load_request(
    engine: AsyncEngine, export_id: UUID
) -> dict[str, object] | None:
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                sa.text(
                    "SELECT ej.id, ej.kind, ej.params, ej.status, ej.requested_by, "
                    "ej.result_meta, ej.error, ej.created_at, u.email AS requested_email "
                    "FROM export_jobs ej JOIN users u ON u.id = ej.requested_by "
                    "WHERE ej.id = :id"
                ),
                {"id": export_id},
            )
        ).mappings().one_or_none()
    return None if row is None else dict(row)


def _may_read(actor: ActorContext, request_row: dict[str, object]) -> bool:
    """The person who asked, or an administrator.

    A coordinator does not get to download another coordinator's extract just
    because they share a cycle: ANA-4 audits exports by requester, and the
    audit only means something if the requester is who fetched it.
    """
    if actor.role == "admin":
        return True
    return actor.user_id is not None and actor.user_id == request_row["requested_by"]


def mount_export_routes(
    app: FastAPI,
    *,
    actor_provider: ActorProvider,
    limiter: InProcessRateLimiter,
) -> None:
    actor_dependency = Depends(actor_provider)

    @app.get("/api/v1/exports/{export_id}")
    async def export_status(
        export_id: UUID, actor: ActorContext = actor_dependency
    ) -> JSONResponse:
        engine = cast(AsyncEngine, app.state.database_engine)
        request_row = await _load_request(engine, export_id)
        if request_row is None:
            return _problem(EXPORT_NOT_FOUND, "No such export", 404)
        if not _may_read(actor, request_row):
            raise AuthorizationDenied(authenticated=actor.user_id is not None)
        return JSONResponse(
            content={
                "export_id": str(export_id),
                "kind": str(request_row["kind"]),
                "status": str(request_row["status"]),
                "error": request_row["error"],
                # `ready` streams on demand; `queued` is the >5k path and the
                # client polls this until the worker flips it.
                "download_url": (
                    f"/api/v1/exports/{export_id}/download"
                    if str(request_row["status"]) == "ready"
                    else None
                ),
            }
        )

    @app.get("/api/v1/exports/{export_id}/download")
    async def export_download(
        export_id: UUID, actor: ActorContext = actor_dependency
    ) -> Response:
        engine = cast(AsyncEngine, app.state.database_engine)
        request_row = await _load_request(engine, export_id)
        if request_row is None:
            return _problem(EXPORT_NOT_FOUND, "No such export", 404)
        if not _may_read(actor, request_row):
            raise AuthorizationDenied(authenticated=actor.user_id is not None)
        if str(request_row["status"]) != "ready":
            return _problem(
                EXPORT_NOT_READY,
                "This export is still being built",
                409,
            )
        await limiter.check(actor.principal_id, "export_download", DOWNLOAD_RATE_LIMIT)

        params = cast("dict[str, object]", request_row["params"])
        stored = cast("dict[str, object] | None", request_row["result_meta"])
        if stored is not None and stored.get("content"):
            # The deferred path already built this; serving the stored bytes is
            # what makes the poll worth waiting for.  An oversize result stored
            # nothing (LLD section 12) and falls through to a rebuild.
            payload = b64decode(str(stored["content"]))
            media_type, filename = _naming(params)
        else:
            async with engine.connect() as connection:
                table = await build_table(connection, params)
            payload, media_type, filename = render(
                table,
                params,
                requested_by=str(request_row["requested_email"]),
                built_at=datetime.now(UTC),
            )
        return Response(
            content=payload,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


def _naming(params: dict[str, object]) -> tuple[str, str]:
    """Media type and filename for bytes that were built earlier."""
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    if str(params["format"]) == "csv":
        return "text/csv; charset=utf-8", f"{params['kind']}-{stamp}.csv"
    return (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        f"{params['kind']}-{stamp}.xlsx",
    )


def _problem(code: str, human: str, status: int) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": f"/problems/{code.replace('_', '-')}",
            "title": human,
            "status": status,
            "reasons": [asdict(Reason(code=code, human=human))],
        },
    )
