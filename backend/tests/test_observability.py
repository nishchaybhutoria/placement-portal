"""Operational telemetry contracts: correlation, privacy, and alert delivery."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app.alert_relay import AlertWebhook, create_alert_relay, render_email
from app.main import create_app
from app.observability import JsonFormatter, command_log_context, request_log_context


@pytest.mark.asyncio
async def test_request_id_is_canonical_and_returned() -> None:
    app = create_app("postgresql+asyncpg://cds:cds@127.0.0.1:1/cds")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/healthz", headers={"X-Request-ID": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}
        )

    assert response.headers["X-Request-ID"] == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


@pytest.mark.asyncio
async def test_malformed_request_id_is_replaced() -> None:
    app = create_app("postgresql+asyncpg://cds:cds@127.0.0.1:1/cds")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz", headers={"X-Request-ID": "log injection\n"})

    assert response.headers["X-Request-ID"] != "log injection\n"
    assert len(response.headers["X-Request-ID"]) == 36


def test_json_formatter_does_not_serialize_arbitrary_extra_fields() -> None:
    import logging

    record = logging.LogRecord("test", logging.INFO, __file__, 1, "safe", (), None)
    record.recipient = "student@example.edu"
    record.body = "private notification body"
    record.command = "apply"
    record.actor_user_id = "11111111-1111-4111-8111-111111111111"
    record.cycle_id = "22222222-2222-4222-8222-222222222222"
    record.job_id = "33333333-3333-4333-8333-333333333333"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["command"] == "apply"
    assert payload["actor_user_id"] == "11111111-1111-4111-8111-111111111111"
    assert payload["cycle_id"] == "22222222-2222-4222-8222-222222222222"
    assert payload["job_id"] == "33333333-3333-4333-8333-333333333333"
    assert "recipient" not in payload
    assert "body" not in payload


def test_command_log_context_includes_actor_and_domain_ids_without_pii() -> None:
    context = command_log_context(
        SimpleNamespace(
            cycle_id="22222222-2222-4222-8222-222222222222",
            job_id="33333333-3333-4333-8333-333333333333",
            email="private@example.edu",
        ),
        SimpleNamespace(
            user_id="11111111-1111-4111-8111-111111111111",
            role="coordinator",
            is_system=False,
            is_test_harness=False,
            email="actor@example.edu",
        ),
    )

    assert context == {
        "actor_user_id": "11111111-1111-4111-8111-111111111111",
        "actor_role": "coordinator",
        "actor_kind": "authenticated",
        "cycle_id": "22222222-2222-4222-8222-222222222222",
        "job_id": "33333333-3333-4333-8333-333333333333",
    }


def test_request_log_context_uses_route_actor_and_valid_scope_ids_only() -> None:
    cycle_id = "22222222-2222-4222-8222-222222222222"
    scope: dict[str, object] = {
        "method": "GET",
        "route": SimpleNamespace(path="/api/v1/screens/staff/job/{job_id}"),
        "query_string": (
            f"cycle_id={cycle_id}&job_id=not-a-uuid&email=private%40example.edu"
        ).encode(),
        "actor_user_id": "11111111-1111-4111-8111-111111111111",
        "actor_role": "coordinator",
    }

    context = request_log_context(scope)

    assert context == {
        "http_method": "GET",
        "route": "/api/v1/screens/staff/job/{job_id}",
        "actor_user_id": "11111111-1111-4111-8111-111111111111",
        "actor_role": "coordinator",
        "cycle_id": cycle_id,
    }


def test_alert_email_uses_only_allowlisted_values() -> None:
    payload = AlertWebhook.model_validate(
        {
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {
                        "alertname": "ApiUnavailable",
                        "severity": "critical",
                        "student_email": "private@example.edu",
                    },
                    "annotations": {
                        "summary": "API is unavailable",
                        "request_body": "private body",
                    },
                }
            ],
        }
    )

    subject, body = render_email(payload)

    assert "ApiUnavailable" in subject
    assert "API is unavailable" in body
    assert "private@example.edu" not in body
    assert "private body" not in body


class _FakeSes:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def send_email(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return {}


@pytest.mark.asyncio
async def test_alert_relay_requires_token_and_sends_via_ses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALERT_WEBHOOK_TOKEN", "test-secret")
    monkeypatch.setenv("SES_SENDER", "sender@example.edu")
    monkeypatch.setenv("SES_REPLY_TO", "cds@example.edu, tech.cds@example.edu")
    monkeypatch.setenv("ALERT_RECIPIENT", "ops@example.edu")
    ses = _FakeSes()
    app = create_alert_relay(client=ses)
    transport = httpx.ASGITransport(app=app)
    body = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "DiskFull", "severity": "critical"},
                "annotations": {"summary": "Disk is almost full"},
            }
        ],
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        denied = await client.post("/alerts", json=body)
        accepted = await client.post(
            "/alerts", json=body, headers={"Authorization": "Bearer test-secret"}
        )

    assert denied.status_code == 401
    assert accepted.status_code == 202
    assert len(ses.calls) == 1
    assert ses.calls[0]["ReplyToAddresses"] == [
        "cds@example.edu",
        "tech.cds@example.edu",
    ]
