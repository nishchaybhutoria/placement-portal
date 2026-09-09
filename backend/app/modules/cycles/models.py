"""Cycle, policy, coordinator, and membership models from LLD section 8."""

from datetime import date, datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin
from app.domain.shared import CycleKind, MembershipStatus, OfferExpiry, OutcomeTag


class Cycle(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "cycles"
    __table_args__ = (
        sa.UniqueConstraint("name", name="uq_cycles_name"),
        sa.CheckConstraint(
            "starts_on IS NULL OR ends_on IS NULL OR starts_on <= ends_on",
            name="ck_cycles_start_before_end",
        ),
    )

    name: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    kind: Mapped[str] = mapped_column(
        sa.Enum(*(item.value for item in CycleKind), name="cycle_kind_t"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(sa.Text())
    starts_on: Mapped[date | None] = mapped_column(sa.Date())
    ends_on: Mapped[date | None] = mapped_column(sa.Date())
    registration_opens_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    registration_closes_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, server_default=sa.false()
    )
    archived_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class CyclePolicy(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "cycle_policies"
    __table_args__ = (sa.UniqueConstraint("cycle_id", name="uq_cycle_policies_cycle_id"),)

    cycle_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("cycles.id", ondelete="RESTRICT"), nullable=False
    )
    membership_requires_approval: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False)
    join_rule: Mapped[dict[str, object] | None] = mapped_column(JSONB())
    max_accepted_offers: Mapped[int | None] = mapped_column(sa.Integer())
    penalty_blocks_applications: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False)
    allow_withdrawal_after_deadline: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False
    )
    allow_edit_after_deadline: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False)
    strike_on_absence: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False)
    offer_expiry_behavior: Mapped[str] = mapped_column(
        sa.Enum(*(item.value for item in OfferExpiry), name="offer_expiry_t"),
        nullable=False,
        server_default=sa.text("'auto_decline'::offer_expiry_t"),
    )
    deadline_reminder_hours: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, server_default=sa.text("6")
    )
    round_reminder_hours: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, server_default=sa.text("24")
    )


class CycleCoordinator(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "cycle_coordinators"
    __table_args__ = (
        sa.UniqueConstraint(
            "cycle_id", "user_id", name="uq_cycle_coordinators_cycle_id_user_id"
        ),
    )

    cycle_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("cycles.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class CycleMembership(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "cycle_memberships"
    __table_args__ = (
        sa.UniqueConstraint(
            "cycle_id", "enrollment_id", name="uq_cycle_memberships_cycle_id_enrollment_id"
        ),
    )

    cycle_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("cycles.id", ondelete="RESTRICT"), nullable=False
    )
    enrollment_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("enrollments.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        sa.Enum(*(item.value for item in MembershipStatus), name="membership_status_t"),
        nullable=False,
    )
    default_resume_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("resumes.id", ondelete="SET NULL")
    )
    consented_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    decided_by: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT")
    )
    decided_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(sa.Text())
    outcome_tag: Mapped[str | None] = mapped_column(
        sa.Enum(*(item.value for item in OutcomeTag), name="outcome_tag_t")
    )
    auto_created: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, server_default=sa.false()
    )

