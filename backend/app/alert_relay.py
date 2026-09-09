"""Independent Alertmanager webhook to SES relay.

Only allow-listed operational labels and annotations enter email. The relay has
no database access and remains useful while the portal API is unavailable.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from typing import Literal, Protocol, cast

from fastapi import FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.observability import configure_logging

configure_logging()
LOGGER = logging.getLogger(__name__)
MAX_BODY_BYTES = 64 * 1024
_ALLOWED_LABELS = ("alertname", "severity", "component", "service", "instance")
_ALLOWED_ANNOTATIONS = ("summary", "description", "runbook_url")


class Alert(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["firing", "resolved"]
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: str = ""
    endsAt: str = ""


class AlertWebhook(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["firing", "resolved"]
    alerts: list[Alert] = Field(max_length=100)


class SesClient(Protocol):
    def send_email(self, **kwargs: object) -> object: ...


def render_email(payload: AlertWebhook) -> tuple[str, str]:
    """Render bounded, privacy-safe alert text from an Alertmanager webhook."""

    names = sorted(
        {alert.labels.get("alertname", "UnnamedAlert") for alert in payload.alerts}
    )
    subject_names = ", ".join(names[:3])
    if len(names) > 3:
        subject_names += f" (+{len(names) - 3} more)"
    subject = f"[CDS Portal][{payload.status.upper()}] {subject_names}"

    blocks: list[str] = []
    for alert in payload.alerts:
        lines = [f"Status: {alert.status}"]
        for key in _ALLOWED_LABELS:
            if value := alert.labels.get(key):
                lines.append(f"{key}: {value[:500]}")
        for key in _ALLOWED_ANNOTATIONS:
            if value := alert.annotations.get(key):
                lines.append(f"{key}: {value[:2000]}")
        if alert.startsAt:
            lines.append(f"started_at: {alert.startsAt[:100]}")
        if alert.endsAt:
            lines.append(f"ended_at: {alert.endsAt[:100]}")
        blocks.append("\n".join(lines))
    return subject[:500], "\n\n---\n\n".join(blocks)


def _client() -> SesClient:
    import boto3

    return cast(
        SesClient,
        boto3.client(
            "ses",
            region_name=os.environ.get("SES_REGION", "ap-south-1"),
            aws_access_key_id=os.environ.get("SES_ACCESS_KEY_ID") or None,
            aws_secret_access_key=os.environ.get("SES_SECRET_ACCESS_KEY") or None,
        ),
    )


def _webhook_token() -> str:
    token_file = os.environ.get("ALERT_WEBHOOK_TOKEN_FILE")
    if token_file:
        try:
            with open(token_file, encoding="utf-8") as handle:
                return handle.read().strip()
        except OSError:
            return ""
    return os.environ.get("ALERT_WEBHOOK_TOKEN", "")


def create_alert_relay(*, client: SesClient | None = None) -> FastAPI:
    relay = FastAPI(title="CDS Alert Relay", docs_url=None, redoc_url=None)
    ses = client

    @relay.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @relay.post("/alerts", status_code=status.HTTP_202_ACCEPTED)
    async def alerts(
        payload: AlertWebhook,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        expected = _webhook_token()
        supplied = authorization.removeprefix("Bearer ") if authorization else ""
        if not expected or not secrets.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="Invalid relay credential")
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Alert payload is too large")
        sender = os.environ.get("SES_SENDER", "")
        recipient = os.environ.get("ALERT_RECIPIENT", "")
        reply_to_addresses = [
            address.strip()
            for address in os.environ.get("SES_REPLY_TO", "").split(",")
            if address.strip()
        ]
        if not sender or not recipient:
            raise HTTPException(status_code=503, detail="Alert email is not configured")
        subject, body = render_email(payload)

        def send() -> None:
            request: dict[str, object] = {
                "Source": sender,
                "Destination": {"ToAddresses": [recipient]},
                "Message": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
                },
            }
            if reply_to_addresses:
                request["ReplyToAddresses"] = reply_to_addresses
            (ses or _client()).send_email(**request)

        await asyncio.to_thread(send)
        LOGGER.info("Alert email delivered", extra={"outcome": payload.status})
        return {"status": "accepted"}

    return relay


app = create_alert_relay()
