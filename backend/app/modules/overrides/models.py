"""Scoped override persistence model from LLD section 8."""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UpdatedAtMixin, UUIDPrimaryKeyMixin
from app.domain.shared import RuleDomain


class Override(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "overrides"
    __table_args__ = (
        sa.CheckConstraint(
            """
            (cycle_id IS NOT NULL AND job_id IS NULL
                AND enrollment_id IS NULL AND application_id IS NULL)
            OR (cycle_id IS NULL AND job_id IS NOT NULL
                AND enrollment_id IS NULL AND application_id IS NULL)
            OR (cycle_id IS NULL AND job_id IS NULL
                AND enrollment_id IS NOT NULL AND application_id IS NULL)
            OR (cycle_id IS NOT NULL AND job_id IS NULL
                AND enrollment_id IS NOT NULL AND application_id IS NULL)
            OR (cycle_id IS NULL AND job_id IS NOT NULL
                AND enrollment_id IS NOT NULL AND application_id IS NULL)
            OR (cycle_id IS NULL AND job_id IS NULL
                AND enrollment_id IS NULL AND application_id IS NOT NULL)
            """,
            name="ck_overrides_scope_combination",
        ),
    )

    rule_domain: Mapped[str] = mapped_column(
        sa.Enum(*(item.value for item in RuleDomain), name="rule_domain_t"), nullable=False
    )
    allow: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, server_default=sa.true()
    )
    cycle_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("cycles.id", ondelete="RESTRICT")
    )
    job_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("jobs.id", ondelete="RESTRICT")
    )
    enrollment_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("enrollments.id", ondelete="RESTRICT")
    )
    application_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("applications.id", ondelete="RESTRICT")
    )
    reason: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    granted_by: Mapped[UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, server_default=sa.true()
    )

