"""Idempotent development seed executed exclusively through commands.

Every row here is written by running a real command as a real actor, never by
INSERT.  That is the point of the module: if the seed can build the world, the
commands can, and a seeded database is reachable through the UI rather than
being a shape only the seed knows how to make.

It grew in F1.5 from "an admin and the taxonomies" to a world the whole
front end can be clicked through: three cycles, students in every membership
state including a queue waiting for approval, companies with contacts (and a
duplicate to merge), jobs and applications across their workflows, discipline
history, portal offers across offered/accepted/re-extended/terminated states,
and external offers across status and attachment states. Rules deliberately
split the seeded roster, because a unanimous impact preview proves nothing.

Idempotent by construction: every step either looks the row up first or runs a
command that is itself an upsert, so running it twice changes nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from app.bootstrap import build_executor, build_registry
from app.core.db import create_engine
from app.core.executor import Executor
from app.core.plan import ActorContext, Result
from app.domain.shared import (
    ApplicationStatus,
    Attendance,
    CycleKind,
    ExternalSource,
    ExternalStatus,
    MembershipStatus,
    OfferExpiry,
    Outcome,
    OutcomeTag,
    QuestionType,
    Role,
    RuleDomain,
    TerminationKind,
)
from app.modules.admin.commands import ResolveFindingInput
from app.modules.applications.attendance import MarkAttendanceInput
from app.modules.applications.commands import AnswerInput, ApplyInput
from app.modules.applications.finalization import FinalizeRoundInput
from app.modules.applications.lifecycle import WithdrawApplicationInput
from app.modules.companies.commands import ContactCreateInput, CreateCompanyInput
from app.modules.cycles.commands import (
    CoordinatorInput,
    CreateCycleInput,
    UpdateCyclePolicyInput,
)
from app.modules.cycles.memberships import (
    JoinCycleInput,
    SetOutcomeTagInput,
    WithdrawMembershipInput,
)
from app.modules.discipline.commands import (
    AwardPenaltyInput,
    AwardStrikeInput,
    RevokePenaltyInput,
    RevokeStrikeInput,
)
from app.modules.identity.admin_commands import SetUserRoleInput
from app.modules.identity.commands import email_matches_domain, new_login_input
from app.modules.jobs.builder import (
    JobQuestionRow,
    JobRoundRow,
    UpsertJobQuestionsInput,
    UpsertJobRoundsInput,
)
from app.modules.jobs.commands import (
    CreateJobInput,
    ProgramCtcRow,
    PublishJobInput,
    UpdateJobBasicsInput,
)
from app.modules.jobs.eligibility import UpdateJobEligibilityInput
from app.modules.offers.commands import OfferResponseInput
from app.modules.offers.expiry import EnforceOfferExpiryInput
from app.modules.offers.external import (
    AttachExternalOfferInput,
    CreateExternalOfferInput,
    UpdateExternalOfferInput,
)
from app.modules.offers.termination import (
    ReExtendOfferInput,
    RestoreSelection,
    TerminateOfferInput,
)
from app.modules.overrides.commands import (
    CreateOverrideInput,
    DeactivateOverrideInput,
)
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

BTECH_BRANCHES = (
    "Artificial Intelligence", "Chemical Engineering", "Civil Engineering",
    "Computer Science and Engineering", "Electrical Engineering",
    "Materials Engineering", "Mechanical Engineering",
)
MTECH_BRANCHES = (
    "Artificial Intelligence", "Biological Engineering", "Chemical Engineering",
    "Civil Engineering", "Computer Science and Engineering", "Earth Sciences",
    "Electrical Engineering", "Integrated Circuit Design and Technology",
    "Materials Engineering", "Mechanical Engineering",
)
MSC_BRANCHES = ("Chemistry", "Cognitive Science", "Mathematics", "Physics")
BRANCHES = tuple(dict.fromkeys((
    *BTECH_BRANCHES, *MTECH_BRANCHES, *MSC_BRANCHES,
    "Humanities and Social Sciences",
)))
PROGRAMS: dict[str, tuple[str, ...]] = {
    "BTech": BTECH_BRANCHES,
    "MTech": MTECH_BRANCHES,
    "MSc": MSC_BRANCHES,
    "MA": ("Humanities and Social Sciences",),
    "PhD": BRANCHES,
}
SECTORS = ("Technology", "Consulting", "Finance", "Core Engineering")
ROUND_TYPES = (
    "Aptitude Test",
    "Technical Interview",
    "HR Interview",
    "Group Discussion",
)
MINORS = ("Computer Science", "Entrepreneurship", "Physics")

#: A real Drive file id shape, so the resume preview URL the UI builds resolves
#: to something with the right form rather than an obviously fake string.
DRIVE_URL = "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view"


@dataclass(frozen=True, slots=True)
class SeedStudent:
    """One student and the profile they will declare.

    ``cpi`` and ``branch`` vary across the roster on purpose: the builder's
    impact preview and the student eligibility verdict are only worth looking
    at when some of the seeded membership fails the rule.  ``secondary_branch``
    is set on exactly one student for the same reason: PRO-1's conditional join
    requirement and ELG-2's dual-major clause both have nothing to say until
    somebody in the roster actually holds a second major.
    """

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
    #: The second major, for a dual major (the design review section 4.32).
    secondary_branch: str | None = None


STUDENTS: tuple[SeedStudent, ...] = (
    SeedStudent(
        email="asha.mehta@example.edu",
        full_name="Asha Mehta",
        roll_number="21110001",
        program="BTech",
        branch="Computer Science and Engineering",
        cpi="9.10",
        graduating_year=2026,
        gender="female",
    ),
    SeedStudent(
        email="bikram.singh@example.edu",
        full_name="Bikram Singh",
        roll_number="21110002",
        program="BTech",
        branch="Computer Science and Engineering",
        cpi="8.20",
        graduating_year=2026,
        gender="male",
        # The roster's one dual major: CSE primary, EE secondary.
        secondary_branch="Electrical Engineering",
    ),
    SeedStudent(
        email="chitra.rao@example.edu",
        full_name="Chitra Rao",
        roll_number="21110003",
        program="BTech",
        branch="Electrical Engineering",
        cpi="7.60",
        graduating_year=2026,
        gender="female",
    ),
    SeedStudent(
        email="dev.patel@example.edu",
        full_name="Dev Patel",
        roll_number="21110004",
        program="BTech",
        branch="Mechanical Engineering",
        cpi="6.90",
        graduating_year=2026,
        gender="male",
        active_backlogs=1,
        total_backlogs=2,
    ),
    SeedStudent(
        email="esha.nair@example.edu",
        full_name="Esha Nair",
        roll_number="22120005",
        program="MTech",
        branch="Computer Science and Engineering",
        cpi="8.80",
        graduating_year=2026,
        gender="female",
    ),
    SeedStudent(
        email="farhan.khan@example.edu",
        full_name="Farhan Khan",
        roll_number="22120006",
        program="MTech",
        branch="Electrical Engineering",
        cpi="8.05",
        graduating_year=2026,
        gender="male",
    ),
)

#: Added only by ``app.e2e_seed``.  The profile and resume are ready so the
#: browser suite starts at the behavior under test -- joining -- while the
#: membership itself is deliberately absent.  Mechanical + one active backlog
#: gives the job list two simultaneous, human-readable eligibility failures.
E2E_STUDENT = SeedStudent(
    email="e2e.student@example.edu",
    full_name="End-to-End Student",
    roll_number="29990001",
    program="BTech",
    branch="Mechanical Engineering",
    cpi="9.10",
    graduating_year=2026,
    gender="other",
    active_backlogs=1,
    total_backlogs=1,
)

#: The coordinator is an ordinary user; "staff" is a cycle_coordinators row,
#: not a role.  Seeding one proves the non-admin staff path works in the UI.
COORDINATOR_EMAIL = "coordinator@example.edu"
COORDINATOR_NAME = "Priya Coordinator"


_IDENTITY_SELECT = (
    "SELECT u.id, u.email, u.full_name, u.role, u.is_active, "
    "(SELECT s.id FROM sessions s WHERE s.user_id = u.id "
    " AND s.revoked_at IS NULL AND s.expires_at > now() "
    " ORDER BY s.created_at DESC LIMIT 1) AS session_id "
    "FROM users u "
)


async def _user_row(engine: AsyncEngine, email: str) -> dict[str, object] | None:
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                sa.text(_IDENTITY_SELECT + "WHERE u.email = :email"),
                {"email": email},
            )
        ).mappings().one_or_none()
    return dict(row) if row is not None else None


async def _active_admin_row(engine: AsyncEngine) -> dict[str, object] | None:
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                sa.text(
                    _IDENTITY_SELECT
                    + "WHERE u.role = 'admin' AND u.is_active ORDER BY u.created_at, u.id LIMIT 1"
                )
            )
        ).mappings().one_or_none()
    return dict(row) if row is not None else None



async def _scalar(engine: AsyncEngine, sql: str, params: dict[str, object]) -> object:
    async with engine.connect() as connection:
        return await connection.scalar(sa.text(sql), params)


async def _rows(
    engine: AsyncEngine, sql: str, params: dict[str, object]
) -> list[dict[str, object]]:
    async with engine.connect() as connection:
        result = (await connection.execute(sa.text(sql), params)).mappings().all()
    return [dict(row) for row in result]


async def _login(
    executor: Executor, engine: AsyncEngine, *, email: str, full_name: str,
    settings: Settings,
) -> dict[str, object]:
    """Sign a user in, creating them if this is their first time.

    google_login is the only way a user comes into existence in production, so
    it is the only way one comes into existence here.  A user who already holds
    a live session is left alone, which is what makes the step idempotent.
    """
    row = await _user_row(engine, email)
    if row is None or row["session_id"] is None:
        await executor.run(
            "google_login",
            new_login_input(email=email, full_name=full_name, settings=settings),
            ActorContext(principal_id="seed", is_system=True),
        )
        row = await _user_row(engine, email)
    if row is None:
        raise RuntimeError(f"Seed user {email} could not be created")
    return row


async def _enrollment_id(engine: AsyncEngine, user_id: UUID) -> UUID:
    found = await _scalar(
        engine,
        "SELECT id FROM enrollments WHERE user_id = :user_id AND is_current",
        {"user_id": user_id},
    )
    if not isinstance(found, UUID):
        raise RuntimeError("Seed user has no current enrollment")
    return found


async def _student_actor(
    executor: Executor, engine: AsyncEngine, *, email: str, full_name: str,
    settings: Settings,
) -> ActorContext:
    row = await _login(
        executor, engine, email=email, full_name=full_name, settings=settings
    )
    user_id, session_id = row["id"], row["session_id"]
    if not isinstance(user_id, UUID) or not isinstance(session_id, UUID):
        raise RuntimeError(f"Seed student {email} has no usable session")
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


async def _seed_students(
    executor: Executor, engine: AsyncEngine, *, taxonomy: dict[tuple[TaxonomyKind, str], UUID],
    settings: Settings, roster: tuple[SeedStudent, ...] = STUDENTS,
) -> dict[str, ActorContext]:
    """Every student declares their own profile and adds a resume.

    declare_profile is the only command that sets declared_at, and join_cycle
    requires it, so the seed has to run it as the student rather than filling
    the columns administratively (the design review 4.15).
    """
    actors: dict[str, ActorContext] = {}
    for student in roster:
        actor = await _student_actor(
            executor,
            engine,
            email=student.email,
            full_name=student.full_name,
            settings=settings,
        )
        if not actor.profile_declared:
            await executor.run(
                "declare_profile",
                DeclareProfileInput(
                    enrollment_id=actor.current_enrollment_id,  # type: ignore[arg-type]
                    fields={
                        "roll_number": student.roll_number,
                        "program_id": str(taxonomy[(TaxonomyKind.PROGRAM, student.program)]),
                        "primary_branch_id": str(
                            taxonomy[(TaxonomyKind.BRANCH, student.branch)]
                        ),
                        "is_dual_major": student.secondary_branch is not None,
                        **(
                            {
                                "secondary_branch_id": str(
                                    taxonomy[
                                        (TaxonomyKind.BRANCH, student.secondary_branch)
                                    ]
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
                        "personal_email": student.email.replace(
                            "@example.edu", "@example.com"
                        ),
                        "contact_number": f"+1 202-555-01{int(student.roll_number[-2:]):02d}",
                        "nationality": "IN",
                        "tenth_percent": "92.00",
                        "tenth_year": 2019,
                        "twelfth_percent": "94.00",
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
                    enrollment_id=actor.current_enrollment_id,  # type: ignore[arg-type]
                    label="Primary resume",
                    drive_url=DRIVE_URL,
                    is_default=True,
                ),
                actor,
            )
        actors[student.email] = actor
    return actors


async def _cycle(
    executor: Executor, admin: ActorContext, engine: AsyncEngine, *, name: str,
    kind: CycleKind, description: str, opens_days: int, closes_days: int,
) -> UUID:
    """Create the cycle unless it is already there (names are unique)."""
    found = await _scalar(
        engine, "SELECT id FROM cycles WHERE name = :name", {"name": name}
    )
    if isinstance(found, UUID):
        return found
    now = datetime.now(UTC)
    result = await executor.run(
        "create_cycle",
        CreateCycleInput(
            name=name,
            kind=kind,
            description=description,
            registration_opens_at=now + timedelta(days=opens_days),
            registration_closes_at=now + timedelta(days=closes_days),
            is_active=True,
        ),
        admin,
    )
    return UUID(str(result.summary["cycle_id"]))


async def _company(
    executor: Executor, admin: ActorContext, engine: AsyncEngine, *, name: str,
    description: str, website_url: str, sector_id: UUID,
) -> UUID:
    found = await _scalar(
        engine, "SELECT id FROM companies WHERE name = :name", {"name": name}
    )
    if isinstance(found, UUID):
        return found
    result = await executor.run(
        "create_company",
        CreateCompanyInput(
            name=name,
            description=description,
            website_url=website_url,
            sector_id=sector_id,
        ),
        admin,
    )
    return UUID(str(result.summary["company_id"]))


async def _contact(
    executor: Executor, admin: ActorContext, engine: AsyncEngine, *, company_id: UUID,
    name: str, email: str, phone: str, designation: str, is_primary: bool,
) -> None:
    exists = await _scalar(
        engine,
        "SELECT 1 FROM company_contacts WHERE company_id = :company_id "
        "AND email = :email",
        {"company_id": company_id, "email": email},
    )
    if exists:
        return
    await executor.run(
        "contact_create",
        ContactCreateInput(
            company_id=company_id,
            name=name,
            email=email,
            phone=phone,
            designation=designation,
            is_primary=is_primary,
        ),
        admin,
    )


async def _job(
    executor: Executor, staff: ActorContext, engine: AsyncEngine, *, cycle_id: UUID,
    company_id: UUID, title: str, description: str, outcome: Outcome | None,
    location: str, sector_id: UUID, ctc_lpa: str | None, stipend_month: str | None,
    deadline_days: int, program_ctc: list[ProgramCtcRow] | None = None,
) -> UUID:
    found = await _scalar(
        engine,
        "SELECT id FROM jobs WHERE cycle_id = :cycle_id AND title = :title "
        "AND company_id = :company_id",
        {"cycle_id": cycle_id, "title": title, "company_id": company_id},
    )
    if isinstance(found, UUID):
        return found
    result = await executor.run(
        "create_job",
        CreateJobInput(
            cycle_id=cycle_id,
            company_id=company_id,
            title=title,
            description=description,
            outcome=outcome,
            location=location,
            sector_id=sector_id,
            ctc_lpa=Decimal(ctc_lpa) if ctc_lpa else None,
            stipend_month=Decimal(stipend_month) if stipend_month else None,
            application_deadline=datetime.now(UTC) + timedelta(days=deadline_days),
            program_ctc=program_ctc or [],
        ),
        staff,
    )
    return UUID(str(result.summary["job_id"]))


async def _publish(
    executor: Executor, staff: ActorContext, engine: AsyncEngine, *, cycle_id: UUID,
    job_id: UUID,
) -> None:
    published = await _scalar(
        engine, "SELECT is_published FROM jobs WHERE id = :id", {"id": job_id}
    )
    if published:
        return
    await executor.run(
        "publish_job", PublishJobInput(cycle_id=cycle_id, job_id=job_id), staff
    )


async def _memberships(
    executor: Executor, engine: AsyncEngine, *, cycle_id: UUID,
    students: dict[str, ActorContext], emails: tuple[str, ...],
) -> None:
    """Join each named student to the cycle, skipping anyone already in it."""
    for email in emails:
        actor = students[email]
        exists = await _scalar(
            engine,
            "SELECT 1 FROM cycle_memberships WHERE cycle_id = :cycle_id "
            "AND enrollment_id = :enrollment_id",
            {"cycle_id": cycle_id, "enrollment_id": actor.current_enrollment_id},
        )
        if exists:
            continue
        resume_id = await _scalar(
            engine,
            "SELECT id FROM resumes WHERE enrollment_id = :id AND is_default",
            {"id": actor.current_enrollment_id},
        )
        if not isinstance(resume_id, UUID):
            raise RuntimeError(f"Seed student {email} has no default resume")
        await executor.run(
            "join_cycle",
            JoinCycleInput(
                cycle_id=cycle_id,
                enrollment_id=actor.current_enrollment_id,  # type: ignore[arg-type]
                default_resume_id=resume_id,
                consent=True,
            ),
            actor,
        )


async def _approve(
    executor: Executor, staff: ActorContext, engine: AsyncEngine, *, cycle_id: UUID,
    emails: tuple[str, ...],
) -> None:
    """Approve the named students, leaving everyone else in the queue.

    The approvals screen is worth nothing with an empty queue, so the seed
    deliberately approves only some of the cycle's pending requests.
    """
    pending = await _rows(
        engine,
        "SELECT m.id, u.email FROM cycle_memberships m "
        "JOIN enrollments e ON e.id = m.enrollment_id "
        "JOIN users u ON u.id = e.user_id "
        "WHERE m.cycle_id = :cycle_id AND m.status = 'pending'",
        {"cycle_id": cycle_id},
    )
    rows = [
        {"membership_id": str(row["id"])}
        for row in pending
        if str(row["email"]) in emails
    ]
    if not rows:
        return
    # The key covers the rows, not just the cycle: the seed re-runs against a
    # database whose queue has moved on, and a second batch under the same key
    # with a different membership set is an idempotency conflict, not a replay.
    digest = sha256(
        "".join(sorted(row["membership_id"] for row in rows)).encode()
    ).hexdigest()[:16]
    await executor.run_bulk(
        "approve_memberships",
        rows,  # type: ignore[arg-type]
        f"seed-approvals-{cycle_id}-{digest}",
        staff,
        batch_fields={"cycle_id": cycle_id},
    )

async def run_seed(
    *,
    database_url: str | None = None,
    settings: Settings | None = None,
    admin_email: str | None = None,
    admin_emails: tuple[str, ...] = (),
    include_e2e: bool = False,
    include_demo: bool = True,
) -> None:
    resolved_settings = settings or Settings.from_env()
    requested_admins = tuple(
        dict.fromkeys(item.strip().casefold() for item in admin_emails if item.strip())
    )
    email = (
        (requested_admins[0] if requested_admins else None)
        or admin_email
        or os.environ.get("SEED_ADMIN_EMAIL")
        or f"admin@{resolved_settings.allowed_domain}"
    ).strip().casefold()

    engine = create_engine(database_url)
    try:
        registry = build_registry(settings=resolved_settings)
        executor = build_executor(registry, engine)
        row = await _active_admin_row(engine)
        needs_first_admin = row is None
        if needs_first_admin:
            if not email_matches_domain(email, resolved_settings.allowed_domain):
                raise ValueError("Seed administrator must use the allowed institute domain")
            row = await _user_row(engine, email)
        login_email = email if row is None else str(row["email"])
        login_name = "CDS Administrator" if row is None else str(row["full_name"])
        if row is None or row["session_id"] is None:
            login_input = new_login_input(
                email=login_email,
                full_name=login_name,
                settings=resolved_settings,
            )
            await executor.run(
                "google_login",
                login_input,
                ActorContext(principal_id="seed", is_system=True),
            )
            row = await _user_row(engine, login_email)
        if row is None or not bool(row["is_active"]):
            raise RuntimeError("Seed administrator is unavailable or inactive")

        user_id = row["id"]
        session_id = row["session_id"]
        if not isinstance(user_id, UUID) or not isinstance(session_id, UUID):
            raise RuntimeError("Seed administrator identity is invalid")
        admin_actor = ActorContext(
            principal_id=str(user_id),
            user_id=user_id,
            role="admin",
            session_id=session_id,
        )
        if needs_first_admin:
            # Sanctioned authorization exception: only this non-HTTP seed entry point
            # may supply initial admin capability before any persisted admin exists.
            await executor.run(
                "set_user_role",
                SetUserRoleInput(user_id=user_id, role=Role.ADMIN),
                admin_actor,
            )

        # A clean production bootstrap may nominate more than one administrator
        # without loading the demonstration world. They are provisioned through
        # the same login command as every real account, then promoted by the
        # now-persisted first administrator.
        for requested_email in requested_admins:
            if not email_matches_domain(requested_email, resolved_settings.allowed_domain):
                raise ValueError("Seed administrators must use the allowed institute domain")
            admin_row = await _login(
                executor,
                engine,
                email=requested_email,
                full_name="CDS Administrator",
                settings=resolved_settings,
            )
            requested_id = admin_row["id"]
            if not isinstance(requested_id, UUID):
                raise RuntimeError(f"Seed administrator {requested_email} is invalid")
            await executor.run(
                "set_user_role",
                SetUserRoleInput(user_id=requested_id, role=Role.ADMIN),
                admin_actor,
            )

        taxonomy_ids: dict[tuple[TaxonomyKind, str], UUID] = {}

        async def upsert(
            kind: TaxonomyKind,
            name: str,
            *,
            branch_ids: list[UUID] | None = None,
        ) -> UUID:
            result = await executor.run(
                "upsert_taxonomy_item",
                UpsertTaxonomyItemInput(
                    kind=kind,
                    name=name,
                    branch_ids=branch_ids,
                ),
                admin_actor,
            )
            item_id = UUID(str(result.summary["item_id"]))
            taxonomy_ids[(kind, name)] = item_id
            return item_id

        for branch in BRANCHES:
            await upsert(TaxonomyKind.BRANCH, branch)
        for program, branches in PROGRAMS.items():
            await upsert(
                TaxonomyKind.PROGRAM,
                program,
                branch_ids=[
                    taxonomy_ids[(TaxonomyKind.BRANCH, branch)]
                    for branch in branches
                ],
            )
        for sector in SECTORS:
            await upsert(TaxonomyKind.SECTOR, sector)
        for round_type in ROUND_TYPES:
            await upsert(TaxonomyKind.ROUND_TYPE, round_type)
        for minor in MINORS:
            await upsert(TaxonomyKind.MINOR, minor)

        if include_demo:
            await _seed_world(
                executor,
                engine,
                admin_actor=admin_actor,
                taxonomy=taxonomy_ids,
                settings=resolved_settings,
                include_e2e=include_e2e,
            )
    finally:
        await engine.dispose()


async def _already_built(
    engine: AsyncEngine, *, table: str, job_id: UUID
) -> bool:
    """Has this job's builder tab already been filled?

    ``upsert_job_rounds`` and ``upsert_job_questions`` replace the whole set,
    and M9 blocks replacing a round an application already sits in or a question
    that already has answers (JOB-2).  Both are right to: the seed re-running is
    not a reason to move a student's pipeline position.  So the seed asks first,
    exactly as it does before joining a cycle or creating a company -- the
    alternative is a seed that works once and fails on every run after the first
    application exists.
    """
    return bool(
        await _scalar(
            engine,
            f"SELECT 1 FROM {table} WHERE job_id = :job_id LIMIT 1",  # noqa: S608
            {"job_id": job_id},
        )
    )


#: What each question type gets answered with when the seed applies.  Driven by
#: the type rather than by the question, so a builder edit in a later milestone
#: does not silently leave a required question unanswered and the seed failing.
def _seed_answer(qtype: QuestionType, options: tuple[str, ...], student: str) -> object:
    match qtype:
        case QuestionType.SINGLE:
            return options[0] if options else None
        case QuestionType.MULTI:
            return list(options[:2])
        case QuestionType.BOOLEAN:
            return True
        case QuestionType.NUMBER:
            return "2"
        case QuestionType.DATE:
            return "2026-06-01"
        case QuestionType.EMAIL:
            return student
        case QuestionType.URL:
            return "https://github.com/example/project"
        case QuestionType.TEXT:
            return "Distributed systems and databases."
        case QuestionType.LONGTEXT:
            return (
                "I ran the ingestion pipeline for a campus analytics project: "
                "two services, a Postgres primary with a read replica, and the "
                "on-call rota that came with it."
            )


async def _apply_as(
    executor: Executor,
    engine: AsyncEngine,
    *,
    cycle_id: UUID,
    title: str,
    actor: ActorContext,
) -> UUID:
    """File one application through APP-1, or skip if one already stands.

    The skip predicate is the partial-unique predicate, so a re-run leaves a
    live application alone while a withdrawn one is genuinely re-appliable --
    the same rule the command itself enforces.
    """
    job_id = await _scalar(
        engine,
        "SELECT id FROM jobs WHERE cycle_id = :cycle_id AND title = :title",
        {"cycle_id": cycle_id, "title": title},
    )
    if not isinstance(job_id, UUID):
        raise RuntimeError(f"Seed job {title!r} does not exist")
    standing = await _scalar(
        engine,
        "SELECT id FROM applications WHERE job_id = :job_id "
        "AND enrollment_id = :enrollment_id "
        "AND status NOT IN ('withdrawn', 'auto_withdrawn')",
        {"job_id": job_id, "enrollment_id": actor.current_enrollment_id},
    )
    if isinstance(standing, UUID):
        return standing
    questions = await _rows(
        engine,
        "SELECT q.id, q.qtype, coalesce("
        "  (SELECT array_agg(o.text ORDER BY o.ord) FROM job_question_options o "
        "   WHERE o.question_id = q.id), ARRAY[]::text[]) AS options "
        "FROM job_questions q WHERE q.job_id = :job_id ORDER BY q.ord",
        {"job_id": job_id},
    )
    result = await executor.run(
        "apply",
        ApplyInput(
            cycle_id=cycle_id,
            job_id=job_id,
            enrollment_id=cast(UUID, actor.current_enrollment_id),
            answers=[
                AnswerInput(
                    question_id=cast(UUID, row["id"]),
                    value=_seed_answer(
                        QuestionType(row["qtype"]),
                        tuple(cast("list[str]", row["options"] or [])),
                        str(actor.email),
                    ),
                )
                for row in questions
            ],
        ),
        actor,
    )
    if not isinstance(result, Result):
        raise RuntimeError("Seed apply cannot preview")
    return UUID(cast(str, result.summary["application_id"]))


async def _withdraw_from(
    executor: Executor,
    engine: AsyncEngine,
    *,
    cycle_id: UUID,
    title: str,
    actor: ActorContext,
) -> None:
    """Leave one withdrawn application behind (APP-3).

    The guard is "any application at all for this pair", not "a live one": after
    the withdrawal there is no live application, so the apply-then-withdraw pair
    would run again on every re-seed and stack up withdrawn rows.  The seed says
    what it wants -- one withdrawal on the record -- rather than replaying the
    steps that produced it.
    """
    job_id = await _scalar(
        engine,
        "SELECT id FROM jobs WHERE cycle_id = :cycle_id AND title = :title",
        {"cycle_id": cycle_id, "title": title},
    )
    if not isinstance(job_id, UUID):
        raise RuntimeError(f"Seed job {title!r} does not exist")
    existing = await _scalar(
        engine,
        "SELECT id FROM applications WHERE job_id = :job_id "
        "AND enrollment_id = :enrollment_id",
        {"job_id": job_id, "enrollment_id": actor.current_enrollment_id},
    )
    if isinstance(existing, UUID):
        return
    application_id = await _apply_as(
        executor, engine, cycle_id=cycle_id, title=title, actor=actor
    )
    await executor.run(
        "withdraw_application",
        WithdrawApplicationInput(
            cycle_id=cycle_id,
            enrollment_id=cast(UUID, actor.current_enrollment_id),
            application_id=application_id,
        ),
        actor,
    )


async def _round_op(
    executor: Executor,
    engine: AsyncEngine,
    *,
    cycle_id: UUID,
    title: str,
    email: str,
    operation: str,
    staff: ActorContext,
) -> None:
    """Run one board operation for one applicant, if it is not already done.

    Idempotency here is stated as a *target state*, not as a replayed step: the
    seed asks "is this applicant already past round one" rather than "have I run
    advance before", because running advance twice moves them two rounds and a
    seed that deepens the pipeline on every run is worse than one that fails.
    """
    row = await _rows(
        engine,
        "SELECT a.id, a.job_id, a.status, s.result, r.ord "
        "FROM applications a "
        "JOIN jobs j ON j.id = a.job_id "
        "JOIN enrollments e ON e.id = a.enrollment_id "
        "JOIN users u ON u.id = e.user_id "
        "LEFT JOIN job_rounds r ON r.id = a.current_round_id "
        "LEFT JOIN application_round_states s "
        "  ON s.application_id = a.id AND s.round_id = a.current_round_id "
        "WHERE j.cycle_id = :cycle_id AND j.title = :title AND u.email = :email",
        {"cycle_id": cycle_id, "title": title, "email": email},
    )
    if not row:
        raise RuntimeError(f"Seed applicant {email} has no application to {title!r}")
    current = row[0]
    if operation == "advance" and int(cast(int, current["ord"] or 0)) > 1:
        return
    if operation == "waitlist" and current["result"] == "waitlisted":
        return
    command = {
        "advance": "advance_applications",
        "waitlist": "waitlist_applications",
    }[operation]
    await executor.run_bulk(
        command,
        [{"application_id": str(current["id"])}],
        f"seed-{operation}-{current['id']}",
        staff,
        batch_fields={"cycle_id": cycle_id, "job_id": current["job_id"]},
    )


async def _round_position(
    engine: AsyncEngine, *, cycle_id: UUID, title: str, email: str, ord: int
) -> dict[str, object]:
    """One applicant's state in a named round, for the seed's target-state checks."""
    rows = await _rows(
        engine,
        "SELECT a.id AS application_id, r.id AS round_id, s.attendance, "
        "       s.venue_override, s.scheduled_at_override "
        "FROM applications a "
        "JOIN jobs j ON j.id = a.job_id "
        "JOIN enrollments e ON e.id = a.enrollment_id "
        "JOIN users u ON u.id = e.user_id "
        "JOIN job_rounds r ON r.job_id = j.id AND r.ord = :ord "
        "LEFT JOIN application_round_states s "
        "  ON s.application_id = a.id AND s.round_id = r.id "
        "WHERE j.cycle_id = :cycle_id AND j.title = :title AND u.email = :email",
        {"cycle_id": cycle_id, "title": title, "email": email, "ord": ord},
    )
    if not rows:
        raise RuntimeError(f"Seed applicant {email} has no round {ord} on {title!r}")
    return rows[0]


async def _bulk_present(
    executor: Executor,
    engine: AsyncEngine,
    *,
    cycle_id: UUID,
    title: str,
    identifiers: list[str],
    ord: int,
    staff: ActorContext,
) -> None:
    """The sheet a coordinator carries out of the room (RND-3).

    Safe to replay: a row already marked is a per-row skip, not an error, which
    is the same answer a coordinator pasting the sheet twice would get.
    """
    job_id = await _scalar(
        engine,
        "SELECT id FROM jobs WHERE cycle_id = :cycle_id AND title = :title",
        {"cycle_id": cycle_id, "title": title},
    )
    round_id = await _scalar(
        engine,
        "SELECT id FROM job_rounds WHERE job_id = :job_id AND ord = :ord",
        {"job_id": job_id, "ord": ord},
    )
    if not isinstance(round_id, UUID):
        raise RuntimeError(f"Seed job {title!r} has no round {ord}")
    await executor.run_bulk(
        "bulk_mark_present",
        [{"identifier": identifier} for identifier in identifiers],
        f"seed-present-{round_id}",
        staff,
        batch_fields={
            "cycle_id": cycle_id,
            "job_id": cast(UUID, job_id),
            "round_id": round_id,
        },
    )


async def _mark_attendance(
    executor: Executor,
    engine: AsyncEngine,
    *,
    cycle_id: UUID,
    title: str,
    email: str,
    ord: int,
    attendance: str,
    staff: ActorContext,
) -> None:
    """Set one applicant's attendance, unless it already says that (RND-3)."""
    position = await _round_position(
        engine, cycle_id=cycle_id, title=title, email=email, ord=ord
    )
    current = position["attendance"]
    if current is None or str(current) == attendance:
        return
    job_id = await _scalar(
        engine,
        "SELECT id FROM jobs WHERE cycle_id = :cycle_id AND title = :title",
        {"cycle_id": cycle_id, "title": title},
    )
    await executor.run(
        "mark_attendance",
        MarkAttendanceInput(
            cycle_id=cycle_id,
            job_id=cast(UUID, job_id),
            round_id=cast(UUID, position["round_id"]),
            application_id=cast(UUID, position["application_id"]),
            attendance=Attendance(attendance),
            expected_attendance=Attendance(str(current)),
        ),
        staff,
    )


