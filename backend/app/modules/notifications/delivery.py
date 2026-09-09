"""Email backends and the five-attempt notification delivery loop."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from app.core.executor import Executor
from app.core.plan import ActorContext, Result
from app.modules.notifications.commands import (
    DeliverNotificationInput,
    RecordNotificationAttemptInput,
)
from app.modules.notifications.dev_email import dev_email_logger, dev_email_output_enabled

LOGGER = logging.getLogger(__name__)
MAX_DELIVERY_ATTEMPTS = 5
CONTACT_FOOTER = (
    "Contact your placement office if you have questions about this notification."
)


@dataclass(frozen=True, slots=True)
class EmailMessage:
    recipient: str
    sender: str
    subject: str
    body: str
    notification_id: UUID | None = None
    event_key: str | None = None


class EmailBackend(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


class ConsoleEmailBackend:
    """Console delivery marker, with an explicit development-only envelope sink."""

    def __init__(self) -> None:
        self._envelopes = dev_email_logger()

    async def send(self, message: EmailMessage) -> None:
        if self._envelopes is not None:
            self._envelopes.info(
                "Development email",
                extra={
                    "dev_email": {
                        "recipient": message.recipient,
                        "sender": message.sender,
                        "subject": message.subject,
                        "body": message.body,
                        "notification_id": (
                            str(message.notification_id) if message.notification_id else None
                        ),
                        "event_key": message.event_key,
                    }
                },
            )
        LOGGER.info(
            "Console notification delivered",
            extra={"notification_id": message.notification_id, "event_key": message.event_key},
        )


class SesEmailBackend:
    """AWS SES adapter; boto3's blocking call is kept off the worker loop."""

    def __init__(
        self,
        *,
        region: str,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        reply_to_addresses: tuple[str, ...] = (),
        client: object | None = None,
    ) -> None:
        if client is None:
            import boto3

            client = boto3.client(
                "ses",
                region_name=region,
                aws_access_key_id=access_key_id or None,
                aws_secret_access_key=secret_access_key or None,
            )
        self._client = client
        self._reply_to_addresses = reply_to_addresses

    async def send(self, message: EmailMessage) -> None:
        if not message.sender:
            raise ValueError("SES sender is not configured")

        def send_email() -> None:
            client = cast("_SesClient", self._client)
            request: dict[str, object] = {
                "Source": message.sender,
                "Destination": {"ToAddresses": [message.recipient]},
                "Message": {
                    "Subject": {"Data": message.subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": message.body, "Charset": "UTF-8"}},
                },
            }
            if self._reply_to_addresses:
                request["ReplyToAddresses"] = list(self._reply_to_addresses)
            client.send_email(**request)

        await asyncio.to_thread(send_email)


class _SesClient(Protocol):
    def send_email(self, **kwargs: object) -> object: ...


def email_backend_from_env() -> EmailBackend:
    dev_email_output_enabled()
    backend = os.environ.get("NOTIFICATION_BACKEND", "console").strip().lower()
    if backend == "console":
        return ConsoleEmailBackend()
    if backend == "ses":
        return SesEmailBackend(
            region=os.environ.get("SES_REGION", "ap-south-1"),
            access_key_id=os.environ.get("SES_ACCESS_KEY_ID"),
            secret_access_key=os.environ.get("SES_SECRET_ACCESS_KEY"),
            reply_to_addresses=tuple(
                address.strip()
                for address in os.environ.get("SES_REPLY_TO", "").split(",")
                if address.strip()
            ),
        )
    raise ValueError("NOTIFICATION_BACKEND must be 'console' or 'ses'")


Sleep = Callable[[float], Awaitable[None]]


class NotificationDeliveryService:
    """Prepare, send, and record one notification without direct database writes."""

    def __init__(
        self,
        executor: Executor,
        backend: EmailBackend,
        *,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._executor = executor
        self._backend = backend
        self._sleep = sleep
        self._system = ActorContext(principal_id="system", is_system=True)

    async def deliver(
        self,
        *,
        job_id: int,
        event_key: str,
        recipient: str,
        context: dict[str, object],
        notification_id: UUID | None = None,
    ) -> None:
        log_id = notification_id or uuid5(NAMESPACE_URL, f"cds:notification-job:{job_id}")
        prepared = await self._executor.run(
            "deliver_notification",
            DeliverNotificationInput(
                notification_id=log_id,
                event_key=event_key,
                recipient=recipient,
                context=context,
            ),
            self._system,
        )
        assert isinstance(prepared, Result)
        if not bool(prepared.summary["should_send"]):
            return

        attempts = cast(int, prepared.summary["attempts"])
        message = EmailMessage(
            recipient=recipient,
            sender=str(prepared.summary["sender"] or os.environ.get("SES_SENDER", "")),
            subject=str(prepared.summary["subject"]),
            body=f"{str(prepared.summary['body']).rstrip()}\n\n{CONTACT_FOOTER}",
            notification_id=log_id,
            event_key=event_key,
        )
        while attempts < MAX_DELIVERY_ATTEMPTS:
            error_text: str | None = None
            delivered = False
            try:
                await self._backend.send(message)
                delivered = True
            except Exception as error:
                # External delivery errors are data for the attempt command;
                # command/database failures below still propagate to the queue.
                error_text = f"{type(error).__name__}: {error}"

            recorded = await self._executor.run(
                "record_notification_attempt",
                RecordNotificationAttemptInput(
                    notification_id=log_id,
                    delivered=delivered,
                    error=error_text,
                ),
                self._system,
            )
            assert isinstance(recorded, Result)
            attempts = cast(int, recorded.summary["attempts"])
            status = str(recorded.summary["status"])
            if delivered or status == "dead":
                return
            await self._sleep(float(2 ** (attempts - 1)))
