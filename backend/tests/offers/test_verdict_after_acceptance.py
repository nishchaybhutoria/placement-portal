"""M12b's explicit card/command gate after a real portal acceptance."""

from __future__ import annotations

import os
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import DomainRejection
from app.core.plan import ActorContext, Result
from app.modules.jobs.queries import student_cycle_jobs
from app.seed import run_seed
from app.settings import Settings
from tests.applications.conftest import seed_world
from tests.offers.conftest import (
    build_test_executor,
    seed_application,
    seed_cycle,
    seed_job,
    seed_portal_offer,
)
from tests.offers.test_gate_cutover import _apply_reasons, _displayed_reasons

pytestmark = pytest.mark.asyncio


async def test_DER1_real_portal_acceptance_blocks_card_and_apply_equally() -> None:
    world = await seed_world(kind="placement", outcome="placement")
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            accepted_cycle = await seed_cycle(
                connection, name="A different placement cycle"
            )
            accepted_job = await seed_job(
                connection, cycle_id=accepted_cycle, title="Accepted elsewhere"
            )
            accepted_application, _ = await seed_application(
                connection,
                cycle_id=accepted_cycle,
                enrollment_id=world.student.enrollment_id,
                status="offered",
                job_id=accepted_job,
            )
            accepted_offer = await seed_portal_offer(
                connection, application_id=accepted_application
            )
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    spec = executor.registry.commands["accept_offer"]
    try:
        result = await executor.run(
            "accept_offer",
            spec.input_model.model_validate(
                {
                    "cycle_id": accepted_cycle,
                    "job_id": accepted_job,
                    "application_id": accepted_application,
                    "offer_id": accepted_offer,
                    "enrollment_id": world.student.enrollment_id,
                    "expected_status": "offered",
                }
            ),
            world.student.actor,
        )
    finally:
        await engine.dispose()
    assert isinstance(result, Result)

    displayed = await _displayed_reasons(world)
    applied = await _apply_reasons(world)
    assert displayed == applied
    assert [reason["code"] for reason in applied] == ["outcome_gate_placement"]


async def test_Chitras_penalty_gate_fires_even_when_the_seeded_job_rule_also_fails() -> None:
    await run_seed(
        database_url=os.environ["TEST_DATABASE_URL"],
        settings=Settings(
            session_secret="m12b-seed-verdict-secret-32-chars",
            allowed_domain="example.edu",
            dev_login=False,
        ),
        admin_email="admin@example.edu",
    )
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    sa.text(
                        "SELECT e.id AS enrollment_id, u.id AS user_id, "
                        "c.id AS cycle_id "
                        "FROM enrollments e JOIN users u ON u.id = e.user_id "
                        "JOIN cycle_memberships m ON m.enrollment_id = e.id "
                        "JOIN cycles c ON c.id = m.cycle_id "
                        "WHERE u.email = 'chitra.rao@example.edu' "
                        "AND c.name = 'Placement 2026'"
                    )
                )
            ).mappings().one()
            admin_id = await connection.scalar(
                sa.text("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
            )
    finally:
        await engine.dispose()
    assert isinstance(admin_id, UUID)
    enrollment_id = UUID(str(row["enrollment_id"]))
    cycle_id = UUID(str(row["cycle_id"]))

    # Chitra's seeded quantitative rule already fails.  Add a real active
    # penalty, then demand both failures: a short-circuiting gate would report
    # only not_eligible and this regression would fail.
    executor, engine = build_test_executor()
    award = executor.registry.commands["award_penalty"]
    try:
        await executor.run(
            "award_penalty",
            award.input_model.model_validate(
                {
                    "enrollment_id": enrollment_id,
                    "reasons": "M12b independent gate proof",
                }
            ),
            ActorContext(
                principal_id=str(admin_id),
                user_id=admin_id,
                role="admin",
                session_id=uuid4(),
            ),
        )
    finally:
        await engine.dispose()

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        listing = await student_cycle_jobs(
            engine, cycle_id=cycle_id, enrollment_id=enrollment_id
        )
    finally:
        await engine.dispose()
    assert listing is not None
    jobs = cast("list[dict[str, object]]", listing["jobs"])
    quantitative = next(
        job for job in jobs if job["title"] == "Quantitative Researcher"
    )
    reasons = cast("list[dict[str, object]]", quantitative["reasons"])
    codes = [reason["code"] for reason in reasons]
    assert "not_eligible" in codes
    assert "penalty_active" in codes

    executor, engine = build_test_executor()
    apply_spec = executor.registry.commands["apply"]
    try:
        with pytest.raises(DomainRejection) as error:
            await executor.run(
                "apply",
                apply_spec.input_model.model_validate(
                    {
                        "cycle_id": cycle_id,
                        "job_id": quantitative["id"],
                        "enrollment_id": enrollment_id,
                    }
                ),
                ActorContext(
                    principal_id=str(row["user_id"]),
                    user_id=UUID(str(row["user_id"])),
                    role="student",
                    session_id=uuid4(),
                    current_enrollment_id=enrollment_id,
                ),
                dry_run=True,
            )
    finally:
        await engine.dispose()
    command_codes = [
        reason.code for reason in error.value.rejection.reasons
    ]
    assert command_codes == codes
    assert "not_eligible" in command_codes
    assert "penalty_active" in command_codes
