"""Worlds for the M14 override suites, one per rule domain.

Each domain gets a world in which one real command is refused for exactly that
domain's reason, and a ``run`` that drives the command and reports back what
happened: the reason codes it failed with, and the override ids the event it
wrote credited.  The per-domain tests then assert the same five properties
against every entry, so a seventh domain cannot be added without a world.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.db import create_engine
from app.core.errors import (
    DEADLINE_PASSED,
    JOIN_RULE_FAILED,
    NOT_ELIGIBLE,
    OFFER_CAP_REACHED,
    OUTCOME_GATE_INTERNSHIP,
    REGISTRATION_CLOSED,
    WINDOW_CLOSED,
    DomainRejection,
)
from app.core.executor import Executor
from app.core.plan import Result
from app.domain.shared import ApplicationStatus, RuleDomain
from app.modules.applications.commands import ApplyInput
from app.modules.applications.lifecycle import (
    EditApplicationInput,
    WithdrawApplicationInput,
)
from app.modules.cycles.memberships import JoinCycleInput
from app.modules.offers.commands import OfferResponseInput
from tests.cycles.conftest import (  # noqa: F401
    Person,
    build_test_executor,
    seed_admin,
    seed_complete_profile,
    seed_cycle,
    seed_job,
    seed_membership,
    seed_person,
    seed_round_type,
    seed_taxonomy,
)

DRIVE_URL = "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view"


@pytest_asyncio.fixture
async def clean_overrides() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
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
                    "resumes, profiles, sessions, enrollments, users, companies, "
                    "programs, branches, sectors, round_types, procrastinate_jobs "
                    "CASCADE"
                )
            )
    finally:
        await engine.dispose()


def write_engine():  # noqa: ANN201 - compact test helper
    return create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])


@dataclass(frozen=True, slots=True)
class Attempt:
    """What one run of the domain's command did."""

    accepted: bool
    codes: tuple[str, ...]
    applied_override_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class DomainWorld:
    """One rule domain, the world it is refused in, and how to drive it."""

    domain: RuleDomain
    expected_code: str
    cycle_id: UUID
    job_id: UUID
    enrollment_id: UUID
    application_id: UUID | None
    run: Callable[[], Awaitable[Attempt]]
    #: The scope ladder this domain's command can actually resolve, most
    #: specific first.  ``apply`` carries no application id -- the application
    #: does not exist yet -- so an application-scoped override is not applicable
    #: to it, which is a property of the command rather than a gap in the test.
    ladder: tuple[str, ...] = (
        "application",
        "job+enrollment",
        "cycle+enrollment",
        "enrollment",
        "job",
        "cycle",
    )
    #: Codes that legitimately remain after this domain's own override applies,
    #: because the world cannot separate them from it.  Empty for every domain
    #: whose failure can stand alone.
    residual_codes: tuple[str, ...] = ()
    #: The other domains that must also be granted before the command can
    #: succeed here.  Only ``offer_cap`` has one: a dedicated internship cycle
    #: derives the cap and the outcome gate from the same accepted row, so no
    #: world can make the cap fail alone.
    also_grant: tuple[RuleDomain, ...] = ()

    def scope_kwargs(self, scope: str) -> dict[str, UUID]:
        return {
            "cycle": {"cycle_id": self.cycle_id},
            "job": {"job_id": self.job_id},
            "enrollment": {"enrollment_id": self.enrollment_id},
            "cycle+enrollment": {
                "cycle_id": self.cycle_id,
                "enrollment_id": self.enrollment_id,
            },
            "job+enrollment": {
                "job_id": self.job_id,
                "enrollment_id": self.enrollment_id,
            },
            "application": {"application_id": cast(UUID, self.application_id)},
        }[scope]


