"""The card and the apply must agree, always (the design review section 4.21).

This is the deliverable the shared builder exists to serve, not the builder
itself.  Both call sites can import one function and still populate its context
differently, so these tests run the **full display path** (the real screen
handler, over the real engine) and the **full apply path** (the real command,
through the real executor) for the same student and job, and compare what each
one says -- verdict and the ordered list of reasons, code, sentence and path.

The ineligible case fails on a rule-tree leaf on purpose.  An incidental failure
like a passed deadline would prove far less: both paths read the deadline from
the same column, whereas the rule runs through the evaluator with labels, a
profile snapshot shape, and a criterion context -- which is where the two would
actually drift.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import cast
from uuid import UUID

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import NOT_ELIGIBLE, DomainRejection
from app.core.plan import Preview
from app.modules.jobs.queries import student_cycle_jobs, student_job_detail
from tests.applications.conftest import (
    World,
    build_test_executor,
    cpi_floor_rule,
    seed_world,
    set_eligibility_rule,
)

pytestmark = pytest.mark.asyncio


async def _apply(world: World, *, dry_run: bool = True) -> Preview | object:
    executor, engine = build_test_executor()
    model = executor.registry.commands["apply"].input_model
    try:
        return await executor.run(
            "apply",
            model.model_validate(
                {
                    "cycle_id": str(world.cycle_id),
                    "job_id": str(world.job_id),
                    "enrollment_id": str(world.student.enrollment_id),
                }
            ),
            world.student.actor,
            dry_run=dry_run,
        )
    finally:
        await engine.dispose()


async def _display_reasons(world: World) -> tuple[bool, list[dict[str, object]]]:
    """What the student's own screens say, both of them."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        listing = await student_cycle_jobs(
            engine, cycle_id=world.cycle_id, enrollment_id=world.student.enrollment_id
        )
        detail = await student_job_detail(
            engine, job_id=world.job_id, enrollment_id=world.student.enrollment_id
        )
    finally:
        await engine.dispose()
    assert listing is not None
    assert detail is not None
    card = next(
        job
        for job in cast("list[dict[str, object]]", listing["jobs"])
        if job["id"] == str(world.job_id)
    )
    # The two student screens must agree with each other before either is
    # compared with apply; they render from one call but through two handlers.
    eligibility = cast("dict[str, object]", detail["eligibility"])
    assert card["eligible"] == eligibility["eligible"]
    assert card["reasons"] == eligibility["reasons"]
    return bool(card["eligible"]), cast("list[dict[str, object]]", card["reasons"])


async def _apply_reasons(world: World) -> tuple[bool, list[dict[str, object]]]:
    try:
        await _apply(world)
    except DomainRejection as rejection:
        return False, [asdict(reason) for reason in rejection.rejection.reasons]
    return True, []


async def _rule_on(world: World, floor: str) -> None:
    rule, summary = cpi_floor_rule(floor)
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await set_eligibility_rule(
                connection, job_id=world.job_id, rule=rule, summary=summary
            )
    finally:
        await engine.dispose()


async def test_ELG1_card_and_apply_agree_when_the_rule_passes() -> None:
    world = await seed_world(cpi="8.40")
    await _rule_on(world, "8.00")

    displayed, display_reasons = await _display_reasons(world)
    applied, apply_reasons = await _apply_reasons(world)

    assert displayed is True
    assert applied is True
    assert display_reasons == apply_reasons == []


async def test_ELG1_card_and_apply_agree_when_the_rule_fails_on_a_leaf() -> None:
    """A CPI floor the student misses: the rule path, not circumstance."""
    world = await seed_world(cpi="7.90")
    await _rule_on(world, "9.00")

    displayed, display_reasons = await _display_reasons(world)
    applied, apply_reasons = await _apply_reasons(world)

    assert displayed is False
    assert applied is False
    # Same reasons, same order, same sentences, same paths -- not merely the
    # same verdict.  A student reads the sentence, not the boolean.
    assert display_reasons == apply_reasons
    assert [reason["code"] for reason in apply_reasons] == [NOT_ELIGIBLE]
    assert "9.0" in str(apply_reasons[0]["human"])


async def test_ELG1_card_and_apply_agree_when_a_gate_and_the_rule_both_fail() -> None:
    """Every reason, in one order, on both paths (JOB-4)."""
    world = await seed_world(cpi="7.90", membership_status="pending")
    await _rule_on(world, "9.00")

    displayed, display_reasons = await _display_reasons(world)
    applied, apply_reasons = await _apply_reasons(world)

    assert displayed is False
    assert applied is False
    assert display_reasons == apply_reasons
    assert len(apply_reasons) == 2


async def test_INT2_card_and_apply_agree_when_an_override_lets_the_student_in() -> None:
    """An override that bypasses the rule must be visible on the card too.

    This is the case the shared *populate* path exists for: the command gets its
    overrides from the executor and the screen resolves its own, so an override
    honoured at apply time and ignored on the card would leave a student staring
    at a rule they have already been excused from.
    """
    world = await seed_world(cpi="7.90")
    await _rule_on(world, "9.00")

    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin_id = cast(
                UUID,
                await connection.scalar(
                    sa.text("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
                ),
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO overrides (id, rule_domain, enrollment_id, job_id, "
                    "allow, reason, granted_by, created_at) VALUES "
                    "(gen_random_uuid(), 'eligibility', :enrollment_id, :job_id, "
                    "true, 'Committee decision', :granted_by, now())"
                ),
                {
                    "enrollment_id": world.student.enrollment_id,
                    "job_id": world.job_id,
                    "granted_by": admin_id,
                },
            )
    finally:
        await engine.dispose()

    displayed, display_reasons = await _display_reasons(world)
    applied, apply_reasons = await _apply_reasons(world)

    assert display_reasons == apply_reasons == []
    assert displayed is True
    assert applied is True
