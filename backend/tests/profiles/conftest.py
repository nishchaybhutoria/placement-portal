"""Shared database fixtures for the M6 profile suites."""

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

DRIVE_URL = "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view"
OTHER_DRIVE_URL = "https://docs.google.com/document/d/1ZyXwVuTsRqPoNmLkJiHgFeDcBa987654/edit"


@dataclass(frozen=True, slots=True)
class Student:
    user_id: UUID
    enrollment_id: UUID
    session_id: UUID
    email: str

    @property
    def actor(self) -> ActorContext:
        return ActorContext(
            principal_id=str(self.user_id),
            user_id=self.user_id,
            role="student",
            session_id=self.session_id,
            current_enrollment_id=self.enrollment_id,
        )


@dataclass(frozen=True, slots=True)
class Taxonomy:
    program_id: UUID
    other_program_id: UUID
    branch_id: UUID
    second_branch_id: UUID
    unmapped_branch_id: UUID
    minor_id: UUID
    program_name: str = "BTech"
    branch_name: str = "Computer Science and Engineering"


def profiles_settings() -> Settings:
    return Settings(
        session_secret="profiles-test-session-secret-32-characters",
        dev_login=False,
    )


def build_test_executor() -> tuple[Executor, AsyncEngine]:
    registry = build_registry(settings=profiles_settings())
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker[AsyncSession](
        engine, expire_on_commit=False, autobegin=False
    )
    return (
        Executor(registry=registry, session_factory=factory, authorizer=Authorizer()),
        engine,
    )


@pytest_asyncio.fixture
async def clean_profiles() -> None:
    """Truncate every table the profile suites touch (opt-in, DB suites only)."""
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "TRUNCATE audit_log, idempotency_keys, staged_profile_rows, resumes, "
                    "profiles, program_branches, programs, branches, minors, sectors, "
                    "round_types, cycle_memberships, cycle_policies, cycle_coordinators, "
                    "cycles, sessions, enrollments, users CASCADE"
                )
            )
    finally:
        await engine.dispose()


async def seed_admin(connection: AsyncConnection, email: str = "admin@example.edu") -> ActorContext:
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
    return ActorContext(
        principal_id=str(user_id), user_id=user_id, role="admin", session_id=session_id
    )


async def seed_student(
    connection: AsyncConnection,
    email: str,
    *,
    roll_number: str | None = None,
    full_name: str = "Test Student",
    is_current: bool = True,
) -> Student:
    user_id, enrollment_id, session_id = uuid4(), uuid4(), uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO users (id, email, full_name, role) "
            "VALUES (:id, :email, :full_name, 'student')"
        ),
        {"id": user_id, "email": email, "full_name": full_name},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO enrollments (id, user_id, is_current, roll_number) "
            "VALUES (:id, :user_id, :is_current, :roll_number)"
        ),
        {
            "id": enrollment_id,
            "user_id": user_id,
            "is_current": is_current,
            "roll_number": roll_number,
        },
    )
    await connection.execute(
        sa.text(
            "INSERT INTO sessions (id, token_hash, user_id, expires_at) "
            "VALUES (:id, :token, :user_id, now() + interval '1 day')"
        ),
        {"id": session_id, "token": str(session_id), "user_id": user_id},
    )
    return Student(
        user_id=user_id, enrollment_id=enrollment_id, session_id=session_id, email=email
    )


async def add_enrollment(
    connection: AsyncConnection, student: Student, *, roll_number: str | None = None
) -> UUID:
    """Supersede a student's enrollment the way IDN-2's rejoin flow does."""
    enrollment_id = uuid4()
    await connection.execute(
        sa.text("UPDATE enrollments SET is_current = false WHERE user_id = :user_id"),
        {"user_id": student.user_id},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO enrollments (id, user_id, is_current, roll_number) "
            "VALUES (:id, :user_id, true, :roll_number)"
        ),
        {"id": enrollment_id, "user_id": student.user_id, "roll_number": roll_number},
    )
    return enrollment_id


async def seed_taxonomy(connection: AsyncConnection) -> Taxonomy:
    ids = {name: uuid4() for name in ("program", "other", "branch", "second", "unmapped", "minor")}
    await connection.execute(
        sa.text(
            "INSERT INTO programs (id, name, is_active) VALUES "
            "(:program, 'BTech', true), (:other, 'MTech', true)"
        ),
        {"program": ids["program"], "other": ids["other"]},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO branches (id, name, is_active) VALUES "
            "(:branch, 'Computer Science and Engineering', true), "
            "(:second, 'Electrical Engineering', true), "
            "(:unmapped, 'Civil Engineering', true)"
        ),
        {"branch": ids["branch"], "second": ids["second"], "unmapped": ids["unmapped"]},
    )
    await connection.execute(
        sa.text("INSERT INTO minors (id, name, is_active) VALUES (:minor, 'Design', true)"),
        {"minor": ids["minor"]},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO program_branches (program_id, branch_id) VALUES "
            "(:program, :branch), (:program, :second), (:other, :branch)"
        ),
        {
            "program": ids["program"],
            "other": ids["other"],
            "branch": ids["branch"],
            "second": ids["second"],
        },
    )
    return Taxonomy(
        program_id=ids["program"],
        other_program_id=ids["other"],
        branch_id=ids["branch"],
        second_branch_id=ids["second"],
        unmapped_branch_id=ids["unmapped"],
        minor_id=ids["minor"],
    )
