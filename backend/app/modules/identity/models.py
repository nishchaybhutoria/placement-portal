"""Identity persistence models from LLD section 8."""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UpdatedAtMixin, UUIDPrimaryKeyMixin
from app.domain.shared import Role


class User(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "users"
    __table_args__ = (sa.UniqueConstraint("email", name="uq_users_email"),)

    email: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    full_name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    role: Mapped[str] = mapped_column(
        sa.Enum(*(item.value for item in Role), name="role_t", create_constraint=False),
        nullable=False,
        server_default=sa.text("'student'::role_t"),
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, server_default=sa.true()
    )


class Session(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "sessions"
    __table_args__ = (sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),)

    token_hash: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class Enrollment(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "enrollments"
    __table_args__ = (
        sa.Index(
            "uq_enrollments_current_roll_number",
            "roll_number",
            unique=True,
            postgresql_where=sa.text("is_current AND roll_number IS NOT NULL"),
        ),
        sa.Index(
            "uq_enrollments_current_user_id",
            "user_id",
            unique=True,
            postgresql_where=sa.text("is_current"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    is_current: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False)
    roll_number: Mapped[str | None] = mapped_column(CITEXT())

