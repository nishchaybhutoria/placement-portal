"""The test executor must be the production executor (M10a regression guard).

``tests/cycles/conftest.build_test_executor`` is the assembly every suite from
M8 onward runs commands through.  Until M10 it constructed its own ``Executor``
and omitted ``override_resolver``, so **every override was inert under it** while
production resolved them.  Nothing failed: a test could assert that an override
bypassed a gate, watch the command succeed for the unrelated reason that no
override was ever loaded, and pass.

M12 (offer-cap and offer-deadline overrides) and M14 (the override system
itself) both reach for this helper, so the bug would have been discovered as two
milestones of false green.  (M11 was listed here too, for "penalty overrides";
the design review section 4.14 makes the penalty gate explicitly non-overridable and
`RuleDomain` has no penalty member, so no such override exists.)

These tests pin the class: not "the helper passes a resolver today" -- which
a refactor could quietly undo -- but "the two assemblies decide an
override-consulting command identically".
"""

from __future__ import annotations

import os
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.bootstrap import build_executor, build_registry
from app.core.db import create_engine
from app.core.errors import NOT_ELIGIBLE, DomainRejection
from app.core.executor import Executor
from app.core.plan import Preview
from app.settings import Settings
from tests.applications.conftest import (
    World,
    build_test_executor,
    cpi_floor_rule,
    seed_world,
    set_eligibility_rule,
)

pytestmark = pytest.mark.asyncio


def _production_executor() -> tuple[Executor, object]:
    registry = build_registry(
        settings=Settings(
            session_secret="assembly-test-session-secret-32-chars", dev_login=False
        )
    )
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    return build_executor(registry, engine), engine


async def _apply_under(executor: Executor, world: World) -> Preview | list[str]:
    model = executor.registry.commands["apply"].input_model
    payload = {
        "cycle_id": str(world.cycle_id),
        "job_id": str(world.job_id),
        "enrollment_id": str(world.student.enrollment_id),
    }
    try:
        result = await executor.run(
            "apply", model.model_validate(payload), world.student.actor, dry_run=True
        )
        return cast(Preview, result)
    except DomainRejection as rejection:
        return [reason.code for reason in rejection.rejection.reasons]


async def _world_with_a_rule_the_student_fails() -> World:
    world = await seed_world(cpi="7.90")
    rule, summary = cpi_floor_rule("9.00")
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await set_eligibility_rule(
                connection, job_id=world.job_id, rule=rule, summary=summary
            )
    finally:
        await engine.dispose()
    return world


async def _grant_eligibility_override(world: World) -> UUID:
    override_id = uuid4()
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "INSERT INTO overrides (id, rule_domain, enrollment_id, job_id, "
                    "allow, reason, granted_by, created_at) SELECT :id, 'eligibility', "
                    ":enrollment, :job, true, 'Committee decision', u.id, now() "
                    "FROM users u WHERE u.role = 'admin' LIMIT 1"
                ),
                {
                    "id": override_id,
                    "enrollment": world.student.enrollment_id,
                    "job": world.job_id,
                },
            )
    finally:
        await engine.dispose()
    return override_id


async def test_INT2_both_assemblies_refuse_identically_without_an_override() -> None:
    """The control: with no override, both must reject on the rule."""
    world = await _world_with_a_rule_the_student_fails()

    shared, shared_engine = build_test_executor()
    production, production_engine = _production_executor()
    try:
        under_shared = await _apply_under(shared, world)
        under_production = await _apply_under(production, world)
    finally:
        await shared_engine.dispose()
        await production_engine.dispose()  # type: ignore[attr-defined]

    assert under_shared == under_production == [NOT_ELIGIBLE]


async def test_INT2_both_assemblies_honour_an_override_identically() -> None:
    """The regression: an override must not be inert under the test helper.

    If ``build_test_executor`` stops resolving overrides, the shared assembly
    rejects here while production allows -- and this test says so, instead of a
    later milestone's bypass test passing for the wrong reason.
    """
    world = await _world_with_a_rule_the_student_fails()
    await _grant_eligibility_override(world)

    shared, shared_engine = build_test_executor()
    production, production_engine = _production_executor()
    try:
        under_shared = await _apply_under(shared, world)
        under_production = await _apply_under(production, world)
    finally:
        await shared_engine.dispose()
        await production_engine.dispose()  # type: ignore[attr-defined]

    assert isinstance(under_shared, Preview), (
        "the shared test executor ignored an override that production honours"
    )
    assert isinstance(under_production, Preview)
    assert under_shared.events == under_production.events
