"""Seed an entirely synthetic cast for the full lifecycle rehearsal.

``python -m app.mock_seed`` builds eleven numbered demo students, two demo
coordinators, the admin, the taxonomy, six fictional companies, and four
cycles. Nine students have declared profiles and resumes. Demo Students 05 and
10 deliberately stop after account creation so first-login self-declaration
remains part of the exercise. No applications, offers, memberships, or
discipline history are pre-created.

Kept strictly separate from ``app/seed.py``: nothing here imports or edits
that load-bearing analytics/demo seed. The named run uses a dedicated database;
its exact cast and taxonomy are not intended to be overlaid on the demo world.
The one deliberately shared identity is ``admin@<allowed_domain>``.

Every write here goes through a real command and the executor, never a raw
INSERT -- the same discipline ``app/seed.py`` holds itself to, and for the
same reason: if this seed can build the exercise's starting world, so can the
humans clicking through it live. The one deliberate exception is ``--reset``,
which tears rows back out; there is no ``delete_cycle`` or ``delete_user``
command to route that through, so it is the one place this module reaches for
raw, carefully-ordered SQL.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.bootstrap import build_executor, build_registry
from app.core.db import create_engine
from app.core.executor import Executor
from app.core.plan import ActorContext
from app.domain.shared import CycleKind, OfferExpiry, Outcome, Role
from app.modules.companies.commands import CompanyIdInput, ContactCreateInput, CreateCompanyInput
from app.modules.cycles.commands import CoordinatorInput, CreateCycleInput, UpdateCyclePolicyInput
from app.modules.identity.admin_commands import SetUserRoleInput
from app.modules.identity.commands import email_matches_domain, new_login_input
from app.modules.jobs.commands import CreateJobInput, PublishJobInput
from app.modules.profiles.commands import (
    AddResumeInput,
    AdminUpdateProfileInput,
    DeclareProfileInput,
)
from app.modules.taxonomies.commands import (
    SetSettingInput,
    SettingKey,
    TaxonomyKind,
    UpsertTaxonomyItemInput,
)
from app.settings import Settings

#: How many minutes ahead the seeded job's application deadline sits, by
#: default. ``--minutes`` also scales all four registration windows.
DEFAULT_MINUTES = 20

#: A real Drive file id shape, matching what the resume preview URL expects.
DRIVE_URL = "https://drive.google.com/file/d/1MockRunHandoutResumeFileId00000/view"

BRANCHES: tuple[str, ...] = ("CSE", "EE", "Mechanical", "Civil", "Chemical")
PROGRAMS: dict[str, tuple[str, ...]] = {
    "BTech": BRANCHES,
    "MTech": BRANCHES,
}
SECTORS: tuple[str, ...] = (
    "Technology & Software",
    "Core Engineering & Manufacturing",
    "Financial Services",
)
ROUND_TYPES: tuple[str, ...] = (
    "Resume Shortlist",
    "Online Assessment",
    "Technical",
    "HR",
    "Group Discussion",
)
MINORS: tuple[str, ...] = ("Data Science", "Design Thinking", "Public Policy")


@dataclass(frozen=True, slots=True)
class MockPerson:
    email: str
    full_name: str


PRIMARY_COORDINATOR = MockPerson("demo.coordinator01@example.edu", "Demo Coordinator 01")
WINTER_COORDINATOR = MockPerson("demo.coordinator02@example.edu", "Demo Coordinator 02")
COORDINATORS: tuple[MockPerson, ...] = (PRIMARY_COORDINATOR, WINTER_COORDINATOR)


@dataclass(frozen=True, slots=True)
class MockStudent:
    email: str
    full_name: str
    roll_number: str
    program: str
    branch: str
    cpi: str
    graduating_year: int
    gender: str
    active_backlogs: int = 0
    total_backlogs: int = 0
    secondary_branch: str | None = None


# Every identity is visibly synthetic. The 99-series roll numbers are reserved
# for this demo and the ``demo.`` local parts cannot be mistaken for accounts
# imported from a placement-office roster.
STUDENTS_WITH_PROFILES: tuple[MockStudent, ...] = (
    MockStudent(
        "demo.student01@example.edu",
        "Demo Student 01",
        "99000001",
        "BTech",
        "CSE",
        "8.60",
        2027,
        "other",
    ),
    MockStudent(
        "demo.student02@example.edu",
        "Demo Student 02",
        "99000002",
        "BTech",
        "CSE",
        "8.20",
        2027,
        "other",
    ),
    MockStudent(
        "demo.student03@example.edu",
        "Demo Student 03",
        "99000003",
        "BTech",
        "EE",
        "7.95",
        2027,
        "other",
    ),
    MockStudent(
        "demo.student04@example.edu",
        "Demo Student 04",
        "99000004",
        "BTech",
        "CSE",
        "7.80",
        2027,
        "other",
        secondary_branch="EE",
    ),
    MockStudent(
        "demo.student06@example.edu",
        "Demo Student 06",
        "99000006",
        "BTech",
        "CSE",
        "9.10",
        2027,
        "other",
    ),
    MockStudent(
        "demo.student07@example.edu",
        "Demo Student 07",
        "99000007",
        "MTech",
        "CSE",
        "8.40",
        2027,
        "other",
    ),
    MockStudent(
        "demo.student08@example.edu",
        "Demo Student 08",
        "99000008",
        "BTech",
        "EE",
        "7.94",
        2027,
        "other",
    ),
    MockStudent(
        "demo.student09@example.edu",
        "Demo Student 09",
        "99000009",
        "BTech",
        "Chemical",
        "7.60",
        2027,
        "other",
    ),
    MockStudent(
        "demo.student11@example.edu",
        "Demo Student 11",
        "99000011",
        "BTech",
        "Mechanical",
        "8.05",
        2027,
        "other",
    ),
)

STUDENTS_WITHOUT_PROFILES: tuple[MockStudent, ...] = (
    MockStudent(
        "demo.student05@example.edu",
        "Demo Student 05",
        "99000005",
        "BTech",
        "Mechanical",
        "7.10",
        2027,
        "other",
        active_backlogs=1,
        total_backlogs=1,
    ),
    MockStudent(
        "demo.student10@example.edu",
        "Demo Student 10",
        "99000010",
        "BTech",
        "Civil",
        "7.40",
        2027,
        "other",
        active_backlogs=0,
        total_backlogs=2,
    ),
)


@dataclass(frozen=True, slots=True)
class MockCompany:
    name: str
    description: str
    website_url: str
    sector: str
    contact_name: str
    contact_email: str
    contact_phone: str
    contact_designation: str
    inactive: bool = False


COMPANIES: tuple[MockCompany, ...] = (
    MockCompany(
        "Solstice Robotics",
        "Autonomous warehouse robotics.",
        "https://solstice.example.com",
        "Technology & Software",
        "Rhea Fernandes",
        "rhea.fernandes@solstice.example.com",
        "+1 202-555-0151",
        "Campus Recruiting Lead",
    ),
    MockCompany(
        "BluePeak Analytics",
        "Applied ML for retail demand forecasting.",
        "https://bluepeak.example.com",
        "Technology & Software",
        "Nikhil Sarin",
        "nikhil.sarin@bluepeak.example.com",
        "+1 202-555-0152",
        "Talent Partner",
    ),
    MockCompany(
        "Ashbourne Capital",
        "Quantitative asset management.",
        "https://ashbourne.example.com",
        "Financial Services",
        "Meera Kapoor",
        "meera.kapoor@ashbourne.example.com",
        "+1 202-555-0153",
        "Campus Hiring Manager",
    ),
    MockCompany(
        "Vantage Point Consulting",
        "Operations strategy consulting.",
        "https://vantagepoint.example.com",
        "Financial Services",
        "Aditya Rane",
        "aditya.rane@vantagepoint.example.com",
        "+1 202-555-0154",
        "Recruiting Associate",
    ),
    MockCompany(
        "Terra Nova Materials",
        "Advanced composite materials.",
        "https://terranova.example.com",
        "Core Engineering & Manufacturing",
        "Sana Bilgrami",
        "sana.bilgrami@terranova.example.com",
        "+1 202-555-0155",
        "HR Business Partner",
    ),
    # The one company this seed leaves deactivated (CMP: still attached to
    # whatever it ever touched, hidden only from pickers).
    MockCompany(
        "Ferrous Dynamics",
        "Heavy industrial fabrication.",
        "https://ferrousdynamics.example.com",
        "Core Engineering & Manufacturing",
        "Devraj Shetty",
        "devraj.shetty@ferrousdynamics.example.com",
        "+1 202-555-0156",
        "Recruiting Coordinator",
        inactive=True,
    ),
)

OPEN_CYCLE_NAME = "Open Opportunities — Summer"
INTERNSHIP_CYCLE_NAME = "Summer Internships 2027"
PLACEMENT_CYCLE_NAME = "Placements 2027–28"
WINTER_CYCLE_NAME = "Winter Internships 2027"
JOB_COMPANY_NAME = "Solstice Robotics"
JOB_TITLE = "Campus Community Associate"


# --------------------------------------------------------------------------
# Small DB helpers, mirroring app/seed.py's own but written independently so
# this module never imports from it.
# --------------------------------------------------------------------------

_IDENTITY_SELECT = (
    "SELECT u.id, u.email, u.full_name, u.role, u.is_active, "
    "(SELECT s.id FROM sessions s WHERE s.user_id = u.id "
    " AND s.revoked_at IS NULL AND s.expires_at > now() "
    " ORDER BY s.created_at DESC LIMIT 1) AS session_id "
    "FROM users u "
)


async def _scalar(engine: AsyncEngine, sql: str, params: dict[str, object]) -> object:
    async with engine.connect() as connection:
        return await connection.scalar(sa.text(sql), params)


async def _rows(
    engine: AsyncEngine, sql: str, params: dict[str, object]
) -> list[dict[str, object]]:
    async with engine.connect() as connection:
        result = (await connection.execute(sa.text(sql), params)).mappings().all()
    return [dict(row) for row in result]


async def _user_row(engine: AsyncEngine, email: str) -> dict[str, object] | None:
    async with engine.connect() as connection:
        row = (
            (
                await connection.execute(
                    sa.text(_IDENTITY_SELECT + "WHERE u.email = :email"), {"email": email}
                )
            )
            .mappings()
            .one_or_none()
        )
    return dict(row) if row is not None else None


async def _active_admin_row(engine: AsyncEngine) -> dict[str, object] | None:
    async with engine.connect() as connection:
        row = (
            (
                await connection.execute(
                    sa.text(
                        _IDENTITY_SELECT
                        + "WHERE u.role = 'admin' AND u.is_active "
                        "ORDER BY u.created_at, u.id LIMIT 1"
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
    return dict(row) if row is not None else None


async def _login(
    executor: Executor, engine: AsyncEngine, *, email: str, full_name: str, settings: Settings
) -> dict[str, object]:
    """Sign a user in, creating them if this is their first time (IDN-1)."""
    row = await _user_row(engine, email)
    if row is None or row["session_id"] is None:
        await executor.run(
            "google_login",
            new_login_input(email=email, full_name=full_name, settings=settings),
            ActorContext(principal_id="mock-seed", is_system=True),
        )
        row = await _user_row(engine, email)
    if row is None:
        raise RuntimeError(f"Mock seed user {email} could not be created")
    return row


async def _enrollment_id(engine: AsyncEngine, user_id: UUID) -> UUID:
    found = await _scalar(
        engine,
        "SELECT id FROM enrollments WHERE user_id = :user_id AND is_current",
        {"user_id": user_id},
    )
    if not isinstance(found, UUID):
        raise RuntimeError("Mock seed user has no current enrollment")
    return found


async def _student_actor(
    executor: Executor, engine: AsyncEngine, *, email: str, full_name: str, settings: Settings
) -> ActorContext:
    row = await _login(executor, engine, email=email, full_name=full_name, settings=settings)
    user_id, session_id = row["id"], row["session_id"]
    if not isinstance(user_id, UUID) or not isinstance(session_id, UUID):
        raise RuntimeError(f"Mock seed student {email} has no usable session")
    enrollment_id = await _enrollment_id(engine, user_id)
    declared = await _scalar(
        engine,
        "SELECT declared_at IS NOT NULL FROM profiles WHERE enrollment_id = :id",
        {"id": enrollment_id},
    )
    return ActorContext(
        principal_id=str(user_id),
        user_id=user_id,
        role="student",
        session_id=session_id,
        current_enrollment_id=enrollment_id,
        email=str(row["email"]),
        full_name=str(row["full_name"]),
        profile_declared=bool(declared),
    )


async def _ensure_admin(
    executor: Executor, engine: AsyncEngine, *, settings: Settings
) -> ActorContext:
    """Sign in as ``admin@<allowed_domain>``, bootstrapping the role once.

    This is the one identity ``app/seed.py`` and this module deliberately
    share: whichever seed runs first creates it, and the other reuses it.
    """
    email = f"admin@{settings.allowed_domain}".strip().casefold()
    row = await _active_admin_row(engine)
    needs_first_admin = row is None
    if needs_first_admin:
        if not email_matches_domain(email, settings.allowed_domain):
            raise ValueError("Mock seed administrator must use the allowed institute domain")
        row = await _user_row(engine, email)
    login_email = email if row is None else str(row["email"])
    login_name = "CDS Administrator" if row is None else str(row["full_name"])
    if row is None or row["session_id"] is None:
        await executor.run(
            "google_login",
            new_login_input(email=login_email, full_name=login_name, settings=settings),
            ActorContext(principal_id="mock-seed", is_system=True),
        )
        row = await _user_row(engine, login_email)
    if row is None or not bool(row["is_active"]):
        raise RuntimeError("Mock seed administrator is unavailable or inactive")

    user_id, session_id = row["id"], row["session_id"]
    if not isinstance(user_id, UUID) or not isinstance(session_id, UUID):
        raise RuntimeError("Mock seed administrator identity is invalid")
    admin_actor = ActorContext(
        principal_id=str(user_id), user_id=user_id, role="admin", session_id=session_id
    )
    if needs_first_admin:
        # Sanctioned authorization exception, in the same spirit as
        # app.seed's own: only a non-HTTP seed entry point may grant initial
        # admin capability before any persisted admin exists.
        await executor.run(
            "set_user_role", SetUserRoleInput(user_id=user_id, role=Role.ADMIN), admin_actor
        )
    return admin_actor


# --------------------------------------------------------------------------
# Taxonomy, students, cycles, companies, and the one job.
# --------------------------------------------------------------------------


async def _seed_taxonomy(
    executor: Executor, admin_actor: ActorContext
) -> dict[tuple[TaxonomyKind, str], UUID]:
    taxonomy: dict[tuple[TaxonomyKind, str], UUID] = {}

    async def upsert(
        kind: TaxonomyKind, name: str, *, branch_ids: list[UUID] | None = None
    ) -> None:
        result = await executor.run(
            "upsert_taxonomy_item",
            UpsertTaxonomyItemInput(kind=kind, name=name, branch_ids=branch_ids),
            admin_actor,
        )
        taxonomy[(kind, name)] = UUID(str(result.summary["item_id"]))

    for branch in BRANCHES:
        await upsert(TaxonomyKind.BRANCH, branch)
    for program, branches in PROGRAMS.items():
        await upsert(
            TaxonomyKind.PROGRAM,
            program,
            branch_ids=[taxonomy[(TaxonomyKind.BRANCH, branch)] for branch in branches],
        )
    for sector in SECTORS:
        await upsert(TaxonomyKind.SECTOR, sector)
    for round_type in ROUND_TYPES:
        await upsert(TaxonomyKind.ROUND_TYPE, round_type)
    for minor in MINORS:
        await upsert(TaxonomyKind.MINOR, minor)
    return taxonomy


async def _seed_students_with_profiles(
    executor: Executor,
    engine: AsyncEngine,
    *,
    taxonomy: dict[tuple[TaxonomyKind, str], UUID],
    settings: Settings,
) -> None:
    """Each student declares their own profile (PRO-1) and adds a resume.

    ``declare_profile`` is the only command that sets ``declared_at``, so the
    seed runs it as the student rather than filling the columns
    administratively, matching app.seed's own discipline.
    """
    for index, student in enumerate(STUDENTS_WITH_PROFILES, start=1):
        actor = await _student_actor(
            executor, engine, email=student.email, full_name=student.full_name, settings=settings
        )
        if not actor.profile_declared:
            await executor.run(
                "declare_profile",
                DeclareProfileInput(
                    enrollment_id=cast(UUID, actor.current_enrollment_id),
                    fields={
                        "roll_number": student.roll_number,
                        "program_id": str(taxonomy[(TaxonomyKind.PROGRAM, student.program)]),
                        "primary_branch_id": str(taxonomy[(TaxonomyKind.BRANCH, student.branch)]),
                        "is_dual_major": student.secondary_branch is not None,
                        **(
                            {
                                "secondary_branch_id": str(
                                    taxonomy[(TaxonomyKind.BRANCH, student.secondary_branch)]
                                )
                            }
                            if student.secondary_branch is not None
                            else {}
                        ),
                        "graduating_year": student.graduating_year,
                        "cpi": student.cpi,
                        "active_backlogs": student.active_backlogs,
                        "total_backlogs": student.total_backlogs,
                        "gender": student.gender,
                        "personal_email": student.email.replace("@example.edu", "@example.com"),
                        "contact_number": f"+1 202-555-{100 + index:04d}",
                        "nationality": "IN",
                        "tenth_percent": "90.00",
                        "tenth_year": 2019,
                        "twelfth_percent": "92.00",
                        "twelfth_year": 2021,
                    },
                ),
                actor,
            )
            actor = await _student_actor(
                executor,
                engine,
                email=student.email,
                full_name=student.full_name,
                settings=settings,
            )
        resumes = await _scalar(
            engine,
            "SELECT count(*) FROM resumes WHERE enrollment_id = :id",
            {"id": actor.current_enrollment_id},
        )
        if not resumes:
            await executor.run(
                "add_resume",
                AddResumeInput(
                    enrollment_id=cast(UUID, actor.current_enrollment_id),
                    label="Primary resume",
                    drive_url=DRIVE_URL,
                    is_default=True,
                ),
                actor,
            )


async def _seed_students_without_profiles(
    executor: Executor,
    engine: AsyncEngine,
    *,
    admin_actor: ActorContext,
    settings: Settings,
) -> None:
    """Create P5/P10 accounts and roll numbers without declaring profiles."""
    for student in STUDENTS_WITHOUT_PROFILES:
        row = await _login(
            executor, engine, email=student.email, full_name=student.full_name, settings=settings
        )
        user_id = row["id"]
        if not isinstance(user_id, UUID):
            raise RuntimeError(f"Mock seed student {student.email} has no usable identity")
        enrollment_id = await _enrollment_id(engine, user_id)
        roll = await _scalar(
            engine, "SELECT roll_number FROM enrollments WHERE id = :id", {"id": enrollment_id}
        )
        if roll is None:
            await executor.run(
                "admin_update_profile",
                AdminUpdateProfileInput(
                    enrollment_id=enrollment_id,
                    fields={"roll_number": student.roll_number},
                ),
                admin_actor,
            )


async def _seed_coordinator_roll(
    executor: Executor,
    engine: AsyncEngine,
    *,
    admin_actor: ActorContext,
    user_id: UUID,
) -> None:
    """Give the primary coordinator an identifier without declaring a profile."""
    enrollment_id = await _enrollment_id(engine, user_id)
    roll = await _scalar(
        engine, "SELECT roll_number FROM enrollments WHERE id = :id", {"id": enrollment_id}
    )
    if roll is None:
        await executor.run(
            "admin_update_profile",
            AdminUpdateProfileInput(
                enrollment_id=enrollment_id,
                fields={"roll_number": "99000901"},
            ),
            admin_actor,
        )


async def _cycle(
    executor: Executor,
    admin_actor: ActorContext,
    engine: AsyncEngine,
    *,
    name: str,
    kind: CycleKind,
    description: str,
    opens_at: datetime,
    closes_at: datetime,
) -> UUID:
    found = await _scalar(engine, "SELECT id FROM cycles WHERE name = :name", {"name": name})
    if isinstance(found, UUID):
        return found
    result = await executor.run(
        "create_cycle",
        CreateCycleInput(
            name=name,
            kind=kind,
            description=description,
            registration_opens_at=opens_at,
            registration_closes_at=closes_at,
            is_active=True,
        ),
        admin_actor,
    )
    return UUID(str(result.summary["cycle_id"]))


async def _ensure_open_policy(
    executor: Executor, admin_actor: ActorContext, engine: AsyncEngine, *, cycle_id: UUID
) -> None:
    """Approval off, uncapped -- already CYC-2's default for an open cycle,
    stated explicitly here so it reads as intentional rather than accidental."""
    matches = await _scalar(
        engine,
        "SELECT EXISTS (SELECT 1 FROM cycle_policies WHERE cycle_id = :id "
        "AND NOT membership_requires_approval AND max_accepted_offers IS NULL)",
        {"id": cycle_id},
    )
    if not matches:
        await executor.run(
            "update_cycle_policy",
            UpdateCyclePolicyInput(
                cycle_id=cycle_id, membership_requires_approval=False, max_accepted_offers=None
            ),
            admin_actor,
        )


async def _ensure_internship_policy(
    executor: Executor, admin_actor: ActorContext, engine: AsyncEngine, *, cycle_id: UUID
) -> None:
    """Approval on, cap 1, strike on absence, auto-decline on expiry."""
    matches = await _scalar(
        engine,
        "SELECT EXISTS (SELECT 1 FROM cycle_policies WHERE cycle_id = :id "
        "AND membership_requires_approval AND max_accepted_offers = 1 "
        "AND strike_on_absence AND offer_expiry_behavior = 'auto_decline')",
        {"id": cycle_id},
    )
    if not matches:
        await executor.run(
            "update_cycle_policy",
            UpdateCyclePolicyInput(
                cycle_id=cycle_id,
                membership_requires_approval=True,
                max_accepted_offers=1,
                strike_on_absence=True,
                offer_expiry_behavior=OfferExpiry.AUTO_DECLINE,
            ),
            admin_actor,
        )


async def _ensure_ses_sender(
    executor: Executor, admin_actor: ActorContext, engine: AsyncEngine, *, sender: str
) -> None:
    """The From address every notification is rendered with.

    ``app/seed.py`` sets this and this module did not, so every envelope the
    mock world produced carried an empty sender -- cosmetic under the console
    backend, and fatal under SES, where ``SesEmailBackend.send`` refuses an
    empty ``Source``. Reading the From line is also part of the Step 33 review.

    Target-state checked like every other policy here, so a re-run writes no
    same-value audit row.
    """
    matches = await _scalar(
        engine,
        "SELECT EXISTS (SELECT 1 FROM settings WHERE key = 'ses_sender' "
        "AND value #>> '{}' = :sender)",
        {"sender": sender},
    )
    if not matches:
        await executor.run(
            "set_setting",
            SetSettingInput(key=SettingKey.SES_SENDER, value=sender),
            admin_actor,
        )


async def _assign_coordinator(
    executor: Executor,
    admin_actor: ActorContext,
    engine: AsyncEngine,
    *,
    cycle_id: UUID,
    user_id: UUID,
) -> None:
    assigned = await _scalar(
        engine,
        "SELECT 1 FROM cycle_coordinators WHERE cycle_id = :cycle_id AND user_id = :user_id",
        {"cycle_id": cycle_id, "user_id": user_id},
    )
    if not assigned:
        await executor.run(
            "assign_coordinator", CoordinatorInput(cycle_id=cycle_id, user_id=user_id), admin_actor
        )


async def _company(
    executor: Executor,
    admin_actor: ActorContext,
    engine: AsyncEngine,
    *,
    mock: MockCompany,
    sector_id: UUID,
) -> UUID:
    found = await _scalar(
        engine, "SELECT id FROM companies WHERE name = :name", {"name": mock.name}
    )
    if isinstance(found, UUID):
        company_id = found
    else:
        result = await executor.run(
            "create_company",
            CreateCompanyInput(
                name=mock.name,
                description=mock.description,
                website_url=mock.website_url,
                sector_id=sector_id,
            ),
            admin_actor,
        )
        company_id = UUID(str(result.summary["company_id"]))

    has_contact = await _scalar(
        engine,
        "SELECT 1 FROM company_contacts WHERE company_id = :id AND email = :email",
        {"id": company_id, "email": mock.contact_email},
    )
    if not has_contact:
        await executor.run(
            "contact_create",
            ContactCreateInput(
                company_id=company_id,
                name=mock.contact_name,
                email=mock.contact_email,
                phone=mock.contact_phone,
                designation=mock.contact_designation,
                is_primary=True,
            ),
            admin_actor,
        )

    if mock.inactive:
        active = await _scalar(
            engine, "SELECT is_active FROM companies WHERE id = :id", {"id": company_id}
        )
        if active:
            await executor.run(
                "deactivate_company", CompanyIdInput(company_id=company_id), admin_actor
            )
    return company_id


async def _seed_job(
    executor: Executor,
    admin_actor: ActorContext,
    engine: AsyncEngine,
    *,
    cycle_id: UUID,
    company_id: UUID,
    sector_id: UUID,
    deadline: datetime,
) -> None:
    job_id = await _scalar(
        engine,
        "SELECT id FROM jobs WHERE cycle_id = :cycle_id AND title = :title "
        "AND company_id = :company_id",
        {"cycle_id": cycle_id, "title": JOB_TITLE, "company_id": company_id},
    )
    if not isinstance(job_id, UUID):
        result = await executor.run(
            "create_job",
            CreateJobInput(
                cycle_id=cycle_id,
                company_id=company_id,
                title=JOB_TITLE,
                description=(
                    "Represent the company on campus for the summer: help run "
                    "outreach events and answer student questions about the "
                    "internship pipeline."
                ),
                # An open cycle carries both kinds and fixes neither (JOB-6), so
                # the outcome has to be stated explicitly.
                outcome=Outcome.INTERNSHIP,
                location="On campus",
                sector_id=sector_id,
                stipend_month=Decimal("5000"),
                application_deadline=deadline,
            ),
            admin_actor,
        )
        job_id = UUID(str(result.summary["job_id"]))

    published = await _scalar(
        engine, "SELECT is_published FROM jobs WHERE id = :id", {"id": job_id}
    )
    if not published:
        await executor.run(
            "publish_job", PublishJobInput(cycle_id=cycle_id, job_id=job_id), admin_actor
        )


# --------------------------------------------------------------------------
# Summary handout.
# --------------------------------------------------------------------------


async def _print_summary(engine: AsyncEngine, *, admin_email: str) -> None:
    print("\nMock run accounts")
    print("=" * 100)

    admin_rows = await _rows(
        engine, "SELECT email, full_name FROM users WHERE email = :email", {"email": admin_email}
    )
    coordinator_rows = await _rows(
        engine,
        "SELECT u.email, u.full_name, "
        "coalesce(string_agg(c.name, ', ' ORDER BY c.name), '(unassigned)') AS cycles "
        "FROM users u "
        "LEFT JOIN cycle_coordinators cc ON cc.user_id = u.id "
        "LEFT JOIN cycles c ON c.id = cc.cycle_id "
        "WHERE u.email = ANY(:emails) GROUP BY u.id, u.email, u.full_name ORDER BY u.email",
        {"emails": [c.email for c in COORDINATORS]},
    )

    print(f"{'Email':<28} {'Role':<14} Detail")
    print("-" * 100)
    for row in admin_rows:
        print(f"{row['email']:<28} {'admin':<14} {row['full_name']}")
    for row in coordinator_rows:
        print(
            f"{row['email']:<28} {'coordinator':<14} {row['full_name']} "
            f"-- coordinates: {row['cycles']}"
        )

    student_rows = await _rows(
        engine,
        "SELECT u.email, u.full_name, e.roll_number, prog.name AS program, "
        "br.name AS branch, p.cpi, (p.declared_at IS NOT NULL) AS has_profile "
        "FROM users u "
        "JOIN enrollments e ON e.user_id = u.id AND e.is_current "
        "LEFT JOIN profiles p ON p.enrollment_id = e.id "
        "LEFT JOIN programs prog ON prog.id = p.program_id "
        "LEFT JOIN branches br ON br.id = p.primary_branch_id "
        "WHERE u.email = ANY(:emails) ORDER BY u.email",
        {
            "emails": [s.email for s in STUDENTS_WITH_PROFILES]
            + [s.email for s in STUDENTS_WITHOUT_PROFILES]
        },
    )
    print()
    print(f"{'Email':<16} {'Roll No.':<12} {'Program':<10} {'Branch':<34} {'CPI':<6} {'Profile'}")
    print("-" * 100)
    for row in student_rows:
        print(
            f"{row['email']:<16} {str(row['roll_number'] or '—'):<12} "
            f"{str(row['program'] or '—'):<10} {str(row['branch'] or '—'):<34} "
            f"{str(row['cpi'] or '—'):<6} {'yes' if row['has_profile'] else 'no'}"
        )
    print()


# --------------------------------------------------------------------------
# --reset: tear this seed's own cycle/company/job state back out, in
# dependency order against the schema's FKs (all ON DELETE RESTRICT). There
# is no command for any of this, so it is the one place this module writes
# raw SQL.
#
# Two tables -- audit_log and application_events -- are append-only at the
# database grant level (migration 0002_grants revokes UPDATE/DELETE on them
# for the application role entirely; see its docstring). That is a real,
# deliberate invariant, not an oversight this script can route around: an
# audit trail that a seed script could erase would not be one. Two
# consequences follow, and this function is built around both:
#
#   - A user who has ever taken an audited action (declaring a profile,
#     adding a resume, ...) can never be deleted: audit_log.actor_user_id is
#     RESTRICT, and audit_log itself cannot be deleted. So --reset never
#     touches users, sessions, enrollments, profiles, or resumes at all --
#     the account roster is permanent once created, which is fine, since
#     re-seeding onto an already-declared profile is already a no-op.
#   - An application can never be deleted once filed: applications.id is
#     referenced by its own permanent "created" application_event. That
#     makes its job, and that job's cycle and company, permanently
#     un-deletable too (RESTRICT all the way up). So --reset partitions jobs
#     into those with zero applications (torn down completely, including
#     the cycle/company they leave behind if nothing else references them)
#     and those with real application history (left fully alone, history and
#     all) -- rather than crashing on the first blocked DELETE.
#
# Cycle membership and coordinator assignment carry no such history and are
# always cleared, even for a cycle whose jobs are retained, so a fresh join
# queue is still what a reset run gets even when old application history
# survives underneath it.
# --------------------------------------------------------------------------


async def _reset_mock_data(engine: AsyncEngine) -> None:
    coordinator_emails = [c.email for c in COORDINATORS]
    student_emails = [s.email for s in STUDENTS_WITH_PROFILES] + [
        s.email for s in STUDENTS_WITHOUT_PROFILES
    ]
    company_names = [c.name for c in COMPANIES]
    cycle_names = [
        OPEN_CYCLE_NAME,
        INTERNSHIP_CYCLE_NAME,
        PLACEMENT_CYCLE_NAME,
        WINTER_CYCLE_NAME,
    ]

    async def id_list(connection: AsyncConnection, sql: str, **params: object) -> list[UUID]:
        result = await connection.execute(sa.text(sql), params)
        return [row[0] for row in result.all()]

    async def delete(connection: AsyncConnection, sql: str, **params: object) -> None:
        await connection.execute(sa.text(sql), params)

    # No explicit transaction here (LLD section 14 reserves `.begin`/`.commit`
    # for core/executor.py): each statement below runs and commits on its own
    # under AUTOCOMMIT. That is safe because every statement is itself
    # idempotent -- re-running any prefix of this sequence against whatever it
    # left behind deletes the same rows or nothing -- so an interruption here
    # is just a --reset that needs running again, not a corrupt half-state.
    async with engine.connect() as connection:
        await connection.execution_options(isolation_level="AUTOCOMMIT")

        cycle_ids = await id_list(
            connection,
            "SELECT id FROM cycles WHERE name = ANY(CAST(:names AS citext[]))",
            names=cycle_names,
        )
        all_company_ids = await id_list(
            connection,
            "SELECT id FROM companies WHERE name = ANY(CAST(:names AS citext[]))",
            names=company_names,
        )
        if not (cycle_ids or all_company_ids):
            return  # Nothing this seed created is on the database yet.

        enrollment_ids = await id_list(
            connection,
            "SELECT e.id FROM enrollments e JOIN users u ON u.id = e.user_id "
            "WHERE u.email = ANY(CAST(:emails AS citext[]))",
            emails=coordinator_emails + student_emails,
        )
        jobs = (
            await connection.execute(
                sa.text(
                    "SELECT id, cycle_id, company_id FROM jobs "
                    "WHERE cycle_id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": cycle_ids},
            )
        ).all()
        blocked_job_ids = set(
            await id_list(
                connection,
                "SELECT DISTINCT job_id FROM applications WHERE job_id = ANY(CAST(:ids AS uuid[]))",
                ids=[row.id for row in jobs],
            )
        )
        deletable_job_ids = [row.id for row in jobs if row.id not in blocked_job_ids]
        blocked_cycle_ids = {row.cycle_id for row in jobs if row.id in blocked_job_ids}
        blocked_company_ids = {row.company_id for row in jobs if row.id in blocked_job_ids}
        deletable_cycle_ids = [c for c in cycle_ids if c not in blocked_cycle_ids]
        deletable_company_ids = [c for c in all_company_ids if c not in blocked_company_ids]
        question_ids = await id_list(
            connection,
            "SELECT id FROM job_questions WHERE job_id = ANY(CAST(:ids AS uuid[]))",
            ids=deletable_job_ids,
        )

        # Discipline and overrides carry no permanence of their own -- always
        # clear everything tied to our people, our companies, or our cycles,
        # whether or not the job/cycle underneath survives as retained history.
        await delete(
            connection,
            "DELETE FROM export_jobs WHERE requested_by IN "
            "(SELECT id FROM users WHERE email = ANY(CAST(:emails AS citext[])))",
            emails=coordinator_emails + student_emails,
        )
        await delete(
            connection,
            "DELETE FROM export_presets WHERE job_id = ANY(CAST(:ids AS uuid[]))",
            ids=deletable_job_ids,
        )
        await delete(
            connection,
            "DELETE FROM overrides WHERE cycle_id = ANY(CAST(:cycles AS uuid[])) "
            "OR enrollment_id = ANY(CAST(:enrollments AS uuid[]))",
            cycles=cycle_ids,
            enrollments=enrollment_ids,
        )
        await delete(
            connection,
            "DELETE FROM strikes WHERE enrollment_id = ANY(CAST(:ids AS uuid[]))",
            ids=enrollment_ids,
        )
        await delete(
            connection,
            "DELETE FROM penalties WHERE enrollment_id = ANY(CAST(:ids AS uuid[]))",
            ids=enrollment_ids,
        )
        await delete(
            connection,
            "DELETE FROM external_offers WHERE enrollment_id = ANY(CAST(:enrollments AS uuid[])) "
            "OR company_id = ANY(CAST(:companies AS uuid[])) "
            "OR attached_cycle_id = ANY(CAST(:cycles AS uuid[]))",
            enrollments=enrollment_ids,
            companies=all_company_ids,
            cycles=cycle_ids,
        )
        await delete(
            connection,
            "DELETE FROM cycle_memberships WHERE cycle_id = ANY(CAST(:ids AS uuid[]))",
            ids=cycle_ids,
        )
        await delete(
            connection,
            "DELETE FROM cycle_coordinators WHERE cycle_id = ANY(CAST(:ids AS uuid[]))",
            ids=cycle_ids,
        )

        # Everything below is scoped to the *deletable* subset only -- a job
        # with real application history, and the cycle or company left behind
        # by it, is left exactly as it was.
        await delete(
            connection,
            "DELETE FROM job_question_options WHERE question_id = ANY(CAST(:ids AS uuid[]))",
            ids=question_ids,
        )
        await delete(
            connection,
            "DELETE FROM job_questions WHERE job_id = ANY(CAST(:ids AS uuid[]))",
            ids=deletable_job_ids,
        )
        await delete(
            connection,
            "DELETE FROM job_rounds WHERE job_id = ANY(CAST(:ids AS uuid[]))",
            ids=deletable_job_ids,
        )
        await delete(
            connection,
            "DELETE FROM job_program_ctc WHERE job_id = ANY(CAST(:ids AS uuid[]))",
            ids=deletable_job_ids,
        )
        await delete(
            connection,
            "DELETE FROM jobs WHERE id = ANY(CAST(:ids AS uuid[]))",
            ids=deletable_job_ids,
        )
        await delete(
            connection,
            "DELETE FROM company_contacts WHERE company_id = ANY(CAST(:ids AS uuid[]))",
            ids=deletable_company_ids,
        )
        await delete(
            connection,
            "DELETE FROM companies WHERE id = ANY(CAST(:ids AS uuid[]))",
            ids=deletable_company_ids,
        )
        await delete(
            connection,
            "DELETE FROM cycle_policies WHERE cycle_id = ANY(CAST(:ids AS uuid[]))",
            ids=deletable_cycle_ids,
        )
        await delete(
            connection,
            "DELETE FROM cycles WHERE id = ANY(CAST(:ids AS uuid[]))",
            ids=deletable_cycle_ids,
        )

        if blocked_job_ids:
            print(
                f"--reset: {len(blocked_job_ids)} job(s) carry real application "
                "history (a permanent audit trail the application role cannot "
                "erase) and were left in place along with any cycle or company "
                "that still has one; everything else was cleared. Re-seeding "
                "will build alongside what remains rather than replace it."
            )


# --------------------------------------------------------------------------
# Orchestration and CLI.
# --------------------------------------------------------------------------


async def run_mock_seed(
    *,
    database_url: str | None = None,
    settings: Settings | None = None,
    minutes: int = DEFAULT_MINUTES,
    reset: bool = False,
) -> None:
    resolved_settings = settings or Settings.from_env()
    engine = create_engine(database_url)
    try:
        if reset:
            await _reset_mock_data(engine)

        registry = build_registry(settings=resolved_settings)
        executor = build_executor(registry, engine)

        admin_actor = await _ensure_admin(executor, engine, settings=resolved_settings)
        taxonomy = await _seed_taxonomy(executor, admin_actor)

        for coordinator in COORDINATORS:
            await _login(
                executor,
                engine,
                email=coordinator.email,
                full_name=coordinator.full_name,
                settings=resolved_settings,
            )
        await _seed_students_with_profiles(
            executor, engine, taxonomy=taxonomy, settings=resolved_settings
        )
        await _seed_students_without_profiles(
            executor,
            engine,
            admin_actor=admin_actor,
            settings=resolved_settings,
        )

        now = datetime.now(UTC)
        # Registration windows open now; how long they stay open scales with
        # --minutes, well past the one job's own (shorter) deadline below.
        registration_closes_at = now + timedelta(minutes=minutes * 6)
        open_id = await _cycle(
            executor,
            admin_actor,
            engine,
            name=OPEN_CYCLE_NAME,
            kind=CycleKind.OPEN,
            description=(
                "Off-cycle roles anyone can join immediately: no approval queue, no offer cap."
            ),
            opens_at=now,
            closes_at=registration_closes_at,
        )
        internship_id = await _cycle(
            executor,
            admin_actor,
            engine,
            name=INTERNSHIP_CYCLE_NAME,
            kind=CycleKind.INTERNSHIP,
            description=(
                "The mock run's capped internship season: membership needs "
                "approval, one accepted offer per student, and an unanswered "
                "offer auto-declines at its deadline."
            ),
            opens_at=now,
            closes_at=registration_closes_at,
        )
        placement_id = await _cycle(
            executor,
            admin_actor,
            engine,
            name=PLACEMENT_CYCLE_NAME,
            kind=CycleKind.PLACEMENT,
            description="The mock run's placement season.",
            opens_at=now,
            closes_at=registration_closes_at,
        )
        winter_id = await _cycle(
            executor,
            admin_actor,
            engine,
            name=WINTER_CYCLE_NAME,
            kind=CycleKind.INTERNSHIP,
            description="The mock run's winter internship season.",
            opens_at=now,
            closes_at=registration_closes_at,
        )
        await _ensure_ses_sender(
            executor,
            admin_actor,
            engine,
            sender=os.environ.get("SES_SENDER", "").strip()
            or "CDS noreply <noreply@cdsportal.example.edu>",
        )
        await _ensure_open_policy(executor, admin_actor, engine, cycle_id=open_id)
        for cycle_id in (internship_id, placement_id, winter_id):
            await _ensure_internship_policy(executor, admin_actor, engine, cycle_id=cycle_id)

        primary_coordinator_id = await _scalar(
            engine,
            "SELECT id FROM users WHERE email = :email",
            {"email": PRIMARY_COORDINATOR.email},
        )
        winter_coordinator_id = await _scalar(
            engine,
            "SELECT id FROM users WHERE email = :email",
            {"email": WINTER_COORDINATOR.email},
        )
        if not isinstance(primary_coordinator_id, UUID) or not isinstance(
            winter_coordinator_id, UUID
        ):
            raise RuntimeError("Mock seed coordinators have no usable identity")
        await _seed_coordinator_roll(
            executor,
            engine,
            admin_actor=admin_actor,
            user_id=primary_coordinator_id,
        )
        for cycle_id in (open_id, internship_id, placement_id):
            await _assign_coordinator(
                executor,
                admin_actor,
                engine,
                cycle_id=cycle_id,
                user_id=primary_coordinator_id,
            )
        await _assign_coordinator(
            executor,
            admin_actor,
            engine,
            cycle_id=winter_id,
            user_id=winter_coordinator_id,
        )

        company_ids: dict[str, UUID] = {}
        for company in COMPANIES:
            sector_id = taxonomy[(TaxonomyKind.SECTOR, company.sector)]
            company_ids[company.name] = await _company(
                executor, admin_actor, engine, mock=company, sector_id=sector_id
            )

        await _seed_job(
            executor,
            admin_actor,
            engine,
            cycle_id=open_id,
            company_id=company_ids[JOB_COMPANY_NAME],
            sector_id=taxonomy[(TaxonomyKind.SECTOR, "Technology & Software")],
            deadline=now + timedelta(minutes=minutes),
        )

        await _print_summary(
            engine, admin_email=f"admin@{resolved_settings.allowed_domain}".strip().casefold()
        )
    finally:
        await engine.dispose()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Seed the mock live-run world: a second, additional seed on top "
            "of (or independent of) app/seed.py's own."
        )
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Truncate this seed's own data (and anything built on top of it live), then re-seed.",
    )
    parser.add_argument(
        "--minutes",
        type=int,
        default=DEFAULT_MINUTES,
        help=f"Scale every relative deadline this seed computes (default {DEFAULT_MINUTES}).",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = _parse_args()
    if args.minutes < 1:
        raise SystemExit("--minutes must be at least 1")
    asyncio.run(run_mock_seed(minutes=args.minutes, reset=args.reset))


if __name__ == "__main__":
    main()