async def latest_event_overrides(application_id: UUID) -> tuple[UUID, ...]:
    """The override ids the application's newest event credited."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            payload = await connection.scalar(
                sa.text(
                    "SELECT payload FROM application_events "
                    "WHERE application_id = :id ORDER BY created_at DESC, id DESC "
                    "LIMIT 1"
                ),
                {"id": application_id},
            )
    finally:
        await engine.dispose()
    values = cast("dict[str, object]", payload or {}).get("applied_override_ids", [])
    return tuple(UUID(str(item)) for item in cast("list[object]", values))


async def _latest_audit_overrides(subject_id: UUID) -> tuple[UUID, ...]:
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            details = await connection.scalar(
                sa.text(
                    "SELECT details FROM audit_log WHERE subject_id = :id "
                    "ORDER BY audit_seq DESC LIMIT 1"
                ),
                {"id": subject_id},
            )
    finally:
        await engine.dispose()
    values = cast("dict[str, object]", details or {}).get(
        "applied_override_ids", []
    )
    return tuple(UUID(str(item)) for item in cast("list[object]", values))


async def _attempt_join(
    executor: Executor,
    input_value: JoinCycleInput,
    actor: object,
) -> Attempt:
    try:
        result = await executor.run("join_cycle", input_value, actor)  # type: ignore[arg-type]
    except DomainRejection as rejection:
        return Attempt(
            accepted=False,
            codes=tuple(reason.code for reason in rejection.rejection.reasons),
            applied_override_ids=(),
        )
    assert isinstance(result, Result)
    membership_id = UUID(str(result.summary["membership_id"]))
    return Attempt(
        accepted=True,
        codes=(),
        applied_override_ids=await _latest_audit_overrides(membership_id),
    )


async def _attempt(
    executor: Executor,
    name: str,
    input_value: object,
    actor: object,
    resolve_application: Callable[[], Awaitable[UUID]],
) -> Attempt:
    """Run the command and report what it did, never what it was expected to do."""
    try:
        result = await executor.run(name, input_value, actor)  # type: ignore[arg-type]
    except DomainRejection as rejection:
        return Attempt(
            accepted=False,
            codes=tuple(reason.code for reason in rejection.rejection.reasons),
            applied_override_ids=(),
        )
    assert isinstance(result, Result)
    return Attempt(
        accepted=True,
        codes=(),
        applied_override_ids=await latest_event_overrides(await resolve_application()),
    )


async def _student_world(
    connection: AsyncConnection, *, cycle_kind: str = "placement"
) -> tuple[Person, UUID, UUID, UUID]:
    """A declared student, active in one cycle, with a resume."""
    program_id, branch_id = await _taxonomy(connection)
    student = await seed_person(connection, email=f"student-{uuid4().hex[:8]}@example.edu")
    resume_id = await seed_complete_profile(
        connection,
        student,
        program_id=program_id,
        branch_id=branch_id,
        roll_number=f"21{uuid4().hex[:6]}",
    )
    cycle_id = await seed_cycle(connection, name=f"Cycle {uuid4().hex[:8]}", kind=cycle_kind)
    # The membership default is what `apply` falls back to when the student
    # names no resume, so a world without it refuses for RESUME_REQUIRED and
    # would never reach the gate under test.
    await seed_membership(
        connection,
        cycle_id=cycle_id,
        enrollment_id=student.enrollment_id,
        resume_id=resume_id,
    )
    return student, cycle_id, program_id, branch_id


async def _taxonomy(connection: AsyncConnection) -> tuple[UUID, UUID]:
    """One program and branch, reused when a world seeds a second student."""
    existing = (
        await connection.execute(
            sa.text(
                "SELECT p.id AS program_id, b.id AS branch_id "
                "FROM programs p JOIN program_branches pb ON pb.program_id = p.id "
                "JOIN branches b ON b.id = pb.branch_id LIMIT 1"
            )
        )
    ).mappings().one_or_none()
    if existing is not None:
        return cast(UUID, existing["program_id"]), cast(UUID, existing["branch_id"])
    return await seed_taxonomy(connection)


async def _job_with_deadline(
    connection: AsyncConnection,
    *,
    cycle_id: UUID,
    outcome: str = "placement",
    days: int,
    rule: str | None = None,
) -> UUID:
    job_id = await seed_job(
        connection,
        cycle_id=cycle_id,
        outcome=outcome,
        is_published=True,
        title=f"Role {uuid4().hex[:6]}",
    )
    await connection.execute(
        sa.text(
            "UPDATE jobs SET application_deadline = :deadline, "
            "eligibility_rule = CAST(:rule AS jsonb) WHERE id = :id"
        ),
        {
            "id": job_id,
            "deadline": datetime.now(UTC) + timedelta(days=days),
            "rule": rule,
        },
    )
    return job_id


async def _seed_application(
    connection: AsyncConnection,
    *,
    job_id: UUID,
    enrollment_id: UUID,
    status: str,
) -> UUID:
    application_id = uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO applications (id, job_id, enrollment_id, status, "
            "resume_url, profile_snapshot, applied_at) VALUES "
            "(:id, :job_id, :enrollment_id, CAST(:status AS application_status_t), "
            ":url, CAST('{}' AS jsonb), now())"
        ),
        {
            "id": application_id,
            "job_id": job_id,
            "enrollment_id": enrollment_id,
            "status": status,
            "url": DRIVE_URL,
        },
    )
    return application_id


async def _seed_offer(
    connection: AsyncConnection,
    *,
    application_id: UUID,
    response: str | None = None,
    deadline: datetime | None = None,
) -> UUID:
    offer_id = uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO offers (id, application_id, extended_at, deadline_at, "
            "response, responded_at) VALUES (:id, :application_id, now(), :deadline, "
            "CAST(:response AS offer_response_t), "
            "CASE WHEN :response IS NULL THEN NULL ELSE now() END)"
        ),
        {
            "id": offer_id,
            "application_id": application_id,
            "deadline": deadline,
            "response": response,
        },
    )
    return offer_id


async def build_eligibility_world(
    connection: AsyncConnection, executor: Executor
) -> DomainWorld:
    """ELG-2's job rule refuses the student; only the rule is overridable."""
    student, cycle_id, _program, _branch = await _student_world(connection)
    job_id = await _job_with_deadline(
        connection,
        cycle_id=cycle_id,
        days=30,
        rule='{"field": "cpi", "op": "gte", "value": 9.5}',
    )
    async def run() -> Attempt:
        return await _attempt(
            executor,
            "apply",
            ApplyInput(
                cycle_id=cycle_id,
                job_id=job_id,
                enrollment_id=student.enrollment_id,
            ),
            student.actor,
            lambda: _application_of(job_id, student.enrollment_id),
        )

    return DomainWorld(
        domain=RuleDomain.ELIGIBILITY,
        expected_code=NOT_ELIGIBLE,
        cycle_id=cycle_id,
        job_id=job_id,
        enrollment_id=student.enrollment_id,
        application_id=None,
        ladder=(
            "job+enrollment",
            "cycle+enrollment",
            "enrollment",
            "job",
            "cycle",
        ),
        run=run,
    )


