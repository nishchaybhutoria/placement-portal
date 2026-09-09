"""SES/console delivery, five attempts, and dead-letter resend (Behavior NTF)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.executor import Executor
from app.core.plan import ActorContext
from app.modules.notifications.commands import ResendNotificationInput
from app.modules.notifications.delivery import (
    EmailMessage,
    NotificationDeliveryService,
    SesEmailBackend,
)

ADMIN = UUID("00000000-0000-0000-0000-000000001401")
ADMIN_ACTOR = ActorContext(
    principal_id=str(ADMIN),
    user_id=ADMIN,
    role="admin",
    session_id=UUID("00000000-0000-0000-0000-000000001402"),
)


@dataclass
class RecordingBackend:
    failures_left: int
    messages: list[EmailMessage] = field(default_factory=list)

    async def send(self, message: EmailMessage) -> None:
        self.messages.append(message)
        if self.failures_left:
            self.failures_left -= 1
            raise RuntimeError("SES is unavailable")


class FakeSesClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def send_email(self, **kwargs: object) -> object:
        self.requests.append(kwargs)
        return {"MessageId": "ses-test"}


@pytest.mark.asyncio
async def test_NTF_SES_adapter_sends_utf8_subject_and_body() -> None:
    client = FakeSesClient()
    backend = SesEmailBackend(
        region="ap-south-1",
        reply_to_addresses=("cds@example.edu", "tech.cds@example.edu"),
        client=client,
    )
    await backend.send(
        EmailMessage(
            recipient="student@example.edu",
            sender="cds@example.edu",
            subject="Offer extended",
            body="Congratulations",
        )
    )
    assert client.requests == [
        {
            "Source": "cds@example.edu",
            "Destination": {"ToAddresses": ["student@example.edu"]},
            "ReplyToAddresses": ["cds@example.edu", "tech.cds@example.edu"],
            "Message": {
                "Subject": {"Data": "Offer extended", "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": "Congratulations", "Charset": "UTF-8"}
                },
            },
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_key", "context", "expected_subject", "expected_body"),
    [
        (
            "deadline_changed",
            {
                "student": "Asha Mehta",
                "job": "Backend Engineer",
                "application_deadline": "18 September 2026, 5:00 PM IST",
                "offer_acceptance_deadline": "20 September 2026, 5:00 PM IST",
                "shortened": True,
            },
            "Deadline updated: Backend Engineer",
            "A deadline for Backend Engineer has been updated.",
        ),
        (
            "declined_confirm",
            {
                "student": "Asha Mehta",
                "job": "Backend Engineer",
                "company": "Northwind Systems",
            },
            "Offer declined: Backend Engineer at Northwind Systems",
            "Your decision to decline the Backend Engineer offer from Northwind Systems",
        ),
    ],
)
async def test_NTF_amended_catalog_events_are_delivered_not_suppressed(
    notification_executor: Executor,
    event_key: str,
    context: dict[str, object],
    expected_subject: str,
    expected_body: str,
) -> None:
    backend = RecordingBackend(failures_left=0)
    await NotificationDeliveryService(notification_executor, backend).deliver(
        job_id=601,
        event_key=event_key,
        recipient="asha@example.edu",
        context=context,
    )

    assert len(backend.messages) == 1
    message = backend.messages[0]
    assert message.subject == expected_subject
    assert expected_body in message.body
    assert message.body.startswith("Dear Asha Mehta,")
    assert message.body.endswith(
        "Contact your placement office if you have questions about this notification."
    )


async def _seed_admin() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "INSERT INTO users (id, email, full_name, role) "
                    "VALUES (:id, 'delivery-admin@example.edu', 'Delivery Admin', 'admin')"
                ),
                {"id": ADMIN},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO settings (key, value, updated_by) "
                    "VALUES ('ses_sender', to_jsonb('cds@example.edu'::text), :admin)"
                ),
                {"admin": ADMIN},
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_NTF_five_failed_attempts_are_recorded_dead_then_staff_can_resend(
    notification_executor: Executor,
) -> None:
    await _seed_admin()
    notification_id = uuid4()
    sleeps: list[float] = []

    async def no_wait(delay: float) -> None:
        sleeps.append(delay)

    failing = RecordingBackend(failures_left=5)
    service = NotificationDeliveryService(notification_executor, failing, sleep=no_wait)
    await service.deliver(
        job_id=501,
        notification_id=notification_id,
        event_key="offer_extended",
        recipient="student@example.edu",
        context={
            "student": "Asha",
            "job": "Backend Engineer",
            "company": "Northwind Systems",
            "deadline": "tomorrow",
        },
    )

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        sa.text(
                            "SELECT recipient, event_key, subject, status, attempts, "
                            "last_error, sent_at FROM notification_log WHERE id = :id"
                        ),
                        {"id": notification_id},
                    )
                )
                .mappings()
                .one()
            )
    finally:
        await engine.dispose()
    assert len(failing.messages) == 5
    assert sleeps == [1.0, 2.0, 4.0, 8.0]
    assert dict(row) == {
        "recipient": "student@example.edu",
        "event_key": "offer_extended",
        "subject": "Offer extended: Backend Engineer at Northwind Systems",
        "status": "dead",
        "attempts": 5,
        "last_error": "RuntimeError: SES is unavailable",
        "sent_at": None,
    }

    resent = await notification_executor.run(
        "resend_notification",
        ResendNotificationInput(notification_id=notification_id),
        ADMIN_ACTOR,
    )
    assert resent.summary == {
        "notification_id": str(notification_id),
        "queued": True,
    }

    succeeding = RecordingBackend(failures_left=0)
    await NotificationDeliveryService(notification_executor, succeeding, sleep=no_wait).deliver(
        job_id=502,
        notification_id=notification_id,
        event_key="offer_extended",
        recipient="student@example.edu",
        context={
            "student": "Asha",
            "job": "Backend Engineer",
            "company": "Northwind Systems",
            "deadline": "tomorrow",
        },
    )
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            final = (
                (
                    await connection.execute(
                        sa.text(
                            "SELECT status, attempts, last_error, sent_at "
                            "FROM notification_log WHERE id = :id"
                        ),
                        {"id": notification_id},
                    )
                )
                .mappings()
                .one()
            )
            queued_resends = int(
                await connection.scalar(
                    sa.text(
                        "SELECT count(*) FROM procrastinate_jobs "
                        "WHERE task_name = 'deliver_notification' "
                        "AND args->>'notification_id' = :id"
                    ),
                    {"id": str(notification_id)},
                )
                or 0
            )
    finally:
        await engine.dispose()
    assert final["status"] == "sent"
    assert final["attempts"] == 1
    assert final["last_error"] is None
    assert final["sent_at"] is not None
    assert len(succeeding.messages) == 1
    assert queued_resends == 1
