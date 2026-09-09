"""Database engine, declarative base, and session factory for LLD sections 3 and 8."""

from __future__ import annotations

import os
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DEFAULT_DATABASE_URL = "postgresql+asyncpg://cds_app:cds_app@127.0.0.1:5432/cds"


class Base(DeclarativeBase):
    """Declarative base shared by every vertical-slice model."""


class UUIDPrimaryKeyMixin:
    """LLD-standard UUIDv4-compatible database primary key."""

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class CreatedAtMixin:
    """LLD-standard UTC creation timestamp."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class UpdatedAtMixin(CreatedAtMixin):
    """Creation and mutation timestamps for mutable rows."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


def database_url() -> str:
    """Return the application-role database URL."""
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def create_engine(url: str | None = None) -> AsyncEngine:
    """Create an async engine without opening a connection."""
    return create_async_engine(url or database_url(), pool_pre_ping=True)


engine = create_engine()
sessionmaker = async_sessionmaker[AsyncSession](
    engine,
    expire_on_commit=False,
    autobegin=False,
)

