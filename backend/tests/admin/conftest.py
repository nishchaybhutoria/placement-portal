"""A consistent world, and the corruptions the checker must find in it.

Every corruption is injected over the **superuser** connection, because most of
them are states the application role and the schema between them make
unreachable -- which is exactly why the checker exists: the drift it looks for
comes from a bug, a migration, or a hand-run statement, never from a command.
Four of them are refused by a unique index, so those fixtures drop it, plant the
row, and put it back afterwards.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.db import create_engine
from app.core.plan import ActorContext
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


def write_engine():  # noqa: ANN201 - compact test helper
    """The superuser connection every corruption is planted through."""
    return create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])


def read_engine():  # noqa: ANN201 - compact test helper
    return create_engine(os.environ["TEST_DATABASE_URL"])


@pytest_asyncio.fixture
async def clean_findings() -> None:
    engine = write_engine()
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
                    "resumes, profiles, company_contacts, sessions, enrollments, "
                    "users, companies, settings, programs, branches, minors, sectors, "
                    "round_types, procrastinate_jobs CASCADE"
                )
            )
    finally:
        await engine.dispose()


@dataclass(frozen=True, slots=True)
class CheckerWorld:
    """A world in which every LLD section 12 invariant currently holds."""

    admin: Person
    student: Person
    placement_cycle: UUID
    internship_cycle: UUID
    open_cycle: UUID
    company_id: UUID
    contact_id: UUID
    job_id: UUID
    open_job_id: UUID
    internship_job_id: UUID
    rounds: tuple[UUID, ...]
    application_id: UUID
    membership_id: UUID
    resume_id: UUID

    @property
    def admin_actor(self) -> ActorContext:
        return self.admin.actor


async def _company(connection: AsyncConnection, name: str) -> tuple[UUID, UUID]:
    company_id, contact_id = uuid4(), uuid4()
    await connection.execute(
        sa.text("INSERT INTO companies (id, name, is_active) VALUES (:id, :name, true)"),
        {"id": company_id, "name": name},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO company_contacts (id, company_id, name, email, is_primary) "
            "VALUES (:id, :company_id, 'Priya Nair', :email, true)"
        ),
        {
            "id": contact_id,
            "company_id": company_id,
            "email": f"priya.{uuid4().hex[:6]}@example.com",
        },
    )
    return company_id, contact_id


async def build_checker_world() -> CheckerWorld:
    """One clean world: the checker must find nothing in it."""
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            program_id, branch_id = await seed_taxonomy(connection)
            suffix = uuid4().hex[:8]
            admin = await seed_admin(connection, email=f"admin-{suffix}@example.edu")
            student = await seed_person(
                connection, email=f"student-{suffix}@example.edu", full_name="Asha Mehta"
            )
            resume_id = await seed_complete_profile(
                connection,
                student,
                program_id=program_id,
                branch_id=branch_id,
                roll_number=f"21{suffix}",
            )
            assert resume_id is not None
            placement = await seed_cycle(connection, name=f"Placement {suffix}")
            internship = await seed_cycle(
                connection, name=f"Internship {suffix}", kind="internship"
            )
            open_cycle = await seed_cycle(
                connection, name=f"Open {suffix}", kind="open"
            )
            company_id, contact_id = await _company(connection, f"Acme {suffix}")
            membership_id = await seed_membership(
                connection,
                cycle_id=placement,
                enrollment_id=student.enrollment_id,
                resume_id=resume_id,
            )
            await seed_membership(
                connection, cycle_id=internship, enrollment_id=student.enrollment_id
            )
            await seed_membership(
                connection, cycle_id=open_cycle, enrollment_id=student.enrollment_id
            )
            job_id = await seed_job(
                connection,
                cycle_id=placement,
                company_id=company_id,
                is_published=True,
                title="Backend Engineer",
            )
            internship_job = await seed_job(
                connection,
                cycle_id=internship,
                company_id=company_id,
                outcome="internship",
                is_published=True,
                title="Summer Intern",
            )
            open_job = await seed_job(
                connection,
                cycle_id=open_cycle,
                company_id=company_id,
                is_published=True,
                title="Open Role",
                with_deadline=False,
            )
            rounds = await _rounds(connection, job_id)
            application_id = await seed_application(
                connection,
                job_id=job_id,
                enrollment_id=student.enrollment_id,
                status="in_progress",
                current_round_id=rounds[0],
            )
            await seed_round_state(
                connection, application_id=application_id, round_id=rounds[0]
            )
            await seed_event(
                connection,
                application_id=application_id,
                event_type="created",
                to_status="in_progress",
            )
    finally:
        await engine.dispose()
    return CheckerWorld(
        admin=admin,
        student=student,
        placement_cycle=placement,
        internship_cycle=internship,
        open_cycle=open_cycle,
        company_id=company_id,
        contact_id=contact_id,
        job_id=job_id,
        open_job_id=open_job,
        internship_job_id=internship_job,
        rounds=rounds,
        application_id=application_id,
        membership_id=membership_id,
        resume_id=resume_id,
    )


async def _rounds(connection: AsyncConnection, job_id: UUID) -> tuple[UUID, ...]:
    round_type_id = await seed_round_type(connection)
    ids: list[UUID] = []
    for ordinal, name in enumerate(("Screening", "Technical"), start=1):
        round_id = uuid4()
        await connection.execute(
            sa.text(
                "INSERT INTO job_rounds (id, job_id, round_type_id, ord, name) "
                "VALUES (:id, :job_id, :type_id, :ord, :name)"
            ),
            {
                "id": round_id,
                "job_id": job_id,
                "type_id": round_type_id,
                "ord": ordinal,
                "name": name,
            },
        )
        ids.append(round_id)
    return tuple(ids)


async def seed_application(
    connection: AsyncConnection,
    *,
    job_id: UUID,
    enrollment_id: UUID,
    status: str,
    current_round_id: UUID | None = None,
) -> UUID:
    application_id = uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO applications (id, job_id, enrollment_id, status, "
            "current_round_id, resume_url, profile_snapshot, applied_at) VALUES "
            "(:id, :job_id, :enrollment_id, CAST(:status AS application_status_t), "
            ":round_id, :url, CAST('{}' AS jsonb), now())"
        ),
        {
            "id": application_id,
            "job_id": job_id,
            "enrollment_id": enrollment_id,
            "status": status,
            "round_id": current_round_id,
            "url": DRIVE_URL,
        },
    )
    return application_id


async def seed_round_state(
    connection: AsyncConnection,
    *,
    application_id: UUID,
    round_id: UUID,
    result: str = "pending",
) -> UUID:
    state_id = uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO application_round_states (id, application_id, round_id, result) "
            "VALUES (:id, :application_id, :round_id, CAST(:result AS round_result_t))"
        ),
        {
            "id": state_id,
            "application_id": application_id,
            "round_id": round_id,
            "result": result,
        },
    )
    return state_id


async def seed_event(
    connection: AsyncConnection,
    *,
    application_id: UUID,
    event_type: str,
    to_status: str | None,
    from_status: str | None = None,
    payload: str = "{}",
    created_at: datetime | None = None,
) -> UUID:
    event_id = uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO application_events (id, application_id, event_type, "
            "from_status, to_status, payload, created_at) VALUES "
            "(:id, :application_id, CAST(:event_type AS event_type_t), "
            "CAST(:from_status AS application_status_t), "
            "CAST(:to_status AS application_status_t), CAST(:payload AS jsonb), "
            "coalesce(:created_at, now()))"
        ),
        {
            "id": event_id,
            "application_id": application_id,
            "event_type": event_type,
            "from_status": from_status,
            "to_status": to_status,
            "payload": payload,
            "created_at": created_at,
        },
    )
    return event_id


async def seed_offer(
    connection: AsyncConnection,
    *,
    application_id: UUID,
    response: str | None = None,
    terminated: bool = False,
) -> UUID:
    offer_id = uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO offers (id, application_id, extended_at, response, "
            "responded_at, terminated_at, termination_kind, termination_reason) VALUES "
            "(:id, :application_id, now(), CAST(:response AS offer_response_t), "
            "CASE WHEN :response IS NULL THEN NULL ELSE now() END, "
            "CASE WHEN :terminated THEN now() ELSE NULL END, "
            "CASE WHEN :terminated THEN 'admin_correction'::termination_kind_t END, "
            "CASE WHEN :terminated THEN 'Planted' END)"
        ),
        {
            "id": offer_id,
            "application_id": application_id,
            "response": response,
            "terminated": terminated,
        },
    )
    return offer_id


@dataclass(frozen=True, slots=True)
class Corruption:
    """One planted violation and what the finding it raises must say."""

    #: Plants the corruption and returns the subject keys the finding must carry.
    inject: Callable[[AsyncConnection, CheckerWorld], Awaitable[dict[str, object]]]
    suggested_fix: str
    #: The unique index that refuses this state, dropped for the injection and
    #: rebuilt afterwards.  Empty for corruption the schema permits.
    drop_index: str | None = None
    #: Statements that undo the corruption so a dropped index can be rebuilt.
    cleanup: tuple[str, ...] = field(default_factory=tuple)
    #: True when the compensating command can be prefilled from the subject and
    #: is therefore dry-run by the test.
    fix_is_runnable: bool = True


def actor_of(world: CheckerWorld) -> ActorContext:
    return world.admin_actor


def past(days: int = 1) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


async def finding_rows(invariant: str | None = None) -> list[sa.RowMapping]:
    engine = read_engine()
    try:
        async with engine.connect() as connection:
            return list(
                (
                    await connection.execute(
                        sa.text(
                            "SELECT id, invariant, subject, detail, status, "
                            "suggested_fix FROM consistency_findings "
                            "WHERE CAST(:invariant AS text) IS NULL "
                            "   OR invariant = CAST(:invariant AS text) "
                            "ORDER BY created_at, id"
                        ),
                        {"invariant": invariant},
                    )
                ).mappings().all()
            )
    finally:
        await engine.dispose()


async def scalar(sql: str, params: dict[str, object] | None = None) -> object:
    engine = read_engine()
    try:
        async with engine.connect() as connection:
            return await connection.scalar(sa.text(sql), params or {})
    finally:
        await engine.dispose()


def subject_of(row: sa.RowMapping) -> dict[str, object]:
    return cast("dict[str, object]", row["subject"])
