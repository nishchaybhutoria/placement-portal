"""Database-backed offer facts (Behavior DER-1 and ELG-3.6/3.7)."""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.db import create_engine
from app.modules.offers.derivations import (
    cap_used,
    internship_placed_in_cycle,
    placement_placed_enrollments,
    placement_placed_global,
)
from tests.offers.conftest import (
    seed_admin,
    seed_application,
    seed_cycle,
    seed_job,
    seed_person,
)

pytestmark = pytest.mark.asyncio


async def _portal_offer(
    connection: AsyncConnection,
    *,
    enrollment_id: UUID,
    cycle_id: UUID,
    outcome: str,
    response: str | None = "accepted",
    terminated: bool = False,
) -> UUID:
    job_id = await seed_job(
        connection,
        cycle_id=cycle_id,
        outcome=outcome,
        title=f"{outcome.title()} role {uuid4()}",
    )
    application_id, _round_id = await seed_application(
        connection,
        cycle_id=cycle_id,
        enrollment_id=enrollment_id,
        status="accepted" if response == "accepted" else "offered",
        job_id=job_id,
    )
    offer_id = uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO offers (id, application_id, extended_at, response, "
            "responded_at, terminated_at, termination_kind, termination_reason) "
            "VALUES (:id, :application_id, now(), "
            "CAST(:response AS offer_response_t), "
            "CASE WHEN :response IS NULL THEN NULL ELSE now() END, "
            "CASE WHEN :terminated THEN now() ELSE NULL END, "
            "CASE WHEN :terminated THEN 'admin_correction'::termination_kind_t "
            "ELSE NULL END, "
            "CASE WHEN :terminated THEN 'Test correction' ELSE NULL END)"
        ),
        {
            "id": offer_id,
            "application_id": application_id,
            "response": response,
            "terminated": terminated,
        },
    )
    return offer_id


async def _external_offer(
    connection: AsyncConnection,
    *,
    enrollment_id: UUID,
    created_by: UUID,
    outcome: str,
    status: str = "accepted",
    attached_cycle_id: UUID | None = None,
) -> UUID:
    company_id, external_offer_id = uuid4(), uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO companies (id, name, is_active) VALUES (:id, :name, true)"
        ),
        {"id": company_id, "name": f"External company {company_id}"},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO external_offers (id, enrollment_id, company_id, outcome, "
            "source, status, attached_cycle_id, created_by) VALUES "
            "(:id, :enrollment_id, :company_id, CAST(:outcome AS outcome_t), "
            "'off_campus', CAST(:status AS external_status_t), :cycle_id, :created_by)"
        ),
        {
            "id": external_offer_id,
            "enrollment_id": enrollment_id,
            "company_id": company_id,
            "outcome": outcome,
            "status": status,
            "cycle_id": attached_cycle_id,
            "created_by": created_by,
        },
    )
    return external_offer_id


async def _read_facts(enrollment_id: UUID, cycle_id: UUID) -> tuple[bool, bool, int]:
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            return (
                await placement_placed_global(connection, enrollment_id),
                await internship_placed_in_cycle(connection, enrollment_id, cycle_id),
                await cap_used(connection, enrollment_id, cycle_id),
            )
    finally:
        await engine.dispose()


async def test_DER1_an_accepted_portal_placement_counts_until_terminated() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await seed_admin(connection)
            student = await seed_person(connection, email="student@example.edu")
            cycle_id = await seed_cycle(connection, kind="placement")
            offer_id = await _portal_offer(
                connection,
                enrollment_id=student.enrollment_id,
                cycle_id=cycle_id,
                outcome="placement",
            )
    finally:
        await engine.dispose()

    assert await _read_facts(student.enrollment_id, cycle_id) == (True, False, 1)

    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "UPDATE offers SET terminated_at = now(), "
                    "termination_kind = 'admin_correction', "
                    "termination_reason = 'Corrected' WHERE id = :id"
                ),
                {"id": offer_id},
            )
    finally:
        await engine.dispose()

    assert await _read_facts(student.enrollment_id, cycle_id) == (False, False, 0)