async def _assign_slot(
    executor: Executor,
    engine: AsyncEngine,
    *,
    cycle_id: UUID,
    title: str,
    email: str,
    ord: int,
    venue: str,
    time: str,
    staff: ActorContext,
) -> None:
    """Publish one applicant's venue and time, unless it already stands (RND-4).

    Replaying would otherwise re-notify the student and flag the second mail as
    an update, which is the seed telling a lie about what happened.
    """
    position = await _round_position(
        engine, cycle_id=cycle_id, title=title, email=email, ord=ord
    )
    if position["venue_override"] == venue and position["scheduled_at_override"]:
        return
    job_id = await _scalar(
        engine,
        "SELECT id FROM jobs WHERE cycle_id = :cycle_id AND title = :title",
        {"cycle_id": cycle_id, "title": title},
    )
    await executor.run_bulk(
        "assign_venue_timing",
        [{"identifier": email, "venue": venue, "time": time}],
        f"seed-venue-{position['application_id']}-{ord}",
        staff,
        batch_fields={
            "cycle_id": cycle_id,
            "job_id": cast(UUID, job_id),
            "round_id": cast(UUID, position["round_id"]),
        },
    )


async def _seed_applications(
    executor: Executor,
    engine: AsyncEngine,
    *,
    students: dict[str, ActorContext],
    staff: ActorContext,
    placement_id: UUID,
    internship_id: UUID,
    open_id: UUID,
) -> None:
    """Applications, filed by the students themselves (APP-1).

    Students file them; the coordinator then moves some of them, exactly as
    both would in the app.  Attendance is still uniformly pending: marking it is
    M10c's command, and this module writes nothing by INSERT.

    Who applies is chosen so the screens have both answers to show: on the
    flagship job the two students its rule admits apply and the two it excludes
    do not, and the quant role takes only the one student clearing its floor.
    """
    await _apply_as(
        executor, engine, cycle_id=placement_id, title="Backend Engineer",
        actor=students["asha.mehta@example.edu"],
    )
    await _apply_as(
        executor, engine, cycle_id=placement_id, title="Backend Engineer",
        actor=students["bikram.singh@example.edu"],
    )
    # CPI floor 8.5: of the placement membership only Asha clears it, so the
    # quant pipeline is deliberately thin.
    await _apply_as(
        executor, engine, cycle_id=placement_id, title="Quantitative Researcher",
        actor=students["asha.mehta@example.edu"],
    )
    await _apply_as(
        executor, engine, cycle_id=internship_id, title="Software Engineering Intern",
        actor=students["esha.nair@example.edu"],
    )
    # JOB-6: an open-cycle application holds no round position at all, which is
    # the case every board and timeline has to render without a pipeline.
    await _apply_as(
        executor, engine, cycle_id=open_id, title="Campus Ambassador",
        actor=students["chitra.rao@example.edu"],
    )
    # The pipeline spread the ATS board exists to show: one applicant moved on
    # to the second round, one waitlisted where they are, one still sitting at
    # round one.  Possible for the first time now that the M10b operations
    # exist -- before them the seed could only ever produce round one.
    await _round_op(
        executor, engine, cycle_id=placement_id, title="Backend Engineer",
        email="asha.mehta@example.edu", operation="advance", staff=staff,
    )
    await _round_op(
        executor, engine, cycle_id=placement_id, title="Backend Engineer",
        email="bikram.singh@example.edu", operation="waitlist", staff=staff,
    )

    # A withdrawn application, so the dashboard has the state that reads as
    # "you left this one" and the slot it frees is visibly re-appliable.  It
    # belongs to the same student as the live ones on purpose: one sign-in
    # should show every state the applications screen can render, rather than
    # sending a developer round three accounts to see three cards.
    await _withdraw_from(
        executor, engine, cycle_id=open_id, title="Campus Ambassador",
        actor=students["asha.mehta@example.edu"],
    )

    # Attendance and venues, so the board is read against a marked sheet and
    # the M11 finalize card has one to finalize.  Both entry paths are
    # exercised, because both are what a coordinator actually uses: the paste
    # after a round, the single toggle for the one correction.  `excused` is
    # the one chip the seed cannot show -- it needs a fourth applicant in a
    # round, and inventing one to colour a chip would distort the eligibility
    # split the flagship job exists to demonstrate.
    await _bulk_present(
        executor, engine, cycle_id=placement_id, title="Backend Engineer",
        identifiers=["21110002"], ord=1, staff=staff,
    )
    await _mark_attendance(
        executor, engine, cycle_id=placement_id, title="Quantitative Researcher",
        email="asha.mehta@example.edu", ord=1, attendance="absent", staff=staff,
    )
    # Published slots on both rounds the flagship has people in, so the board
    # shows RND-1's per-student override next to the round's own default.  The
    # quant board deliberately keeps neither: a round with no venue published
    # yet is the state the venue panel exists to fix.
    await _assign_slot(
        executor, engine, cycle_id=placement_id, title="Backend Engineer",
        email="bikram.singh@example.edu", ord=1,
        venue="AB 1 / 101", time="2026-09-15 09:30", staff=staff,
    )
    await _assign_slot(
        executor, engine, cycle_id=placement_id, title="Backend Engineer",
        email="asha.mehta@example.edu", ord=2,
        venue="AB 5 / 204", time="2026-09-16 10:30", staff=staff,
    )


