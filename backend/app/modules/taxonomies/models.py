"""Taxonomy and settings persistence models from LLD section 8."""

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin


class Program(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "programs"
    __table_args__ = (sa.UniqueConstraint("name", name="uq_programs_name"),)

    name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False)


class Branch(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "branches"
    __table_args__ = (sa.UniqueConstraint("name", name="uq_branches_name"),)

    name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False)


class ProgramBranch(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "program_branches"
    __table_args__ = (
        sa.UniqueConstraint(
            "program_id", "branch_id", name="uq_program_branches_program_id_branch_id"
        ),
    )

    program_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("programs.id", ondelete="RESTRICT"), nullable=False
    )
    branch_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )


class Minor(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "minors"
    __table_args__ = (sa.UniqueConstraint("name", name="uq_minors_name"),)

    name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False)


class Sector(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "sectors"
    __table_args__ = (sa.UniqueConstraint("name", name="uq_sectors_name"),)

    name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False)


class RoundType(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "round_types"
    __table_args__ = (sa.UniqueConstraint("name", name="uq_round_types_name"),)

    name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False)


class Setting(UpdatedAtMixin, Base):
    __tablename__ = "settings"

    # SPEC-GAP: LLD section 8 says every table has a UUID primary key but explicitly
    # declares settings.key as the primary key. The explicit table declaration wins.
    key: Mapped[str] = mapped_column(sa.Text(), primary_key=True)
    value: Mapped[object] = mapped_column(JSONB(), nullable=False)
    updated_by: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT")
    )

