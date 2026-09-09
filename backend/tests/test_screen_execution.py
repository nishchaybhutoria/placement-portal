"""Every registered screen must actually run (LLD section 11.3).

M9 found four screens that raised before returning a row -- an f-string had
eaten a `{filter}` placeholder, and a query named a column the table does not
have.  Nothing caught it, because the authz matrix and the preview-parity
harness both stop at the route: neither ever calls a screen's handler, so a
screen can be entirely broken and still pass every other suite.

This module closes that gap and keeps it closed.  ``test_every_screen_executes``
is parametrized over the *registry*, not over a list written here, so a screen
added in M10-M15 without a fixture fails immediately with a message saying what
to add.  The per-screen assertions below it are the shape checks: executing is
the floor, not the goal.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.bootstrap import build_registry
from app.core.db import create_engine
from app.main import create_app
from app.modules.identity.session import hash_session_token
from app.settings import Settings
from tests.notifications.seed_defaults import restore_migration_defaults

ADMIN_TOKEN = "screen-sweep-admin-token"
STAFF_TOKEN = "screen-sweep-staff-token"
STUDENT_TOKEN = "screen-sweep-student-token"
DRIVE_URL = "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view"


def screen_settings() -> Settings:
    return Settings(
        session_secret="screen-sweep-session-secret-32-characters",
        dev_login=False,
    )


@dataclass(frozen=True, slots=True)
class World:
    """Ids of the seeded fixture, for building each screen's path."""

    cycle_id: UUID
    job_id: UUID
    company_id: UUID
    program_id: UUID
    student_enrollment_id: UUID


@dataclass(frozen=True, slots=True)
class Case:
    """How to call one screen, and the least its body must contain."""

    token: str
    path: str
    expect_keys: tuple[str, ...] = ()
    #: Dotted paths into the body that the fixture populates, so an empty one
    #: means the query ran but matched nothing -- a silently wrong WHERE clause.
    expect_nonempty: tuple[str, ...] = ()
    query: dict[str, str] = field(default_factory=dict)


