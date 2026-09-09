"""EXT-3 dedicated attachment, cap effects, and membership semantics."""

from __future__ import annotations

import os
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.db import create_engine
from app.core.errors import DomainRejection
from app.core.plan import Result
from app.domain.shared import RuleDomain
from app.modules.offers.derivations import cap_used
from tests.cycles.conftest import seed_application
from tests.offers.conftest import (
    build_test_executor,
    seed_admin,
    seed_cycle,
    seed_external_offer,
    seed_job,
    seed_person,
    seed_portal_offer,
)
from tests.overrides.conftest import grant

pytestmark = pytest.mark.asyncio


async def _company(connection: AsyncConnection, job_id: UUID) -> UUID:
    value = await connection.scalar(
        sa.text("SELECT company_id FROM jobs WHERE id = :id"), {"id": job_id}
    )
    assert isinstance(value, UUID)
    return value


async def test_EXT3_attach_is_dedicated_kind_matched_and_auto_creates_membership_once() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="attach@example.edu")
            cycle = await seed_cycle(connection, name="Internships", kind="internship")
            job = await seed_job(
                connection, cycle_id=cycle, outcome="internship", title="Internship"
            )
            company_id = await _company(connection, job)
            external_offer = await seed_external_offer(
                connection,
                enrollment_id=student.enrollment_id,
                company_id=company_id,
                created_by=admin.user_id,
                outcome="internship",
                status="accepted",
                stipend_month=Decimal("80000"),
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    attach = executor.registry.commands["attach_external_offer"]
    try:
        result = await executor.run(
            "attach_external_offer",
            attach.input_model.model_validate(
                {
                    "cycle_id": cycle,
                    "external_offer_id": external_offer,
                    "expected_attached_cycle_id": None,
                    "reason": "Count this internship in the dedicated cycle",
                }
            ),
            admin.actor,
        )
    finally:
        await command_engine.dispose()
    assert isinstance(result, Result)
    assert result.summary["membership_auto_created"] is True

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            membership = (
                (
                    await connection.execute(
                        sa.text(
                            "SELECT id, status, auto_created FROM cycle_memberships "
                            "WHERE cycle_id = :cycle AND enrollment_id = :enrollment"
                        ),
                        {"cycle": cycle, "enrollment": student.enrollment_id},
                    )
                )
                .mappings()
                .one()
            )
            assert await cap_used(connection, student.enrollment_id, cycle) == 1
    finally:
        await engine.dispose()
    assert membership["status"] == "active"
    assert membership["auto_created"] is True

    executor, command_engine = build_test_executor()
    detach = executor.registry.commands["detach_external_offer"]
    try:
        detached = await executor.run(
            "detach_external_offer",
            detach.input_model.model_validate(
                {
                    "cycle_id": cycle,
                    "external_offer_id": external_offer,
                    "expected_attached_cycle_id": cycle,
                    "reason": "Move to a later cycle",
                }
            ),
            admin.actor,
        )
    finally:
        await command_engine.dispose()
    assert isinstance(detached, Result)
    assert detached.summary["membership_left_in_place"] is True

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    sa.text(
                        "SELECT count(*) FROM cycle_memberships "
                        "WHERE cycle_id = :cycle AND enrollment_id = :enrollment"
                    ),
                    {"cycle": cycle, "enrollment": student.enrollment_id},
                )
                == 1
            )
            assert await cap_used(connection, student.enrollment_id, cycle) == 0
    finally:
        await engine.dispose()


