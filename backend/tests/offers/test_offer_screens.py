"""M12f offer screens and the design review section 4.22 equivalence pins."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import DomainRejection
from app.core.plan import Preview, Result
from app.modules.offers.screens import (
    staff_cycle_external_offers,
    staff_external_offers,
    staff_job_offers,
    student_dashboard,
)
from tests.cycles.conftest import Person
from tests.offers.conftest import (
    build_test_executor,
    seed_admin,
    seed_application,
    seed_cycle,
    seed_external_offer,
    seed_job,
    seed_membership,
    seed_person,
    seed_portal_offer,
)

pytestmark = pytest.mark.asyncio


def _read_engine():  # noqa: ANN202 - compact test helper
    return create_engine(os.environ["TEST_DATABASE_URL"])


def _write_engine():  # noqa: ANN202 - compact test helper
    return create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])


async def _execute(sql: str, values: dict[str, object]) -> None:
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(sa.text(sql), values)
    finally:
        await engine.dispose()


def _permission(row: dict[str, object], action: str) -> bool:
    actions = cast("dict[str, object]", row["actions"])
    permission = cast("dict[str, object]", actions[action])
    return permission["allowed"] is True


async def _offer_world() -> tuple[Person, Person, UUID, UUID, UUID, UUID]:
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="screen-offer@example.edu")
            cycle = await seed_cycle(connection)
            await seed_membership(
                connection,
                cycle_id=cycle,
                enrollment_id=student.enrollment_id,
            )
            job = await seed_job(connection, cycle_id=cycle, title="Screen offer")
            await connection.execute(
                sa.text(
                    "UPDATE jobs SET offer_acceptance_deadline = now() + interval '60 days' "
                    "WHERE id = :id"
                ),
                {"id": job},
            )
            application, _ = await seed_application(
                connection,
                cycle_id=cycle,
                enrollment_id=student.enrollment_id,
                status="offered",
                job_id=job,
            )
            offer = await seed_portal_offer(
                connection,
                application_id=application,
                deadline=datetime.now(UTC) + timedelta(days=60),
            )
    finally:
        await engine.dispose()
    return admin, student, cycle, job, application, offer


async def _dashboard_offer(enrollment_id: UUID, offer_id: UUID) -> dict[str, object]:
    engine = _read_engine()
    try:
        dashboard = await student_dashboard(engine, enrollment_id)
    finally:
        await engine.dispose()
    offers = cast("list[dict[str, object]]", dashboard["offers"])
    return next(row for row in offers if row["offer_id"] == str(offer_id))


async def test_OFR3_dashboard_accept_and_decline_controls_match_real_commands() -> None:
    """True, false, override, and gate-failure states all agree (§4.22)."""
    admin, student, cycle, job, application, offer = await _offer_world()
    executor, command_engine = build_test_executor()
    accept_spec = executor.registry.commands["accept_offer"]
    input_value = accept_spec.input_model.model_validate(
        {
            "cycle_id": cycle,
            "job_id": job,
            "application_id": application,
            "offer_id": offer,
            "enrollment_id": student.enrollment_id,
            "expected_status": "offered",
        }
    )

    async def allows(command: str) -> bool:
        try:
            await executor.run(command, input_value, student.actor, dry_run=True)
        except DomainRejection:
            return False
        return True

    try:
        # 1. Current and in-window.
        card = await _dashboard_offer(student.enrollment_id, offer)
        assert _permission(card, "accept") is await allows("accept_offer") is True
        assert _permission(card, "decline") is await allows("decline_offer") is True

        # 2. Closed deadline.
        await _execute(
            "UPDATE offers SET deadline_at = now() - interval '1 day' WHERE id = :id",
            {"id": offer},
        )
        card = await _dashboard_offer(student.enrollment_id, offer)
        assert _permission(card, "accept") is await allows("accept_offer") is False
        assert _permission(card, "decline") is await allows("decline_offer") is False

        # 3. A live offer-deadline override reopens both controls.
        await _execute(
            "INSERT INTO overrides (id, rule_domain, application_id, allow, reason, "
            "granted_by) VALUES (:id, 'offer_deadline', :application, true, "
            "'Office extension', :admin)",
            {"id": uuid4(), "application": application, "admin": admin.user_id},
        )
        card = await _dashboard_offer(student.enrollment_id, offer)
        assert _permission(card, "accept") is await allows("accept_offer") is True
        assert _permission(card, "decline") is await allows("decline_offer") is True

        # 4. An existing accepted placement blocks acceptance, not decline.
        engine = _write_engine()
        try:
            async with engine.begin() as connection:
                company_id = await connection.scalar(
                    sa.text("SELECT company_id FROM jobs WHERE id = :id"), {"id": job}
                )
                assert isinstance(company_id, UUID)
                await seed_external_offer(
                    connection,
                    enrollment_id=student.enrollment_id,
                    company_id=company_id,
                    created_by=admin.user_id,
                    status="accepted",
                )
        finally:
            await engine.dispose()
        card = await _dashboard_offer(student.enrollment_id, offer)
        assert _permission(card, "accept") is await allows("accept_offer") is False
        assert _permission(card, "decline") is await allows("decline_offer") is True
    finally:
        await command_engine.dispose()


async def test_OFR2_OFR5_staff_offer_controls_match_extension_termination_and_reextend() -> None:
    admin, student, cycle, job, application, offer = await _offer_world()
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            second = await seed_person(connection, email="extend-screen@example.edu")
            pending_application, _ = await seed_application(
                connection,
                cycle_id=cycle,
                enrollment_id=second.enrollment_id,
                status="pending_offer",
                job_id=job,
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    terminate = executor.registry.commands["terminate_offer"]
    reextend = executor.registry.commands["re_extend_offer"]
    try:
        engine = _read_engine()
        try:
            screen = await staff_job_offers(engine, job_id=job)
        finally:
            await engine.dispose()
        assert screen is not None
        rows = cast("list[dict[str, object]]", screen["applications"])
        offered = next(row for row in rows if row["application_id"] == str(application))
        pending = next(row for row in rows if row["application_id"] == str(pending_application))

        terminate_input = terminate.input_model.model_validate(
            {
                "cycle_id": cycle,
                "job_id": job,
                "application_id": application,
                "offer_id": offer,
                "expected_status": "offered",
                "termination_kind": "admin_correction",
                "reason": "Screen equivalence",
            }
        )
        terminate_allowed = True
        try:
            preview = await executor.run(
                "terminate_offer", terminate_input, admin.actor, dry_run=True
            )
            assert isinstance(preview, Preview)
        except DomainRejection:
            terminate_allowed = False
        assert _permission(offered, "terminate") is terminate_allowed is True

        extend_result = await executor.run_bulk(
            "extend_offers",
            [{"application_id": str(pending_application)}],
            "screen-extend-preview",
            admin.actor,
            dry_run=True,
            batch_fields={"cycle_id": cycle, "job_id": job},
        )
        extend_rows = cast("list[dict[str, object]]", extend_result.summary["rows"])
        assert _permission(pending, "extend") is (extend_rows[0]["status"] == "ok") is True

        result = await executor.run("terminate_offer", terminate_input, admin.actor)
        assert isinstance(result, Result)
        engine = _read_engine()
        try:
            after = await staff_job_offers(engine, job_id=job)
        finally:
            await engine.dispose()
        assert after is not None
        terminated = next(
            row
            for row in cast("list[dict[str, object]]", after["applications"])
            if row["application_id"] == str(application)
        )
        reextend_input = reextend.input_model.model_validate(
            {
                "cycle_id": cycle,
                "job_id": job,
                "application_id": application,
                "offer_id": offer,
                "expected_status": "offer_terminated",
                "reason": "Screen re-extension",
            }
        )
        reextend_allowed = True
        try:
            await executor.run("re_extend_offer", reextend_input, admin.actor, dry_run=True)
        except DomainRejection:
            reextend_allowed = False
        assert _permission(terminated, "re_extend") is reextend_allowed is True
    finally:
        await command_engine.dispose()


async def test_OFR5_staff_screen_carries_causal_restoration_choices_with_rounds() -> None:
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            await seed_admin(connection)
            student = await seed_person(connection, email="screen-restore@example.edu")
            cycle = await seed_cycle(connection)
            other_cycle = await seed_cycle(connection, name="Restoration cycle")
            job = await seed_job(connection, cycle_id=cycle, title="Accepted screen offer")
            application, _ = await seed_application(
                connection,
                cycle_id=cycle,
                enrollment_id=student.enrollment_id,
                status="offered",
                job_id=job,
            )
            offer = await seed_portal_offer(connection, application_id=application)
            other_job = await seed_job(connection, cycle_id=other_cycle, title="Prior process")
            other_application, prior_round = await seed_application(
                connection,
                cycle_id=other_cycle,
                enrollment_id=student.enrollment_id,
                status="pending_offer",
                with_round=True,
                job_id=other_job,
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    spec = executor.registry.commands["accept_offer"]
    try:
        result = await executor.run(
            "accept_offer",
            spec.input_model.model_validate(
                {
                    "cycle_id": cycle,
                    "job_id": job,
                    "application_id": application,
                    "offer_id": offer,
                    "enrollment_id": student.enrollment_id,
                    "expected_status": "offered",
                }
            ),
            student.actor,
        )
        assert isinstance(result, Result)
    finally:
        await command_engine.dispose()

    engine = _read_engine()
    try:
        screen = await staff_job_offers(engine, job_id=job)
    finally:
        await engine.dispose()
    assert screen is not None
    row = cast("list[dict[str, object]]", screen["applications"])[0]
    candidates = cast("list[dict[str, object]]", row["restoration_candidates"])
    assert candidates == [
        {
            **candidates[0],
            "application_id": str(other_application),
            "restore_status": "pending_offer",
            "target_round_id": str(prior_round),
            "selected": False,
        }
    ]
    assert _permission(row, "terminate") is True


async def test_EXT3_cycle_attach_permission_matches_the_real_command_at_cap_edges() -> None:
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="attach-pin@example.edu")
            cycle = await seed_cycle(connection, kind="internship")
            portal_job = await seed_job(
                connection, cycle_id=cycle, outcome="internship", title="Accepted portal"
            )
            company_id = await connection.scalar(
                sa.text("SELECT company_id FROM jobs WHERE id = :id"),
                {"id": portal_job},
            )
            assert isinstance(company_id, UUID)
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
                status="offered",
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    spec = executor.registry.commands["attach_external_offer"]
    input_value = spec.input_model.model_validate(
        {
            "cycle_id": cycle,
            "external_offer_id": external_offer,
            "reason": "Equivalence pin",
        }
    )

    async def command_allows() -> bool:
        try:
            await executor.run(
                "attach_external_offer", input_value, admin.actor, dry_run=True
            )
        except DomainRejection:
            return False
        return True

    async def screen_allows() -> bool:
        engine = _read_engine()
        try:
            screen = await staff_cycle_external_offers(engine, cycle_id=cycle)
        finally:
            await engine.dispose()
        assert screen is not None
        row = cast("list[dict[str, object]]", screen["unattached_pool"])[0]
        return _permission(row, "attach")

    try:
        # Offered rows consume no cap, so they may attach even when one accepted
        # portal offer already fills the cycle.
        assert await screen_allows() is await command_allows() is True
        await _execute(
            "UPDATE external_offers SET status = 'accepted' WHERE id = :id",
            {"id": external_offer},
        )
        assert await screen_allows() is await command_allows() is False
    finally:
        await command_engine.dispose()


async def test_EXT_screens_show_global_pool_cycle_pool_and_student_read_only_rows() -> None:
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="external-screen@example.edu")
            cycle = await seed_cycle(connection)
            await seed_membership(connection, cycle_id=cycle, enrollment_id=student.enrollment_id)
            job = await seed_job(connection, cycle_id=cycle)
            company_id = await connection.scalar(
                sa.text("SELECT company_id FROM jobs WHERE id = :id"), {"id": job}
            )
            assert isinstance(company_id, UUID)
            external_offer = await seed_external_offer(
                connection,
                enrollment_id=student.enrollment_id,
                company_id=company_id,
                created_by=admin.user_id,
            )
    finally:
        await engine.dispose()

    engine = _read_engine()
    try:
        global_screen = await staff_external_offers(engine)
        cycle_screen = await staff_cycle_external_offers(engine, cycle_id=cycle)
        dashboard = await student_dashboard(engine, student.enrollment_id)
    finally:
        await engine.dispose()
    global_rows = cast("list[dict[str, object]]", global_screen["offers"])
    assert [row["id"] for row in global_rows] == [str(external_offer)]
    assert cycle_screen is not None
    pool = cast("list[dict[str, object]]", cycle_screen["unattached_pool"])
    assert [row["id"] for row in pool] == [str(external_offer)]
    assert _permission(pool[0], "attach") is True
    student_rows = cast("list[dict[str, object]]", dashboard["external_offers"])
    assert [row["id"] for row in student_rows] == [str(external_offer)]
    assert student_rows[0]["read_only"] is True
    assert student_rows[0]["actions"] == {}