async def _seed_discipline(
    executor: Executor,
    engine: AsyncEngine,
    *,
    admin: ActorContext,
    staff: ActorContext,
    placement_id: UUID,
) -> None:
    """A closed round and a reconstructable record behind the DIS screen.

    Each M11 write path runs through its real command. Target-state checks make
    rerunning the seed a no-op rather than finalizing twice or growing the
    student's record on every developer restart.
    """
    job_id = await _scalar(
        engine,
        "SELECT id FROM jobs WHERE cycle_id = :cycle_id "
        "AND title = 'Quantitative Researcher'",
        {"cycle_id": placement_id},
    )
    round_id = await _scalar(
        engine,
        "SELECT id FROM job_rounds WHERE job_id = :job_id AND ord = 1",
        {"job_id": job_id},
    )
    finalized_at = await _scalar(
        engine,
        "SELECT finalized_at FROM job_rounds WHERE id = :id",
        {"id": round_id},
    )
    if finalized_at is None:
        await executor.run(
            "finalize_round",
            FinalizeRoundInput(
                cycle_id=placement_id,
                job_id=cast(UUID, job_id),
                round_id=cast(UUID, round_id),
            ),
            staff,
        )

    async def enrollment(email: str) -> UUID:
        value = await _scalar(
            engine,
            "SELECT e.id FROM enrollments e JOIN users u ON u.id = e.user_id "
            "WHERE u.email = :email AND e.is_current",
            {"email": email},
        )
        return cast(UUID, value)

    asha = await enrollment("asha.mehta@example.edu")
    manual_reason = "Missed the coordinator follow-up"
    if not await _scalar(
        engine,
        "SELECT 1 FROM strikes WHERE enrollment_id = :id AND reason = :reason",
        {"id": asha, "reason": manual_reason},
    ):
        # Together with finalization's absence strike this crosses the default
        # threshold, leaving one active converted penalty to demonstrate.
        await executor.run(
            "award_strike",
            AwardStrikeInput(enrollment_id=asha, reason=manual_reason),
            admin,
        )

    bikram = await enrollment("bikram.singh@example.edu")
    direct_reason = "Repeated failure to respond"
    penalty_id = await _scalar(
        engine,
        "SELECT id FROM penalties WHERE enrollment_id = :id AND reasons = :reason",
        {"id": bikram, "reason": direct_reason},
    )
    if not isinstance(penalty_id, UUID):
        await executor.run(
            "award_penalty",
            AwardPenaltyInput(enrollment_id=bikram, reasons=direct_reason),
            admin,
        )
        penalty_id = await _scalar(
            engine,
            "SELECT id FROM penalties WHERE enrollment_id = :id AND reasons = :reason",
            {"id": bikram, "reason": direct_reason},
        )
    penalty_active = await _scalar(
        engine,
        "SELECT is_active FROM penalties WHERE id = :id",
        {"id": penalty_id},
    )
    if penalty_active:
        await executor.run(
            "revoke_penalty",
            RevokePenaltyInput(
                penalty_id=cast(UUID, penalty_id),
                reason="Student supplied the missing response",
            ),
            admin,
        )

    dev = await enrollment("dev.patel@example.edu")
    corrected_reason = "Attendance sheet mismatch"
    strike = await _rows(
        engine,
        "SELECT id, is_active FROM strikes "
        "WHERE enrollment_id = :id AND reason = :reason",
        {"id": dev, "reason": corrected_reason},
    )
    if not strike:
        await executor.run(
            "award_strike",
            AwardStrikeInput(enrollment_id=dev, reason=corrected_reason),
            admin,
        )
        strike = await _rows(
            engine,
            "SELECT id, is_active FROM strikes "
            "WHERE enrollment_id = :id AND reason = :reason",
            {"id": dev, "reason": corrected_reason},
        )
    if bool(strike[0]["is_active"]):
        await executor.run(
            "revoke_strike",
            RevokeStrikeInput(
                strike_id=cast(UUID, strike[0]["id"]),
                reason="Corrected against the signed attendance sheet",
            ),
            admin,
        )