def cases(world: World) -> dict[str, Case]:
    """One entry per registered screen id. Adding a screen means adding one."""
    return {
        "admin/taxonomies": Case(
            ADMIN_TOKEN,
            "admin/taxonomies",
            expect_keys=("programs", "branches", "sectors", "round_types"),
            expect_nonempty=("programs", "branches", "sectors", "program_branches"),
        ),
        # The same lists under the id the JOB-1 builder reads, which a
        # coordinator must be able to open.
        "staff/taxonomies": Case(
            STAFF_TOKEN,
            "staff/taxonomies",
            expect_keys=("programs", "branches", "sectors", "round_types"),
            expect_nonempty=("programs", "branches", "sectors", "program_branches"),
        ),
        "admin/settings": Case(
            ADMIN_TOKEN,
            "admin/settings",
            expect_keys=("settings",),
            expect_nonempty=("settings",),
        ),
        "admin/users": Case(
            ADMIN_TOKEN,
            "admin/users",
            expect_keys=("filters", "users", "counts"),
            expect_nonempty=("users", "counts"),
        ),
        "admin/templates": Case(
            ADMIN_TOKEN,
            "admin/templates",
            expect_keys=("templates", "cycles", "dead_letters"),
            expect_nonempty=("templates", "cycles"),
        ),
        "admin/discipline": Case(
            ADMIN_TOKEN,
            "admin/discipline",
            expect_keys=("threshold", "roster", "student"),
            expect_nonempty=("roster", "student", "student.strikes", "student.penalties"),
            query={"enrollment_id": str(world.student_enrollment_id)},
        ),
        "admin/overrides": Case(
            ADMIN_TOKEN,
            "admin/overrides",
            expect_keys=("overrides", "filters", "rule_domains", "cycles", "counts"),
            expect_nonempty=("overrides", "rule_domains", "scopes", "states", "cycles"),
        ),
        "admin/findings": Case(
            ADMIN_TOKEN,
            "admin/findings",
            expect_keys=(
                "findings",
                "filters",
                "statuses",
                "invariants",
                "counts",
                "actions",
            ),
            expect_nonempty=("findings", "statuses", "invariants", "actions"),
        ),
        "staff/student/{enrollment_id}": Case(
            STAFF_TOKEN,
            f"staff/student/{world.student_enrollment_id}",
            expect_keys=(
                "enrollment",
                "enrollments",
                "memberships",
                "applications",
                "offers",
                "external_offers",
                "discipline",
                "audit",
                "timeline",
                "profile",
                "actions",
            ),
            # The timeline and the audit trail are the two joins this screen
            # exists for, so an empty one is the failure worth catching.
            expect_nonempty=(
                "enrollment",
                "enrollments",
                "memberships",
                "applications",
                "offers",
                "external_offers",
                "discipline.strikes",
                "discipline.penalties",
                "audit",
                "timeline",
                "actions",
                # The INT-1 correction dialog offers taxonomy choices, so an
                # empty list is a form that can only clear a program.
                "profile.taxonomies",
                "profile.program_branches",
            ),
        ),
        "admin/bulk-upsert": Case(
            ADMIN_TOKEN,
            "admin/bulk-upsert",
            expect_keys=("columns", "email_column", "staged"),
            expect_nonempty=("columns",),
        ),
        "me/profile": Case(
            STUDENT_TOKEN,
            "me/profile",
            expect_keys=("enrollment", "fields", "values", "resumes", "declared_at"),
            expect_nonempty=("enrollment", "fields", "values", "resumes"),
        ),
        "staff/job/{id}/board": Case(
            ADMIN_TOKEN,
            f"staff/job/{world.job_id}/board",
            expect_keys=("job", "cycle", "rounds", "columns", "settled", "counts"),
            # `columns` proves the rounds joined; `settled` would be empty if
            # the fixture's one application were mis-grouped, so both are
            # populated deliberately -- the world seeds a pipeline row and the
            # board must place it in a column, leaving settled empty. Only the
            # populated paths are asserted non-empty.
            expect_nonempty=("job", "cycle", "rounds", "columns", "counts"),
        ),
        "staff/job/{id}/offers": Case(
            ADMIN_TOKEN,
            f"staff/job/{world.job_id}/offers",
            expect_keys=("job", "cycle", "applications", "counts", "actions"),
            expect_nonempty=("job", "cycle", "applications", "counts", "actions"),
        ),
        "staff/external": Case(
            STAFF_TOKEN,
            "staff/external",
            expect_keys=("filters", "actions", "companies", "enrollments", "offers"),
            expect_nonempty=("actions", "companies", "enrollments", "offers"),
        ),
        "staff/cycle/{id}/external": Case(
            STAFF_TOKEN,
            f"staff/cycle/{world.cycle_id}/external",
            expect_keys=("cycle", "policy", "attached", "unattached_pool"),
            expect_nonempty=("cycle", "policy", "unattached_pool"),
        ),
        "me/dashboard": Case(
            STUDENT_TOKEN,
            "me/dashboard",
            expect_keys=(
                "enrollment_id",
                "memberships",
                "applications",
                "upcoming_rounds",
                "offers",
                "external_offers",
                "discipline",
            ),
            expect_nonempty=(
                "enrollment_id",
                "memberships",
                "applications",
                "offers",
                "external_offers",
                "discipline",
            ),
        ),
        "me/applications": Case(
            STUDENT_TOKEN,
            "me/applications",
            expect_keys=("applications", "counts", "enrollment_id"),
            expect_nonempty=("applications", "counts", "enrollment_id"),
        ),
        # The seed delivers nothing, so the list is legitimately empty here:
        # what this case proves is that the screen executes for a student and
        # answers in its own shape (LLD section 18).
        "me/notifications": Case(
            STUDENT_TOKEN,
            "me/notifications",
            expect_keys=("notifications",),
        ),
        "cycles/joinable": Case(
            STUDENT_TOKEN,
            "cycles/joinable",
            expect_keys=("cycles", "profile_complete", "required_fields"),
            expect_nonempty=("cycles", "required_fields"),
        ),
        "staff/cycles": Case(
            STAFF_TOKEN,
            "staff/cycles",
            expect_keys=("cycles", "filters"),
            expect_nonempty=("cycles",),
        ),
        "staff/cycle/{id}": Case(
            STAFF_TOKEN,
            f"staff/cycle/{world.cycle_id}",
            expect_keys=("cycle", "policy", "coordinators", "memberships"),
            expect_nonempty=("cycle", "policy", "coordinators", "memberships"),
        ),
        "staff/cycle/{id}/analytics": Case(
            STAFF_TOKEN,
            f"staff/cycle/{world.cycle_id}/analytics",
            expect_keys=(
                "cycle",
                "funnel",
                "compensation",
                "breakdowns",
                "top_companies",
                "timeline",
                "discipline",
                "pending_approvals",
                "export_columns",
            ),
            expect_nonempty=(
                "cycle",
                "funnel.registered",
                "funnel.applied",
                "funnel.offered",
                "funnel.placed.total",
                # The external half of ANA-1's split, specifically: a fixture
                # whose placed figure is all on-portal cannot distinguish a
                # working attachment scope from one that drops externals.
                "funnel.placed.split.portal",
                "funnel.placed.split.external",
                "funnel.placed.external_sources.ppo",
                "compensation.placement.covered",
                "breakdowns.program",
                "breakdowns.branch",
                "breakdowns.gender",
                "top_companies",
                "timeline",
            ),
        ),
        "staff/job/{id}/analytics": Case(
            STAFF_TOKEN,
            f"staff/job/{world.job_id}/analytics",
            expect_keys=(
                "job",
                "shape",
                "funnel",
                "statuses",
                "compensation",
                "rounds",
                "export_columns",
            ),
            expect_nonempty=(
                "job",
                "shape",
                "funnel.applied",
                "statuses",
                "rounds",
                "export_columns",
            ),
        ),
        "admin/analytics/portal": Case(
            ADMIN_TOKEN,
            "admin/analytics/portal",
            expect_keys=(
                "years",
                "overall",
                "participation",
                "program_mix",
                "sector_mix",
                "portal_wide_placed",
                "canned_report",
            ),
            expect_nonempty=(
                "years",
                "overall.registered",
                "overall.placed.total",
                "overall.placed.split.external",
                "participation",
                "program_mix",
                "portal_wide_placed.split.external",
                "canned_report.columns",
                "canned_report.rows",
                "canned_report.note",
            ),
        ),
        "staff/cycle/{id}/approvals": Case(
            STAFF_TOKEN,
            f"staff/cycle/{world.cycle_id}/approvals",
            expect_keys=("cycle", "rows", "filters", "statuses"),
            expect_nonempty=("cycle", "statuses"),
        ),
        "staff/companies": Case(
            STAFF_TOKEN,
            "staff/companies",
            expect_keys=("companies", "sectors", "filters"),
            expect_nonempty=("companies", "sectors"),
        ),
        "staff/company/{id}": Case(
            STAFF_TOKEN,
            f"staff/company/{world.company_id}",
            expect_keys=("company", "contacts", "jobs", "analytics"),
            expect_nonempty=(
                "company",
                "contacts",
                "jobs",
                "analytics.totals.jobs",
                "analytics.totals.applicants",
                "analytics.totals.placed.total",
                "analytics.hires_by_program",
                "analytics.compensation_history",
                "analytics.external_offers",
            ),
        ),
        "staff/cycle/{id}/jobs": Case(
            STAFF_TOKEN,
            f"staff/cycle/{world.cycle_id}/jobs",
            expect_keys=("cycle", "jobs", "filters"),
            expect_nonempty=("cycle", "jobs"),
        ),
        "staff/job/{id}/builder": Case(
            STAFF_TOKEN,
            f"staff/job/{world.job_id}/builder",
            expect_keys=("cycle", "job", "eligibility", "cancellation_preview"),
            expect_nonempty=(
                "cycle",
                "job",
                "job.rounds",
                "job.questions",
                "job.program_ctc",
                "eligibility.impact.members",
            ),
            query={"cycle_id": str(world.cycle_id)},
        ),
        "cycle/{id}/jobs": Case(
            STUDENT_TOKEN,
            f"cycle/{world.cycle_id}/jobs",
            expect_keys=("cycle", "jobs", "eligible_count", "membership_status"),
            expect_nonempty=("cycle", "jobs"),
        ),
        "job/{id}": Case(
            STUDENT_TOKEN,
            f"job/{world.job_id}",
            expect_keys=(
                "job",
                "compensation",
                "eligibility",
                "rounds",
                "apply_form",
            ),
            expect_nonempty=(
                "job",
                "compensation",
                "eligibility",
                "rounds",
                "apply_form.questions",
            ),
        ),
    }


