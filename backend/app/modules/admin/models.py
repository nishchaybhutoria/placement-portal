"""Audit, idempotency, and consistency models from LLD section 8."""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin
from app.domain.shared import FindingStatus


class AuditLog(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "audit_log"
    __table_args__ = (sa.UniqueConstraint("audit_seq", name="uq_audit_log_audit_seq"),)

    # Same rule as ApplicationEvent.event_seq (the design review 4.41, extended by
    # 4.48): identity is UUID, causality is append order. Two audit rows written
    # in one transaction share now(), and a UUID tie-break is a coin toss.
    audit_seq: Mapped[int] = mapped_column(
        sa.BigInteger(), sa.Identity(always=True, cache=1, cycle=False), nullable=False
    )

    actor_user_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT")
    )
    action: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    subject_type: Mapped[str | None] = mapped_column(sa.Text())
    subject_id: Mapped[UUID | None] = mapped_column(sa.Uuid())
    details: Mapped[dict[str, object]] = mapped_column(JSONB(), nullable=False)


class IdempotencyKey(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (sa.UniqueConstraint("key", name="uq_idempotency_keys_key"),)

    key: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    command: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    result: Mapped[dict[str, object]] = mapped_column(JSONB(), nullable=False)


class ConsistencyFinding(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "consistency_findings"

    invariant: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    subject: Mapped[dict[str, object]] = mapped_column(JSONB(), nullable=False)
    detail: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    status: Mapped[str] = mapped_column(
        sa.Enum(*(item.value for item in FindingStatus), name="finding_status_t"),
        nullable=False,
        server_default=sa.text("'open'::finding_status_t"),
    )
    suggested_fix: Mapped[str | None] = mapped_column(sa.Text())
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

