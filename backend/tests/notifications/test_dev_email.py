"""NTF / the design review 4.42: explicit development envelopes, never general telemetry."""

from __future__ import annotations

import json
import logging
from uuid import UUID

import pytest

from app.core.executor import Executor
from app.main import create_app
from app.modules.notifications.delivery import (
    ConsoleEmailBackend,
    EmailMessage,
    NotificationDeliveryService,
    SesEmailBackend,
    email_backend_from_env,
)
from app.observability import JsonFormatter
from app.worker import create_procrastinate_app
from tests.notifications.test_delivery import FakeSesClient

MESSAGE = EmailMessage(
    recipient="student@example.edu",
    sender="cds@example.edu",
    subject="Offer accepted — congratulations",
    body="Dear Student,\nYour offer is accepted.",
    notification_id=UUID("00000000-0000-4000-a000-000000000042"),
    event_key="offer_accepted",
)


def enable(monkeypatch: pytest.MonkeyPatch, environment: str = "test") -> None:
    monkeypatch.setenv("DEV_EMAIL_OUTPUT", "1")
    monkeypatch.setenv("APP_ENV", environment)
    monkeypatch.setenv("NOTIFICATION_BACKEND", "console")


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["development", "test"])
async def test_NTF_opt_in_emits_exact_envelope_without_propagating_to_telemetry(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    environment: str,
) -> None:
    enable(monkeypatch, environment)
    with caplog.at_level(logging.INFO):
        await email_backend_from_env().send(MESSAGE)
    assert json.loads(capsys.readouterr().out) == {
        "kind": "dev_email",
        "recipient": MESSAGE.recipient,
        "sender": MESSAGE.sender,
        "subject": MESSAGE.subject,
        "body": MESSAGE.body,
        "notification_id": str(MESSAGE.notification_id),
        "event_key": MESSAGE.event_key,
    }
    assert caplog.records
    assert all(r.name != "cds.dev_email" for r in caplog.records)
    for record in caplog.records:
        formatted = json.loads(JsonFormatter().format(record))
        assert not {"recipient", "sender", "subject", "body", "dev_email"} & formatted.keys()
        assert MESSAGE.body not in str(record.__dict__)


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", [None, "0"])
async def test_NTF_disabled_console_never_exposes_an_envelope(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    flag: str | None,
) -> None:
    enable(monkeypatch)
    if flag is None:
        monkeypatch.delenv("DEV_EMAIL_OUTPUT")
    else:
        monkeypatch.setenv("DEV_EMAIL_OUTPUT", flag)
    with caplog.at_level(logging.INFO):
        await ConsoleEmailBackend().send(MESSAGE)
    assert capsys.readouterr().out == ""
    assert "Console notification delivered" in caplog.text
    assert MESSAGE.body not in caplog.text
    assert MESSAGE.recipient not in str([r.__dict__ for r in caplog.records])


@pytest.mark.parametrize(
    "environment,backend",
    [
        ("production", "console"),
        ("staging", "console"),
        (None, "console"),
        ("test", "ses"),
        ("test", None),
        ("test", "unknown"),
    ],
)
@pytest.mark.parametrize("entrypoint", ["api", "worker", "backend"])
def test_NTF_unsafe_opt_in_fails_startup_even_with_an_injected_backend(
    monkeypatch: pytest.MonkeyPatch,
    environment: str | None,
    backend: str | None,
    entrypoint: str,
) -> None:
    # Construct an otherwise safe injected backend before the invalid config.
    monkeypatch.delenv("DEV_EMAIL_OUTPUT", raising=False)
    injected = ConsoleEmailBackend()
    enable(monkeypatch)
    for key, value in (("APP_ENV", environment), ("NOTIFICATION_BACKEND", backend)):
        if value is None:
            monkeypatch.delenv(key)
        else:
            monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match="DEV_EMAIL_OUTPUT=1 requires"):
        if entrypoint == "api":
            create_app()
        elif entrypoint == "worker":
            create_procrastinate_app(email_backend=injected)
        else:
            email_backend_from_env()


def test_NTF_invalid_flag_is_not_silently_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    enable(monkeypatch)
    monkeypatch.setenv("DEV_EMAIL_OUTPUT", "yes-please")
    with pytest.raises(ValueError, match="must be 0 or 1"):
        create_app()


@pytest.mark.asyncio
async def test_NTF_SES_never_emits_an_envelope(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("DEV_EMAIL_OUTPUT", "0")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("NOTIFICATION_BACKEND", "ses")
    client = FakeSesClient()
    await SesEmailBackend(region="ap-south-1", client=client).send(MESSAGE)
    assert client.requests[0]["Source"] == MESSAGE.sender
    assert capsys.readouterr().out == ""
    assert MESSAGE.body not in caplog.text


@pytest.mark.asyncio
async def test_NTF_actual_rendered_delivery_carries_its_notification_identity(
    notification_executor: Executor,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    enable(monkeypatch)
    service = NotificationDeliveryService(notification_executor, email_backend_from_env())
    await service.deliver(
        job_id=42,
        notification_id=MESSAGE.notification_id,
        event_key="offer_accepted",
        recipient=MESSAGE.recipient,
        context={"student": "Asha", "job": "Engineer", "company": "Acme"},
    )
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["notification_id"] == str(MESSAGE.notification_id)
    assert envelope["event_key"] == "offer_accepted"
    assert envelope["recipient"] == MESSAGE.recipient
    assert envelope["subject"] == "Offer accepted: Engineer at Acme"
    assert "Dear Asha," in envelope["body"]
    assert "Engineer" in envelope["body"]
    assert envelope["body"].endswith(
        "Contact your placement office if you have questions about this notification."
    )
