"""Parse-only upload endpoint feeding ``assign_venue_timing`` (Behavior RND-4).

This route writes nothing: it turns a CSV/XLSX upload into the rows the command
consumes, so staff preview (``dry_run``) and commit the same parsed data.  The
authorization that matters is the command's -- this endpoint only refuses a
caller who is not staff at all, since the file names no cycle to be scoped by.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import Depends, FastAPI, File, UploadFile
from fastapi.responses import JSONResponse

from app.core.errors import UNPARSABLE_UPLOAD, AuthorizationDenied
from app.core.plan import ActorContext, Reason
from app.core.rate_limit import InProcessRateLimiter
from app.core.routes import ActorProvider
from app.core.uploads import UploadParseError
from app.modules.applications.slots import parse_slot_upload

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
UPLOAD_RATE_LIMIT = "10/min"
UPLOAD_FILE = File(...)


def mount_venue_upload_route(
    app: FastAPI,
    *,
    actor_provider: ActorProvider,
    limiter: InProcessRateLimiter,
) -> None:
    actor_dependency = Depends(actor_provider)

    @app.post("/api/v1/uploads/venue-rows")
    async def parse_venue_upload(
        file: UploadFile = UPLOAD_FILE,
        actor: ActorContext = actor_dependency,
    ) -> JSONResponse:
        authenticated = actor.user_id is not None and actor.session_id is not None
        is_staff = actor.role == "admin" or bool(actor.coordinated_cycle_ids)
        if not (authenticated and is_staff):
            raise AuthorizationDenied(authenticated=authenticated)
        await limiter.check(actor.principal_id, "upload_venue_rows", UPLOAD_RATE_LIMIT)
        payload = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(payload) > MAX_UPLOAD_BYTES:
            return _problem("The upload exceeds 5 MB")
        try:
            parsed = parse_slot_upload(payload, file.filename or "")
        except UploadParseError as error:
            return _problem(str(error))
        return JSONResponse(
            content={
                "rows": [asdict(row) for row in parsed.rows],
                "errors": [asdict(error) for error in parsed.errors],
                "headers": list(parsed.headers),
            }
        )


def _problem(human: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        media_type="application/problem+json",
        content={
            "type": "/problems/unparsable-upload",
            "title": "Upload could not be parsed",
            "status": 422,
            "reasons": [asdict(Reason(code=UNPARSABLE_UPLOAD, human=human))],
        },
    )
