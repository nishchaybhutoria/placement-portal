"""Profile and resume persistence models from LLD section 8."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UpdatedAtMixin, UUIDPrimaryKeyMixin
from app.domain.shared import Gender


class Profile(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "profiles"
    __table_args__ = (
        sa.UniqueConstraint("enrollment_id", name="uq_profiles_enrollment_id"),
        sa.CheckConstraint(
            "NOT (is_dual_major AND is_dual_degree)", name="ck_profiles_one_dual_kind"
        ),
        sa.CheckConstraint(
            "is_dual_degree = (secondary_program_id IS NOT NULL)",
            name="ck_profiles_dual_degree_program",
        ),
        sa.CheckConstraint(
            "secondary_branch_id IS NULL OR is_dual_major OR is_dual_degree",
            name="ck_profiles_secondary_branch_kind",
        ),
    )

    enrollment_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("enrollments.id", ondelete="RESTRICT"), nullable=False
    )
    program_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("programs.id", ondelete="RESTRICT")
    )
    primary_branch_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("branches.id", ondelete="RESTRICT")
    )
    # A student completing two majors at once, one primary and one secondary
    # (the design review section 4.32).  NOT NULL because "unknown" is not one of the
    # answers: every student either is or is not, and PRO-1 asks the secondary
    # branch of exactly the ones who are.
    is_dual_major: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, server_default=sa.false()
    )
    # Dual degrees keep BTech as program_id and name the postgraduate degree.
    is_dual_degree: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, server_default=sa.false()
    )
    secondary_program_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("programs.id", ondelete="RESTRICT")
    )
    secondary_branch_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("branches.id", ondelete="RESTRICT")
    )
    graduating_year: Mapped[int | None] = mapped_column(sa.Integer())
    cpi: Mapped[Decimal | None] = mapped_column(sa.Numeric(4, 2))
    active_backlogs: Mapped[int | None] = mapped_column(sa.Integer())
    total_backlogs: Mapped[int | None] = mapped_column(sa.Integer())
    gender: Mapped[str | None] = mapped_column(
        sa.Enum(*(item.value for item in Gender), name="gender_t", create_constraint=False)
    )
    personal_email: Mapped[str | None] = mapped_column(CITEXT())
    contact_number: Mapped[str | None] = mapped_column(sa.Text())
    nationality: Mapped[str | None] = mapped_column(
        sa.Text(), server_default=sa.text("'IN'")
    )
    tenth_percent: Mapped[Decimal | None] = mapped_column(sa.Numeric(5, 2))
    tenth_year: Mapped[int | None] = mapped_column(sa.Integer())
    twelfth_percent: Mapped[Decimal | None] = mapped_column(sa.Numeric(5, 2))
    twelfth_year: Mapped[int | None] = mapped_column(sa.Integer())
    minor1_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("minors.id", ondelete="RESTRICT")
    )
    minor2_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("minors.id", ondelete="RESTRICT")
    )
    github_url: Mapped[str | None] = mapped_column(sa.Text())
    linkedin_url: Mapped[str | None] = mapped_column(sa.Text())
    portfolio_url: Mapped[str | None] = mapped_column(sa.Text())
    declared_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class Resume(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "resumes"
    __table_args__ = (
        sa.Index(
            "uq_resumes_default_enrollment_id",
            "enrollment_id",
            unique=True,
            postgresql_where=sa.text("is_default"),
        ),
    )

    enrollment_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("enrollments.id", ondelete="RESTRICT"), nullable=False
    )
    label: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    drive_url: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    is_default: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False)


class StagedProfileRow(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "staged_profile_rows"

    institute_email: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB(), nullable=False)
    uploaded_by: Mapped[UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    applied_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(sa.Text())