async def _seed_offers(
    executor: Executor,
    engine: AsyncEngine,
    *,
    admin: ActorContext,
    staff: ActorContext,
    students: dict[str, ActorContext],
    placement_id: UUID,
    internship_id: UUID,
) -> None:
    """Reach every M12 surface through its production command.

    The target states are intentionally different: current portal offers in
    offered, accepted, and terminated states; a re-extension with its declined
    predecessor intact; accepted and offered external records; an unattached
    PPO; and an accepted internship attachment that auto-created membership.
    The temporary accepted PPO for Asha executes a real placement cascade and
    then moves away from accepted while selecting restoration, leaving the
    evidence both previews reconstruct without leaving her demo account placed.
    """

    async def application(email: str, title: str) -> dict[str, object]:
        rows = await _rows(
            engine,
            "SELECT a.id, a.status, a.job_id, j.cycle_id FROM applications a "
            "JOIN jobs j ON j.id = a.job_id "
            "JOIN enrollments e ON e.id = a.enrollment_id "
            "JOIN users u ON u.id = e.user_id "
            "WHERE u.email = :email AND j.title = :title "
            "ORDER BY a.applied_at DESC, a.id DESC LIMIT 1",
            {"email": email, "title": title},
        )
        if not rows:
            raise RuntimeError(f"Seed offer application {email} / {title} is absent")
        return rows[0]

    async def latest_offer(application_id: UUID) -> dict[str, object] | None:
        rows = await _rows(
            engine,
            "SELECT id, response, terminated_at, deadline_at FROM offers "
            "WHERE application_id = :id ORDER BY extended_at DESC, id DESC LIMIT 1",
            {"id": application_id},
        )
        return rows[0] if rows else None

    async def extend_if_needed(row: dict[str, object], key: str) -> None:
        if row["status"] not in {"in_progress", "pending_offer"}:
            return
        await executor.run_bulk(
            "extend_offers",
            [{"application_id": str(row["id"]), "expected_status": str(row["status"])}],
            key,
            staff,
            batch_fields={"cycle_id": row["cycle_id"], "job_id": row["job_id"]},
        )

    # A real external placement cascade followed by selective restoration.
    asha = students["asha.mehta@example.edu"]
    asha_backend = await application(asha.email or "", "Backend Engineer")
    northwind = await _scalar(
        engine, "SELECT id FROM companies WHERE name = 'Northwind Systems'", {}
    )
    if not isinstance(northwind, UUID):
        raise RuntimeError("Northwind Systems is absent from the seed")

    async def external(
        *,
        marker: str,
        actor: ActorContext,
        outcome: Outcome,
        source: ExternalSource,
        status: ExternalStatus,
        company_id: UUID = northwind,
    ) -> UUID:
        found = await _scalar(
            engine,
            "SELECT id FROM external_offers WHERE enrollment_id = :enrollment AND notes = :marker",
            {"enrollment": actor.current_enrollment_id, "marker": marker},
        )
        if isinstance(found, UUID):
            return found
        result = await executor.run(
            "create_external_offer",
            CreateExternalOfferInput(
                enrollment_id=cast(UUID, actor.current_enrollment_id),
                company_id=company_id,
                outcome=outcome,
                source=source,
                status=status,
                notes=marker,
                reason=f"Development seed: {marker}",
                notify=True,
            ),
            admin,
        )
        return UUID(cast(str, result.summary["external_offer_id"]))

    asha_cascade = await external(
        marker="seed: accepted PPO cascade then corrected",
        actor=asha,
        outcome=Outcome.PLACEMENT,
        source=ExternalSource.PPO,
        status=ExternalStatus.ACCEPTED,
    )
    asha_external_status = await _scalar(
        engine, "SELECT status FROM external_offers WHERE id = :id", {"id": asha_cascade}
    )
    if asha_external_status == ExternalStatus.ACCEPTED.value:
        await executor.run(
            "update_external_offer",
            UpdateExternalOfferInput(
                external_offer_id=asha_cascade,
                expected_status=ExternalStatus.ACCEPTED,
                status=ExternalStatus.DECLINED,
                restore=[RestoreSelection(application_id=cast(UUID, asha_backend["id"]))],
                reason="Development seed correction with restoration",
                notify=True,
            ),
            admin,
        )

    # The restored application is terminated pre-acceptance, leaving OFR-5's
    # offered -> terminated state and intervention available in history.
    asha_backend = await application(asha.email or "", "Backend Engineer")
    await extend_if_needed(asha_backend, f"seed-offer-asha-{asha_backend['id']}")
    asha_backend = await application(asha.email or "", "Backend Engineer")
    if asha_backend["status"] == ApplicationStatus.OFFERED.value:
        current = await latest_offer(cast(UUID, asha_backend["id"]))
        if current is not None and current["terminated_at"] is None:
            await executor.run(
                "terminate_offer",
                TerminateOfferInput(
                    cycle_id=cast(UUID, asha_backend["cycle_id"]),
                    job_id=cast(UUID, asha_backend["job_id"]),
                    application_id=cast(UUID, asha_backend["id"]),
                    offer_id=cast(UUID, current["id"]),
                    expected_status=ApplicationStatus.OFFERED,
                    termination_kind=TerminationKind.COMPANY_REVOKED,
                    reason="Development seed: company withdrew the role",
                    notify=True,
                ),
                staff,
            )

    # Esha has the straightforward unanswered offer students act on.
    esha = students["esha.nair@example.edu"]
    esha_intern = await application(esha.email or "", "Software Engineering Intern")
    await extend_if_needed(esha_intern, f"seed-offer-esha-{esha_intern['id']}")

    # Bikram's current offer is a re-extension; the original row stays declined.
    bikram = students["bikram.singh@example.edu"]
    bikram_backend = await application(bikram.email or "", "Backend Engineer")
    await extend_if_needed(bikram_backend, f"seed-offer-bikram-{bikram_backend['id']}")
    bikram_backend = await application(bikram.email or "", "Backend Engineer")
    current = await latest_offer(cast(UUID, bikram_backend["id"]))
    if bikram_backend["status"] == ApplicationStatus.OFFERED.value and current is not None:
        count = await _scalar(
            engine,
            "SELECT count(*) FROM offers WHERE application_id = :id",
            {"id": bikram_backend["id"]},
        )
        if int(cast(int, count)) == 1:
            await executor.run(
                "decline_offer",
                OfferResponseInput(
                    cycle_id=cast(UUID, bikram_backend["cycle_id"]),
                    job_id=cast(UUID, bikram_backend["job_id"]),
                    application_id=cast(UUID, bikram_backend["id"]),
                    offer_id=cast(UUID, current["id"]),
                    enrollment_id=cast(UUID, bikram.current_enrollment_id),
                    expected_status=ApplicationStatus.OFFERED,
                ),
                bikram,
            )
    bikram_backend = await application(bikram.email or "", "Backend Engineer")
    if bikram_backend["status"] == ApplicationStatus.DECLINED.value:
        current = await latest_offer(cast(UUID, bikram_backend["id"]))
        if current is not None:
            await executor.run(
                "re_extend_offer",
                ReExtendOfferInput(
                    cycle_id=cast(UUID, bikram_backend["cycle_id"]),
                    job_id=cast(UUID, bikram_backend["job_id"]),
                    application_id=cast(UUID, bikram_backend["id"]),
                    offer_id=cast(UUID, current["id"]),
                    expected_status=ApplicationStatus.DECLINED,
                    reason="Development seed: office granted more response time",
                    notify=True,
                ),
                staff,
            )

    # Farhan applies, receives, and accepts an internship offer.
    farhan = students["farhan.khan@example.edu"]
    await _apply_as(
        executor,
        engine,
        cycle_id=internship_id,
        title="Software Engineering Intern",
        actor=farhan,
    )
    farhan_intern = await application(farhan.email or "", "Software Engineering Intern")
    await extend_if_needed(farhan_intern, f"seed-offer-farhan-{farhan_intern['id']}")
    farhan_intern = await application(farhan.email or "", "Software Engineering Intern")
    if farhan_intern["status"] == ApplicationStatus.OFFERED.value:
        current = await latest_offer(cast(UUID, farhan_intern["id"]))
        if current is not None:
            await executor.run(
                "accept_offer",
                OfferResponseInput(
                    cycle_id=cast(UUID, farhan_intern["cycle_id"]),
                    job_id=cast(UUID, farhan_intern["job_id"]),
                    application_id=cast(UUID, farhan_intern["id"]),
                    offer_id=cast(UUID, current["id"]),
                    enrollment_id=cast(UUID, farhan.current_enrollment_id),
                    expected_status=ApplicationStatus.OFFERED,
                ),
                farhan,
            )

    # Accepted placement gates immediately while unattached.
    dev = students["dev.patel@example.edu"]
    await external(
        marker="seed: accepted unattached off-campus placement",
        actor=dev,
        outcome=Outcome.PLACEMENT,
        source=ExternalSource.OFF_CAMPUS,
        status=ExternalStatus.ACCEPTED,
    )

    # Chitra has no internship membership; attaching this accepted record must
    # create one active auto_created membership and consume her cap.
    chitra = students["chitra.rao@example.edu"]
    attached = await external(
        marker="seed: accepted attached external internship",
        actor=chitra,
        outcome=Outcome.INTERNSHIP,
        source=ExternalSource.OFF_CAMPUS,
        status=ExternalStatus.ACCEPTED,
    )
    attached_cycle = await _scalar(
        engine,
        "SELECT attached_cycle_id FROM external_offers WHERE id = :id",
        {"id": attached},
    )
    if attached_cycle is None:
        await executor.run(
            "attach_external_offer",
            AttachExternalOfferInput(
                cycle_id=internship_id,
                external_offer_id=attached,
                expected_attached_cycle_id=None,
                reason="Development seed: attach matching internship record",
            ),
            staff,
        )

    # One ordinary PPO remains offered in the unattached pool.
    await external(
        marker="seed: offered PPO waiting for placement attachment",
        actor=esha,
        outcome=Outcome.PLACEMENT,
        source=ExternalSource.PPO,
        status=ExternalStatus.OFFERED,
    )

    # M15: the placement cycle needs a placement that came from *outside* the
    # portal, or its ANA-1 split is entirely on-campus and a dashboard reading
    # zero externals cannot be told apart from one whose attachment scoping is
    # broken. Being a PPO rather than off-campus, it also fills the bucket
    # ANA-1 names first.
    #
    # It goes to Chitra rather than Farhan deliberately. Farhan holds the only
    # accepted *portal* offer in the seed, and the design review 4.30e attributes a
    # student with several acceptances to their most recent one -- so giving
    # him a newer external would move him out of the on-campus bucket and leave
    # the portal half of the split empty everywhere. Chitra's other acceptance
    # is an internship in a different cycle, so both halves stay populated.
    chitra_ppo = await external(
        marker="seed: accepted PPO attached to the placement cycle",
        actor=chitra,
        outcome=Outcome.PLACEMENT,
        source=ExternalSource.PPO,
        status=ExternalStatus.ACCEPTED,
    )
    chitra_ppo_cycle = await _scalar(
        engine,
        "SELECT attached_cycle_id FROM external_offers WHERE id = :id",
        {"id": chitra_ppo},
    )
    if chitra_ppo_cycle is None:
        await executor.run(
            "attach_external_offer",
            AttachExternalOfferInput(
                cycle_id=placement_id,
                external_offer_id=chitra_ppo,
                expected_attached_cycle_id=None,
                reason="Development seed: attach accepted PPO to the placement cycle",
            ),
            staff,
        )