async def _resolved(application_id: UUID) -> UUID:
    return application_id


async def _application_of(job_id: UUID, enrollment_id: UUID) -> UUID:
    """The application row apply just wrote, or a placeholder when it refused."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            found = await connection.scalar(
                sa.text(
                    "SELECT id FROM applications WHERE job_id = :job_id "
                    "AND enrollment_id = :enrollment_id "
                    "ORDER BY applied_at DESC LIMIT 1"
                ),
                {"job_id": job_id, "enrollment_id": enrollment_id},
            )
    finally:
        await engine.dispose()
    return cast(UUID, found) if found is not None else uuid4()


async def build_application_deadline_world(
    connection: AsyncConnection, executor: Executor
) -> DomainWorld:
    """APP-1 refuses an application after the deadline; INT-1's late override reopens it."""
    student, cycle_id, _program, _branch = await _student_world(connection)
    job_id = await _job_with_deadline(connection, cycle_id=cycle_id, days=-1)

    async def run() -> Attempt:
        return await _attempt(
            executor,
            "apply",
            ApplyInput(
                cycle_id=cycle_id,
                job_id=job_id,
                enrollment_id=student.enrollment_id,
            ),
            student.actor,
            lambda: _application_of(job_id, student.enrollment_id),
        )

    return DomainWorld(
        domain=RuleDomain.APPLICATION_DEADLINE,
        expected_code=DEADLINE_PASSED,
        cycle_id=cycle_id,
        job_id=job_id,
        enrollment_id=student.enrollment_id,
        application_id=None,
        ladder=(
            "job+enrollment",
            "cycle+enrollment",
            "enrollment",
            "job",
            "cycle",
        ),
        run=run,
    )