async def test_DER1_an_unattached_external_placement_is_global_but_consumes_no_cap() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="student@example.edu")
            cycle_id = await seed_cycle(connection, kind="placement")
            external_id = await _external_offer(
                connection,
                enrollment_id=student.enrollment_id,
                created_by=admin.user_id,
                outcome="placement",
            )
    finally:
        await engine.dispose()

    assert await _read_facts(student.enrollment_id, cycle_id) == (True, False, 0)

    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text("UPDATE external_offers SET status = 'declined' WHERE id = :id"),
                {"id": external_id},
            )
    finally:
        await engine.dispose()

    assert await _read_facts(student.enrollment_id, cycle_id) == (False, False, 0)


async def test_ELG36_internship_placed_is_scoped_to_the_portal_or_attached_cycle() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="student@example.edu")
            first = await seed_cycle(
                connection, name="Internships A", kind="internship"
            )
            second = await seed_cycle(
                connection, name="Internships B", kind="internship"
            )
            await _portal_offer(
                connection,
                enrollment_id=student.enrollment_id,
                cycle_id=first,
                outcome="internship",
            )
            await _external_offer(
                connection,
                enrollment_id=student.enrollment_id,
                created_by=admin.user_id,
                outcome="internship",
                attached_cycle_id=second,
            )
            await _external_offer(
                connection,
                enrollment_id=student.enrollment_id,
                created_by=admin.user_id,
                outcome="internship",
            )
    finally:
        await engine.dispose()

    assert await _read_facts(student.enrollment_id, first) == (False, True, 1)
    assert await _read_facts(student.enrollment_id, second) == (False, True, 1)


async def test_ELG37_cap_combines_portal_and_attached_external_acceptances_only() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="student@example.edu")
            cycle_id = await seed_cycle(connection, kind="internship")
            await _portal_offer(
                connection,
                enrollment_id=student.enrollment_id,
                cycle_id=cycle_id,
                outcome="internship",
            )
            await _portal_offer(
                connection,
                enrollment_id=student.enrollment_id,
                cycle_id=cycle_id,
                outcome="internship",
                terminated=True,
            )
            await _external_offer(
                connection,
                enrollment_id=student.enrollment_id,
                created_by=admin.user_id,
                outcome="internship",
                attached_cycle_id=cycle_id,
            )
            await _external_offer(
                connection,
                enrollment_id=student.enrollment_id,
                created_by=admin.user_id,
                outcome="internship",
                status="declined",
                attached_cycle_id=cycle_id,
            )
            await _external_offer(
                connection,
                enrollment_id=student.enrollment_id,
                created_by=admin.user_id,
                outcome="internship",
            )
    finally:
        await engine.dispose()

    assert await _read_facts(student.enrollment_id, cycle_id) == (False, True, 2)


async def test_DER1_the_batch_placement_derivation_returns_only_placed_enrollments() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            portal = await seed_person(connection, email="portal@example.edu")
            external = await seed_person(connection, email="external@example.edu")
            unplaced = await seed_person(connection, email="unplaced@example.edu")
            cycle_id = await seed_cycle(connection, kind="placement")
            await _portal_offer(
                connection,
                enrollment_id=portal.enrollment_id,
                cycle_id=cycle_id,
                outcome="placement",
            )
            await _external_offer(
                connection,
                enrollment_id=external.enrollment_id,
                created_by=admin.user_id,
                outcome="placement",
            )
    finally:
        await engine.dispose()

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            placed = await placement_placed_enrollments(
                connection,
                (portal.enrollment_id, external.enrollment_id, unplaced.enrollment_id),
            )
            empty = await placement_placed_enrollments(connection, ())
    finally:
        await engine.dispose()

    assert placed == frozenset({portal.enrollment_id, external.enrollment_id})
    assert empty == frozenset()