async def _seed_world(
    executor: Executor,
    engine: AsyncEngine,
    *,
    admin_actor: ActorContext,
    taxonomy: dict[tuple[TaxonomyKind, str], UUID],
    settings: Settings,
    include_e2e: bool,
) -> None:
    """Everything past the taxonomies: people, cycles, companies, and jobs."""
    await executor.run(
        "set_setting",
        SetSettingInput(
            key=SettingKey.SES_SENDER,
            value=(
                os.environ.get("SES_SENDER", "").strip()
                or "CDS noreply <noreply@cdsportal.example.edu>"
            ),
        ),
        admin_actor,
    )
    students = await _seed_students(
        executor, engine, taxonomy=taxonomy, settings=settings
    )
    coordinator = await _login(
        executor,
        engine,
        email=COORDINATOR_EMAIL,
        full_name=COORDINATOR_NAME,
        settings=settings,
    )
    coordinator_user_id = coordinator["id"]
    coordinator_session_id = coordinator["session_id"]
    if not isinstance(coordinator_user_id, UUID) or not isinstance(
        coordinator_session_id, UUID
    ):
        raise RuntimeError("Seed coordinator has no usable session")

    placement_id = await _cycle(
        executor,
        admin_actor,
        engine,
        name="Placement 2026",
        kind=CycleKind.PLACEMENT,
        description="Final-year placement cycle for the 2026 graduating batch.",
        opens_days=-14,
        closes_days=45,
    )
    internship_id = await _cycle(
        executor,
        admin_actor,
        engine,
        name="Summer Internship 2026",
        kind=CycleKind.INTERNSHIP,
        description="Summer internship cycle for pre-final-year students.",
        opens_days=-7,
        closes_days=60,
    )
    open_id = await _cycle(
        executor,
        admin_actor,
        engine,
        name="Open Opportunities",
        kind=CycleKind.OPEN,
        description="Off-cycle roles that need no rounds and no approval.",
        opens_days=-30,
        closes_days=300,
    )

    # The placement cycle is the one the UI is meant to be explored through, so
    # it is the one that gets a coordinator, a queue, and a full job. Avoid a
    # no-op policy command on re-seed: even a same-value update is an audit row.
    placement_policy_matches = await _scalar(
        engine,
        "SELECT EXISTS (SELECT 1 FROM cycle_policies WHERE cycle_id = :cycle_id "
        "AND membership_requires_approval AND max_accepted_offers = 1 "
        "AND penalty_blocks_applications AND NOT allow_withdrawal_after_deadline)",
        {"cycle_id": placement_id},
    )
    if not placement_policy_matches:
        await executor.run(
            "update_cycle_policy",
            UpdateCyclePolicyInput(
                cycle_id=placement_id,
                membership_requires_approval=True,
                max_accepted_offers=1,
                penalty_blocks_applications=True,
                allow_withdrawal_after_deadline=False,
            ),
            admin_actor,
        )
    # Two cycles, not three: the open cycle is left to the admin, so the seeded
    # world contains a cycle the coordinator provably cannot touch.
    for coordinated in (placement_id, internship_id):
        assigned = await _scalar(
            engine,
            "SELECT 1 FROM cycle_coordinators WHERE cycle_id = :cycle_id "
            "AND user_id = :user_id",
            {"cycle_id": coordinated, "user_id": coordinator_user_id},
        )
        if not assigned:
            await executor.run(
                "assign_coordinator",
                CoordinatorInput(cycle_id=coordinated, user_id=coordinator_user_id),
                admin_actor,
            )
    staff_actor = ActorContext(
        principal_id=str(coordinator_user_id),
        user_id=coordinator_user_id,
        role="student",
        session_id=coordinator_session_id,
        coordinated_cycle_ids=(placement_id, internship_id),
        email=COORDINATOR_EMAIL,
        full_name=COORDINATOR_NAME,
    )

    everyone = tuple(student.email for student in STUDENTS)
    await _memberships(
        executor, engine, cycle_id=placement_id, students=students, emails=everyone
    )
    # Four in, two left waiting: the approvals queue has to have rows in it.
    await _approve(
        executor,
        staff_actor,
        engine,
        cycle_id=placement_id,
        emails=everyone[:4],
    )
    # The internship cycle takes the two students the placement queue is still
    # holding, so a student account exists that is active in one cycle and
    # waiting in another -- which is what the joinable screen has to render.
    await _memberships(
        executor, engine, cycle_id=internship_id, students=students, emails=everyone[3:]
    )
    await _approve(
        executor, staff_actor, engine, cycle_id=internship_id, emails=everyone[3:]
    )
    await _memberships(
        executor, engine, cycle_id=open_id, students=students, emails=everyone[:3]
    )

    await _seed_companies_and_jobs(
        executor,
        engine,
        admin_actor=admin_actor,
        staff_actor=staff_actor,
        taxonomy=taxonomy,
        placement_id=placement_id,
        internship_id=internship_id,
        open_id=open_id,
    )

    await _seed_applications(
        executor,
        engine,
        students=students,
        staff=staff_actor,
        placement_id=placement_id,
        internship_id=internship_id,
        open_id=open_id,
    )
    await _seed_discipline(
        executor,
        engine,
        admin=admin_actor,
        staff=staff_actor,
        placement_id=placement_id,
    )
    await _seed_offers(
        executor,
        engine,
        admin=admin_actor,
        staff=staff_actor,
        students=students,
        placement_id=placement_id,
        internship_id=internship_id,
    )
    await _seed_outcome_tags(
        executor,
        engine,
        staff=staff_actor,
        students=students,
        placement_id=placement_id,
    )
    await _seed_interventions(
        executor,
        engine,
        admin=admin_actor,
        staff=staff_actor,
        students=students,
        placement_id=placement_id,
        taxonomy=taxonomy,
    )
    if include_e2e:
        await _seed_e2e_scenarios(
            executor,
            engine,
            staff=staff_actor,
            students=students,
            placement_id=placement_id,
            taxonomy=taxonomy,
            settings=settings,
        )