async def _build_application_window_world(
    connection: AsyncConnection,
    executor: Executor,
    *,
    domain: RuleDomain,
) -> DomainWorld:
    """One closed APP-3 action, with edit and withdrawal kept independent."""
    student, cycle_id, _program, _branch = await _student_world(connection)
    job_id = await _job_with_deadline(connection, cycle_id=cycle_id, days=-1)
    application_id = await _seed_application(
        connection, job_id=job_id, enrollment_id=student.enrollment_id, status="in_progress"
    )

    async def run() -> Attempt:
        command = (
            "edit_application"
            if domain is RuleDomain.EDIT_WINDOW
            else "withdraw_application"
        )
        input_value = (
            EditApplicationInput(
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                application_id=application_id,
            )
            if domain is RuleDomain.EDIT_WINDOW
            else WithdrawApplicationInput(
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                application_id=application_id,
            )
        )
        return await _attempt(
            executor,
            command,
            input_value,
            student.actor,
            lambda: _resolved(application_id),
        )

    return DomainWorld(
        domain=domain,
        expected_code=WINDOW_CLOSED,
        cycle_id=cycle_id,
        job_id=job_id,
        enrollment_id=student.enrollment_id,
        application_id=application_id,
        run=run,
    )


async def build_edit_window_world(
    connection: AsyncConnection, executor: Executor
) -> DomainWorld:
    return await _build_application_window_world(
        connection, executor, domain=RuleDomain.EDIT_WINDOW
    )


async def build_withdraw_window_world(
    connection: AsyncConnection, executor: Executor
) -> DomainWorld:
    return await _build_application_window_world(
        connection, executor, domain=RuleDomain.WITHDRAW_WINDOW
    )


async def build_outcome_gate_world(
    connection: AsyncConnection, executor: Executor
) -> DomainWorld:
    """DER-1 closes placement roles to a placed student; OFR-3 re-checks on accept."""
    student, cycle_id, _program, _branch = await _student_world(connection)
    placed_job = await _job_with_deadline(connection, cycle_id=cycle_id, days=30)
    placed_application = await _seed_application(
        connection, job_id=placed_job, enrollment_id=student.enrollment_id, status="accepted"
    )
    await _seed_offer(connection, application_id=placed_application, response="accepted")

    # A second placement cycle, so the cap of the first is not what refuses this.
    second_cycle = await seed_cycle(
        connection, name=f"Second {uuid4().hex[:8]}", kind="placement"
    )
    await seed_membership(
        connection, cycle_id=second_cycle, enrollment_id=student.enrollment_id
    )
    job_id = await _job_with_deadline(connection, cycle_id=second_cycle, days=30)
    application_id = await _seed_application(
        connection, job_id=job_id, enrollment_id=student.enrollment_id, status="offered"
    )
    offer_id = await _seed_offer(connection, application_id=application_id)

    async def run() -> Attempt:
        return await _attempt(
            executor,
            "accept_offer",
            OfferResponseInput(
                cycle_id=second_cycle,
                job_id=job_id,
                application_id=application_id,
                offer_id=offer_id,
                enrollment_id=student.enrollment_id,
                expected_status=ApplicationStatus.OFFERED,
            ),
            student.actor,
            lambda: _resolved(application_id),
        )

    return DomainWorld(
        domain=RuleDomain.OUTCOME_GATE,
        expected_code="outcome_gate_placement",
        cycle_id=second_cycle,
        job_id=job_id,
        enrollment_id=student.enrollment_id,
        application_id=application_id,
        run=run,
    )


