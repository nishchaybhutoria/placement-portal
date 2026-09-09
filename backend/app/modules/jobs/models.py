"""Job builder persistence models from LLD section 8."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UpdatedAtMixin, UUIDPrimaryKeyMixin
from app.domain.shared import Outcome, QuestionType


class Job(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        sa.CheckConstraint(
            "offer_acceptance_deadline IS NULL OR application_deadline IS NULL "
            "OR offer_acceptance_deadline > application_deadline",
            name="ck_jobs_offer_deadline_after_application_deadline",
        ),
    )

    cycle_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("cycles.id", ondelete="RESTRICT"), nullable=False
    )
    company_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    outcome: Mapped[str] = mapped_column(
        sa.Enum(*(item.value for item in Outcome), name="outcome_t"), nullable=False
    )
    title: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    description: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    location: Mapped[str | None] = mapped_column(sa.Text())
    sector_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("sectors.id", ondelete="RESTRICT")
    )
    ctc_lpa: Mapped[Decimal | None] = mapped_column(sa.Numeric(10, 2))
    ctc_breakdown: Mapped[str | None] = mapped_column(sa.Text())
    stipend_month: Mapped[Decimal | None] = mapped_column(sa.Numeric(10, 2))
    application_deadline: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    offer_acceptance_deadline: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True)
    )
    is_published: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, server_default=sa.false()
    )
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    eligibility_rule: Mapped[dict[str, object] | None] = mapped_column(JSONB())
    eligibility_summary: Mapped[str | None] = mapped_column(sa.Text())


class JobProgramCtc(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "job_program_ctc"
    __table_args__ = (
        sa.UniqueConstraint(
            "job_id", "program_id", name="uq_job_program_ctc_job_id_program_id"
        ),
    )

    job_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False
    )
    program_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("programs.id", ondelete="RESTRICT"), nullable=False
    )
    ctc_lpa: Mapped[Decimal] = mapped_column(sa.Numeric(10, 2), nullable=False)


class JobRound(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "job_rounds"
    __table_args__ = (
        sa.UniqueConstraint(
            "job_id",
            "ord",
            name="uq_job_rounds_job_id_ord",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    job_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False
    )
    round_type_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("round_types.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    ord: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    venue: Mapped[str | None] = mapped_column(sa.Text())
    scheduled_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    duration_min: Mapped[int | None] = mapped_column(sa.Integer())
    instructions: Mapped[str | None] = mapped_column(sa.Text())
    # RND-3 finalization, recorded rather than derived (the design review section 4.25).
    finalized_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    finalized_by: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT")
    )


class JobQuestion(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "job_questions"

    job_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False
    )
    ord: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    text: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    qtype: Mapped[str] = mapped_column(
        sa.Enum(*(item.value for item in QuestionType), name="question_type_t"),
        nullable=False,
    )
    required: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False)


class JobQuestionOption(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "job_question_options"

    question_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("job_questions.id", ondelete="RESTRICT"), nullable=False
    )
    ord: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    text: Mapped[str] = mapped_column(sa.Text(), nullable=False)