async def _seed_e2e_scenarios(
    executor: Executor,
    engine: AsyncEngine,
    *,
    staff: ActorContext,
    students: dict[str, ActorContext],
    placement_id: UUID,
    taxonomy: dict[tuple[TaxonomyKind, str], UUID],
    settings: Settings,
) -> None:
    """Minimal mutable cohort shared by F5's three serial browser flows.

    The standard development world stays untouched unless ``include_e2e`` is
    explicit.  Setup still uses production commands: the journey student has
    no membership yet, while the two bulk-board applicants begin in round one.
    """
    await _seed_students(
        executor,
        engine,
        taxonomy=taxonomy,
        settings=settings,
        roster=(E2E_STUDENT,),
    )

    company_id = await _scalar(
        engine,
        "SELECT id FROM companies WHERE name = 'Northwind Systems'",
        {},
    )
    if not isinstance(company_id, UUID):
        raise RuntimeError("E2E seed company is absent")
    job_id = await _job(
        executor,
        staff,
        engine,
        cycle_id=placement_id,
        company_id=company_id,
        title="Platform Engineer",
        description="Build the platform used by every product engineering team.",
        outcome=Outcome.PLACEMENT,
        location="Bengaluru",
        sector_id=taxonomy[(TaxonomyKind.SECTOR, "Technology")],
        ctc_lpa="26.00",
        stipend_month=None,
        deadline_days=30,
    )
    if not await _already_built(engine, table="job_rounds", job_id=job_id):
        await executor.run(
            "upsert_job_rounds",
            UpsertJobRoundsInput(
                cycle_id=placement_id,
                job_id=job_id,
                rounds=[
                    JobRoundRow(
                        round_type_id=taxonomy[
                            (TaxonomyKind.ROUND_TYPE, "Technical Interview")
                        ],
                        name="Platform Interview",
                        duration_min=60,
                    )
                ],
            ),
            staff,
        )
    await _publish(executor, staff, engine, cycle_id=placement_id, job_id=job_id)

    bulk_emails = ("esha.nair@example.edu", "farhan.khan@example.edu")
    await _approve(
        executor,
        staff,
        engine,
        cycle_id=placement_id,
        emails=bulk_emails,
    )
    for email in bulk_emails:
        await _apply_as(
            executor,
            engine,
            cycle_id=placement_id,
            title="Platform Engineer",
            actor=students[email],
        )