async def build_offer_cap_world(
    connection: AsyncConnection, executor: Executor
) -> DomainWorld:
    """CYC-2's cap is consumed in this cycle, so a second acceptance is refused.

    An internship cycle cannot separate the cap from the outcome gate -- both
    derive from the same accepted row -- so the world states that plainly: this
    domain's override removes its own reason and leaves the other standing,
    which is itself the proof that a domain override is not a general amnesty.
    """
    student, cycle_id, _program, _branch = await _student_world(
        connection, cycle_kind="internship"
    )
    first_job = await _job_with_deadline(
        connection, cycle_id=cycle_id, outcome="internship", days=30
    )
    first_application = await _seed_application(
        connection, job_id=first_job, enrollment_id=student.enrollment_id, status="accepted"
    )
    await _seed_offer(connection, application_id=first_application, response="accepted")

    job_id = await _job_with_deadline(
        connection, cycle_id=cycle_id, outcome="internship", days=30
    )
    application_id = await _seed_application(
        connection, job_id=job_id, enrollment_id=student.enrollment_id, status="offered"
    )
    offer_id = await _seed_offer(connection, application_id=application_id)

    async def run() -> Attempt:
        return await _attempt(
            executor,
            "accept_offer",
            OfferResponseInput(
                cycle_id=cycle_id,
                job_id=job_id,
                application_id=application_id,
                offer_id=offer_id,
                enrollment_id=student.enrollment_id,
                expected_status=ApplicationStatus.OFFERED,
            ),
            student.actor,
            lambda: _resolved(application_id),
        )

    return DomainWorld(
        domain=RuleDomain.OFFER_CAP,
        expected_code=OFFER_CAP_REACHED,
        cycle_id=cycle_id,
        job_id=job_id,
        enrollment_id=student.enrollment_id,
        application_id=application_id,
        run=run,
        residual_codes=(OUTCOME_GATE_INTERNSHIP,),
        also_grant=(RuleDomain.OUTCOME_GATE,),
    )


async def build_offer_deadline_world(
    connection: AsyncConnection, executor: Executor
) -> DomainWorld:
    """OFR-4's response deadline has closed; its own domain reopens it."""
    student, cycle_id, _program, _branch = await _student_world(connection)
    job_id = await _job_with_deadline(connection, cycle_id=cycle_id, days=-30)
    application_id = await _seed_application(
        connection, job_id=job_id, enrollment_id=student.enrollment_id, status="offered"
    )
    offer_id = await _seed_offer(
        connection,
        application_id=application_id,
        deadline=datetime.now(UTC) - timedelta(days=1),
    )

    async def run() -> Attempt:
        return await _attempt(
            executor,
            "accept_offer",
            OfferResponseInput(
                cycle_id=cycle_id,
                job_id=job_id,
                application_id=application_id,
                offer_id=offer_id,
                enrollment_id=student.enrollment_id,
                expected_status=ApplicationStatus.OFFERED,
            ),
            student.actor,
            lambda: _resolved(application_id),
        )

    return DomainWorld(
        domain=RuleDomain.OFFER_DEADLINE,
        expected_code=DEADLINE_PASSED,
        cycle_id=cycle_id,
        job_id=job_id,
        enrollment_id=student.enrollment_id,
        application_id=application_id,
        run=run,
    )


