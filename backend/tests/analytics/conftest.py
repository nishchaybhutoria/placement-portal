"""The definition world: every way a student can and cannot be *placed*.

ANA-1's placed sentence has four clauses and each one excludes something.  A
fixture that only builds the happy case proves nothing, so this world builds
one enrollment per clause -- accepted, terminated, wrong cycle, attached
external, unattached external, offered-not-accepted, applied-only, registered
only, off-campus, pending membership, and an acceptance whose cached
application status was later forced elsewhere -- and the suites assert *which*
enrollments came back, not how many.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.plan import ActorContext
from tests.cycles.conftest import (  # noqa: F401
    build_test_executor,
    clean_cycles,
    seed_admin,
    seed_application,
    seed_complete_profile,
    seed_cycle,
    seed_job,
    seed_membership,
    seed_person,
    seed_taxonomy,
)


async def set_job_compensation(
    connection: AsyncConnection,
    job_id: UUID,
    *,
    ctc_lpa: str | None = None,
    stipend_month: str | None = None,
) -> None:
    await connection.execute(
        sa.text(
            "UPDATE jobs SET ctc_lpa = CAST(:ctc AS numeric), "
            "stipend_month = CAST(:stipend AS numeric) WHERE id = :id"
        ),
        {"id": job_id, "ctc": ctc_lpa, "stipend": stipend_month},
    )


async def set_program_ctc(
    connection: AsyncConnection, job_id: UUID, program_id: UUID, ctc_lpa: str
) -> None:
    """The per-program CTC row ANA-1 prefers over the job's own figure."""
    await connection.execute(
        sa.text(
            "INSERT INTO job_program_ctc (id, job_id, program_id, ctc_lpa) "
            "VALUES (:id, :job_id, :program_id, CAST(:ctc AS numeric))"
        ),
        {"id": uuid4(), "job_id": job_id, "program_id": program_id, "ctc": ctc_lpa},
    )


async def set_snapshot_program(
    connection: AsyncConnection, application_id: UUID, program_id: UUID | None
) -> None:
    """Stamp the snapshot the per-program CTC pick reads (the design review 4.30d)."""
    await connection.execute(
        sa.text(
            "UPDATE applications SET profile_snapshot = "
            "CASE WHEN CAST(:program AS text) IS NULL THEN CAST('{}' AS jsonb) "
            "ELSE jsonb_build_object('program_id', CAST(:program AS text)) END "
            "WHERE id = :id"
        ),
        {"id": application_id, "program": None if program_id is None else str(program_id)},
    )


async def accept_portal_offer(
    connection: AsyncConnection,
    *,
    cycle_id: UUID,
    enrollment_id: UUID,
    outcome: str = "placement",
    job_id: UUID | None = None,
    response: str | None = "accepted",
    terminated: bool = False,
    accepted_at: datetime | None = None,
    application_status: str | None = None,
) -> tuple[UUID, UUID]:
    """A portal offer with its application and job. Returns (job, application)."""
    if job_id is None:
        job_id = await seed_job(
            connection, cycle_id=cycle_id, outcome=outcome, title=f"Role {uuid4()}"
        )
    status = application_status or (
        "accepted" if response == "accepted" else "offered" if response is None else "declined"
    )
    application_id, _round = await seed_application(
        connection,
        cycle_id=cycle_id,
        enrollment_id=enrollment_id,
        status=status,
        job_id=job_id,
    )
    await connection.execute(
        sa.text(
            "INSERT INTO offers (id, application_id, extended_at, response, "
            "responded_at, terminated_at, terminated_by, termination_kind, "
            "termination_reason) VALUES (:id, :application_id, :extended_at, "
            "CAST(:response AS offer_response_t), "
            "CASE WHEN CAST(:response AS text) IS NULL THEN NULL "
            "ELSE CAST(:accepted_at AS timestamptz) END, "
            "CASE WHEN :terminated THEN now() ELSE NULL END, NULL, "
            "CASE WHEN :terminated THEN 'admin_correction'::termination_kind_t "
            "ELSE NULL END, "
            "CASE WHEN :terminated THEN 'Fixture termination' ELSE NULL END)"
        ),
        {
            "id": uuid4(),
            "application_id": application_id,
            "extended_at": (accepted_at or datetime.now(UTC)) - timedelta(days=1),
            "response": response,
            "accepted_at": accepted_at or datetime.now(UTC),
            "terminated": terminated,
        },
    )
    return job_id, application_id


