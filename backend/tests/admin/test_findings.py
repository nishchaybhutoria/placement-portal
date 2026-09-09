"""Finding verdicts and the admin/findings surface (LLD sections 11.3, 12)."""

from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from pydantic import ValidationError

from app.core.authz import Authorizer
from app.core.errors import (
    FINDING_NOT_FOUND,
    FINDING_NOT_OPEN,
    AuthorizationDenied,
    DomainRejection,
)
from app.core.plan import Preview, Result
from app.modules.admin.checker import INVARIANTS
from app.modules.admin.commands import ResolveFindingInput, RunConsistencyCheckerInput
from app.modules.admin.queries import admin_findings
from tests.admin.conftest import (
    CheckerWorld,
    Person,
    build_checker_world,
    build_test_executor,
    finding_rows,
    read_engine,
    seed_person,
    write_engine,
)
from tests.admin.test_consistency_checker import CORRUPTIONS, _inject, _run_checker

pytestmark = pytest.mark.asyncio


async def _screen(**filters: object) -> dict[str, object]:
    engine = read_engine()
    try:
        return await admin_findings(engine, **filters)  # type: ignore[arg-type]
    finally:
        await engine.dispose()


def _rows(body: dict[str, object]) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", body["findings"])


async def _one_finding() -> tuple[UUID, CheckerWorld]:
    world = await build_checker_world()
    await _inject(CORRUPTIONS["no_live_application_without_active_membership"], world)
    await _run_checker()
    rows = await finding_rows("no_live_application_without_active_membership")
    return cast(UUID, rows[0]["id"]), world


async def test_S16_the_findings_screen_carries_the_fix_the_checker_named(
    clean_findings: None,
) -> None:
    """The button's payload comes from the same catalog entry as the suggestion.

    If the screen assembled its own input, the finding could name one command
    and the button send another -- and nobody would find out until an
    administrator pressed it during an incident.
    """
    del clean_findings
    finding_id, world = await _one_finding()

    body = await _screen()
    rows = _rows(body)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == str(finding_id)
    assert row["invariant"] == "no_live_application_without_active_membership"
    assert row["description"]
    assert row["status"] == "open"
    fix = cast("dict[str, object]", row["suggested_fix"])
    assert fix["command"] == "restore_membership"
    payload = cast("dict[str, object]", fix["input"])
    assert payload["membership_id"] == str(world.membership_id)
    assert cast("dict[str, object]", row["actions"])["resolve"] == {
        "allowed": True,
        "reason": None,
        "human": None,
    }
    assert [item["id"] for item in cast("list[dict[str, object]]", body["invariants"])] == [
        invariant.id for invariant in INVARIANTS
    ]


async def test_S16_resolving_and_dismissing_close_a_finding_with_a_reason(
    clean_findings: None,
) -> None:
    del clean_findings
    finding_id, _world = await _one_finding()
    executor, _engine = build_test_executor()
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            admin = await seed_person(
                connection, email=f"resolver-{uuid4().hex[:6]}@example.edu", role="admin"
            )
    finally:
        await engine.dispose()

    result = await executor.run(
        "resolve_finding",
        ResolveFindingInput(
            finding_id=finding_id, reason="Membership restored by hand this morning"
        ),
        admin.actor,
    )
    assert isinstance(result, Result)
    assert result.summary["status"] == "resolved"

    body = await _screen()
    row = _rows(body)[0]
    assert row["status"] == "resolved"
    assert row["resolved_at"] is not None
    actions = cast("dict[str, object]", row["actions"])
    assert cast("dict[str, object]", actions["dismiss"])["allowed"] is False
    assert cast("dict[str, object]", actions["dismiss"])["reason"] == FINDING_NOT_OPEN

    with pytest.raises(DomainRejection) as repeated:
        await executor.run(
            "dismiss_finding",
            ResolveFindingInput(finding_id=finding_id, reason="Already closed"),
            admin.actor,
        )
    assert [r.code for r in repeated.value.rejection.reasons] == [FINDING_NOT_OPEN]

    engine = read_engine()
    try:
        async with engine.connect() as connection:
            audit = (
                await connection.execute(
                    sa.text(
                        "SELECT action, details FROM audit_log WHERE subject_id = :id"
                    ),
                    {"id": finding_id},
                )
            ).mappings().one()
    finally:
        await engine.dispose()
    assert audit["action"] == "resolve_finding"
    assert (
        cast("dict[str, object]", audit["details"])["reason"]
        == "Membership restored by hand this morning"
    )


