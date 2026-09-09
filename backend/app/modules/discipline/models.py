"""Enrollment-scoped discipline persistence models from LLD section 8."""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UpdatedAtMixin, UUIDPrimaryKeyMixin
from app.domain.shared import StrikeSource


class Strike(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "strikes"

    enrollment_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("enrollments.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    source: Mapped[str] = mapped_column(
        sa.Enum(*(item.value for item in StrikeSource), name="strike_source_t"),
        nullable=False,
    )
    awarded_by: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT")
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, server_default=sa.true()
    )
    consumed_by_penalty_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("penalties.id", ondelete="RESTRICT")
    )


class Penalty(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "penalties"

    enrollment_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("enrollments.id", ondelete="RESTRICT"), nullable=False
    )
    reasons: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    from_strikes: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, server_default=sa.true()
    )
    created_by: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    revoked_by: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT")
    )