async def record_external_offer(
    connection: AsyncConnection,
    *,
    enrollment_id: UUID,
    created_by: UUID,
    company_id: UUID | None = None,
    outcome: str = "placement",
    status: str = "accepted",
    source: str = "ppo",
    attached_cycle_id: UUID | None = None,
    ctc_lpa: str | None = None,
    stipend_month: str | None = None,
    responded_on: date | None = None,
) -> UUID:
    external_id = uuid4()
    if company_id is None:
        company_id = uuid4()
        await connection.execute(
            sa.text("INSERT INTO companies (id, name, is_active) VALUES (:id, :name, true)"),
            {"id": company_id, "name": f"External company {external_id}"},
        )
    await connection.execute(
        sa.text(
            "INSERT INTO external_offers (id, enrollment_id, company_id, outcome, "
            "source, ctc_lpa, stipend_month, status, offered_on, responded_on, "
            "attached_cycle_id, created_by) VALUES (:id, :enrollment_id, :company_id, "
            "CAST(:outcome AS outcome_t), CAST(:source AS external_source_t), "
            "CAST(:ctc AS numeric), CAST(:stipend AS numeric), "
            "CAST(:status AS external_status_t), :offered_on, :responded_on, "
            ":attached_cycle_id, :created_by)"
        ),
        {
            "id": external_id,
            "enrollment_id": enrollment_id,
            "company_id": company_id,
            "outcome": outcome,
            "source": source,
            "ctc": ctc_lpa,
            "stipend": stipend_month,
            "status": status,
            "offered_on": date(2026, 1, 10),
            "responded_on": responded_on or date(2026, 1, 20),
            "attached_cycle_id": attached_cycle_id,
            "created_by": created_by,
        },
    )
    return external_id


@dataclass(frozen=True, slots=True)
class Student:
    """One enrollment plus the sentence that says why it is in or out."""

    key: str
    enrollment_id: UUID
    email: str
    why: str
    resume_id: UUID
    user_id: UUID
    session_id: UUID

    @property
    def actor(self) -> ActorContext:
        return ActorContext(
            principal_id=str(self.user_id),
            user_id=self.user_id,
            role="student",
            session_id=self.session_id,
            current_enrollment_id=self.enrollment_id,
            email=self.email,
        )


@dataclass(frozen=True, slots=True)
class DefinitionWorld:
    """The fixture the ANA-1 suites assert against."""

    cycle_id: UUID
    other_cycle_id: UUID
    program_id: UUID
    branch_id: UUID
    admin_id: UUID
    students: dict[str, Student]

    def enrollment(self, key: str) -> UUID:
        return self.students[key].enrollment_id

    def ids(self, *keys: str) -> frozenset[UUID]:
        return frozenset(self.enrollment(key) for key in keys)

    def key_for(self, enrollment_id: UUID) -> str:
        for student in self.students.values():
            if student.enrollment_id == enrollment_id:
                return student.key
        return f"<unknown {enrollment_id}>"

    def explain(self, ids: frozenset[UUID]) -> set[str]:
        """Enrollment ids as the readable keys an assertion failure can name."""
        return {self.key_for(enrollment_id) for enrollment_id in ids}


#: What each enrollment is for.  The suites read these strings into their
#: failure messages so a broken WHERE clause reports which clause it broke.
PLACED_IN_CYCLE = {
    "accepted_portal": "an accepted, unterminated portal offer on this cycle's job",
    "off_campus_external": "an accepted off-campus external attached to this cycle",
    "ppo_external": "an accepted PPO external attached to this cycle",
    "forced_status": "accepted offer row; the cached application status was forced away",
}

NOT_PLACED_IN_CYCLE = {
    "terminated_portal": "the acceptance was terminated, so the offer no longer counts",
    "other_cycle": "the accepted offer belongs to another cycle's job",
    "unattached_external": "accepted but attached to no cycle: DER-1 global, not this cycle",
    "offered_external": "an attached external still at 'offered' is not an acceptance",
    "applied_only": "an application, never an offer",
    "registered_only": "an active membership and nothing else",
    "pending_member": "applied, but the membership is pending, so never registered",
}


