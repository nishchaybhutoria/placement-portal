"""SES/console delivery, scheduled retries, and dead-letter resend (Behavior NTF)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import DomainRejection
from app.core.executor import Executor
from app.core.plan import ActorContext
from app.modules.notifications.catalog import expires_at
from app.modules.notifications.commands import (
    MAX_DELIVERY_ATTEMPTS,
    NOTIFICATION_EXPIRED,
    RETRY_DELAYS,
    ResendNotificationInput,
)
from app.modules.notifications.delivery import (
    EmailMessage,
    NotificationDeliveryService,
    SesEmailBackend,
)
from app.modules.notifications.wording import format_time

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
async def test_NTF_failed_sends_back_off_for_days_then_dead_then_staff_can_resend(
    notification_executor: Executor,
) -> None:
    await _seed_admin()
    notification_id = uuid4()
    context: dict[str, object] = {
        "student": "Asha",
        "job": "Backend Engineer",
        "company": "Northwind Systems",
        "deadline": "tomorrow",
    }
    # A seconds-long blip once dead-lettered every email in flight; the
    # schedule now has to outlast an outage of a couple of days.
    assert sum(RETRY_DELAYS, timedelta()) >= timedelta(days=2)

    failing = RecordingBackend(failures_left=MAX_DELIVERY_ATTEMPTS)
    service = NotificationDeliveryService(notification_executor, failing)
    delays: list[timedelta] = []
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        # Each job makes one attempt; run every scheduled retry back to back.
        for attempt in range(1, MAX_DELIVERY_ATTEMPTS + 1):
            await service.deliver(
                job_id=500 + attempt,
                notification_id=notification_id,
                event_key="offer_extended",
                recipient="student@example.edu",
                context=context,
            )
            if attempt == MAX_DELIVERY_ATTEMPTS:
                break
            async with engine.connect() as connection:
                retry = (
                    (
                        await connection.execute(
                            sa.text(
                                "SELECT j.args, j.scheduled_at - n.updated_at AS delay "
                                "FROM procrastinate_jobs j, notification_log n "
                                "WHERE n.id = :id "
                                "AND j.task_name = 'deliver_notification' "
                                "AND j.args->>'notification_id' = :key "
                                "ORDER BY j.scheduled_at DESC LIMIT 1"
                            ),
                            {"id": notification_id, "key": str(notification_id)},
                        )
                    )
                    .mappings()
                    .one()
                )
            # The retry carries the log's identity, not a fresh job-derived one.
            assert retry["args"] == {
                "notification_id": str(notification_id),
                "event_key": "offer_extended",
                "recipient": "student@example.edu",
                "context": context,
            }
            delays.append(retry["delay"])
        # A job that fires after the notification died sends nothing.
        await service.deliver(
            job_id=500 + MAX_DELIVERY_ATTEMPTS + 1,
            notification_id=notification_id,
            event_key="offer_extended",
            recipient="student@example.edu",
            context=context,
        )
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
    assert len(failing.messages) == MAX_DELIVERY_ATTEMPTS
    assert delays == list(RETRY_DELAYS)
    assert dict(row) == {
        "recipient": "student@example.edu",
        "event_key": "offer_extended",
        "subject": "Offer extended: Backend Engineer at Northwind Systems",
        "status": "dead",
        "attempts": MAX_DELIVERY_ATTEMPTS,
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
    await NotificationDeliveryService(notification_executor, succeeding).deliver(
        job_id=600,
        notification_id=notification_id,
        event_key="offer_extended",
        recipient="student@example.edu",
        context=context,
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
            queued_jobs = int(
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
    # One job per scheduled retry, one for the staff resend, and none after
    # the success.
    assert queued_jobs == len(RETRY_DELAYS) + 1


async def _delivery_record(notification_id: UUID) -> tuple[dict[str, object], int]:
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            row = (
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
            jobs = int(
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
    return dict(row), jobs


@pytest.mark.asyncio
async def test_NTF_a_time_bound_notice_stops_retrying_once_it_would_arrive_too_late(
    notification_executor: Executor,
) -> None:
    await _seed_admin()
    notification_id = uuid4()
    # Ten minutes of usefulness fits the one- and five-minute retries; the
    # fifteen-minute one would land after the round has started.
    context: dict[str, object] = {
        "student": "Asha",
        "job": "Backend Engineer",
        "round": "Technical interview",
        "venue": "LH 101",
        "time": "in ten minutes",
        **expires_at(datetime.now(UTC) + timedelta(minutes=10)),
    }
    failing = RecordingBackend(failures_left=MAX_DELIVERY_ATTEMPTS)
    service = NotificationDeliveryService(notification_executor, failing)
    for job_id in (701, 702, 703, 704):
        await service.deliver(
            job_id=job_id,
            notification_id=notification_id,
            event_key="round_reminder",
            recipient="student@example.edu",
            context=context,
        )

    row, jobs = await _delivery_record(notification_id)
    assert len(failing.messages) == 3
    assert jobs == 2
    assert row == {
        "status": "dead",
        "attempts": 3,
        "last_error": "RuntimeError: SES is unavailable",
        "sent_at": None,
    }


@pytest.mark.asyncio
async def test_NTF_an_expired_notice_is_not_sent_and_cannot_be_resent(
    notification_executor: Executor,
) -> None:
    await _seed_admin()
    notification_id = uuid4()
    deadline = datetime.now(UTC) - timedelta(minutes=1)
    backend = RecordingBackend(failures_left=0)
    await NotificationDeliveryService(notification_executor, backend).deliver(
        job_id=801,
        notification_id=notification_id,
        event_key="deadline_reminder",
        recipient="student@example.edu",
        context={
            "student": "Asha",
            "job": "Backend Engineer",
            "company": "Northwind Systems",
            "hours_left": 6,
            **expires_at(deadline),
        },
    )

    row, jobs = await _delivery_record(notification_id)
    # A worker that fell behind does not tell a student to apply before a
    # deadline that has already passed; staff still see it never went out.
    assert backend.messages == []
    assert jobs == 0
    assert row == {
        "status": "dead",
        "attempts": 0,
        "last_error": f"Expired at {format_time(deadline)} before it could be delivered",
        "sent_at": None,
    }

    with pytest.raises(DomainRejection) as rejected:
        await notification_executor.run(
            "resend_notification",
            ResendNotificationInput(notification_id=notification_id),
            ADMIN_ACTOR,
        )
    assert [reason.code for reason in rejected.value.rejection.reasons] == [
        NOTIFICATION_EXPIRED
    ]