async def _build_join_world(
    connection: AsyncConnection,
    executor: Executor,
    *,
    domain: RuleDomain,
) -> DomainWorld:
    program_id, branch_id = await _taxonomy(connection)
    student = await seed_person(
        connection, email=f"join-{domain.value}-{uuid4().hex[:8]}@example.edu"
    )
    resume_id = await seed_complete_profile(
        connection,
        student,
        program_id=program_id,
        branch_id=branch_id,
        roll_number=f"22{uuid4().hex[:6]}",
        cpi="7.20",
    )
    assert resume_id is not None
    cycle_id = await seed_cycle(
        connection,
        name=f"Join {domain.value} {uuid4().hex[:6]}",
        registration_open=domain is not RuleDomain.CYCLE_REGISTRATION_WINDOW,
        join_rule=(
            '{"all": [{"field": "cpi", "op": "gte", "value": 9.0}]}'
            if domain is RuleDomain.CYCLE_JOIN_RULE
            else None
        ),
    )

    async def run() -> Attempt:
        return await _attempt_join(
            executor,
            JoinCycleInput(
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                default_resume_id=resume_id,
                consent=True,
            ),
            student.actor,
        )

    return DomainWorld(
        domain=domain,
        expected_code=(
            REGISTRATION_CLOSED
            if domain is RuleDomain.CYCLE_REGISTRATION_WINDOW
            else JOIN_RULE_FAILED
        ),
        cycle_id=cycle_id,
        job_id=uuid4(),
        enrollment_id=student.enrollment_id,
        application_id=None,
        run=run,
        ladder=("cycle+enrollment", "enrollment", "cycle"),
    )


async def build_cycle_registration_window_world(
    connection: AsyncConnection, executor: Executor
) -> DomainWorld:
    return await _build_join_world(
        connection, executor, domain=RuleDomain.CYCLE_REGISTRATION_WINDOW
    )


async def build_cycle_join_rule_world(
    connection: AsyncConnection, executor: Executor
) -> DomainWorld:
    return await _build_join_world(
        connection, executor, domain=RuleDomain.CYCLE_JOIN_RULE
    )


#: One builder per rule domain.  The per-domain tests parametrize over
#: ``RuleDomain`` itself and look the builder up here, so a domain added to the
#: enum without a world fails with a message saying exactly that.
WORLD_BUILDERS: dict[
    RuleDomain, Callable[[AsyncConnection, Executor], Awaitable[DomainWorld]]
] = {
    RuleDomain.ELIGIBILITY: build_eligibility_world,
    RuleDomain.APPLICATION_DEADLINE: build_application_deadline_world,
    RuleDomain.EDIT_WINDOW: build_edit_window_world,
    RuleDomain.WITHDRAW_WINDOW: build_withdraw_window_world,
    RuleDomain.OUTCOME_GATE: build_outcome_gate_world,
    RuleDomain.OFFER_CAP: build_offer_cap_world,
    RuleDomain.OFFER_DEADLINE: build_offer_deadline_world,
    RuleDomain.CYCLE_REGISTRATION_WINDOW: build_cycle_registration_window_world,
    RuleDomain.CYCLE_JOIN_RULE: build_cycle_join_rule_world,
}


async def grant(
    connection: AsyncConnection,
    *,
    domain: RuleDomain,
    granted_by: UUID,
    allow: bool = True,
    is_active: bool = True,
    expires_at: datetime | None = None,
    cycle_id: UUID | None = None,
    job_id: UUID | None = None,
    enrollment_id: UUID | None = None,
    application_id: UUID | None = None,
) -> UUID:
    """Insert one override row directly, for worlds the command cannot build.

    ``create_override`` refuses a past expiry and only an administrator may
    grant across enrollments; both are correct and both are in the way of a
    test that needs an *already expired* row, so those rows are seeded.
    """
    override_id = uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO overrides (id, rule_domain, allow, cycle_id, job_id, "
            "enrollment_id, application_id, reason, granted_by, expires_at, "
            "is_active, created_at) VALUES "
            "(:id, CAST(:domain AS rule_domain_t), :allow, :cycle_id, :job_id, "
            ":enrollment_id, :application_id, :reason, :granted_by, :expires_at, "
            ":is_active, now())"
        ),
        {
            "id": override_id,
            "domain": domain.value,
            "allow": allow,
            "cycle_id": cycle_id,
            "job_id": job_id,
            "enrollment_id": enrollment_id,
            "application_id": application_id,
            "reason": f"Test grant for {domain.value}",
            "granted_by": granted_by,
            "expires_at": expires_at,
            "is_active": is_active,
        },
    )
    return override_id
