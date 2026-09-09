"""Procrastinate worker registrations for notifications, reminders, and offer expiry."""

import logging
import os
from base64 import b64encode
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import procrastinate
import sqlalchemy as sa
from procrastinate.job_context import JobContext
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.bootstrap import build_executor, build_registry
from app.core.db import create_engine
from app.core.executor import Executor
from app.core.plan import ActorContext
from app.modules.admin.commands import RunConsistencyCheckerInput
from app.modules.analytics.exports import CompleteExportInput, build_table, render
from app.modules.notifications.delivery import (
    EmailBackend,
    NotificationDeliveryService,
    Sleep,
    email_backend_from_env,
)
from app.modules.notifications.dev_email import dev_email_output_enabled
from app.modules.notifications.reminders import (
    SendDeadlineRemindersInput,
    SendRoundRemindersInput,
)
from app.modules.offers.expiry import EnforceOfferExpiryInput
from app.observability import configure_logging, start_metrics_server_from_env

configure_logging()
start_metrics_server_from_env()

DEFAULT_PROCRASTINATE_DATABASE_URL = "postgresql://cds_app:cds_app@127.0.0.1:5432/cds"
LOGGER = logging.getLogger(__name__)


def _default_executor() -> Executor:
    registry = build_registry()
    return build_executor(registry, create_engine())


def create_procrastinate_app(
    *,
    conninfo: str | None = None,
    executor: Executor | None = None,
    engine: AsyncEngine | None = None,
    email_backend: EmailBackend | None = None,
    sleep: Sleep | None = None,
) -> procrastinate.App:
    dev_email_output_enabled()
    app = procrastinate.App(
        connector=procrastinate.PsycopgConnector(
            conninfo=conninfo
            or os.environ.get("PROCRASTINATE_DATABASE_URL", DEFAULT_PROCRASTINATE_DATABASE_URL)
        )
    )
    command_executor = executor or _default_executor()
    # build_export reads rows outside a command, so it needs a connection of
    # its own; every other task here writes only through the executor.
    read_engine = engine or create_engine()
    delivery = NotificationDeliveryService(
        command_executor,
        email_backend or email_backend_from_env(),
        **({"sleep": sleep} if sleep is not None else {}),
    )
    system = ActorContext(principal_id="system", is_system=True)

    @app.task(name="deliver_notification", pass_context=True)
    async def deliver_notification(
        job_context: JobContext,
        *,
        event_key: str,
        recipient: str,
        notification_id: str | None = None,
        context_data: dict[str, object] | None = None,
        **task_values: object,
    ) -> None:
        notification_context = context_data
        if notification_context is None:
            raw_context = task_values.get("context", {})
            notification_context = raw_context if isinstance(raw_context, dict) else {}
        if job_context.job.id is None:
            raise RuntimeError("Procrastinate task has no job id")
        await delivery.deliver(
            job_id=job_context.job.id,
            event_key=event_key,
            recipient=recipient,
            context=notification_context,
            notification_id=UUID(notification_id) if notification_id else None,
        )
        LOGGER.info(
            "Notification delivery completed",
            extra={"event_key": event_key, "job_id": job_context.job.id},
        )

    @app.task(name="enforce_offer_expiry", pass_context=True)
    async def enforce_offer_expiry(
        job_context: JobContext,
        *,
        offer_id: str,
        scheduled_deadline: str,
    ) -> None:
        if job_context.job.id is None:
            raise RuntimeError("Procrastinate task has no job id")
        await command_executor.run(
            "enforce_offer_expiry",
            EnforceOfferExpiryInput.model_validate(
                {
                    "offer_id": offer_id,
                    "scheduled_deadline": scheduled_deadline,
                }
            ),
            system,
            idempotency_key=f"offer-expiry:{job_context.job.id}",
        )
        LOGGER.info(
            "Offer expiry enforcement completed",
            extra={"offer_id": offer_id, "scheduled_deadline": scheduled_deadline},
        )

    @app.periodic(cron="0 * * * *")
    @app.task(name="send_deadline_reminders")
    async def send_deadline_reminders(timestamp: int) -> None:
        await command_executor.run(
            "send_deadline_reminders",
            SendDeadlineRemindersInput(run_at=datetime.fromtimestamp(timestamp, UTC)),
            system,
        )
        LOGGER.info(
            "Deadline reminder scan completed",
            extra={"scheduled_timestamp": timestamp},
        )

    @app.periodic(cron="0 */6 * * *")
    @app.task(name="send_round_reminders")
    async def send_round_reminders(timestamp: int) -> None:
        await command_executor.run(
            "send_round_reminders",
            SendRoundRemindersInput(run_at=datetime.fromtimestamp(timestamp, UTC)),
            system,
        )
        LOGGER.info(
            "Round reminder scan completed",
            extra={"scheduled_timestamp": timestamp},
        )

    @app.periodic(cron="0 3 * * *")
    @app.task(name="run_consistency_checker")
    async def run_consistency_checker(timestamp: int) -> None:
        summary = await command_executor.run(
            "run_consistency_checker",
            RunConsistencyCheckerInput(run_at=datetime.fromtimestamp(timestamp, UTC)),
            system,
        )
        LOGGER.info(
            "Consistency check completed",
            extra={
                "scheduled_timestamp": timestamp,
                "violations": summary.summary.get("violations"),
                "findings_opened": summary.summary.get("findings_opened"),
            },
        )

    @app.task(name="build_export")
    async def build_export(export_id: str) -> None:
        """The >5k path from LLD section 12, using the same builder as download.

        The task holds no opinion about what an export contains: it runs
        ``build_table``, renders, and hands the result to ``complete_export``,
        which is the only thing here that writes.  A failure is recorded on the
        row rather than swallowed, because a coordinator polling a queued
        export has to be told it will never arrive.
        """
        try:
            async with read_engine.connect() as connection:
                row = (
                    await connection.execute(
                        sa.text(
                            "SELECT ej.params, u.email FROM export_jobs ej "
                            "JOIN users u ON u.id = ej.requested_by WHERE ej.id = :id"
                        ),
                        {"id": UUID(export_id)},
                    )
                ).mappings().one_or_none()
                if row is None:
                    LOGGER.warning("Export vanished before build", extra={"export_id": export_id})
                    return
                params = cast("dict[str, object]", row["params"])
                table = await build_table(connection, params)
            payload, _media_type, _filename = render(
                table, params, requested_by=str(row["email"])
            )
            await command_executor.run(
                "complete_export",
                CompleteExportInput(
                    export_id=UUID(export_id),
                    encoded=b64encode(payload).decode("ascii"),
                    byte_size=len(payload),
                ),
                system,
            )
            LOGGER.info(
                "Export built",
                extra={"export_id": export_id, "bytes": len(payload)},
            )
        except (OSError, ValueError, SQLAlchemyError) as error:
            await command_executor.run(
                "complete_export",
                CompleteExportInput(export_id=UUID(export_id), error=str(error)),
                system,
            )
            LOGGER.exception("Export build failed", extra={"export_id": export_id})

    return app


procrastinate_app = create_procrastinate_app()