def case_for(screen_id: str, world: World) -> Case:
    """The fixture for one screen, or the message telling you to write it."""
    catalogue = cases(world)
    assert screen_id in catalogue, (
        f"Screen {screen_id!r} is registered but has no execution fixture. Add a "
        "Case for it to cases() in tests/test_screen_execution.py -- a screen "
        "that is never executed against real data can be entirely broken and "
        "still pass every other suite, which is how M9 shipped four screens "
        "that raised before returning a row."
    )
    return catalogue[screen_id]


def resolve(body: object, path: str) -> object:
    """Walk a dotted path into a screen body, for the non-empty assertions."""
    current = body
    for part in path.split("."):
        assert isinstance(current, dict), f"{path}: {part} is not under a mapping"
        assert part in current, f"{path}: no {part!r} in {sorted(current)}"
        current = current[part]
    return current


async def _session(connection: AsyncConnection, user_id: UUID, token: str) -> None:
    await connection.execute(
        sa.text(
            "INSERT INTO sessions (id, token_hash, user_id, expires_at) "
            "VALUES (:id, :hash, :user_id, now() + interval '1 day')"
        ),
        {
            "id": uuid4(),
            "hash": hash_session_token(token, screen_settings().session_secret),
            "user_id": user_id,
        },
    )


