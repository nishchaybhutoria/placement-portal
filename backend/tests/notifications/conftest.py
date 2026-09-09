"""Isolated PostgreSQL fixtures for Behavior NTF."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest_asyncio
import sqlalchemy as sa

from app.bootstrap import build_executor, build_registry
from app.core.db import create_engine
from tests.notifications.seed_defaults import restore_migration_defaults


async def _clean() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            # Global rows belong to migration 0007 and are the subject of the
            # set-equality gate. Only mutable cycle overrides are test data.
            await connection.execute(
                sa.text("DELETE FROM notification_templates WHERE cycle_id IS NOT NULL")
            )
            await connection.execute(
                sa.text(
                    "TRUNCATE audit_log, idempotency_keys, notification_log, "
                    "reminder_sends, application_events, application_answers, "
                    "application_round_states, applications, offers, external_offers, "
                    "strikes, penalties, overrides, export_presets, "
                    "job_question_options, job_questions, job_program_ctc, "
                    "job_rounds, jobs, cycle_memberships, cycle_coordinators, "
                    "cycle_policies, resumes, profiles, sessions, "
                    "enrollments, users, company_contacts, companies, "
                    "program_branches, programs, branches, minors, sectors, "
                    "round_types, settings, procrastinate_events, "
                    "procrastinate_periodic_defers, procrastinate_jobs, "
                    "procrastinate_workers RESTART IDENTITY CASCADE"
                )
            )
            await connection.execute(sa.text("DELETE FROM cycles"))
            await restore_migration_defaults(connection)
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def clean_notification_world() -> AsyncIterator[None]:
    await _clean()
    yield
    await _clean()


@pytest_asyncio.fixture
async def notification_executor():
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    executor = build_executor(build_registry(), engine)
    try:
        yield executor
    finally:
        await engine.dispose()
