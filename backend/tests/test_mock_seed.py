"""The Part A.4 mock-run seed has an exact cast and remains idempotent."""

from __future__ import annotations

import os
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa

from app.core.db import create_engine
from app.mock_seed import run_mock_seed
from app.settings import Settings

pytestmark = pytest.mark.usefixtures("clean_seed")


def _seed_settings() -> Settings:
    return Settings(
        session_secret="mock-seed-test-session-secret-32-chars",
        allowed_domain="example.edu",
        dev_login=False,
    )


@pytest_asyncio.fixture
async def clean_seed() -> None:
    """Judge the seed against an empty database, as a tester's first run would."""
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "TRUNCATE audit_log, idempotency_keys, notification_log, "
                    "consistency_findings, overrides, "
                    "application_events, application_answers, "
                    "application_round_states, applications, offers, external_offers, "
                    "export_presets, job_question_options, job_questions, "
                    "job_program_ctc, job_rounds, jobs, "
                    "cycle_memberships, cycle_coordinators, cycle_policies, cycles, "
                    "resumes, profiles, sessions, enrollments, users, companies, "
                    "company_contacts, staged_profile_rows, settings, "
                    "programs, branches, minors, sectors, round_types, "
                    "program_branches, procrastinate_jobs CASCADE"
                )
            )
    finally:
        await engine.dispose()


async def _seed() -> None:
    await run_mock_seed(database_url=os.environ["TEST_DATABASE_URL"], settings=_seed_settings())


async def _one(sql: str, params: dict[str, object] | None = None) -> Any:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            return await connection.scalar(sa.text(sql), params or {})
    finally:
        await engine.dispose()