async def _person(
    connection: AsyncConnection, *, email: str, name: str, role: str, token: str
) -> tuple[UUID, UUID]:
    user_id, enrollment_id = uuid4(), uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO users (id, email, full_name, role) "
            "VALUES (:id, :email, :name, CAST(:role AS role_t))"
        ),
        {"id": user_id, "email": email, "name": name, "role": role},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO enrollments (id, user_id, is_current, roll_number) "
            "VALUES (:id, :user_id, true, :roll)"
        ),
        {"id": enrollment_id, "user_id": user_id, "roll": str(uuid4())[:8]},
    )
    await _session(connection, user_id, token)
    return user_id, enrollment_id


async def _seed_world() -> World:
    """A world with one of everything the fourteen screens read."""
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text("DELETE FROM notification_templates WHERE cycle_id IS NOT NULL")
            )
            await connection.execute(
                sa.text(
                    "TRUNCATE audit_log, idempotency_keys, notification_log, "
                    "consistency_findings, overrides, "
                    "strikes, penalties, application_events, application_answers, "
                    "application_round_states, applications, offers, "
                    "export_presets, job_question_options, job_questions, "
                    "job_program_ctc, job_rounds, jobs, "
                    "cycle_memberships, cycle_coordinators, cycle_policies, "
                    "resumes, profiles, sessions, enrollments, users, companies, "
                    "company_contacts, staged_profile_rows, settings, "
                    "programs, branches, minors, sectors, round_types, "
                    "procrastinate_jobs CASCADE"
                )
            )
            await connection.execute(sa.text("DELETE FROM cycles"))
            await restore_migration_defaults(connection)
            admin_id, _admin_enrollment = await _person(
                connection,
                email="admin@example.edu",
                name="Screen Admin",
                role="admin",
                token=ADMIN_TOKEN,
            )
            # There is no "staff" role: a coordinator is an ordinary user with
            # a cycle_coordinators row, which is what check_screen reads.
            staff_id, _staff_enrollment = await _person(
                connection,
                email="coord@example.edu",
                name="Screen Coordinator",
                role="student",
                token=STAFF_TOKEN,
            )
            _student_id, student_enrollment_id = await _person(
                connection,
                email="asha@example.edu",
                name="Asha Screen",
                role="student",
                token=STUDENT_TOKEN,
            )

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
            sector_id = uuid4()
            await connection.execute(
                sa.text(
                    "INSERT INTO sectors (id, name, is_active) VALUES (:id, 'Technology', true)"
                ),
                {"id": sector_id},
            )
            round_type_id = uuid4()
            await connection.execute(
                sa.text(
                    "INSERT INTO round_types (id, name, is_active) "
                    "VALUES (:id, 'Technical Interview', true)"
                ),
                {"id": round_type_id},
            )

            resume_id = uuid4()
            await connection.execute(
                sa.text(
                    "INSERT INTO profiles (id, enrollment_id, program_id, "
                    "primary_branch_id, graduating_year, cpi, active_backlogs, "
                    "total_backlogs, gender, personal_email, contact_number, "
                    "nationality, tenth_percent, tenth_year, twelfth_percent, "
                    "twelfth_year, declared_at) VALUES (:id, :enrollment_id, "
                    ":program_id, :branch_id, 2026, 8.40, 0, 0, 'female', "
                    "'asha@example.com', '+1 202-555-0100', 'IN', 92.00, 2019, "
                    "94.00, 2021, now())"
                ),
                {
                    "id": uuid4(),
                    "enrollment_id": student_enrollment_id,
                    "program_id": program_id,
                    "branch_id": branch_id,
                },
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO resumes (id, enrollment_id, label, drive_url, "
                    "is_default) VALUES (:id, :enrollment_id, 'Primary', :url, true)"
                ),
                {"id": resume_id, "enrollment_id": student_enrollment_id, "url": DRIVE_URL},
            )

            cycle_id = uuid4()
            await connection.execute(
                sa.text(
                    "INSERT INTO cycles (id, name, kind, is_active, "
                    "registration_opens_at, registration_closes_at) VALUES "
                    "(:id, 'Placement 2026', CAST('placement' AS cycle_kind_t), true, "
                    "now() - interval '1 day', now() + interval '30 days')"
                ),
                {"id": cycle_id},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO cycle_policies (id, cycle_id, "
                    "membership_requires_approval, max_accepted_offers, "
                    "penalty_blocks_applications, allow_withdrawal_after_deadline, "
                    "allow_edit_after_deadline, strike_on_absence) "
                    "VALUES (:id, :cycle_id, true, 1, true, false, false, true)"
                ),
                {"id": uuid4(), "cycle_id": cycle_id},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO cycle_coordinators (id, cycle_id, user_id) "
                    "VALUES (:id, :cycle_id, :user_id)"
                ),
                {"id": uuid4(), "cycle_id": cycle_id, "user_id": staff_id},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO cycle_memberships (id, cycle_id, enrollment_id, "
                    "status, default_resume_id, consented_at) VALUES "
                    "(:id, :cycle_id, :enrollment_id, "
                    "CAST('active' AS membership_status_t), :resume_id, now())"
                ),
                {
                    "id": uuid4(),
                    "cycle_id": cycle_id,
                    "enrollment_id": student_enrollment_id,
                    "resume_id": resume_id,
                },
            )

            await connection.execute(
                sa.text(
                    "INSERT INTO settings (key, value) VALUES "
                    "('notification_from_name', CAST('\"CDS Office\"' AS jsonb))"
                ),
            )
            # The admin discipline screen needs both halves populated. These
            # rows also prove that its strike and penalty counts do not multiply
            # one another through a fan-out join.
            await connection.execute(
                sa.text(
                    "INSERT INTO strikes (id, enrollment_id, reason, source, "
                    "awarded_by, is_active) VALUES (:id, :enrollment_id, "
                    "'Missed the screening round', 'manual', :admin_id, true)"
                ),
                {
                    "id": uuid4(),
                    "enrollment_id": student_enrollment_id,
                    "admin_id": admin_id,
                },
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO penalties (id, enrollment_id, reasons, from_strikes, "
                    "created_by, is_active) VALUES (:id, :enrollment_id, "
                    "'Repeated no-shows', false, :admin_id, true)"
                ),
                {
                    "id": uuid4(),
                    "enrollment_id": student_enrollment_id,
                    "admin_id": admin_id,
                },
            )

            company_id = uuid4()
            await connection.execute(
                sa.text(
                    "INSERT INTO companies (id, name, sector_id, is_active) "
                    "VALUES (:id, 'Acme Corp', :sector_id, true)"
                ),
                {"id": company_id, "sector_id": sector_id},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO company_contacts (id, company_id, name, email, "
                    "is_primary) VALUES (:id, :company_id, 'Rita Rao', "
                    "'rita@acme.example', true)"
                ),
                {"id": uuid4(), "company_id": company_id},
            )

            job_id = uuid4()
            await connection.execute(
                sa.text(
                    "INSERT INTO jobs (id, cycle_id, company_id, sector_id, outcome, "
                    "title, description, ctc_lpa, is_published, published_at, "
                    "application_deadline, eligibility_rule, eligibility_summary) "
                    "VALUES (:id, :cycle_id, :company_id, :sector_id, "
                    "CAST('placement' AS outcome_t), 'Backend Engineer', "
                    "'Builds the thing.', 18.00, true, now(), "
                    "now() + interval '20 days', "
                    "CAST(:rule AS jsonb), :summary)"
                ),
                {
                    "id": job_id,
                    "cycle_id": cycle_id,
                    "company_id": company_id,
                    "sector_id": sector_id,
                    "rule": '{"field": "cpi", "op": "gte", "value": 8.0}',
                    "summary": "Eligible when CPI at least 8.0.",
                },
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO job_rounds (id, job_id, round_type_id, ord, name) "
                    "VALUES (:id, :job_id, :round_type_id, 1, 'Screening')"
                ),
                {"id": uuid4(), "job_id": job_id, "round_type_id": round_type_id},
            )
            round_id = uuid4()
            await connection.execute(
                sa.text(
                    "INSERT INTO job_rounds (id, job_id, round_type_id, ord, name) "
                    "VALUES (:id, :job_id, :round_type_id, 2, 'Interview')"
                ),
                {"id": round_id, "job_id": job_id, "round_type_id": round_type_id},
            )
            # One live application, sitting in a round: me/applications has to
            # report a position, a window, and a timeline, and every one of
            # those is a different join.
            application_id = uuid4()
            await connection.execute(
                sa.text(
                    "INSERT INTO applications (id, job_id, enrollment_id, status, "
                    "current_round_id, resume_url, profile_snapshot, applied_at) "
                    "VALUES (:id, :job_id, :enrollment_id, 'in_progress', :round_id, "
                    ":url, CAST('{}' AS jsonb), now())"
                ),
                {
                    "id": application_id,
                    "job_id": job_id,
                    "enrollment_id": student_enrollment_id,
                    "round_id": round_id,
                    "url": DRIVE_URL,
                },
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO application_events (id, application_id, event_type, "
                    "to_status, payload) VALUES (:id, :application_id, "
                    "CAST('created' AS event_type_t), 'in_progress', "
                    "CAST('{}' AS jsonb))"
                ),
                {"id": uuid4(), "application_id": application_id},
            )
            # A second job gives the dashboard a current actionable offer while
            # the first application remains in-round for the board fixtures.
            offer_job_id, offer_application_id, offer_id = uuid4(), uuid4(), uuid4()
            await connection.execute(
                sa.text(
                    "INSERT INTO jobs (id, cycle_id, company_id, outcome, title, "
                    "description, application_deadline, offer_acceptance_deadline) "
                    "VALUES (:id, :cycle, :company, 'placement', 'Offer Fixture', "
                    "'Dashboard offer', now() + interval '20 days', "
                    "now() + interval '40 days')"
                ),
                {"id": offer_job_id, "cycle": cycle_id, "company": company_id},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO applications (id, job_id, enrollment_id, status, "
                    "resume_url, profile_snapshot, applied_at) VALUES "
                    "(:id, :job, :enrollment, 'offered', :url, '{}'::jsonb, now())"
                ),
                {
                    "id": offer_application_id,
                    "job": offer_job_id,
                    "enrollment": student_enrollment_id,
                    "url": DRIVE_URL,
                },
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO offers (id, application_id, extended_at, deadline_at) "
                    "VALUES (:id, :application, now(), now() + interval '40 days')"
                ),
                {"id": offer_id, "application": offer_application_id},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO external_offers (id, enrollment_id, company_id, "
                    "outcome, source, status, offered_on, created_by) VALUES "
                    "(:id, :enrollment, :company, 'placement', 'ppo', 'offered', "
                    "CURRENT_DATE, :admin)"
                ),
                {
                    "id": uuid4(),
                    "enrollment": student_enrollment_id,
                    "company": company_id,
                    "admin": admin_id,
                },
            )
            # M15: the analytics screens need a real *placed* figure, and one
            # with a non-zero external half -- a dashboard fixture whose split
            # is all zeroes cannot tell a working query from a broken one.
            # Two more students: one accepted on the portal, one carrying an
            # accepted PPO external attached to this cycle.
            for label, email, external in (
                ("Placed Portal", "placed-portal@example.edu", False),
                ("Placed External", "placed-external@example.edu", True),
            ):
                placed_user_id, placed_enrollment_id = await _person(
                    connection,
                    email=email,
                    name=label,
                    role="student",
                    token=f"screen-sweep-{email}",
                )
                await connection.execute(
                    sa.text(
                        "INSERT INTO profiles (id, enrollment_id, program_id, "
                        "primary_branch_id, graduating_year, gender, cpi, "
                        "declared_at) VALUES (:id, :enrollment, :program, :branch, "
                        "2026, 'female', 8.10, now())"
                    ),
                    {
                        "id": uuid4(),
                        "enrollment": placed_enrollment_id,
                        "program": program_id,
                        "branch": branch_id,
                    },
                )
                await connection.execute(
                    sa.text(
                        "INSERT INTO cycle_memberships (id, cycle_id, enrollment_id, "
                        "status, consented_at) VALUES (:id, :cycle, :enrollment, "
                        "'active', now())"
                    ),
                    {
                        "id": uuid4(),
                        "cycle": cycle_id,
                        "enrollment": placed_enrollment_id,
                    },
                )
                if external:
                    await connection.execute(
                        sa.text(
                            "INSERT INTO external_offers (id, enrollment_id, "
                            "company_id, outcome, source, status, ctc_lpa, offered_on, "
                            "responded_on, attached_cycle_id, created_by) VALUES "
                            "(:id, :enrollment, :company, 'placement', 'ppo', "
                            "'accepted', 27.50, CURRENT_DATE, CURRENT_DATE, :cycle, "
                            ":admin)"
                        ),
                        {
                            "id": uuid4(),
                            "enrollment": placed_enrollment_id,
                            "company": company_id,
                            "cycle": cycle_id,
                            "admin": admin_id,
                        },
                    )
                    continue
                placed_application_id, placed_offer_id = uuid4(), uuid4()
                await connection.execute(
                    sa.text(
                        "INSERT INTO applications (id, job_id, enrollment_id, status, "
                        "resume_url, profile_snapshot, applied_at) VALUES "
                        "(:id, :job, :enrollment, 'accepted', :url, "
                        "jsonb_build_object('program_id', CAST(:program AS text)), now())"
                    ),
                    {
                        "id": placed_application_id,
                        "job": offer_job_id,
                        "enrollment": placed_enrollment_id,
                        "url": DRIVE_URL,
                        "program": str(program_id),
                    },
                )
                await connection.execute(
                    sa.text(
                        "INSERT INTO offers (id, application_id, extended_at, "
                        "response, responded_at) VALUES (:id, :application, now(), "
                        "'accepted', now())"
                    ),
                    {"id": placed_offer_id, "application": placed_application_id},
                )
                del placed_user_id

            # M14: an override for the register, a finding for the findings
            # screen, and an audit row so the drill-down's trail is not empty --
            # the trail is the only place an off-campus record shows up at all.
            await connection.execute(
                sa.text(
                    "INSERT INTO overrides (id, rule_domain, allow, cycle_id, reason, "
                    "granted_by, is_active) VALUES (:id, 'application_deadline', true, "
                    ":cycle, 'Late window for the screen fixture', :admin, true)"
                ),
                {"id": uuid4(), "cycle": cycle_id, "admin": admin_id},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO consistency_findings (id, invariant, subject, detail, "
                    "status, suggested_fix) VALUES (:id, "
                    "'no_live_application_without_active_membership', "
                    "CAST(:subject AS jsonb), 'Screen fixture finding', 'open', "
                    "'restore_membership')"
                ),
                {
                    "id": uuid4(),
                    "subject": (
                        f'{{"application_id": "{application_id}", '
                        f'"cycle_id": "{cycle_id}"}}'
                    ),
                },
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO audit_log (id, actor_user_id, action, subject_type, "
                    "subject_id, details) VALUES (:id, :admin, 'create_external_offer', "
                    "'enrollment', :enrollment, CAST('{}' AS jsonb))"
                ),
                {"id": uuid4(), "admin": admin_id, "enrollment": student_enrollment_id},
            )
            question_id = uuid4()
            await connection.execute(
                sa.text(
                    "INSERT INTO job_questions (id, job_id, ord, text, qtype, required) "
                    "VALUES (:id, :job_id, 1, 'Preferred location?', "
                    "CAST('single' AS question_type_t), true)"
                ),
                {"id": question_id, "job_id": job_id},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO job_question_options (id, question_id, ord, text) "
                    "VALUES (:id, :question_id, 1, 'Bengaluru')"
                ),
                {"id": uuid4(), "question_id": question_id},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO job_program_ctc (id, job_id, program_id, ctc_lpa) "
                    "VALUES (:id, :job_id, :program_id, 21.00)"
                ),
                {"id": uuid4(), "job_id": job_id, "program_id": program_id},
            )
    finally:
        await engine.dispose()
    return World(
        cycle_id=cycle_id,
        job_id=job_id,
        company_id=company_id,
        program_id=program_id,
        student_enrollment_id=student_enrollment_id,
    )


