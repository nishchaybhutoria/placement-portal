"""Portal and external offer persistence models from LLD section 8."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UpdatedAtMixin, UUIDPrimaryKeyMixin
from app.domain.shared import (
    ExternalSource,
    ExternalStatus,
    OfferResponse,
    Outcome,
    TerminationKind,
)


class Offer(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "offers"
    __table_args__ = (
        sa.Index(
            "ix_offers_application_id_extended_at_desc",
            "application_id",
            sa.desc("extended_at"),
        ),
    )

    application_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("applications.id", ondelete="RESTRICT"), nullable=False
    )
    extended_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    deadline_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    response: Mapped[str | None] = mapped_column(
        sa.Enum(*(item.value for item in OfferResponse), name="offer_response_t")
    )
    responded_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    terminated_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    terminated_by: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT")
    )
    termination_kind: Mapped[str | None] = mapped_column(
        sa.Enum(*(item.value for item in TerminationKind), name="termination_kind_t")
    )
    termination_reason: Mapped[str | None] = mapped_column(sa.Text())


class ExternalOffer(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "external_offers"

    enrollment_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("enrollments.id", ondelete="RESTRICT"), nullable=False
    )
    company_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    outcome: Mapped[str] = mapped_column(
        sa.Enum(*(item.value for item in Outcome), name="outcome_t"), nullable=False
    )
    source: Mapped[str] = mapped_column(
        sa.Enum(*(item.value for item in ExternalSource), name="external_source_t"),
        nullable=False,
    )
    ctc_lpa: Mapped[Decimal | None] = mapped_column(sa.Numeric(10, 2))
    stipend_month: Mapped[Decimal | None] = mapped_column(sa.Numeric(10, 2))
    status: Mapped[str] = mapped_column(
        sa.Enum(*(item.value for item in ExternalStatus), name="external_status_t"),
        nullable=False,
    )
    offered_on: Mapped[date | None] = mapped_column(sa.Date())
    responded_on: Mapped[date | None] = mapped_column(sa.Date())
    source_application_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("applications.id", ondelete="RESTRICT")
    )
    attached_cycle_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("cycles.id", ondelete="RESTRICT")
    )
    notes: Mapped[str | None] = mapped_column(sa.Text())
    created_by: Mapped[UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

