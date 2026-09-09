"""Export persistence models from LLD section 8."""

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UpdatedAtMixin, UUIDPrimaryKeyMixin


class ExportPreset(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "export_presets"
    __table_args__ = (sa.UniqueConstraint("job_id", name="uq_export_presets_job_id"),)

    job_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False
    )
    columns: Mapped[list[object]] = mapped_column(JSONB(), nullable=False)


class ExportJob(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "export_jobs"

    kind: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    params: Mapped[dict[str, object]] = mapped_column(JSONB(), nullable=False)
    status: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    requested_by: Mapped[UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    result_meta: Mapped[dict[str, object] | None] = mapped_column(JSONB())
    error: Mapped[str | None] = mapped_column(sa.Text())