async def _seed_outcome_tags(
    executor: Executor,
    engine: AsyncEngine,
    *,
    staff: ActorContext,
    students: dict[str, ActorContext],
    placement_id: UUID,
) -> None:
    """ANA-3's honest denominators, on real memberships.

    Without a tagged member the canned report's higher-studies column is zero
    everywhere and the seeking-only rate is identical to the flat one, so the
    two denominators the report exists to distinguish cannot be told apart on
    the seeded dashboard.  Two members are tagged: one leaving for higher
    studies, one not seeking placement at all.
    """
    tags = (
        ("bikram.singh@example.edu", OutcomeTag.HIGHER_STUDIES),
        ("esha.nair@example.edu", OutcomeTag.NOT_SEEKING),
    )
    for email, tag in tags:
        actor = students[email]
        membership = await _scalar(
            engine,
            "SELECT id FROM cycle_memberships "
            "WHERE cycle_id = :cycle AND enrollment_id = :enrollment",
            {"cycle": placement_id, "enrollment": actor.current_enrollment_id},
        )
        if not isinstance(membership, UUID):
            continue
        current = await _scalar(
            engine,
            "SELECT outcome_tag FROM cycle_memberships WHERE id = :id",
            {"id": membership},
        )
        if current is not None:
            continue
        await executor.run(
            "set_outcome_tag",
            SetOutcomeTagInput(
                cycle_id=placement_id,
                membership_id=membership,
                outcome_tag=tag,
            ),
            staff,
        )


async def _seed_interventions(
    executor: Executor,
    engine: AsyncEngine,
    *,
    admin: ActorContext,
    staff: ActorContext,
    students: dict[str, ActorContext],
    placement_id: UUID,
    taxonomy: dict[tuple[TaxonomyKind, str], UUID],
) -> None:
    """The M14 surfaces: standing overrides, a real finding, and a stale snapshot.

    Everything here runs through a production command, including the finding:
    the seed does not plant corruption, it *earns* one.  A student is offered a
    role in an auto-accepting cycle and then leaves the cycle; when the response
    deadline passes, OFR-4's fire-time revalidation finds the membership gone,
    falls back to declining, and records the finding naming the gate that
    failed. The admin then closes that expected intervention through the real
    verdict command, leaving useful history without an open launch finding.
    """
    asha = students["asha.mehta@example.edu"]
    farhan = students["farhan.khan@example.edu"]

    # 1. Two overrides, so the register renders a live grant and a revoked one.
    late_reason = "Company extended their own deadline by a day"
    override_id = await _scalar(
        engine,
        "SELECT id FROM overrides WHERE cycle_id = :cycle_id AND reason = :reason",
        {"cycle_id": placement_id, "reason": late_reason},
    )
    if not isinstance(override_id, UUID):
        await executor.run(
            "create_override",
            CreateOverrideInput(
                rule_domain=RuleDomain.APPLICATION_DEADLINE,
                cycle_id=placement_id,
                reason=late_reason,
                expires_at=datetime.now(UTC) + timedelta(days=14),
            ),
            admin,
        )
    revoked_reason = "Cap frozen while external offers were reconciled"
    revoked_id = await _scalar(
        engine,
        "SELECT id FROM overrides WHERE cycle_id = :cycle_id AND reason = :reason",
        {"cycle_id": placement_id, "reason": revoked_reason},
    )
    if not isinstance(revoked_id, UUID):
        created = await executor.run(
            "create_override",
            CreateOverrideInput(
                rule_domain=RuleDomain.OFFER_CAP,
                cycle_id=placement_id,
                reason=revoked_reason,
            ),
            admin,
        )
        revoked_id = UUID(str(created.summary["override_id"]))
    if await _scalar(
        engine, "SELECT is_active FROM overrides WHERE id = :id", {"id": revoked_id}
    ):
        await executor.run(
            "deactivate_override",
            DeactivateOverrideInput(
                override_id=revoked_id,
                reason="External offers reconciled; the cap applies again",
            ),
            admin,
        )

    # 2. An auto-accepting cycle whose expiry falls back to declining.
    winter_id = await _cycle(
        executor,
        admin,
        engine,
        name="Winter Internship 2026",
        kind=CycleKind.INTERNSHIP,
        description="A short winter cohort that accepts unanswered offers automatically.",
        opens_days=-20,
        closes_days=40,
    )
    winter_policy_matches = await _scalar(
        engine,
        "SELECT EXISTS (SELECT 1 FROM cycle_policies WHERE cycle_id = :cycle_id "
        "AND NOT membership_requires_approval "
        "AND offer_expiry_behavior = 'auto_accept')",
        {"cycle_id": winter_id},
    )
    if not winter_policy_matches:
        await executor.run(
            "update_cycle_policy",
            UpdateCyclePolicyInput(
                cycle_id=winter_id,
                membership_requires_approval=False,
                offer_expiry_behavior=OfferExpiry.AUTO_ACCEPT,
            ),
            admin,
        )
    company_id = await _scalar(
        engine,
        "SELECT id FROM companies WHERE name = :name",
        {"name": "Helios Analytics"},
    )
    if not isinstance(company_id, UUID):
        raise RuntimeError("Seed company for the winter cohort is absent")
    job_id = await _job(
        executor,
        # The demo coordinator runs the placement cycle only, and this cohort is
        # deliberately somebody else's: an administrator does the staff work.
        admin,
        engine,
        cycle_id=winter_id,
        company_id=company_id,
        title="Winter Research Intern",
        description="Six-week winter research internship with the systems group.",
        outcome=Outcome.INTERNSHIP,
        location="Gandhinagar",
        sector_id=taxonomy[(TaxonomyKind.SECTOR, "Technology")],
        ctc_lpa=None,
        stipend_month="45000",
        deadline_days=20,
    )
    if not await _already_built(engine, table="job_rounds", job_id=job_id):
        await executor.run(
            "upsert_job_rounds",
            UpsertJobRoundsInput(
                cycle_id=winter_id,
                job_id=job_id,
                rounds=[
                    JobRoundRow(
                        round_type_id=taxonomy[
                            (TaxonomyKind.ROUND_TYPE, "Technical Interview")
                        ],
                        name="Research Discussion",
                        venue="AB 1 / 306",
                        duration_min=45,
                    )
                ],
            ),
            admin,
        )
    await _publish(executor, admin, engine, cycle_id=winter_id, job_id=job_id)
    await _memberships(
        executor,
        engine,
        cycle_id=winter_id,
        students=students,
        emails=("farhan.khan@example.edu",),
    )
    application_id = await _apply_as(
        executor,
        engine,
        cycle_id=winter_id,
        title="Winter Research Intern",
        actor=farhan,
    )
    offer = await _rows(
        engine,
        "SELECT id, response, deadline_at FROM offers WHERE application_id = :id "
        "ORDER BY extended_at DESC LIMIT 1",
        {"id": application_id},
    )
    if not offer:
        await executor.run(
            "update_job_basics",
            UpdateJobBasicsInput(
                cycle_id=winter_id,
                job_id=job_id,
                offer_acceptance_deadline=datetime.now(UTC) + timedelta(days=25),
            ),
            admin,
        )
        await executor.run_bulk(
            "extend_offers",
            [{"application_id": str(application_id), "expected_status": "in_progress"}],
            f"seed-winter-offer-{application_id}",
            admin,
            batch_fields={"cycle_id": winter_id, "job_id": job_id},
        )
        # JOB-3 propagates the move to the unanswered offer and reschedules its
        # expiry, so the offer's own deadline is the one that has now passed.
        await executor.run(
            "update_job_basics",
            UpdateJobBasicsInput(
                cycle_id=winter_id,
                job_id=job_id,
                application_deadline=datetime.now(UTC) - timedelta(days=2),
                offer_acceptance_deadline=datetime.now(UTC) - timedelta(days=1),
            ),
            admin,
        )
        offer = await _rows(
            engine,
            "SELECT id, response, deadline_at FROM offers WHERE application_id = :id "
            "ORDER BY extended_at DESC LIMIT 1",
            {"id": application_id},
        )
    membership_status = await _scalar(
        engine,
        "SELECT status FROM cycle_memberships WHERE cycle_id = :cycle_id "
        "AND enrollment_id = :enrollment_id",
        {"cycle_id": winter_id, "enrollment_id": farhan.current_enrollment_id},
    )
    if membership_status == MembershipStatus.ACTIVE.value:
        # CYC-4: an offered application is outside APP-4.13, so leaving the
        # cycle does not withdraw it -- which is exactly the state that makes
        # the auto-accept revalidation fail at fire time.
        await executor.run(
            "withdraw_membership",
            WithdrawMembershipInput(
                cycle_id=winter_id,
                enrollment_id=cast(UUID, farhan.current_enrollment_id),
            ),
            farhan,
        )
    if offer and offer[0]["response"] is None and offer[0]["deadline_at"] is not None:
        await executor.run(
            "enforce_offer_expiry",
            EnforceOfferExpiryInput(
                offer_id=cast(UUID, offer[0]["id"]),
                scheduled_deadline=cast(datetime, offer[0]["deadline_at"]),
            ),
            ActorContext(principal_id="seed", is_system=True),
        )
    finding = await _rows(
        engine,
        "SELECT id, status FROM consistency_findings "
        "WHERE invariant = 'offer_expiry_auto_accept_gate_failed'",
        {},
    )
    if finding and finding[0]["status"] == "open":
        await executor.run(
            "resolve_finding",
            ResolveFindingInput(
                finding_id=cast(UUID, finding[0]["id"]),
                reason="Expected demo fallback reviewed; no data repair is required",
            ),
            admin,
        )

    # 3. A profile corrected after the fact, so the drill-down's snapshot diff
    #    has something real to show: the application was judged on the old CPI.
    live_cpi = await _scalar(
        engine,
        "SELECT cpi FROM profiles WHERE enrollment_id = :id",
        {"id": asha.current_enrollment_id},
    )
    if str(live_cpi) != "9.12":
        await executor.run(
            "admin_update_profile",
            AdminUpdateProfileInput(
                enrollment_id=cast(UUID, asha.current_enrollment_id),
                fields={"cpi": "9.12"},
            ),
            admin,
        )


