"""Shared world-building for the M10 application suites.

Builds on the M8/M9 fixtures rather than restating them: an application only
exists inside a job, inside a cycle, held by a member.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.db import create_engine
from app.core.plan import ActorContext
from tests.cycles.conftest import (  # noqa: F401 - re-exported for the suites
    DRIVE_URL,
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


@pytest_asyncio.fixture(autouse=True)
async def clean_applications() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "TRUNCATE audit_log, idempotency_keys, consistency_findings, "
                    "notification_log, "
                    "application_events, application_answers, "
                    "application_round_states, applications, offers, overrides, "
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


@dataclass(frozen=True, slots=True)
class World:
    """One cycle, one published job, one active member who can apply."""

    student: Person
    cycle_id: UUID
    job_id: UUID
    resume_id: UUID
    program_id: UUID
    branch_id: UUID
    student_name: str
    roll_number: str
    round_id: UUID | None = None
    #: A coordinator of this cycle, for the staff-side operations.  Not an
    #: admin: a coordinator is the narrower actor, so a command that works for
    #: them works for both (C2 -- staff is admin OR an assignment).
    staff: Person | None = None

    @property
    def staff_actor(self) -> ActorContext:
        if self.staff is None:
            raise AssertionError("seed_world(with_staff=True) was not used")
        return self.staff.actor


async def seed_round(
    connection: AsyncConnection, *, job_id: UUID, ord: int = 1, name: str = "Screening"
) -> UUID:
    round_id = uuid4()
    round_type_id = await seed_round_type(connection, name=f"{name} {ord}")
    await connection.execute(
        sa.text(
            "INSERT INTO job_rounds (id, job_id, round_type_id, ord, name) "
            "VALUES (:id, :job_id, :round_type_id, :ord, :name)"
        ),
        {
            "id": round_id,
            "job_id": job_id,
            "round_type_id": round_type_id,
            "ord": ord,
            "name": name,
        },
    )
    return round_id


async def seed_question(
    connection: AsyncConnection,
    *,
    job_id: UUID,
    text: str = "Why this role?",
    qtype: str = "text",
    required: bool = True,
    ord: int = 1,
    options: tuple[str, ...] = (),
) -> UUID:
    question_id = uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO job_questions (id, job_id, ord, text, qtype, required) "
            "VALUES (:id, :job_id, :ord, :text, CAST(:qtype AS question_type_t), "
            ":required)"
        ),
        {
            "id": question_id,
            "job_id": job_id,
            "ord": ord,
            "text": text,
            "qtype": qtype,
            "required": required,
        },
    )
    for index, option in enumerate(options, start=1):
        await connection.execute(
            sa.text(
                "INSERT INTO job_question_options (id, question_id, ord, text) "
                "VALUES (:id, :question_id, :ord, :text)"
            ),
            {
                "id": uuid4(),
                "question_id": question_id,
                "ord": index,
                "text": option,
            },
        )
    return question_id


async def set_eligibility_rule(
    connection: AsyncConnection, *, job_id: UUID, rule: str, summary: str
) -> None:
    await connection.execute(
        sa.text(
            "UPDATE jobs SET eligibility_rule = CAST(:rule AS jsonb), "
            "eligibility_summary = :summary WHERE id = :id"
        ),
        {"id": job_id, "rule": rule, "summary": summary},
    )


async def seed_world(
    *,
    kind: str = "placement",
    outcome: str = "placement",
    membership_status: str = "active",
    cpi: str = "8.40",
    is_published: bool = True,
    with_deadline: bool = True,
    with_rounds: bool = False,
    archived: bool = False,
    with_staff: bool = False,
) -> World:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await seed_admin(connection)
            program_id, branch_id = await seed_taxonomy(connection)
            student = await seed_person(
                connection, email="asha@example.edu", full_name="Asha Rao"
            )
            resume_id = await seed_complete_profile(
                connection,
                student,
                program_id=program_id,
                branch_id=branch_id,
                cpi=cpi,
            )
            assert resume_id is not None
            cycle_id = await seed_cycle(connection, kind=kind, archived=archived)
            await seed_membership(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status=membership_status,
                resume_id=resume_id,
            )
            job_id = await seed_job(
                connection,
                cycle_id=cycle_id,
                outcome=outcome,
                is_published=is_published,
                with_deadline=with_deadline,
            )
            round_id = (
                await seed_round(connection, job_id=job_id) if with_rounds else None
            )
            staff: Person | None = None
            if with_staff:
                staff = await seed_person(
                    connection, email="coord@example.edu", full_name="Coordinator Rao"
                )
                await seed_coordinator_link(connection, cycle_id, staff.user_id)
                staff = staff.coordinating(cycle_id)
    finally:
        await engine.dispose()
    return World(
        student=student,
        cycle_id=cycle_id,
        job_id=job_id,
        resume_id=resume_id,
        program_id=program_id,
        branch_id=branch_id,
        student_name="Asha Rao",
        roll_number="21110001",
        round_id=round_id,
        staff=staff,
    )


def cpi_floor_rule(floor: str = "9.00") -> tuple[str, str]:
    """A rule that fails on a leaf, not on circumstance (the design review 4.21).

    The equivalence test needs the *rule* path exercised: a deadline that has
    passed would prove far less, because both callers read the deadline from
    the same column while the rule runs through the evaluator.
    """
    return (
        f'{{"field": "cpi", "op": "gte", "value": {Decimal(floor)}}}',
        f"CPI at least {floor}",
    )