@pytest.mark.parametrize("bad_cycle_kind", ("placement", "open"))
async def test_EXT3_attach_rejects_kind_mismatch_and_open_cycles(
    bad_cycle_kind: str,
) -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email=f"bad-{bad_cycle_kind}@example.edu")
            cycle = await seed_cycle(connection, kind=bad_cycle_kind)
            company_job = await seed_job(
                connection,
                cycle_id=cycle,
                outcome="placement" if bad_cycle_kind != "internship" else "internship",
                with_deadline=bad_cycle_kind != "open",
            )
            company_id = await _company(connection, company_job)
            external_offer = await seed_external_offer(
                connection,
                enrollment_id=student.enrollment_id,
                company_id=company_id,
                created_by=admin.user_id,
                outcome="internship",
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    spec = executor.registry.commands["attach_external_offer"]
    try:
        with pytest.raises(DomainRejection) as error:
            await executor.run(
                "attach_external_offer",
                spec.input_model.model_validate(
                    {
                        "cycle_id": cycle,
                        "external_offer_id": external_offer,
                        "reason": "Wrong target",
                    }
                ),
                admin.actor,
                dry_run=True,
            )
    finally:
        await command_engine.dispose()
    assert error.value.rejection.reasons[0].code in {
        "invalid_transition",
        "attachment_kind_mismatch",
    }


@pytest.mark.parametrize(("cap", "allowed"), ((1, False), (None, True)))
async def test_EXT3_attach_rechecks_cap_under_lock_and_uncapped_skips_it(
    cap: int | None, allowed: bool
) -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email=f"cap-{cap}@example.edu")
            cycle = await seed_cycle(connection, kind="internship")
            await connection.execute(
                sa.text(
                    "UPDATE cycle_policies SET max_accepted_offers = :cap WHERE cycle_id = :cycle"
                ),
                {"cap": cap, "cycle": cycle},
            )
            portal_job = await seed_job(
                connection, cycle_id=cycle, outcome="internship", title="Portal accepted"
            )
            company_id = await _company(connection, portal_job)
            portal_application, _ = await seed_application(
                connection,
                cycle_id=cycle,
                enrollment_id=student.enrollment_id,
                status="accepted",
                job_id=portal_job,
            )
            await seed_portal_offer(
                connection, application_id=portal_application, response="accepted"
            )
            external_offer = await seed_external_offer(
                connection,
                enrollment_id=student.enrollment_id,
                company_id=company_id,
                created_by=admin.user_id,
                outcome="internship",
                status="accepted",
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    spec = executor.registry.commands["attach_external_offer"]
    input_value = spec.input_model.model_validate(
        {
            "cycle_id": cycle,
            "external_offer_id": external_offer,
            "reason": "Attach accepted internship",
        }
    )
    try:
        if allowed:
            result = await executor.run("attach_external_offer", input_value, admin.actor)
            assert isinstance(result, Result)
        else:
            with pytest.raises(DomainRejection) as error:
                await executor.run("attach_external_offer", input_value, admin.actor, dry_run=True)
            assert error.value.rejection.reasons[0].code == "offer_cap_reached"
    finally:
        await command_engine.dispose()


async def test_INT2_offer_cap_override_authorises_attachment_and_is_audited() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="attach-override@example.edu")
            cycle = await seed_cycle(connection, kind="internship")
            job = await seed_job(connection, cycle_id=cycle, outcome="internship")
            company_id = await _company(connection, job)
            application, _ = await seed_application(
                connection,
                cycle_id=cycle,
                enrollment_id=student.enrollment_id,
                status="accepted",
                job_id=job,
            )
            await seed_portal_offer(
                connection, application_id=application, response="accepted"
            )
            external_offer = await seed_external_offer(
                connection,
                enrollment_id=student.enrollment_id,
                company_id=company_id,
                created_by=admin.user_id,
                outcome="internship",
                status="accepted",
            )
            override_id = await grant(
                connection,
                domain=RuleDomain.OFFER_CAP,
                granted_by=admin.user_id,
                enrollment_id=student.enrollment_id,
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    spec = executor.registry.commands["attach_external_offer"]
    try:
        result = await executor.run(
            "attach_external_offer",
            spec.input_model.model_validate(
                {
                    "cycle_id": cycle,
                    "external_offer_id": external_offer,
                    "reason": "The cycle approved one additional accepted offer",
                }
            ),
            admin.actor,
        )
    finally:
        await command_engine.dispose()
    assert isinstance(result, Result)
    assert result.summary["applied_override_ids"] == [str(override_id)]

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            details = await connection.scalar(
                sa.text(
                    "SELECT details FROM audit_log "
                    "WHERE action = 'attach_external_offer'"
                )
            )
    finally:
        await engine.dispose()
    assert details["external_offer_id"] == str(external_offer)
    assert details["applied_override_ids"] == [str(override_id)]


async def test_INT2_bulk_attachment_resolves_offer_cap_overrides_per_student() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            allowed = await seed_person(connection, email="bulk-allowed@example.edu")
            blocked = await seed_person(connection, email="bulk-blocked@example.edu")
            cycle = await seed_cycle(connection, kind="internship")
            job = await seed_job(connection, cycle_id=cycle, outcome="internship")
            company_id = await _company(connection, job)
            external_ids: dict[UUID, UUID] = {}
            for student in (allowed, blocked):
                application, _ = await seed_application(
                    connection,
                    cycle_id=cycle,
                    enrollment_id=student.enrollment_id,
                    status="accepted",
                    job_id=job,
                )
                await seed_portal_offer(
                    connection, application_id=application, response="accepted"
                )
                external_ids[student.enrollment_id] = await seed_external_offer(
                    connection,
                    enrollment_id=student.enrollment_id,
                    company_id=company_id,
                    created_by=admin.user_id,
                    outcome="internship",
                    status="accepted",
                )
            override_id = await grant(
                connection,
                domain=RuleDomain.OFFER_CAP,
                granted_by=admin.user_id,
                enrollment_id=allowed.enrollment_id,
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    try:
        result = await executor.run_bulk(
            "attach_external_offers",
            [
                {"external_offer_id": str(external_ids[allowed.enrollment_id])},
                {"external_offer_id": str(external_ids[blocked.enrollment_id])},
            ],
            "external-bulk-override",
            admin.actor,
            batch_fields={
                "cycle_id": cycle,
                "reason": "Apply only the student's own exception",
            },
        )
    finally:
        await command_engine.dispose()
    assert isinstance(result, Result)
    rows = {
        UUID(cast(str, row["external_offer_id"])): row
        for row in cast("list[dict[str, object]]", result.summary["rows"])
    }
    allowed_row = rows[external_ids[allowed.enrollment_id]]
    blocked_row = rows[external_ids[blocked.enrollment_id]]
    assert allowed_row["status"] == "ok"
    assert allowed_row["applied_override_ids"] == [str(override_id)]
    assert blocked_row["status"] == "skipped"
    assert blocked_row["reason"] == "offer_cap_reached"


async def test_EXT3_bulk_attach_uses_virtual_cap_and_audits_each_enrollment() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="bulk-cap@example.edu")
            cycle = await seed_cycle(connection)
            job = await seed_job(connection, cycle_id=cycle)
            company_id = await _company(connection, job)
            first = await seed_external_offer(
                connection,
                enrollment_id=student.enrollment_id,
                company_id=company_id,
                created_by=admin.user_id,
                status="accepted",
            )
            second = await seed_external_offer(
                connection,
                enrollment_id=student.enrollment_id,
                company_id=company_id,
                created_by=admin.user_id,
                status="accepted",
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    try:
        result = await executor.run_bulk(
            "attach_external_offers",
            [
                {"external_offer_id": str(first)},
                {"external_offer_id": str(second)},
            ],
            "external-bulk-cap",
            admin.actor,
            batch_fields={
                "cycle_id": cycle,
                "reason": "Attach the accepted placement records",
            },
        )
    finally:
        await command_engine.dispose()
    assert isinstance(result, Result)
    rows = cast("list[dict[str, object]]", result.summary["rows"])
    assert [row["status"] for row in rows].count("ok") == 1
    assert [row["reason"] for row in rows].count("offer_cap_reached") == 1

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    sa.text(
                        "SELECT count(*) FROM audit_log "
                        "WHERE action = 'attach_external_offers' "
                        "AND subject_id = :enrollment"
                    ),
                    {"enrollment": student.enrollment_id},
                )
                == 1
            )
    finally:
        await engine.dispose()
