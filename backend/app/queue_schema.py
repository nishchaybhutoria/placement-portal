"""Idempotently apply Procrastinate's own schema during database bootstrap."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys

from sqlalchemy import text

from app.core.db import create_engine

#: Mirrors Settings.session_secret's own min_length; see main().
_MINIMUM_SESSION_SECRET_LENGTH = 32


async def _schema_exists(migration_url: str) -> bool:
    engine = create_engine(migration_url)
    try:
        async with engine.connect() as connection:
            marker = await connection.scalar(
                text("SELECT to_regclass('public.procrastinate_jobs')")
            )
            return marker is not None
    finally:
        await engine.dispose()


def main() -> None:
    migration_url = os.environ.get("MIGRATION_DATABASE_URL")
    if not migration_url:
        raise RuntimeError("MIGRATION_DATABASE_URL is required for queue schema bootstrap")
    if asyncio.run(_schema_exists(migration_url)):
        return

    queue_schema_url = os.environ.get("QUEUE_SCHEMA_DATABASE_URL")
    if not queue_schema_url:
        raise RuntimeError("QUEUE_SCHEMA_DATABASE_URL is required for queue schema bootstrap")

    # `procrastinate --app app.worker.procrastinate_app` imports the worker,
    # which builds Settings, which requires SESSION_SECRET. Without it
    # procrastinate reports only "error: invalid load_app value", which names
    # neither the variable nor the reason -- twenty minutes lost on the morning
    # of a run, to a message that says nothing. Check it here, where the
    # requirement is legible, rather than letting the import fail opaquely.
    session_secret = os.environ.get("SESSION_SECRET", "")
    if len(session_secret) < _MINIMUM_SESSION_SECRET_LENGTH:
        raise RuntimeError(
            "SESSION_SECRET of at least "
            f"{_MINIMUM_SESSION_SECRET_LENGTH} characters is required for queue schema "
            "bootstrap: procrastinate loads app.worker.procrastinate_app, which "
            "constructs the application settings. Any value satisfies the schema "
            "step; it is not the deployment's secret unless you are deploying."
        )

    subprocess.run(
        [
            sys.executable,
            "-m",
            "procrastinate",
            "--app",
            "app.worker.procrastinate_app",
            "schema",
            "--apply",
        ],
        check=True,
        env={**os.environ, "PROCRASTINATE_DATABASE_URL": queue_schema_url},
    )


if __name__ == "__main__":
    main()
