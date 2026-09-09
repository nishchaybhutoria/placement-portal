"""Shared fixtures for the M8 cycle and membership suites."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
)

from app.bootstrap import build_executor, build_registry
from app.core.db import create_engine
from app.core.executor import Executor
from app.core.plan import ActorContext
from app.settings import Settings

DRIVE_URL = "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view"


def cycle_settings() -> Settings:
    return Settings(
        session_secret="cycles-test-session-secret-32-characters",
        dev_login=False,
    )


def build_test_executor() -> tuple[Executor, AsyncEngine]:
    """The executor every suite runs commands through -- the *production* one.

    It assembled its own Executor until M10, which meant it silently omitted
    ``override_resolver``: every override was inert under it while production
    resolved them, so a test could asserted a bypass that never happened and
    pass for the wrong reason.  Deferring to ``bootstrap.build_executor`` makes
    the two assemblies the same object graph by construction, which is the only
    version of this that cannot rot -- a future constructor argument is picked
    up here without anyone remembering to.
    ``tests/applications/test_executor_assembly.py`` pins it.
    """
    registry = build_registry(settings=cycle_settings())
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    return build_executor(registry, engine), engine


@pytest_asyncio.fixture
async def clean_cycles() -> None:
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
                    "programs, branches, sectors, round_types, procrastinate_jobs CASCADE"
                )
            )
    finally:
        await engine.dispose()


@dataclass(frozen=True, slots=True)
class Person:
    user_id: UUID
    session_id: UUID
    enrollment_id: UUID
    email: str
    role: str = "student"
    coordinated: tuple[UUID, ...] = ()

    @property
    def actor(self) -> ActorContext:
        return ActorContext(
            principal_id=str(self.user_id),
            user_id=self.user_id,
            role=self.role,
            session_id=self.session_id,
            current_enrollment_id=self.enrollment_id,
            coordinated_cycle_ids=self.coordinated,
            email=self.email,
        )

    def coordinating(self, *cycle_ids: UUID) -> Person:
        return Person(
            user_id=self.user_id,
            session_id=self.session_id,
            enrollment_id=self.enrollment_id,
            email=self.email,
            role=self.role,
            coordinated=cycle_ids,
        )


async def seed_person(
    connection: AsyncConnection,
    *,
    email: str,
    role: str = "student",
    full_name: str = "Asha Rao",
) -> Person:
    user_id, session_id, enrollment_id = uuid4(), uuid4(), uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO users (id, email, full_name, role) "
            "VALUES (:id, :email, :full_name, :role)"
        ),
        {"id": user_id, "email": email, "full_name": full_name, "role": role},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO enrollments (id, user_id, is_current) "
            "VALUES (:id, :user_id, true)"
        ),
        {"id": enrollment_id, "user_id": user_id},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO sessions (id, token_hash, user_id, expires_at) "
            "VALUES (:id, :token, :user_id, now() + interval '1 day')"
        ),
        {"id": session_id, "token": str(session_id), "user_id": user_id},
    )
    return Person(
        user_id=user_id,
        session_id=session_id,
        enrollment_id=enrollment_id,
        email=email,
        role=role,
    )


async def seed_admin(
    connection: AsyncConnection, email: str = "admin@example.edu"
) -> Person:
    return await seed_person(
        connection, email=email, role="admin", full_name="Administrator"
    )


async def seed_taxonomy(connection: AsyncConnection) -> tuple[UUID, UUID]:
    """One program and one branch, mapped, so profiles can be complete."""
    program_id, branch_id = uuid4(), uuid4()
    await connection.execute(
        sa.text("INSERT INTO programs (id, name, is_active) VALUES (:id, 'BTech', true)"),
        {"id": program_id},
    )
    await connection.execute(
        sa.text("INSERT INTO branches (id, name, is_active) VALUES (:id, 'CSE', true)"),
        {"id": branch_id},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO program_branches (id, program_id, branch_id) "
            "VALUES (:id, :program_id, :branch_id)"
        ),
        {"id": uuid4(), "program_id": program_id, "branch_id": branch_id},
    )
    return program_id, branch_id


async def seed_complete_profile(
    connection: AsyncConnection,
    person: Person,
    *,
    program_id: UUID,
    branch_id: UUID,
    roll_number: str = "21110001",
    declared: bool = True,
    cpi: str = "8.40",
    with_resume: bool = True,
) -> UUID | None:
    """A profile that satisfies the whole PRO-1 join checklist."""
    await connection.execute(
        sa.text("UPDATE enrollments SET roll_number = :roll WHERE id = :id"),
        {"roll": roll_number, "id": person.enrollment_id},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO profiles (id, enrollment_id, program_id, primary_branch_id, "
            "graduating_year, cpi, active_backlogs, total_backlogs, gender, "
            "personal_email, contact_number, nationality, tenth_percent, tenth_year, "
            "twelfth_percent, twelfth_year, declared_at) "
            "VALUES (:id, :enrollment_id, :program_id, :branch_id, 2026, :cpi, 0, 0, "
            "'female', :personal_email, '+1 202-555-0100', 'IN', 92.00, 2019, "
            "94.00, 2021, :declared_at)"
        ),
        {
            "id": uuid4(),
            "enrollment_id": person.enrollment_id,
            "program_id": program_id,
            "branch_id": branch_id,
            "cpi": cpi,
            "personal_email": f"personal.{person.email}",
            "declared_at": datetime.now(UTC) if declared else None,
        },
    )
    if not with_resume:
        return None
    resume_id = uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO resumes (id, enrollment_id, label, drive_url, is_default) "
            "VALUES (:id, :enrollment_id, 'Primary', :url, true)"
        ),
        {"id": resume_id, "enrollment_id": person.enrollment_id, "url": DRIVE_URL},
    )
    return resume_id


async def seed_cycle(
    connection: AsyncConnection,
    *,
    name: str = "Placement 2026",
    kind: str = "placement",
    is_active: bool = True,
    requires_approval: bool | None = None,
    registration_open: bool = True,
    archived: bool = False,
    join_rule: str | None = None,
) -> UUID:
    """A cycle with its policy row, as create_cycle would have written it."""
    cycle_id = uuid4()
    now = datetime.now(UTC)
    window = (
        {"opens": now - timedelta(days=1), "closes": now + timedelta(days=30)}
        if registration_open
        else {"opens": now - timedelta(days=30), "closes": now - timedelta(days=1)}
    )
    await connection.execute(
        sa.text(
            "INSERT INTO cycles (id, name, kind, is_active, registration_opens_at, "
            "registration_closes_at, archived_at) "
            "VALUES (:id, :name, CAST(:kind AS cycle_kind_t), :is_active, :opens, "
            ":closes, :archived_at)"
        ),
        {
            "id": cycle_id,
            "name": name,
            "kind": kind,
            "is_active": is_active,
            "opens": window["opens"],
            "closes": window["closes"],
            "archived_at": now if archived else None,
        },
    )
    approval = (
        kind != "open" if requires_approval is None else requires_approval
    )
    await connection.execute(
        sa.text(
            "INSERT INTO cycle_policies (id, cycle_id, membership_requires_approval, "
            "join_rule, max_accepted_offers, penalty_blocks_applications, "
            "allow_withdrawal_after_deadline, allow_edit_after_deadline, "
            "strike_on_absence) "
            "VALUES (:id, :cycle_id, :approval, CAST(:join_rule AS jsonb), :cap, "
            "true, false, false, true)"
        ),
        {
            "id": uuid4(),
            "cycle_id": cycle_id,
            "approval": approval,
            "join_rule": join_rule,
            "cap": None if kind == "open" else 1,
        },
    )
    return cycle_id


async def seed_coordinator_link(
    connection: AsyncConnection, cycle_id: UUID, user_id: UUID
) -> None:
    await connection.execute(
        sa.text(
            "INSERT INTO cycle_coordinators (id, cycle_id, user_id) "
            "VALUES (:id, :cycle_id, :user_id)"
        ),
        {"id": uuid4(), "cycle_id": cycle_id, "user_id": user_id},
    )


async def seed_membership(
    connection: AsyncConnection,
    *,
    cycle_id: UUID,
    enrollment_id: UUID,
    status: str = "active",
    resume_id: UUID | None = None,
    rejection_reason: str | None = None,
) -> UUID:
    membership_id = uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO cycle_memberships (id, cycle_id, enrollment_id, status, "
            "default_resume_id, consented_at, rejection_reason) "
            "VALUES (:id, :cycle_id, :enrollment_id, "
            "CAST(:status AS membership_status_t), :resume_id, now(), :reason)"
        ),
        {
            "id": membership_id,
            "cycle_id": cycle_id,
            "enrollment_id": enrollment_id,
            "status": status,
            "resume_id": resume_id,
            "reason": rejection_reason,
        },
    )
    return membership_id


async def seed_round_type(connection: AsyncConnection, name: str = "Screening") -> UUID:
    round_type_id = await connection.scalar(
        sa.text("SELECT id FROM round_types WHERE name = :name"), {"name": name}
    )
    if round_type_id is None:
        round_type_id = uuid4()
        await connection.execute(
            sa.text(
                "INSERT INTO round_types (id, name, is_active) "
                "VALUES (:id, :name, true)"
            ),
            {"id": round_type_id, "name": name},
        )
    return cast(UUID, round_type_id)


async def seed_job(
    connection: AsyncConnection,
    *,
    cycle_id: UUID,
    title: str = "Backend Engineer",
    outcome: str = "placement",
    is_published: bool = False,
    company_id: UUID | None = None,
    with_deadline: bool = True,
) -> UUID:
    """One job with its own company, for tests that need a job to point at.

    Carries an application deadline by default because create_job requires one
    outside an open cycle, so a dedicated-cycle job without one is a state
    production cannot reach.
    """
    job_id = uuid4()
    if company_id is None:
        company_id = uuid4()
        await connection.execute(
            sa.text(
                "INSERT INTO companies (id, name, is_active) VALUES (:id, :name, true)"
            ),
            {"id": company_id, "name": f"Company for {title} {job_id}"},
        )
    await connection.execute(
        sa.text(
            "INSERT INTO jobs (id, cycle_id, company_id, outcome, title, "
            "description, is_published, published_at, application_deadline) VALUES "
            "(:id, :cycle_id, :company_id, CAST(:outcome AS outcome_t), :title, "
            "'Factory row', :is_published, "
            "CASE WHEN :is_published THEN now() ELSE NULL END, :deadline)"
        ),
        {
            "id": job_id,
            "cycle_id": cycle_id,
            "company_id": company_id,
            "outcome": outcome,
            "title": title,
            "is_published": is_published,
            "deadline": (
                datetime.now(UTC) + timedelta(days=30) if with_deadline else None
            ),
        },
    )
    return job_id


async def seed_application(
    connection: AsyncConnection,
    *,
    cycle_id: UUID,
    enrollment_id: UUID,
    status: str = "in_progress",
    title: str = "Backend Engineer",
    with_round: bool = False,
    job_id: UUID | None = None,
) -> tuple[UUID, UUID | None]:
    """A factory row: M10 owns applications, M8 and M9 must reach over them."""
    application_id = uuid4()
    if job_id is None:
        job_id = await seed_job(connection, cycle_id=cycle_id, title=title)
    round_id: UUID | None = None
    if with_round:
        round_id = uuid4()
        round_type_id = await seed_round_type(connection)
        await connection.execute(
            sa.text(
                "INSERT INTO job_rounds (id, job_id, round_type_id, ord, name) "
                "VALUES (:id, :job_id, :round_type_id, 1, 'Screening')"
            ),
            {"id": round_id, "job_id": job_id, "round_type_id": round_type_id},
        )
    await connection.execute(
        sa.text(
            "INSERT INTO applications (id, job_id, enrollment_id, status, "
            "current_round_id, resume_url, profile_snapshot, applied_at) "
            "VALUES (:id, :job_id, :enrollment_id, "
            "CAST(:status AS application_status_t), :round_id, :url, "
            "CAST('{}' AS jsonb), now())"
        ),
        {
            "id": application_id,
            "job_id": job_id,
            "enrollment_id": enrollment_id,
            "status": status,
            "round_id": round_id,
            "url": DRIVE_URL,
        },
    )
    return application_id, round_id


async def application_status(connection: AsyncConnection, application_id: UUID) -> str:
    return cast(
        str,
        await connection.scalar(
            sa.text("SELECT status FROM applications WHERE id = :id"),
            {"id": application_id},
        ),
    )


async def membership_row(
    connection: AsyncConnection, membership_id: UUID
) -> sa.RowMapping:
    return (
        await connection.execute(
            sa.text("SELECT * FROM cycle_memberships WHERE id = :id"),
            {"id": membership_id},
        )
    ).mappings().one()