async def _seed_companies_and_jobs(
    executor: Executor,
    engine: AsyncEngine,
    *,
    admin_actor: ActorContext,
    staff_actor: ActorContext,
    taxonomy: dict[tuple[TaxonomyKind, str], UUID],
    placement_id: UUID,
    internship_id: UUID,
    open_id: UUID,
) -> None:
    """Companies, their contacts, and one job per state the builder can show."""
    technology = taxonomy[(TaxonomyKind.SECTOR, "Technology")]
    consulting = taxonomy[(TaxonomyKind.SECTOR, "Consulting")]
    finance = taxonomy[(TaxonomyKind.SECTOR, "Finance")]
    btech = taxonomy[(TaxonomyKind.PROGRAM, "BTech")]
    mtech = taxonomy[(TaxonomyKind.PROGRAM, "MTech")]
    cse = taxonomy[(TaxonomyKind.BRANCH, "Computer Science and Engineering")]
    electrical = taxonomy[(TaxonomyKind.BRANCH, "Electrical Engineering")]
    interview = taxonomy[(TaxonomyKind.ROUND_TYPE, "Technical Interview")]
    aptitude = taxonomy[(TaxonomyKind.ROUND_TYPE, "Aptitude Test")]
    hr_round = taxonomy[(TaxonomyKind.ROUND_TYPE, "HR Interview")]

    northwind = await _company(
        executor,
        admin_actor,
        engine,
        name="Northwind Systems",
        description="Distributed storage and query engines.",
        website_url="https://northwind.example.com",
        sector_id=technology,
    )
    await _contact(
        executor, admin_actor, engine, company_id=northwind,
        name="Rita Rao", email="rita.rao@northwind.example.com",
        phone="+1 202-555-0161", designation="Campus Lead", is_primary=True,
    )
    await _contact(
        executor, admin_actor, engine, company_id=northwind,
        name="Samir Bose", email="samir.bose@northwind.example.com",
        phone="+1 202-555-0162", designation="Engineering Manager", is_primary=False,
    )

    # A near-duplicate, so merge_companies has something real to preview --
    # including a contact that will be dropped for colliding on email, which is
    # the half of the merge payload worth looking at.
    northwind_dup = await _company(
        executor,
        admin_actor,
        engine,
        name="Northwind Systems India",
        description="Duplicate record created by a second coordinator.",
        website_url="https://northwind.example.com",
        sector_id=technology,
    )
    await _contact(
        executor, admin_actor, engine, company_id=northwind_dup,
        name="Rita Rao", email="rita.rao@northwind.example.com",
        phone="+1 202-555-0163", designation="Head of Campus", is_primary=True,
    )
    await _contact(
        executor, admin_actor, engine, company_id=northwind_dup,
        name="Tara Iyer", email="tara.iyer@northwind.example.com",
        phone="+1 202-555-0164", designation="Recruiter", is_primary=False,
    )

    helios = await _company(
        executor, admin_actor, engine,
        name="Helios Analytics",
        description="Quantitative research and trading systems.",
        website_url="https://helios.example.com",
        sector_id=finance,
    )
    await _contact(
        executor, admin_actor, engine, company_id=helios,
        name="Vikram Desai", email="vikram@helios.example.com",
        phone="+1 202-555-0165", designation="Partner", is_primary=True,
    )
    meridian = await _company(
        executor, admin_actor, engine,
        name="Meridian Consulting",
        description="Strategy and operations consulting.",
        website_url="https://meridian.example.com",
        sector_id=consulting,
    )
    await _contact(
        executor, admin_actor, engine, company_id=meridian,
        name="Ananya Gupta", email="ananya@meridian.example.com",
        phone="+1 202-555-0166", designation="Recruiting Manager", is_primary=True,
    )

    # The flagship: published, all four builder tabs populated, and a rule that
    # part of the seeded membership fails so the impact preview is not unanimous.
    backend = await _job(
        executor, staff_actor, engine,
        cycle_id=placement_id, company_id=northwind,
        title="Backend Engineer",
        description=(
            "Build and operate the storage layer: distributed systems work in "
            "Go and Rust, with real on-call ownership from month three."
        ),
        outcome=Outcome.PLACEMENT,
        location="Bengaluru",
        sector_id=technology,
        ctc_lpa="24.00",
        stipend_month=None,
        deadline_days=21,
        program_ctc=[
            ProgramCtcRow(program_id=btech, ctc_lpa=Decimal("24.00")),
            ProgramCtcRow(program_id=mtech, ctc_lpa=Decimal("27.50")),
        ],
    )
    backend_rule: dict[str, object] = {
        "all": [
            {"field": "cpi", "op": "gte", "value": 8.0},
            {"field": "active_backlogs", "op": "lte", "value": 0},
            {
                "field": "primary_branch_id",
                "op": "in",
                "value": [str(cse), str(electrical)],
            },
        ]
    }
    if await _scalar(
        engine,
        "SELECT eligibility_rule FROM jobs WHERE id = :job_id",
        {"job_id": backend},
    ) != backend_rule:
        await executor.run(
            "update_job_eligibility",
            UpdateJobEligibilityInput(
                cycle_id=placement_id,
                job_id=backend,
                eligibility_rule=backend_rule,
            ),
            staff_actor,
        )
    if not await _already_built(engine, table="job_rounds", job_id=backend):
        await executor.run(
            "upsert_job_rounds",
            UpsertJobRoundsInput(
                cycle_id=placement_id,
                job_id=backend,
                rounds=[
                    JobRoundRow(
                        round_type_id=aptitude, name="Online Assessment",
                        venue="Remote", duration_min=90,
                        instructions="Two hours, camera on, no external resources.",
                    ),
                    JobRoundRow(
                        round_type_id=interview, name="Systems Interview",
                        venue="AB 5 / 201", duration_min=60,
                    ),
                    JobRoundRow(
                        round_type_id=hr_round, name="Hiring Manager",
                        venue="AB 5 / 204", duration_min=45,
                    ),
                ],
            ),
            staff_actor,
        )
    if not await _already_built(engine, table="job_questions", job_id=backend):
        await executor.run(
            "upsert_job_questions",
            UpsertJobQuestionsInput(
                cycle_id=placement_id,
                job_id=backend,
                questions=[
                    JobQuestionRow(
                        text="Which office would you prefer?",
                        qtype=QuestionType.SINGLE,
                        required=True,
                        options=["Bengaluru", "Pune", "Hyderabad"],
                    ),
                    JobQuestionRow(
                        text="Which of these have you worked with?",
                        qtype=QuestionType.MULTI,
                        options=["Go", "Rust", "Kubernetes", "Postgres"],
                    ),
                    JobQuestionRow(
                        text="Describe a system you have operated in production.",
                        qtype=QuestionType.LONGTEXT,
                        required=True,
                    ),
                    JobQuestionRow(text="Link to your strongest project", qtype=QuestionType.URL),
                ],
            ),
            staff_actor,
        )
    await _publish(
        executor, staff_actor, engine, cycle_id=placement_id, job_id=backend
    )

    quant = await _job(
        executor, staff_actor, engine,
        cycle_id=placement_id, company_id=helios,
        title="Quantitative Researcher",
        description="Research and productionise systematic trading signals.",
        outcome=Outcome.PLACEMENT,
        location="Mumbai",
        sector_id=finance,
        ctc_lpa="32.00",
        stipend_month=None,
        deadline_days=14,
    )
    quant_rule: dict[str, object] = {"field": "cpi", "op": "gte", "value": 8.5}
    if await _scalar(
        engine,
        "SELECT eligibility_rule FROM jobs WHERE id = :job_id",
        {"job_id": quant},
    ) != quant_rule:
        await executor.run(
            "update_job_eligibility",
            UpdateJobEligibilityInput(
                cycle_id=placement_id,
                job_id=quant,
                eligibility_rule=quant_rule,
            ),
            staff_actor,
        )
    if not await _already_built(engine, table="job_rounds", job_id=quant):
        await executor.run(
            "upsert_job_rounds",
            UpsertJobRoundsInput(
                cycle_id=placement_id,
                job_id=quant,
                rounds=[
                    JobRoundRow(round_type_id=aptitude, name="Quant Test", duration_min=120),
                    JobRoundRow(round_type_id=interview, name="Maths Interview"),
                ],
            ),
            staff_actor,
        )
    await _publish(executor, staff_actor, engine, cycle_id=placement_id, job_id=quant)

    # Left unpublished on purpose: the builder needs a draft to show, and the
    # student screens need something that must stay invisible to them.
    await _job(
        executor, staff_actor, engine,
        cycle_id=placement_id, company_id=meridian,
        title="Associate Consultant",
        description="Client-facing strategy work across sectors.",
        outcome=Outcome.PLACEMENT,
        location="Gurugram",
        sector_id=consulting,
        ctc_lpa="19.50",
        stipend_month=None,
        deadline_days=30,
    )

    intern = await _job(
        executor, staff_actor, engine,
        cycle_id=internship_id, company_id=northwind,
        title="Software Engineering Intern",
        description="Ten-week summer internship on the query engine team.",
        outcome=Outcome.INTERNSHIP,
        location="Bengaluru",
        sector_id=technology,
        ctc_lpa=None,
        stipend_month="80000",
        deadline_days=35,
    )
    await _publish(
        executor, staff_actor, engine, cycle_id=internship_id, job_id=intern
    )

    # JOB-6: an open-cycle job carries no rounds and no acceptance deadline, so
    # the builder must render without a rounds tab at all.  Its outcome has to
    # be stated, because an open cycle carries both kinds and so fixes neither.
    lightweight = await _job(
        executor, admin_actor, engine,
        cycle_id=open_id, company_id=meridian,
        title="Campus Ambassador",
        description="Part-time outreach role, open to any active member.",
        outcome=Outcome.INTERNSHIP,
        location="On campus",
        sector_id=consulting,
        ctc_lpa=None,
        stipend_month="8000",
        deadline_days=90,
    )
    await _publish(
        executor, admin_actor, engine, cycle_id=open_id, job_id=lightweight
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap CDS Portal data")
    parser.add_argument(
        "--admin-email",
        action="append",
        default=[],
        help="Administrator to provision; repeat for multiple administrators",
    )
    parser.add_argument(
        "--no-demo",
        action="store_true",
        help="Create administrators and taxonomies without demonstration data",
    )
    args = parser.parse_args()
    asyncio.run(
        run_seed(
            admin_emails=tuple(args.admin_email),
            include_demo=not args.no_demo,
        )
    )


if __name__ == "__main__":
    main()