@pytest_asyncio.fixture(scope="module")
async def world() -> World:
    return await _seed_world()


async def _get(case: Case) -> httpx.Response:
    application = create_app(os.environ["TEST_DATABASE_URL"], settings=screen_settings())
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
            client.cookies.set("cds_session", case.token)
            return await client.get(
                f"/api/v1/screens/{case.path}",
                params=case.query or None,
            )


def _registered_screen_ids() -> list[str]:
    return sorted(build_registry(settings=screen_settings()).screens)


@pytest.mark.parametrize("screen_id", _registered_screen_ids())
@pytest.mark.asyncio
async def test_every_screen_executes(screen_id: str, world: World) -> None:
    """The ratchet: no registered screen may ship without being executed.

    Parametrized over the registry rather than a list, so a new screen fails
    here until it is given a fixture -- which is the point.  A screen whose
    query does not run is worth nothing, and the authz suites never call one.
    """
    case = case_for(screen_id, world)

    response = await _get(case)

    assert response.status_code == 200, (
        f"{screen_id} returned {response.status_code}: {response.text[:400]}"
    )
    body: Any = response.json()
    assert isinstance(body, dict)
    missing = [key for key in case.expect_keys if key not in body]
    assert not missing, f"{screen_id} is missing {missing} from {sorted(body)}"


