"""Operational telemetry with bounded labels and privacy-safe JSON logs."""

from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from urllib.parse import parse_qsl
from uuid import UUID, uuid4

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
    start_http_server,
)
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID = contextvars.ContextVar[str | None]("request_id", default=None)
COMMAND_EXECUTION_ID = contextvars.ContextVar[str | None](
    "command_execution_id", default=None
)

HTTP_REQUESTS = Counter(
    "cds_http_requests_total",
    "HTTP requests completed by the API.",
    ("method", "route", "status_class"),
)
HTTP_DURATION = Histogram(
    "cds_http_request_duration_seconds",
    "HTTP request duration by route template.",
    ("method", "route"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
COMMAND_EXECUTIONS = Counter(
    "cds_command_executions_total",
    "Command executor invocations.",
    ("command", "outcome", "dry_run"),
)
COMMAND_DURATION = Histogram(
    "cds_command_duration_seconds",
    "Command executor duration.",
    ("command", "outcome", "dry_run"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)

_DOMAIN_ID_FIELDS = {
    "application_id",
    "company_id",
    "cycle_id",
    "enrollment_id",
    "export_id",
    "job_id",
    "notification_id",
    "offer_id",
    "round_id",
    "user_id",
}
_EXTRA_FIELDS = {
    "actor_kind",
    "actor_role",
    "actor_user_id",
    "command",
    "command_execution_id",
    "dry_run",
    "duration_ms",
    "event_key",
    "findings_opened",
    "http_method",
    "outcome",
    "request_id",
    "route",
    "scheduled_deadline",
    "scheduled_timestamp",
    "status_code",
    "task",
    # The *name* of a template variable and which part it was rendering. Both
    # are catalog vocabulary -- "student", "subject" -- fixed in the source and
    # never a value: 116 warnings in the mock run said a variable was missing
    # and could not say which, which is a diagnostic that fires and lands
    # unreadable. Section 4's prohibition is on notification content, and this
    # is not content.
    "part",
    "variable",
    "violations",
    *_DOMAIN_ID_FIELDS,
}


class JsonFormatter(logging.Formatter):
    """Format one line of JSON without serializing arbitrary record values."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": os.environ.get("SERVICE_NAME", "api"),
            "environment": os.environ.get("APP_ENV", "development"),
            "release": os.environ.get("RELEASE", "unknown"),
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = REQUEST_ID.get()
        execution_id = COMMAND_EXECUTION_ID.get()
        if request_id:
            payload["request_id"] = request_id
        if execution_id:
            payload["command_execution_id"] = execution_id
        for key in _EXTRA_FIELDS:
            if key in record.__dict__ and key not in payload:
                payload[key] = _json_value(record.__dict__[key])
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)


def _json_value(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def command_log_context(input_value: object, actor: object) -> dict[str, object]:
    """Return privacy-safe actor and top-level command identifiers for logs."""

    context: dict[str, object] = {}
    actor_user_id = getattr(actor, "user_id", None)
    actor_role = getattr(actor, "role", None)
    if actor_user_id is not None:
        context["actor_user_id"] = str(actor_user_id)
    if actor_role is not None:
        context["actor_role"] = str(actor_role)
    if getattr(actor, "is_system", False):
        context["actor_kind"] = "system"
    elif getattr(actor, "is_test_harness", False):
        context["actor_kind"] = "test_harness"
    elif actor_user_id is not None:
        context["actor_kind"] = "authenticated"
    else:
        context["actor_kind"] = "anonymous"

    for field in _DOMAIN_ID_FIELDS:
        value = getattr(input_value, field, None)
        if value is not None:
            context[field] = str(value)
    return context


def request_log_context(scope: Mapping[str, object]) -> dict[str, object]:
    """Build a safe HTTP context without logging bodies or raw query strings."""

    route = scope.get("route")
    context: dict[str, object] = {
        "http_method": str(scope.get("method", "UNKNOWN")),
        "route": str(getattr(route, "path", "unmatched")),
    }
    for field in ("actor_user_id", "actor_role", "actor_kind"):
        value = scope.get(field)
        if value is not None:
            context[field] = str(value)

    candidates: list[tuple[str, object]] = []
    path_params = scope.get("path_params")
    if isinstance(path_params, dict):
        candidates.extend(path_params.items())
    raw_query = scope.get("query_string")
    if isinstance(raw_query, bytes):
        candidates.extend(parse_qsl(raw_query.decode("ascii", errors="ignore")))
    for field, value in candidates:
        if field not in _DOMAIN_ID_FIELDS or field in context:
            continue
        try:
            context[field] = str(UUID(str(value)))
        except ValueError:
            continue
    return context


def configure_logging() -> None:
    """Install the process-wide JSON formatter exactly once."""

    root = logging.getLogger()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.handlers[:] = [handler]
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True


def start_metrics_server_from_env() -> None:
    """Expose single-process worker metrics without affecting CLI health checks."""

    port = os.environ.get("METRICS_PORT")
    if port and "healthchecks" not in sys.argv:
        start_http_server(int(port))


def metrics_payload() -> bytes:
    """Render either the normal registry or Uvicorn's multiprocess registry."""

    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry)
    return generate_latest()


def valid_request_id(value: str | None) -> str:
    """Return a canonical UUID, replacing malformed edge input."""

    if value:
        try:
            return str(UUID(value))
        except ValueError:
            pass
    return str(uuid4())


class RequestTelemetryMiddleware:
    """Correlate, log, and measure HTTP requests without reading their bodies."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.logger = logging.getLogger("cds.http")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        raw_id = headers.get(b"x-request-id")
        request_id = valid_request_id(
            raw_id.decode("ascii", errors="ignore") if raw_id else None
        )
        token = REQUEST_ID.set(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                response_headers = MutableHeaders(scope=message)
                response_headers["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except BaseException:
            self.logger.exception("HTTP request failed")
            raise
        finally:
            elapsed = time.perf_counter() - started
            route = scope.get("route")
            route_template = getattr(route, "path", "unmatched")
            method = str(scope.get("method", "UNKNOWN"))
            status_class = f"{status_code // 100}xx"
            if route_template not in {"/healthz", "/readyz", "/metrics"}:
                HTTP_REQUESTS.labels(method, route_template, status_class).inc()
                HTTP_DURATION.labels(method, route_template).observe(elapsed)
                self.logger.info(
                    "HTTP request completed",
                    extra={
                        **request_log_context(scope),
                        "duration_ms": round(elapsed * 1000, 3),
                        "status_code": status_code,
                    },
                )
            REQUEST_ID.reset(token)


def command_started() -> tuple[str, contextvars.Token[str | None], float]:
    execution_id = str(uuid4())
    token = COMMAND_EXECUTION_ID.set(execution_id)
    return execution_id, token, time.perf_counter()


def command_finished(
    *,
    command: str,
    dry_run: bool,
    outcome: str,
    started: float,
    token: contextvars.Token[str | None],
) -> float:
    elapsed = time.perf_counter() - started
    preview = str(dry_run).lower()
    try:
        COMMAND_EXECUTIONS.labels(command, outcome, preview).inc()
        COMMAND_DURATION.labels(command, outcome, preview).observe(elapsed)
    except Exception:
        # Telemetry is explicitly outside the command correctness boundary.
        logging.getLogger(__name__).exception("Command metrics update failed")
    finally:
        COMMAND_EXECUTION_ID.reset(token)
    return elapsed
