"""Application, round-state, and event models from LLD section 8."""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin
from app.domain.shared import ApplicationStatus, Attendance, EventType, RoundResult


class Application(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "applications"
    __table_args__ = (
        sa.Index(
            "uq_applications_active_job_enrollment",
            "job_id",
            "enrollment_id",
            unique=True,
            postgresql_where=sa.text(
                "status NOT IN ('withdrawn'::application_status_t, "
                "'auto_withdrawn'::application_status_t)"
            ),
        ),
        sa.Index("ix_applications_enrollment_id_status", "enrollment_id", "status"),
        sa.Index("ix_applications_job_id_status", "job_id", "status"),
    )

    job_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False
    )
    enrollment_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("enrollments.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        sa.Enum(*(item.value for item in ApplicationStatus), name="application_status_t"),
        nullable=False,
    )
    current_round_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("job_rounds.id", ondelete="RESTRICT")
    )
    resume_url: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    profile_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB(), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class ApplicationAnswer(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "application_answers"
    __table_args__ = (
        sa.UniqueConstraint(
            "application_id",
            "question_id",
            name="uq_application_answers_application_id_question_id",
        ),
    )

    application_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("applications.id", ondelete="RESTRICT"), nullable=False
    )
    question_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("job_questions.id", ondelete="RESTRICT"), nullable=False
    )
    value: Mapped[object] = mapped_column(JSONB(), nullable=False)


class ApplicationRoundState(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "application_round_states"
    __table_args__ = (
        sa.UniqueConstraint(
            "application_id",
            "round_id",
            name="uq_application_round_states_application_id_round_id",
        ),
    )

    application_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("applications.id", ondelete="RESTRICT"), nullable=False
    )
    round_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("job_rounds.id", ondelete="RESTRICT"), nullable=False
    )
    result: Mapped[str] = mapped_column(
        sa.Enum(*(item.value for item in RoundResult), name="round_result_t"),
        nullable=False,
        server_default=sa.text("'pending'::round_result_t"),
    )
    attendance: Mapped[str] = mapped_column(
        sa.Enum(*(item.value for item in Attendance), name="attendance_t"),
        nullable=False,
        server_default=sa.text("'pending'::attendance_t"),
    )
    venue_override: Mapped[str | None] = mapped_column(sa.Text())
    scheduled_at_override: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True)
    )
    notified_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class ApplicationEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "application_events"
    __table_args__ = (
        sa.UniqueConstraint("event_seq", name="uq_application_events_event_seq"),
    )

    # the design review 4.41: identity is UUID; causality is append order, never now()/UUID.
    event_seq: Mapped[int] = mapped_column(
        sa.BigInteger(), sa.Identity(always=True, cache=1, cycle=False), nullable=False
    )

    application_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("applications.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(
        sa.Enum(*(item.value for item in EventType), name="event_type_t"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(
        sa.Enum(*(item.value for item in ApplicationStatus), name="application_status_t")
    )
    to_status: Mapped[str | None] = mapped_column(
        sa.Enum(*(item.value for item in ApplicationStatus), name="application_status_t")
    )
    from_round_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("job_rounds.id", ondelete="RESTRICT")
    )
    to_round_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("job_rounds.id", ondelete="RESTRICT")
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT")
    )
    reason: Mapped[str | None] = mapped_column(sa.Text())
    payload: Mapped[dict[str, object]] = mapped_column(
        JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    batch_id: Mapped[UUID | None] = mapped_column(sa.Uuid())

