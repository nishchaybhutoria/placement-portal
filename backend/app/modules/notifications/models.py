"""Notification, template, and reminder persistence models from LLD section 8."""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin
from app.domain.shared import NotificationStatus


class NotificationTemplate(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "notification_templates"
    __table_args__ = (
        sa.UniqueConstraint(
            "event_key",
            "cycle_id",
            name="uq_notification_templates_event_key_cycle_id",
            postgresql_nulls_not_distinct=True,
        ),
    )

    event_key: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    cycle_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("cycles.id", ondelete="RESTRICT")
    )
    subject: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    body: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, server_default=sa.true()
    )


class NotificationLog(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "notification_log"

    recipient: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    event_key: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    subject: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    status: Mapped[str] = mapped_column(
        sa.Enum(*(item.value for item in NotificationStatus), name="notif_status_t"),
        nullable=False,
    )
    attempts: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, server_default=sa.text("0")
    )
    last_error: Mapped[str | None] = mapped_column(sa.Text())
    sent_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    context: Mapped[dict[str, object]] = mapped_column(JSONB(), nullable=False)


class ReminderSend(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "reminder_sends"
    __table_args__ = (sa.UniqueConstraint("dedup_key", name="uq_reminder_sends_dedup_key"),)

    kind: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    dedup_key: Mapped[str] = mapped_column(sa.Text(), nullable=False)

