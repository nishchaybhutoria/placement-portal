"""Company directory persistence models from LLD section 8."""

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UpdatedAtMixin, UUIDPrimaryKeyMixin


class Company(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "companies"
    __table_args__ = (sa.UniqueConstraint("name", name="uq_companies_name"),)

    name: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text())
    website_url: Mapped[str | None] = mapped_column(sa.Text())
    sector_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("sectors.id", ondelete="RESTRICT")
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, server_default=sa.true()
    )


class CompanyContact(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "company_contacts"
    __table_args__ = (
        sa.UniqueConstraint(
            "company_id", "email", name="uq_company_contacts_company_id_email"
        ),
        sa.Index(
            "uq_company_contacts_primary_company_id",
            "company_id",
            unique=True,
            postgresql_where=sa.text("is_primary"),
        ),
    )

    company_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    email: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    phone: Mapped[str | None] = mapped_column(sa.Text())
    designation: Mapped[str | None] = mapped_column(sa.Text())
    is_primary: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False)

