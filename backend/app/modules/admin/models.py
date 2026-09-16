"""Audit, idempotency, and consistency models from LLD section 8."""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin
from app.core.keys import MAX_STORED_KEY_LENGTH
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
    # The unique constraint is a btree, so an over-long key is not a slow write
    # but an impossible one (revision 0020). `app/core/keys.py` bounds every
    # caller-supplied key; this is the backstop that keeps the two in step.
    __table_args__ = (
        sa.UniqueConstraint("key", name="uq_idempotency_keys_key"),
        # NOT VALID, and it stays that way (revision 0020): keys written by
        # the old approvals screen are longer than this and were storable, so
        # validating them would fail every upgrade but the one on an empty
        # database. New rows are checked; the historical ones are evidence.
        sa.CheckConstraint(
            f"char_length(key) <= {MAX_STORED_KEY_LENGTH}",
            name="ck_idempotency_keys_key_length",
            postgresql_not_valid=True,
        ),
    )

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

