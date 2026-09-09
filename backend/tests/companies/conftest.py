"""Shared fixtures for the M7 company-directory suites."""

from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from app.bootstrap import build_registry
from app.core.authz import Authorizer
from app.core.db import create_engine
from app.core.executor import Executor
from app.core.plan import ActorContext
from app.settings import Settings

WEBSITE = "https://acme.example"


def company_settings() -> Settings:
    return Settings(
        session_secret="companies-test-session-secret-32-characters",
        dev_login=False,
    )


def build_test_executor() -> tuple[Executor, AsyncEngine]:
    registry = build_registry(settings=company_settings())
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker[AsyncSession](
        engine, expire_on_commit=False, autobegin=False
    )
    return (
        Executor(registry=registry, session_factory=factory, authorizer=Authorizer()),
        engine,
    )


@pytest_asyncio.fixture
async def clean_companies() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "TRUNCATE audit_log, idempotency_keys, external_offers, "
                    "applications, jobs, company_contacts, companies, cycle_policies, "
                    "cycles, sectors, profiles, sessions, enrollments, users CASCADE"
                )
            )
    finally:
        await engine.dispose()


@dataclass(frozen=True, slots=True)
class Staff:
    user_id: UUID
    session_id: UUID
    cycle_id: UUID | None = None
    role: str = "admin"

    @property
    def actor(self) -> ActorContext:
        return ActorContext(
            principal_id=str(self.user_id),
            user_id=self.user_id,
            role=self.role,
            session_id=self.session_id,
            coordinated_cycle_ids=(self.cycle_id,) if self.cycle_id else (),
        )


async def seed_admin(connection: AsyncConnection, email: str = "admin@example.edu") -> Staff:
    user_id, session_id = uuid4(), uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO users (id, email, full_name, role) "
            "VALUES (:id, :email, 'Administrator', 'admin')"
        ),
        {"id": user_id, "email": email},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO sessions (id, token_hash, user_id, expires_at) "
            "VALUES (:id, :token, :user_id, now() + interval '1 day')"
        ),
        {"id": session_id, "token": str(session_id), "user_id": user_id},
    )
    return Staff(user_id=user_id, session_id=session_id)


async def seed_coordinator(
    connection: AsyncConnection, email: str = "coordinator@example.edu"
) -> Staff:
    user_id, session_id, cycle_id = uuid4(), uuid4(), uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO users (id, email, full_name, role) "
            "VALUES (:id, :email, 'Coordinator', 'student')"
        ),
        {"id": user_id, "email": email},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO sessions (id, token_hash, user_id, expires_at) "
            "VALUES (:id, :token, :user_id, now() + interval '1 day')"
        ),
        {"id": session_id, "token": str(session_id), "user_id": user_id},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO cycles (id, name, kind, is_active) "
            "VALUES (:id, 'Placement 2026', 'placement', true)"
        ),
        {"id": cycle_id},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO cycle_coordinators (cycle_id, user_id) VALUES (:cycle, :user)"
        ),
        {"cycle": cycle_id, "user": user_id},
    )
    return Staff(user_id=user_id, session_id=session_id, cycle_id=cycle_id, role="student")


async def seed_sector(connection: AsyncConnection, name: str = "Technology") -> UUID:
    sector_id = uuid4()
    await connection.execute(
        sa.text("INSERT INTO sectors (id, name, is_active) VALUES (:id, :name, true)"),
        {"id": sector_id, "name": name},
    )
    return sector_id


async def seed_company(
    connection: AsyncConnection, name: str, *, is_active: bool = True
) -> UUID:
    company_id = uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO companies (id, name, is_active) VALUES (:id, :name, :is_active)"
        ),
        {"id": company_id, "name": name, "is_active": is_active},
    )
    return company_id


async def seed_contact(
    connection: AsyncConnection,
    company_id: UUID,
    *,
    name: str,
    email: str,
    phone: str | None = None,
    designation: str | None = None,
    is_primary: bool = False,
) -> UUID:
    contact_id = uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO company_contacts "
            "(id, company_id, name, email, phone, designation, is_primary) "
            "VALUES (:id, :company_id, :name, :email, :phone, :designation, :is_primary)"
        ),
        {
            "id": contact_id,
            "company_id": company_id,
            "name": name,
            "email": email,
            "phone": phone,
            "designation": designation,
            "is_primary": is_primary,
        },
    )
    return contact_id


async def seed_job(connection: AsyncConnection, company_id: UUID, *, title: str) -> UUID:
    """A factory row: M9 owns job creation, but merge must repoint jobs today."""
    job_id, cycle_id = uuid4(), uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO cycles (id, name, kind, is_active) "
            "VALUES (:id, :name, 'placement', true)"
        ),
        {"id": cycle_id, "name": f"Cycle for {title}"},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO jobs (id, cycle_id, company_id, outcome, title, description) "
            "VALUES (:id, :cycle_id, :company_id, 'placement', :title, 'Factory row')"
        ),
        {"id": job_id, "cycle_id": cycle_id, "company_id": company_id, "title": title},
    )
    return job_id


async def seed_external_offer(
    connection: AsyncConnection, company_id: UUID, *, created_by: UUID
) -> UUID:
    """A factory row: M12 owns external offers, but merge must repoint them today."""
    offer_id, user_id, enrollment_id = uuid4(), uuid4(), uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO users (id, email, full_name, role) "
            "VALUES (:id, :email, 'External Student', 'student')"
        ),
        {"id": user_id, "email": f"{offer_id}@example.edu"},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO enrollments (id, user_id, is_current) VALUES (:id, :user_id, true)"
        ),
        {"id": enrollment_id, "user_id": user_id},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO external_offers "
            "(id, enrollment_id, company_id, outcome, source, status, created_by) "
            "VALUES (:id, :enrollment_id, :company_id, 'placement', 'ppo', 'offered', :by)"
        ),
        {
            "id": offer_id,
            "enrollment_id": enrollment_id,
            "company_id": company_id,
            "by": created_by,
        },
    )
    return offer_id
