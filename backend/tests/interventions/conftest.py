"""A pipeline world for the M14 intervention suites."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.db import create_engine
from tests.cycles.conftest import (  # noqa: F401
    Person,
    build_test_executor,
    seed_admin,
    seed_complete_profile,
    seed_coordinator_link,
    seed_cycle,
    seed_job,
    seed_membership,
    seed_person,
    seed_round_type,
    seed_taxonomy,
)

DRIVE_URL = "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view"


@pytest_asyncio.fixture
async def clean_interventions() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "TRUNCATE overrides, consistency_findings, audit_log, "
                    "idempotency_keys, notification_log, reminder_sends, "
                    "application_events, application_answers, "
                    "application_round_states, applications, offers, external_offers, "
                    "export_presets, job_question_options, job_questions, "
                    "job_program_ctc, job_rounds, jobs, strikes, penalties, "
                    "cycle_memberships, cycle_coordinators, cycle_policies, cycles, "
                    "resumes, profiles, sessions, enrollments, users, companies, "
                    "programs, branches, minors, sectors, round_types, "
                    "procrastinate_jobs CASCADE"
                )
            )
    finally:
        await engine.dispose()


@dataclass(frozen=True, slots=True)
class PipelineWorld:
    """One student, one three-round job, and the ids the tests drive."""

    admin: Person
    coordinator: Person
    student: Person
    cycle_id: UUID
    job_id: UUID
    application_id: UUID
    rounds: tuple[UUID, ...]
    round_names: tuple[str, ...]
    membership_id: UUID


def write_engine():  # noqa: ANN201 - compact test helper
    return create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])


def read_engine():  # noqa: ANN201 - compact test helper
    return create_engine(os.environ["TEST_DATABASE_URL"])


async def seed_rounds(
    connection: AsyncConnection, job_id: UUID, names: tuple[str, ...]
) -> tuple[UUID, ...]:
    round_type_id = await seed_round_type(connection)
    ids: list[UUID] = []
    for ordinal, name in enumerate(names, start=1):
        round_id = uuid4()
        await connection.execute(
            sa.text(
                "INSERT INTO job_rounds (id, job_id, round_type_id, ord, name) "
                "VALUES (:id, :job_id, :round_type_id, :ord, :name)"
            ),
            {
                "id": round_id,
                "job_id": job_id,
                "round_type_id": round_type_id,
                "ord": ordinal,
                "name": name,
            },
        )
        ids.append(round_id)
    return tuple(ids)


async def seed_round_state(
    connection: AsyncConnection,
    *,
    application_id: UUID,
    round_id: UUID,
    result: str = "pending",
    attendance: str = "pending",
) -> UUID:
    state_id = uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO application_round_states (id, application_id, round_id, "
            "result, attendance) VALUES (:id, :application_id, :round_id, "
            "CAST(:result AS round_result_t), CAST(:attendance AS attendance_t))"
        ),
        {
            "id": state_id,
            "application_id": application_id,
            "round_id": round_id,
            "result": result,
            "attendance": attendance,
        },
    )
    return state_id


async def seed_application_row(
    connection: AsyncConnection,
    *,
    job_id: UUID,
    enrollment_id: UUID,
    status: str,
    current_round_id: UUID | None = None,
    applied_at: datetime | None = None,
) -> UUID:
    application_id = uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO applications (id, job_id, enrollment_id, status, "
            "current_round_id, resume_url, profile_snapshot, applied_at) VALUES "
            "(:id, :job_id, :enrollment_id, CAST(:status AS application_status_t), "
            ":round_id, :url, CAST(:snapshot AS jsonb), :applied_at)"
        ),
        {
            "id": application_id,
            "job_id": job_id,
            "enrollment_id": enrollment_id,
            "status": status,
            "round_id": current_round_id,
            "url": DRIVE_URL,
            "snapshot": '{"cpi": "8.40", "graduating_year": 2026}',
            "applied_at": applied_at or datetime.now(UTC) - timedelta(days=7),
        },
    )
    return application_id


async def _taxonomy(connection: AsyncConnection) -> tuple[UUID, UUID]:
    """One program and branch, reused when a test builds a second world."""
    existing = (
        await connection.execute(
            sa.text(
                "SELECT p.id AS program_id, b.id AS branch_id "
                "FROM programs p JOIN program_branches pb ON pb.program_id = p.id "
                "JOIN branches b ON b.id = pb.branch_id LIMIT 1"
            )
        )
    ).mappings().one_or_none()
    if existing is not None:
        return cast(UUID, existing["program_id"]), cast(UUID, existing["branch_id"])
    return await seed_taxonomy(connection)


async def build_pipeline_world(
    *,
    status: str = "rejected",
    membership_status: str = "active",
    round_names: tuple[str, ...] = ("Screening", "Technical", "HR"),
    at_round: int = 2,
    results: tuple[str, ...] = ("advanced", "eliminated"),
    attendance: tuple[str, ...] = ("present", "absent"),
) -> PipelineWorld:
    """A student who reached round ``at_round`` and was closed out there."""
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            program_id, branch_id = await _taxonomy(connection)
            suffix = uuid4().hex[:8]
            admin = await seed_admin(connection, email=f"admin-{suffix}@example.edu")
            coordinator = await seed_person(
                connection, email=f"coordinator-{suffix}@example.edu", role="student"
            )
            student = await seed_person(
                connection,
                email=f"student-{suffix}@example.edu",
                full_name="Asha Mehta",
            )
            resume_id = await seed_complete_profile(
                connection,
                student,
                program_id=program_id,
                branch_id=branch_id,
                roll_number=f"21{suffix}",
            )
            cycle_id = await seed_cycle(connection, name=f"Placement {suffix}")
            await seed_coordinator_link(connection, cycle_id, coordinator.user_id)
            membership_id = await seed_membership(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status=membership_status,
                resume_id=resume_id,
            )
            job_id = await seed_job(
                connection, cycle_id=cycle_id, is_published=True, title="Backend Engineer"
            )
            rounds = await seed_rounds(connection, job_id, round_names)
            application_id = await seed_application_row(
                connection,
                job_id=job_id,
                enrollment_id=student.enrollment_id,
                status=status,
                current_round_id=rounds[at_round - 1],
            )
            for index in range(at_round):
                await seed_round_state(
                    connection,
                    application_id=application_id,
                    round_id=rounds[index],
                    result=results[index] if index < len(results) else "pending",
                    attendance=(
                        attendance[index] if index < len(attendance) else "pending"
                    ),
                )
    finally:
        await engine.dispose()
    return PipelineWorld(
        admin=admin,
        coordinator=coordinator.coordinating(cycle_id),
        student=student,
        cycle_id=cycle_id,
        job_id=job_id,
        application_id=application_id,
        rounds=rounds,
        round_names=round_names,
        membership_id=membership_id,
    )


async def application_row(application_id: UUID) -> sa.RowMapping:
    engine = read_engine()
    try:
        async with engine.connect() as connection:
            return (
                await connection.execute(
                    sa.text(
                        "SELECT status, current_round_id FROM applications WHERE id = :id"
                    ),
                    {"id": application_id},
                )
            ).mappings().one()
    finally:
        await engine.dispose()


async def round_states(application_id: UUID) -> list[sa.RowMapping]:
    engine = read_engine()
    try:
        async with engine.connect() as connection:
            return list(
                (
                    await connection.execute(
                        sa.text(
                            "SELECT s.round_id, s.result, s.attendance, r.ord "
                            "FROM application_round_states s "
                            "JOIN job_rounds r ON r.id = s.round_id "
                            "WHERE s.application_id = :id ORDER BY r.ord"
                        ),
                        {"id": application_id},
                    )
                ).mappings().all()
            )
    finally:
        await engine.dispose()


async def latest_event(application_id: UUID) -> sa.RowMapping:
    engine = read_engine()
    try:
        async with engine.connect() as connection:
            return (
                await connection.execute(
                    sa.text(
                        "SELECT event_type, from_status, to_status, from_round_id, "
                        "to_round_id, reason, payload, actor_user_id "
                        "FROM application_events WHERE application_id = :id "
                        "ORDER BY created_at DESC, id DESC LIMIT 1"
                    ),
                    {"id": application_id},
                )
            ).mappings().one()
    finally:
        await engine.dispose()


async def queued_notifications() -> list[dict[str, object]]:
    engine = read_engine()
    try:
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    sa.text(
                        "SELECT args FROM procrastinate_jobs "
                        "WHERE task_name = 'deliver_notification' ORDER BY id"
                    )
                )
            ).scalars().all()
    finally:
        await engine.dispose()
    return [cast("dict[str, object]", row) for row in rows]
