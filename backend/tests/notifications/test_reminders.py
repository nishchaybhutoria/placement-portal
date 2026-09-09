"""Deadline/round selection, live relevance, and dedup gates for Behavior NTF."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.executor import Executor
from app.core.plan import ActorContext
from app.modules.notifications.reminders import (
    SendDeadlineRemindersInput,
    SendRoundRemindersInput,
)

SYSTEM = ActorContext(principal_id="system", is_system=True)
DRIVE_URL = "https://drive.google.com/file/d/reminder-fixture/view"


async def _seed_base(
    run_at: datetime,
    *,
    eligibility_rule: str | None = None,
    cpi: str = "8.50",
) -> dict[str, UUID]:
    ids = {
        key: uuid4()
        for key in (
            "user",
            "enrollment",
            "cycle",
            "company",
            "job",
            "membership",
            "program",
            "branch",
        )
    }
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "INSERT INTO users (id, email, full_name, role) "
                    "VALUES (:id, 'eligible.student@example.edu', 'Eligible Student', 'student')"
                ),
                {"id": ids["user"]},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO enrollments (id, user_id, is_current, roll_number) "
                    "VALUES (:id, :user, true, 'NTF001')"
                ),
                {"id": ids["enrollment"], "user": ids["user"]},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO programs (id, name, is_active) "
                    "VALUES (:id, 'Reminder BTech', true)"
                ),
                {"id": ids["program"]},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO branches (id, name, is_active) VALUES (:id, 'Reminder CSE', true)"
                ),
                {"id": ids["branch"]},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO profiles (enrollment_id, program_id, "
                    "primary_branch_id, graduating_year, cpi, active_backlogs, "
                    "total_backlogs, gender, nationality) VALUES "
                    "(:enrollment, :program, :branch, 2027, :cpi, 0, 0, 'female', 'IN')"
                ),
                {
                    "enrollment": ids["enrollment"],
                    "program": ids["program"],
                    "branch": ids["branch"],
                    "cpi": cpi,
                },
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO cycles (id, name, kind, is_active) "
                    "VALUES (:id, 'Reminder Placement', 'placement', true)"
                ),
                {"id": ids["cycle"]},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO cycle_policies (cycle_id, membership_requires_approval, "
                    "max_accepted_offers, penalty_blocks_applications, "
                    "allow_withdrawal_after_deadline, allow_edit_after_deadline, "
                    "strike_on_absence, deadline_reminder_hours, round_reminder_hours) "
                    "VALUES (:cycle, false, 1, true, false, false, true, 6, 24)"
                ),
                {"cycle": ids["cycle"]},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO cycle_memberships "
                    "(id, cycle_id, enrollment_id, status, consented_at) "
                    "VALUES (:id, :cycle, :enrollment, 'active', :now)"
                ),
                {
                    "id": ids["membership"],
                    "cycle": ids["cycle"],
                    "enrollment": ids["enrollment"],
                    "now": run_at,
                },
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO companies (id, name, is_active) "
                    "VALUES (:id, 'Reminder Systems', true)"
                ),
                {"id": ids["company"]},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO jobs (id, cycle_id, company_id, outcome, title, "
                    "description, application_deadline, is_published, published_at, "
                    "eligibility_rule) VALUES (:id, :cycle, :company, 'placement', "
                    "'Reminder Engineer', 'Reminder fixture', :deadline, true, :now, "
                    "CAST(:rule AS jsonb))"
                ),
                {
                    "id": ids["job"],
                    "cycle": ids["cycle"],
                    "company": ids["company"],
                    "deadline": run_at + timedelta(hours=6),
                    "now": run_at,
                    "rule": eligibility_rule,
                },
            )
    finally:
        await engine.dispose()
    return ids


async def _counts() -> tuple[int, int, list[dict[str, object]]]:
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            sends = int(
                await connection.scalar(sa.text("SELECT count(*) FROM reminder_sends")) or 0
            )
            jobs = (
                (
                    await connection.execute(
                        sa.text(
                            "SELECT args->>'recipient' AS recipient, "
                            "args->>'event_key' AS event_key, args->'context' AS context "
                            "FROM procrastinate_jobs WHERE task_name = 'deliver_notification' "
                            "ORDER BY id"
                        )
                    )
                )
                .mappings()
                .all()
            )
    finally:
        await engine.dispose()
    return sends, len(jobs), [dict(row) for row in jobs]


@pytest.mark.asyncio
async def test_NTF_deadline_cron_twice_sends_exactly_once_per_student_job(
    notification_executor: Executor,
) -> None:
    run_at = datetime(2027, 1, 10, 4, 0, tzinfo=UTC)
    await _seed_base(run_at)
    first = await notification_executor.run(
        "send_deadline_reminders",
        SendDeadlineRemindersInput(run_at=run_at),
        SYSTEM,
    )
    second = await notification_executor.run(
        "send_deadline_reminders",
        SendDeadlineRemindersInput(run_at=run_at),
        SYSTEM,
    )
    sends, queued, jobs = await _counts()
    assert first.summary["queued"] == 1
    assert second.summary["queued"] == 0
    assert (sends, queued) == (1, 1)
    assert jobs[0]["recipient"] == "eligible.student@example.edu"
    assert jobs[0]["event_key"] == "deadline_reminder"
    assert cast(dict[str, object], jobs[0]["context"])["hours_left"] == 6


@pytest.mark.asyncio
async def test_ELG1_NTF_deadline_reminder_uses_the_live_profile_rule(
    notification_executor: Executor,
) -> None:
    run_at = datetime(2027, 1, 10, 4, 0, tzinfo=UTC)
    ids = await _seed_base(
        run_at,
        eligibility_rule='{"field":"cpi","op":"gte","value":8.0}',
        cpi="7.50",
    )
    ineligible = await notification_executor.run(
        "send_deadline_reminders",
        SendDeadlineRemindersInput(run_at=run_at),
        SYSTEM,
    )
    assert ineligible.summary["queued"] == 0

    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text("UPDATE profiles SET cpi = 8.50 WHERE enrollment_id = :id"),
                {"id": ids["enrollment"]},
            )
    finally:
        await engine.dispose()
    eligible = await notification_executor.run(
        "send_deadline_reminders",
        SendDeadlineRemindersInput(run_at=run_at),
        SYSTEM,
    )
    assert eligible.summary["queued"] == 1


@pytest.mark.asyncio
async def test_NTF_deadline_reminder_skips_a_student_who_has_applied(
    notification_executor: Executor,
) -> None:
    run_at = datetime(2027, 1, 10, 4, 0, tzinfo=UTC)
    ids = await _seed_base(run_at)
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "INSERT INTO applications (job_id, enrollment_id, status, "
                    "resume_url, profile_snapshot, applied_at) VALUES "
                    "(:job, :enrollment, 'in_progress', :url, '{}'::jsonb, :now)"
                ),
                {
                    "job": ids["job"],
                    "enrollment": ids["enrollment"],
                    "url": DRIVE_URL,
                    "now": run_at,
                },
            )
    finally:
        await engine.dispose()
    result = await notification_executor.run(
        "send_deadline_reminders",
        SendDeadlineRemindersInput(run_at=run_at),
        SYSTEM,
    )
    assert result.summary["queued"] == 0


async def _seed_round_states(run_at: datetime) -> dict[str, UUID]:
    ids = await _seed_base(run_at)
    ids.update({key: uuid4() for key in ("round_type", "round", "application", "state")})
    rejected_user, rejected_enrollment, rejected_membership = uuid4(), uuid4(), uuid4()
    ids["rejected_enrollment"] = rejected_enrollment
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "INSERT INTO round_types (id, name, is_active) "
                    "VALUES (:id, 'Reminder Interview', true)"
                ),
                {"id": ids["round_type"]},
            )
            # The default is outside the window; the per-student override is in
            # it, directly proving override -> round-default resolution.
            await connection.execute(
                sa.text(
                    "INSERT INTO job_rounds (id, job_id, round_type_id, name, ord, "
                    "venue, scheduled_at) VALUES "
                    "(:id, :job, :type, 'Technical Interview', 1, 'Default Hall', :default)"
                ),
                {
                    "id": ids["round"],
                    "job": ids["job"],
                    "type": ids["round_type"],
                    "default": run_at + timedelta(hours=60),
                },
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO applications (id, job_id, enrollment_id, status, "
                    "current_round_id, resume_url, profile_snapshot, applied_at) "
                    "VALUES (:id, :job, :enrollment, 'in_progress', :round, :url, "
                    "'{}'::jsonb, :now)"
                ),
                {
                    "id": ids["application"],
                    "job": ids["job"],
                    "enrollment": ids["enrollment"],
                    "round": ids["round"],
                    "url": DRIVE_URL,
                    "now": run_at,
                },
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO application_round_states "
                    "(id, application_id, round_id, result, attendance, "
                    "venue_override, scheduled_at_override) VALUES "
                    "(:id, :application, :round, 'pending', 'pending', "
                    "'Student Hall', :scheduled)"
                ),
                {
                    "id": ids["state"],
                    "application": ids["application"],
                    "round": ids["round"],
                    "scheduled": run_at + timedelta(hours=24),
                },
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO users (id, email, full_name, role) VALUES "
                    "(:id, 'rejected.student@example.edu', 'Rejected Student', 'student')"
                ),
                {"id": rejected_user},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO enrollments (id, user_id, is_current) VALUES (:id, :user, true)"
                ),
                {"id": rejected_enrollment, "user": rejected_user},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO cycle_memberships (id, cycle_id, enrollment_id, status) "
                    "VALUES (:id, :cycle, :enrollment, 'active')"
                ),
                {
                    "id": rejected_membership,
                    "cycle": ids["cycle"],
                    "enrollment": rejected_enrollment,
                },
            )
            rejected_application, rejected_state = uuid4(), uuid4()
            await connection.execute(
                sa.text(
                    "INSERT INTO applications (id, job_id, enrollment_id, status, "
                    "current_round_id, resume_url, profile_snapshot, applied_at) "
                    "VALUES (:id, :job, :enrollment, 'rejected', :round, :url, "
                    "'{}'::jsonb, :now)"
                ),
                {
                    "id": rejected_application,
                    "job": ids["job"],
                    "enrollment": rejected_enrollment,
                    "round": ids["round"],
                    "url": DRIVE_URL,
                    "now": run_at,
                },
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO application_round_states "
                    "(id, application_id, round_id, result, attendance, "
                    "scheduled_at_override) VALUES "
                    "(:id, :application, :round, 'eliminated', 'present', :scheduled)"
                ),
                {
                    "id": rejected_state,
                    "application": rejected_application,
                    "round": ids["round"],
                    "scheduled": run_at + timedelta(hours=24),
                },
            )
    finally:
        await engine.dispose()
    return ids


@pytest.mark.asyncio
async def test_RND4_NTF_round_cron_twice_sends_once_and_rejected_gets_nothing(
    notification_executor: Executor,
) -> None:
    run_at = datetime(2027, 1, 10, 6, 0, tzinfo=UTC)
    await _seed_round_states(run_at)
    first = await notification_executor.run(
        "send_round_reminders", SendRoundRemindersInput(run_at=run_at), SYSTEM
    )
    second = await notification_executor.run(
        "send_round_reminders", SendRoundRemindersInput(run_at=run_at), SYSTEM
    )
    sends, queued, jobs = await _counts()
    assert first.summary["queued"] == 1
    assert second.summary["queued"] == 0
    assert (sends, queued) == (1, 1)
    assert jobs[0]["recipient"] == "eligible.student@example.edu"
    context = cast(dict[str, object], jobs[0]["context"])
    assert context["venue"] == "Student Hall"
    assert context["round"] == "Technical Interview"
