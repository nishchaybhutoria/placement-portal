"""Exercise the production worker and notification pipeline after deployment."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4

import sqlalchemy as sa

from app.core.db import create_engine
from app.worker import procrastinate_app


async def run(*, recipient: str, wait_seconds: float) -> int:
    """Queue both reminder scans and one synthetic notification, then await them."""
    timestamp = int(datetime.now(UTC).timestamp())
    notification_id = uuid4()
    await procrastinate_app.connector.open_async()
    try:
        deadline_job = await procrastinate_app.configure_task(
            name="send_deadline_reminders"
        ).defer_async(timestamp=timestamp)
        round_job = await procrastinate_app.configure_task(
            name="send_round_reminders"
        ).defer_async(timestamp=timestamp)
        notification_job = await procrastinate_app.configure_task(
            name="deliver_notification"
        ).defer_async(
            notification_id=str(notification_id),
            event_key="membership_approved",
            recipient=recipient,
            context={"student": "Launch Probe", "cycle": "Go-live readiness"},
        )
    finally:
        await procrastinate_app.connector.close_async()

    expected_jobs = {deadline_job, round_job, notification_job}
    engine = create_engine()
    deadline = monotonic() + wait_seconds
    jobs: dict[int, str] = {}
    notification_status: str | None = None
    attempts = 0
    try:
        while monotonic() < deadline:
            async with engine.connect() as connection:
                rows = (
                    await connection.execute(
                        sa.text(
                            "SELECT id, status FROM procrastinate_jobs "
                            "WHERE id = ANY(CAST(:ids AS bigint[]))"
                        ),
                        {"ids": list(expected_jobs)},
                    )
                ).mappings()
                jobs = {int(row["id"]): str(row["status"]) for row in rows}
                notification = (
                    await connection.execute(
                        sa.text(
                            "SELECT status, attempts FROM notification_log WHERE id = :id"
                        ),
                        {"id": notification_id},
                    )
                ).mappings().one_or_none()
                if notification is not None:
                    notification_status = str(notification["status"])
                    attempts = int(notification["attempts"])
            if (
                jobs.keys() == expected_jobs
                and all(status == "succeeded" for status in jobs.values())
                and notification_status == "sent"
            ):
                break
            await asyncio.sleep(0.25)
    finally:
        await engine.dispose()

    summary = {
        "deadline_reminder_job": deadline_job,
        "round_reminder_job": round_job,
        "notification_job": notification_job,
        "notification_id": str(notification_id),
        "notification_status": notification_status,
        "notification_attempts": attempts,
        "job_statuses": {str(key): value for key, value in sorted(jobs.items())},
    }
    print(json.dumps(summary, sort_keys=True))
    passed = (
        jobs.keys() == expected_jobs
        and all(status == "succeeded" for status in jobs.values())
        and notification_status == "sent"
        and attempts == 1
    )
    return 0 if passed else 2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipient", required=True, help="Institutional launch-test recipient")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(run(recipient=args.recipient, wait_seconds=args.timeout))
    )


if __name__ == "__main__":
    main()
