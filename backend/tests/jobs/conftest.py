"""Shared fixtures for the M9 job and builder suites.

Builds on the M8 cycle fixtures rather than restating them: a job only exists
inside a cycle, and every authorization case here is the cycle's.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.db import create_engine
from tests.cycles.conftest import (  # noqa: F401 - re-exported for the job suites
    DRIVE_URL,
    Person,
    build_test_executor,
    seed_admin,
    seed_application,
    seed_complete_profile,
    seed_coordinator_link,
    seed_cycle,
    seed_job,
    seed_membership,
    seed_person,
    seed_round_type,
    seed_taxonomy,
)


@pytest_asyncio.fixture(autouse=True)
async def clean_jobs() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "TRUNCATE audit_log, idempotency_keys, notification_log, "
                    "application_events, application_answers, "
                    "application_round_states, applications, offers, "
                    "export_presets, job_question_options, job_questions, "
                    "job_program_ctc, job_rounds, jobs, "
                    "cycle_memberships, cycle_coordinators, cycle_policies, cycles, "
                    "resumes, profiles, sessions, enrollments, users, companies, "
                    "programs, branches, minors, sectors, round_types, "
                    "procrastinate_jobs CASCADE"
                )
            )
    finally:
        await engine.dispose()


async def seed_company(
    connection: AsyncConnection, name: str = "Acme Corp"
) -> UUID:
    company_id = uuid4()
    await connection.execute(
        sa.text("INSERT INTO companies (id, name, is_active) VALUES (:id, :name, true)"),
        {"id": company_id, "name": name},
    )
    return company_id


async def seed_sector(connection: AsyncConnection, name: str = "Technology") -> UUID:
    sector_id = uuid4()
    await connection.execute(
        sa.text("INSERT INTO sectors (id, name, is_active) VALUES (:id, :name, true)"),
        {"id": sector_id, "name": name},
    )
    return sector_id


async def job_row(connection: AsyncConnection, job_id: UUID) -> sa.RowMapping:
    return (
        await connection.execute(
            sa.text("SELECT * FROM jobs WHERE id = :id"), {"id": job_id}
        )
    ).mappings().one()


async def seed_answer(
    connection: AsyncConnection, *, application_id: UUID, question_id: UUID, value: str
) -> None:
    await connection.execute(
        sa.text(
            "INSERT INTO application_answers (id, application_id, question_id, value) "
            "VALUES (:id, :application_id, :question_id, CAST(:value AS jsonb))"
        ),
        {
            "id": uuid4(),
            "application_id": application_id,
            "question_id": question_id,
            "value": f'"{value}"',
        },
    )


async def seed_round_state(
    connection: AsyncConnection, *, application_id: UUID, round_id: UUID
) -> None:
    await connection.execute(
        sa.text(
            "INSERT INTO application_round_states (id, application_id, round_id, "
            "result, attendance) VALUES (:id, :application_id, :round_id, "
            "'pending', 'pending')"
        ),
        {"id": uuid4(), "application_id": application_id, "round_id": round_id},
    )


async def seed_offer(
    connection: AsyncConnection,
    *,
    application_id: UUID,
    responded: bool = False,
    terminated: bool = False,
) -> UUID:
    """An offer against an application; open unless answered or already pulled."""
    offer_id = uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO offers (id, application_id, extended_at, response, "
            "responded_at, terminated_at, termination_kind) VALUES "
            "(:id, :application_id, now(), "
            "CAST(:response AS offer_response_t), :responded_at, :terminated_at, "
            "CAST(:kind AS termination_kind_t))"
        ),
        {
            "id": offer_id,
            "application_id": application_id,
            "response": "accepted" if responded else None,
            "responded_at": datetime.now(UTC) if responded else None,
            "terminated_at": datetime.now(UTC) if terminated else None,
            "kind": "company_revoked" if terminated else None,
        },
    )
    return offer_id


async def offer_row(connection: AsyncConnection, offer_id: UUID) -> sa.RowMapping:
    return (
        await connection.execute(
            sa.text("SELECT * FROM offers WHERE id = :id"), {"id": offer_id}
        )
    ).mappings().one()