@pytest.mark.parametrize("screen_id", _registered_screen_ids())
@pytest.mark.asyncio
async def test_every_screen_returns_the_seeded_data(screen_id: str, world: World) -> None:
    """Executing is the floor; a screen must also find what the fixture seeded.

    A 200 with an empty envelope is the other way a screen fails silently -- a
    join or a WHERE clause that matches nothing raises nothing, and every
    assertion about "the shape" still passes.  The world seeds one of
    everything, so any listed path coming back empty is a real defect.
    """
    case = case_for(screen_id, world)

    response = await _get(case)
    body: Any = response.json()

    empty = [path for path in case.expect_nonempty if not resolve(body, path)]
    assert not empty, (
        f"{screen_id} returned 200 but {empty} came back empty, although the "
        "fixture seeds a row for each. The query ran and matched nothing."
    )


def test_the_fixture_table_names_no_screen_that_no_longer_exists() -> None:
    """The other side of the ratchet: a deleted screen must not leave a case.

    Without this the table quietly accumulates entries for screens that were
    renamed or removed, and the next reader cannot tell which are real.
    """
    placeholder = World(
        cycle_id=uuid4(),
        job_id=uuid4(),
        company_id=uuid4(),
        program_id=uuid4(),
        student_enrollment_id=uuid4(),
    )
    stale = sorted(set(cases(placeholder)) - set(_registered_screen_ids()))
    assert not stale, f"cases() names screens that are not registered: {stale}"


