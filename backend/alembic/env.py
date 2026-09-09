"""Async Alembic environment for the CDS Portal database."""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.models  # noqa: F401 - registers every model with Base.metadata
from alembic import context
from app.core.db import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

migration_url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL")
if migration_url:
    config.set_main_option("sqlalchemy.url", migration_url.replace("%", "%%"))

target_metadata = Base.metadata


def include_object(
    _object: object,
    name: str | None,
    type_: str,
    reflected: bool,
    _compare_to: object | None,
) -> bool:
    """Leave Procrastinate-owned tables to Procrastinate's schema manager."""
    return not (
        reflected
        and type_ == "table"
        and name is not None
        and name.startswith("procrastinate_")
    )


def run_migrations_offline() -> None:
    """Run migrations without creating an Engine."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: object) -> None:
    """Configure and run migrations on Alembic's synchronous adapter."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create the async engine and bridge Alembic's migration callable."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations through the async SQLAlchemy driver."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