async def test_S16_a_verdict_requires_a_reason_and_an_existing_finding(
    clean_findings: None,
) -> None:
    del clean_findings
    with pytest.raises(ValidationError):
        ResolveFindingInput(finding_id=uuid4(), reason="  ")

    executor, _engine = build_test_executor()
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            admin = await seed_person(
                connection, email=f"admin-{uuid4().hex[:6]}@example.edu", role="admin"
            )
            staff = await seed_person(
                connection, email=f"staff-{uuid4().hex[:6]}@example.edu", role="student"
            )
    finally:
        await engine.dispose()

    with pytest.raises(DomainRejection) as missing:
        await executor.run(
            "resolve_finding",
            ResolveFindingInput(finding_id=uuid4(), reason="No such finding"),
            admin.actor,
        )
    assert [r.code for r in missing.value.rejection.reasons] == [FINDING_NOT_FOUND]

    # Findings are administrative: a coordinator has no verdict on portal-wide
    # drift, which is why LLD section 10 puts both commands under ADMIN.
    with pytest.raises(AuthorizationDenied):
        await executor.run(
            "dismiss_finding",
            ResolveFindingInput(finding_id=uuid4(), reason="Not mine to close"),
            staff.coordinating(uuid4()).actor,
        )


async def test_S16_the_findings_screen_filters_by_status_and_invariant(
    clean_findings: None,
) -> None:
    del clean_findings
    world = await build_checker_world()
    await _inject(CORRUPTIONS["no_live_application_without_active_membership"], world)
    await _inject(CORRUPTIONS["open_cycle_jobs_carry_no_acceptance_deadline"], world)
    await _run_checker()

    assert len(_rows(await _screen())) == 2
    only = _rows(await _screen(invariant="open_cycle_jobs_carry_no_acceptance_deadline"))
    assert len(only) == 1
    assert only[0]["invariant"] == "open_cycle_jobs_carry_no_acceptance_deadline"
    # A fix the subject cannot prefill is named without a button rather than
    # offering one that would be refused.
    assert cast("dict[str, object]", only[0]["suggested_fix"])["input"] is None

    assert _rows(await _screen(status="resolved")) == []
    assert cast("dict[str, object]", (await _screen())["counts"])["open"] == 2


async def test_S16_an_administrator_can_run_the_checker_from_the_findings_screen(
    clean_findings: None,
) -> None:
    """the design review section 4.36: the nightly pass is also an operator control.

    The pin is the pair of answers: the screen offers the run, the command
    accepts it from the same actor, and the run an administrator triggers opens
    the same finding the 03:00 pass would have. A coordinator is refused at
    both ends -- a checker run is system-wide, not scoped to their cycle.
    """
    del clean_findings
    world = await build_checker_world()
    await _inject(CORRUPTIONS["no_live_application_without_active_membership"], world)

    body = await _screen()
    offered = cast(
        "dict[str, object]",
        cast("dict[str, object]", body["actions"])["run_checker"],
    )
    assert offered["allowed"] is True

    executor, engine = build_test_executor()
    spec = executor.registry.commands["run_consistency_checker"]
    coordinator = await _coordinator()
    try:
        preview = await executor.run(
            "run_consistency_checker",
            RunConsistencyCheckerInput(),
            world.admin_actor,
            dry_run=True,
        )
        assert isinstance(preview, Preview)
        assert preview.summary["violations"] == 1
        # The preview is a read: nothing is recorded until confirm.
        assert await finding_rows() == []

        result = await executor.run(
            "run_consistency_checker", RunConsistencyCheckerInput(), world.admin_actor
        )
        assert isinstance(result, Result)
        assert result.summary["findings_opened"] == 1

        with pytest.raises(AuthorizationDenied):
            Authorizer().check(spec, coordinator.actor, RunConsistencyCheckerInput())
        with pytest.raises(AuthorizationDenied):
            await executor.run(
                "run_consistency_checker",
                RunConsistencyCheckerInput(),
                coordinator.actor,
            )
    finally:
        await engine.dispose()

    rows = await finding_rows("no_live_application_without_active_membership")
    assert len(rows) == 1
    audit = await _last_checker_audit()
    assert audit["actor_user_id"] == world.admin.user_id, (
        "an operator-triggered run must name the operator, not the worker"
    )


async def _coordinator() -> Person:
    """A coordinator of some cycle, which is not enough to run the checker."""
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            person = await seed_person(
                connection, email=f"coord-{uuid4().hex[:6]}@example.edu"
            )
            cycle_id = uuid4()
            await connection.execute(
                sa.text(
                    "INSERT INTO cycles (id, name, kind, is_active) "
                    "VALUES (:id, :name, 'placement', true)"
                ),
                {"id": cycle_id, "name": f"Cycle {uuid4().hex[:6]}"},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO cycle_coordinators (id, cycle_id, user_id) "
                    "VALUES (:id, :cycle_id, :user_id)"
                ),
                {"id": uuid4(), "cycle_id": cycle_id, "user_id": person.user_id},
            )
    finally:
        await engine.dispose()
    return person.coordinating(cycle_id)


async def _last_checker_audit() -> sa.RowMapping:
    engine = read_engine()
    try:
        async with engine.connect() as connection:
            return (
                await connection.execute(
                    sa.text(
                        "SELECT actor_user_id, details FROM audit_log "
                        "WHERE action = 'run_consistency_checker' "
                        "ORDER BY created_at DESC, id DESC LIMIT 1"
                    )
                )
            ).mappings().one()
    finally:
        await engine.dispose()