async def _all(sql: str) -> list[dict[str, Any]]:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            rows = (await connection.execute(sa.text(sql))).mappings().all()
            return [dict(row) for row in rows]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_mock_seed_matches_the_synthetic_cast() -> None:
    await _seed()

    students = await _all(
        "SELECT u.email, u.full_name, e.roll_number, p.declared_at, p.cpi, "
        "p.active_backlogs, p.total_backlogs, p.is_dual_major, "
        "prog.name AS program, branch.name AS branch, secondary.name AS secondary_branch "
        "FROM users u JOIN enrollments e ON e.user_id = u.id AND e.is_current "
        "LEFT JOIN profiles p ON p.enrollment_id = e.id "
        "LEFT JOIN programs prog ON prog.id = p.program_id "
        "LEFT JOIN branches branch ON branch.id = p.primary_branch_id "
        "LEFT JOIN branches secondary ON secondary.id = p.secondary_branch_id "
        "WHERE e.roll_number <> '99000901' ORDER BY e.roll_number"
    )
    expected = {
        "99000002": (
            "Demo Student 02",
            "demo.student02@example.edu",
            "BTech",
            "CSE",
            "8.20",
            0,
            0,
        ),
        "99000003": (
            "Demo Student 03",
            "demo.student03@example.edu",
            "BTech",
            "EE",
            "7.95",
            0,
            0,
        ),
        "99000011": (
            "Demo Student 11",
            "demo.student11@example.edu",
            "BTech",
            "Mechanical",
            "8.05",
            0,
            0,
        ),
        "99000006": ("Demo Student 06", "demo.student06@example.edu", "BTech", "CSE", "9.10", 0, 0),
        "99000009": (
            "Demo Student 09",
            "demo.student09@example.edu",
            "BTech",
            "Chemical",
            "7.60",
            0,
            0,
        ),
        "99000004": ("Demo Student 04", "demo.student04@example.edu", "BTech", "CSE", "7.80", 0, 0),
        "99000001": (
            "Demo Student 01",
            "demo.student01@example.edu",
            "BTech",
            "CSE",
            "8.60",
            0,
            0,
        ),
        "99000008": ("Demo Student 08", "demo.student08@example.edu", "BTech", "EE", "7.94", 0, 0),
        "99000007": ("Demo Student 07", "demo.student07@example.edu", "MTech", "CSE", "8.40", 0, 0),
    }
    declared = {row["roll_number"]: row for row in students if row["declared_at"] is not None}
    assert {
        roll: (
            row["full_name"],
            row["email"],
            row["program"],
            row["branch"],
            str(row["cpi"]),
            row["active_backlogs"],
            row["total_backlogs"],
        )
        for roll, row in declared.items()
    } == expected
    assert sum(row["declared_at"] is not None for row in students) == 9
    undeclared = {row["full_name"] for row in students if row["declared_at"] is None}
    assert undeclared == {"Demo Student 05", "Demo Student 10"}

    demo_student_04 = next(row for row in students if row["full_name"] == "Demo Student 04")
    assert (
        demo_student_04["program"],
        demo_student_04["branch"],
        demo_student_04["secondary_branch"],
    ) == ("BTech", "CSE", "EE")
    assert demo_student_04["is_dual_major"] is True
    demo_student_07 = next(row for row in students if row["full_name"] == "Demo Student 07")
    assert demo_student_07["program"] == "MTech"

    coordinators = await _all(
        "SELECT u.email, e.roll_number, p.declared_at, "
        "array_agg(c.name ORDER BY c.name) AS cycles "
        "FROM users u JOIN enrollments e ON e.user_id = u.id AND e.is_current "
        "LEFT JOIN profiles p ON p.enrollment_id = e.id "
        "JOIN cycle_coordinators cc ON cc.user_id = u.id "
        "JOIN cycles c ON c.id = cc.cycle_id "
        "GROUP BY u.email, e.roll_number, p.declared_at ORDER BY u.email"
    )
    assert coordinators == [
        {
            "email": "demo.coordinator01@example.edu",
            "roll_number": "99000901",
            "declared_at": None,
            "cycles": [
                "Open Opportunities — Summer",
                "Placements 2027–28",
                "Summer Internships 2027",
            ],
        },
        {
            "email": "demo.coordinator02@example.edu",
            "roll_number": None,
            "declared_at": None,
            "cycles": ["Winter Internships 2027"],
        },
    ]
    assert await _one("SELECT count(*) FROM users") == 14
    assert await _one("SELECT count(*) FROM cycle_memberships") == 0
    assert (
        await _one("SELECT count(*) FROM users WHERE email ~ '^(s[0-9]+|coordinator[.][abc])@'")
        == 0
    )


@pytest.mark.asyncio
async def test_NTF_the_mock_world_renders_notifications_with_a_real_sender() -> None:
    """Every mock envelope needs a From line.

    Delivery reads ``settings.ses_sender`` and only falls back to the
    environment, so a world without the setting renders every notification with
    an empty sender: invisible on the console backend, refused outright by
    ``SesEmailBackend.send``, and unreviewable at Step 33.
    """
    await _seed()

    assert (
        await _one("SELECT value #>> '{}' FROM settings WHERE key = 'ses_sender'")
        == "CDS noreply <noreply@cdsportal.example.edu>"
    )


@pytest.mark.asyncio
async def test_the_mock_seed_is_idempotent() -> None:
    await _seed()
    first = {
        table: await _one(f"SELECT count(*) FROM {table}")  # noqa: S608
        for table in (
            "audit_log",
            "users",
            "sessions",
            "enrollments",
            "profiles",
            "resumes",
            "programs",
            "branches",
            "minors",
            "sectors",
            "round_types",
            "program_branches",
            "cycles",
            "cycle_policies",
            "cycle_coordinators",
            "cycle_memberships",
            "companies",
            "company_contacts",
            "jobs",
            "job_rounds",
            "job_questions",
            "applications",
            "settings",
        )
    }

    await _seed()
    second = {table: await _one(f"SELECT count(*) FROM {table}") for table in first}  # noqa: S608

    assert second == first
