"""Shared world for the DIS suites: an enrollment, an admin, and a threshold."""

from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import UUID

import pytest_asyncio
import sqlalchemy as sa

from app.core.db import create_engine
from tests.cycles.conftest import (  # noqa: F401 - re-exported for the suites
    Person,
    build_test_executor,
    seed_admin,
    seed_person,
)


@pytest_asyncio.fixture(autouse=True)
async def clean_discipline() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "TRUNCATE audit_log, idempotency_keys, notification_log, settings, "
                    "strikes, penalties, "
                    "application_events, application_answers, "
                    "application_round_states, applications, offers, "
                    "job_question_options, job_questions, job_program_ctc, "
                    "job_rounds, jobs, cycle_memberships, cycle_coordinators, "
                    "cycle_policies, cycles, resumes, profiles, sessions, "
                    "enrollments, users, companies, programs, branches, minors, "
                    "sectors, round_types, procrastinate_jobs CASCADE"
                )
            )
    finally:
        await engine.dispose()


@dataclass(frozen=True, slots=True)
class DisciplineWorld:
    admin: Person
    student: Person


async def seed_discipline_world() -> DisciplineWorld:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(
                connection, email="asha@example.edu", full_name="Asha Rao"
            )
    finally:
        await engine.dispose()
    return DisciplineWorld(admin=admin, student=student)


async def set_threshold(value: int | None) -> None:
    """Set the global `strikes_per_penalty`, or clear it to disable conversion."""
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            if value is None:
                await connection.execute(
                    sa.text(
                        "INSERT INTO settings (key, value) "
                        "VALUES ('strikes_per_penalty', 'null'::jsonb) "
                        "ON CONFLICT (key) DO UPDATE SET value = 'null'::jsonb"
                    )
                )
            else:
                await connection.execute(
                    sa.text(
                        "INSERT INTO settings (key, value) "
                        "VALUES ('strikes_per_penalty', CAST(:value AS jsonb)) "
                        "ON CONFLICT (key) DO UPDATE SET value = CAST(:value AS jsonb)"
                    ),
                    {"value": str(value)},
                )
    finally:
        await engine.dispose()


async def rows(query: str, params: dict[str, object] | None = None) -> list[sa.RowMapping]:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            return list(
                (await connection.execute(sa.text(query), params or {})).mappings().all()
            )
    finally:
        await engine.dispose()


async def strike_ids(enrollment_id: UUID) -> list[UUID]:
    return [
        UUID(str(row["id"]))
        for row in await rows(
            "SELECT id FROM strikes WHERE enrollment_id = :id ORDER BY created_at, id",
            {"id": enrollment_id},
        )
    ]