#: The staff screens that name a cycle, and how to address a *different* one.
#: `roles=("staff",)` only asks whether the caller coordinates something, so
#: each of these has to ask which cycle for itself (CONTRIBUTING.md invariant 8).
CYCLE_SCOPED_STAFF_SCREENS = (
    "staff/cycle/{cycle}",
    "staff/cycle/{cycle}/approvals",
    "staff/cycle/{cycle}/jobs",
    "staff/cycle/{cycle}/analytics",
    "staff/cycle/{cycle}/external",
)


@pytest.mark.asyncio
async def test_a_coordinator_cannot_read_a_cycle_they_do_not_coordinate(
    world: World,
) -> None:
    """The screen half of IDN-3: staff of *a* cycle is not staff of every cycle."""
    other_cycle = uuid4()
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "INSERT INTO cycles (id, name, kind, is_active) "
                    "VALUES (:id, 'Someone Else''s Cycle', 'internship', true)"
                ),
                {"id": other_cycle},
            )
            # No policy row on purpose: every one of these screens must refuse
            # before it reads anything, so a cycle it could not render is still
            # a 403 and never a 500.
    finally:
        await engine.dispose()

    denied = {}
    for template in CYCLE_SCOPED_STAFF_SCREENS:
        response = await _get(
            Case(STAFF_TOKEN, template.format(cycle=other_cycle))
        )
        denied[template] = response.status_code

    assert set(denied.values()) == {403}, denied


@pytest.mark.asyncio
async def test_a_coordinator_sees_only_the_cycles_they_coordinate(
    world: World,
) -> None:
    """A list offering a row that 403s on click is worse than no row."""
    unlisted = uuid4()
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "INSERT INTO cycles (id, name, kind, is_active) "
                    "VALUES (:id, 'Unlisted Cycle', 'internship', true)"
                ),
                {"id": unlisted},
            )
    finally:
        await engine.dispose()

    staff: Any = (await _get(Case(STAFF_TOKEN, "staff/cycles"))).json()
    admin: Any = (await _get(Case(ADMIN_TOKEN, "staff/cycles"))).json()

    assert [row["id"] for row in staff["cycles"]] == [str(world.cycle_id)]
    assert str(unlisted) in {row["id"] for row in admin["cycles"]}