async def build_definition_world(connection: AsyncConnection) -> DefinitionWorld:
    """Every clause of ANA-1's placed sentence, one enrollment each."""
    program_id, branch_id = await seed_taxonomy(connection)
    admin = await seed_admin(connection, email="analytics-admin@example.edu")
    cycle_id = await seed_cycle(connection, name="Placement 2026", kind="placement")
    other_cycle_id = await seed_cycle(connection, name="Placement 2025", kind="placement")

    students: dict[str, Student] = {}
    roll = 21110000
    for key in (*PLACED_IN_CYCLE, *NOT_PLACED_IN_CYCLE):
        roll += 1
        person = await seed_person(connection, email=f"{key}@example.edu")
        resume_id = await seed_complete_profile(
            connection,
            person,
            program_id=program_id,
            branch_id=branch_id,
            roll_number=str(roll),
        )
        assert resume_id is not None
        why = PLACED_IN_CYCLE.get(key) or NOT_PLACED_IN_CYCLE[key]
        students[key] = Student(
            key=key,
            enrollment_id=person.enrollment_id,
            email=person.email,
            why=why,
            resume_id=resume_id,
            user_id=person.user_id,
            session_id=person.session_id,
        )
        # Everyone is an active member of the cycle except the pending one:
        # registration is what the rate divides by, so it gets its own case.
        await seed_membership(
            connection,
            cycle_id=cycle_id,
            enrollment_id=person.enrollment_id,
            status="pending" if key == "pending_member" else "active",
        )

    world = DefinitionWorld(
        cycle_id=cycle_id,
        other_cycle_id=other_cycle_id,
        program_id=program_id,
        branch_id=branch_id,
        admin_id=admin.user_id,
        students=students,
    )

    # --- placed -----------------------------------------------------------
    job_id, application_id = await accept_portal_offer(
        connection, cycle_id=cycle_id, enrollment_id=world.enrollment("accepted_portal")
    )
    await set_job_compensation(connection, job_id, ctc_lpa="18.00")
    await set_snapshot_program(connection, application_id, program_id)
    await set_program_ctc(connection, job_id, program_id, "21.50")

    await record_external_offer(
        connection,
        enrollment_id=world.enrollment("ppo_external"),
        created_by=admin.user_id,
        source="ppo",
        attached_cycle_id=cycle_id,
        ctc_lpa="24.00",
    )
    await record_external_offer(
        connection,
        enrollment_id=world.enrollment("off_campus_external"),
        created_by=admin.user_id,
        source="off_campus",
        attached_cycle_id=cycle_id,
        ctc_lpa="30.00",
    )
    forced_job, _forced_application = await accept_portal_offer(
        connection,
        cycle_id=cycle_id,
        enrollment_id=world.enrollment("forced_status"),
        # DER-1 is defined from the offer row, never from the denormalised
        # application status, so this row is placed despite saying otherwise.
        application_status="rejected",
    )
    await set_job_compensation(connection, forced_job, ctc_lpa="12.00")

    # --- not placed -------------------------------------------------------
    await accept_portal_offer(
        connection,
        cycle_id=cycle_id,
        enrollment_id=world.enrollment("terminated_portal"),
        terminated=True,
    )
    await accept_portal_offer(
        connection,
        cycle_id=other_cycle_id,
        enrollment_id=world.enrollment("other_cycle"),
    )
    await record_external_offer(
        connection,
        enrollment_id=world.enrollment("unattached_external"),
        created_by=admin.user_id,
        source="off_campus",
        attached_cycle_id=None,
        ctc_lpa="26.00",
    )
    await record_external_offer(
        connection,
        enrollment_id=world.enrollment("offered_external"),
        created_by=admin.user_id,
        status="offered",
        attached_cycle_id=cycle_id,
        ctc_lpa="19.00",
    )
    await seed_application(
        connection,
        cycle_id=cycle_id,
        enrollment_id=world.enrollment("applied_only"),
        status="in_progress",
    )
    await seed_application(
        connection,
        cycle_id=cycle_id,
        enrollment_id=world.enrollment("pending_member"),
        status="in_progress",
    )
    return world


def decimal(value: str) -> Decimal:
    return Decimal(value)


async def build_gate_probe(
    connection: AsyncConnection, world: DefinitionWorld
) -> tuple[UUID, UUID]:
    """A third cycle with a published placement job everyone may attempt.

    The point is the design review 4.22's equivalence pin, one level up: the students a
    dashboard calls placed must be exactly the students the placement gate
    refuses.  A universal gate makes that testable in one job -- placement is
    once per student anywhere, so every globally placed enrollment is blocked
    here whatever cycle placed them.
    """
    probe_cycle = await seed_cycle(connection, name="Gate probe", kind="placement")
    probe_job = await seed_job(
        connection, cycle_id=probe_cycle, outcome="placement", is_published=True
    )
    for student in world.students.values():
        await seed_membership(
            connection,
            cycle_id=probe_cycle,
            enrollment_id=student.enrollment_id,
            status="active",
            resume_id=student.resume_id,
        )
    return probe_cycle, probe_job
