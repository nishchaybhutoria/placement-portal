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
        sa.CheckConstraint("study_year BETWEEN 1 AND 8", name="ck_profiles_study_year_range"),
        sa.CheckConstraint(
            "study_year_session BETWEEN 1900 AND 2100", name="ck_profiles_study_year_session_range"
        ),
        sa.CheckConstraint(
            "(study_year IS NULL) = (study_year_session IS NULL)",
            name="ck_profiles_study_year_pair",
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
    # Whether a second discipline applies, and which degree it belongs to, is
    # the programme's to say (app.domain.pathways) -- the profile names the
    # programme and the two disciplines, and nothing that can contradict them.
    secondary_branch_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("branches.id", ondelete="RESTRICT")
    )
    # Nullable for the additive collection release: never guess existing students' standing.
    study_year: Mapped[int | None] = mapped_column(sa.Integer())
    study_year_session: Mapped[int | None] = mapped_column(sa.Integer())
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

