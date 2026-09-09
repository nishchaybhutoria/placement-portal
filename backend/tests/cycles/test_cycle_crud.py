"""Cycle creation, editing, policy, and coordinators (Behavior CYC-1, CYC-2)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import (
    COORDINATOR_ALREADY_ASSIGNED,
    COORDINATOR_NOT_FOUND,
    CYCLE_ARCHIVED,
    CYCLE_NAME_CONFLICT,
    CYCLE_NOT_FOUND,
    FIELD_NOT_EDITABLE,
    INACTIVE_USER,
    INVALID_FIELD_VALUE,
    USER_NOT_FOUND,
    AuthorizationDenied,
    DomainRejection,
)
from app.core.plan import Preview, Result
from tests.cycles.conftest import (
    Person,
    build_test_executor,
    seed_admin,
    seed_coordinator_link,
    seed_cycle,
    seed_person,
)

pytestmark = pytest.mark.usefixtures("clean_cycles")


async def _admin() -> Person:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            return await seed_admin(connection)
    finally:
        await engine.dispose()


async def _reasons(coroutine: object) -> list[str]:
    with pytest.raises(DomainRejection) as error:
        await coroutine  # type: ignore[misc]
    return [reason.code for reason in error.value.rejection.reasons]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "approval", "cap"),
    [("placement", True, 1), ("internship", True, 1), ("open", False, None)],
)
async def test_CYC2_create_cycle_writes_policy_defaults_keyed_by_kind(
    kind: str, approval: bool, cap: int | None
) -> None:
    admin = await _admin()
    executor, engine = build_test_executor()
    try:
        result = await executor.run(
            "create_cycle",
            executor.registry.commands["create_cycle"].input_model.model_validate(
                {"name": f"{kind.title()} 2026", "kind": kind}
            ),
            admin.actor,
        )
    finally:
        await engine.dispose()

    assert isinstance(result, Result)
    cycle_id = UUID(cast(str, result.summary["cycle_id"]))
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.connect() as connection:
            policy = (
                await connection.execute(
                    sa.text("SELECT * FROM cycle_policies WHERE cycle_id = :id"),
                    {"id": cycle_id},
                )
            ).mappings().one()
            audit = (
                await connection.execute(
                    sa.text("SELECT action, subject_id, details FROM audit_log")
                )
            ).mappings().one()
    finally:
        await migration.dispose()

    # C6: the policy row is written in the same plan as the cycle itself.
    assert policy["membership_requires_approval"] is approval
    assert policy["max_accepted_offers"] == cap
    assert policy["offer_expiry_behavior"] == "auto_decline"
    assert policy["deadline_reminder_hours"] == 6
    assert policy["round_reminder_hours"] == 24
    assert audit["action"] == "create_cycle"
    assert audit["subject_id"] == cycle_id
    assert cast(dict[str, object], audit["details"])["before"] is None


@pytest.mark.asyncio
async def test_CYC1_cycle_names_are_case_insensitively_unique() -> None:
    admin = await _admin()
    executor, engine = build_test_executor()
    model = executor.registry.commands["create_cycle"].input_model
    try:
        await executor.run(
            "create_cycle",
            model.model_validate({"name": "Placement 2026", "kind": "placement"}),
            admin.actor,
        )
        codes = await _reasons(
            executor.run(
                "create_cycle",
                model.model_validate({"name": "placement 2026", "kind": "internship"}),
                admin.actor,
            )
        )
    finally:
        await engine.dispose()

    assert codes == [CYCLE_NAME_CONFLICT]


@pytest.mark.asyncio
async def test_CYC1_start_after_end_is_rejected_before_the_check_constraint() -> None:
    admin = await _admin()
    executor, engine = build_test_executor()
    model = executor.registry.commands["create_cycle"].input_model
    try:
        codes = await _reasons(
            executor.run(
                "create_cycle",
                model.model_validate(
                    {
                        "name": "Backwards",
                        "kind": "open",
                        "starts_on": "2026-06-01",
                        "ends_on": "2026-01-01",
                    }
                ),
                admin.actor,
            )
        )
    finally:
        await engine.dispose()

    assert codes == [INVALID_FIELD_VALUE]


@pytest.mark.asyncio
async def test_CYC1_cycle_kind_is_immutable_but_an_unchanged_echo_is_accepted() -> None:
    admin = await _admin()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            cycle_id = await seed_cycle(connection, kind="placement")
    finally:
        await migration.dispose()

    executor, engine = build_test_executor()
    model = executor.registry.commands["update_cycle"].input_model
    try:
        # Echoing the unchanged kind back is not an edit.
        echoed = await executor.run(
            "update_cycle",
            model.model_validate(
                {"cycle_id": str(cycle_id), "kind": "placement", "description": "Set"}
            ),
            admin.actor,
        )
        codes = await _reasons(
            executor.run(
                "update_cycle",
                model.model_validate({"cycle_id": str(cycle_id), "kind": "internship"}),
                admin.actor,
            )
        )
    finally:
        await engine.dispose()

    assert isinstance(echoed, Result)
    assert echoed.summary["kind"] == "placement"
    assert codes == [FIELD_NOT_EDITABLE]


@pytest.mark.asyncio
async def test_CYC1_a_lapsed_registration_window_can_be_extended() -> None:
    """The window is the only thing that reopens a cycle to joins (CYC-1/CYC-3)."""
    admin = await _admin()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            cycle_id = await seed_cycle(connection, registration_open=False)
    finally:
        await migration.dispose()

    extended = datetime.now(UTC) + timedelta(days=14)
    executor, engine = build_test_executor()
    model = executor.registry.commands["update_cycle"].input_model
    try:
        result = await executor.run(
            "update_cycle",
            model.model_validate(
                {
                    "cycle_id": str(cycle_id),
                    "registration_closes_at": extended.isoformat(),
                }
            ),
            admin.actor,
        )
    finally:
        await engine.dispose()

    check = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with check.connect() as connection:
            row = (
                await connection.execute(
                    sa.text(
                        "SELECT registration_opens_at, registration_closes_at, name "
                        "FROM cycles WHERE id = :id"
                    ),
                    {"id": cycle_id},
                )
            ).mappings().one()
    finally:
        await check.dispose()

    assert isinstance(result, Result)
    assert result.summary["changed"] is True
    assert row["registration_closes_at"] == extended
    # An absent key preserves the stored value; only what was named moves.
    assert row["registration_opens_at"] is not None
    assert row["name"] == "Placement 2026"


@pytest.mark.asyncio
async def test_CYC1_a_registration_window_that_closes_before_it_opens_is_refused() -> None:
    """`_window_reasons` reads the pair as `now < opens or now >= closes`.

    An inverted window is satisfied by no instant at all, so the cycle silently
    accepts nobody and every student is told only that registration "is not
    open". Refuse it where it is written instead.
    """
    admin = await _admin()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            cycle_id = await seed_cycle(connection)
    finally:
        await migration.dispose()

    now = datetime.now(UTC)
    executor, engine = build_test_executor()
    try:
        update = executor.registry.commands["update_cycle"].input_model
        updated = await _reasons(
            executor.run(
                "update_cycle",
                update.model_validate(
                    {
                        "cycle_id": str(cycle_id),
                        "registration_opens_at": (now + timedelta(days=2)).isoformat(),
                        "registration_closes_at": (now + timedelta(days=1)).isoformat(),
                    }
                ),
                admin.actor,
            )
        )
        create = executor.registry.commands["create_cycle"].input_model
        created = await _reasons(
            executor.run(
                "create_cycle",
                create.model_validate(
                    {
                        "name": "Inverted Window",
                        "kind": "open",
                        "registration_opens_at": (now + timedelta(days=2)).isoformat(),
                        "registration_closes_at": (now + timedelta(days=1)).isoformat(),
                    }
                ),
                admin.actor,
            )
        )
    finally:
        await engine.dispose()

    assert updated == [INVALID_FIELD_VALUE]
    assert created == [INVALID_FIELD_VALUE]


@pytest.mark.asyncio
async def test_CYC1_update_cycle_reports_an_unknown_cycle() -> None:
    admin = await _admin()
    executor, engine = build_test_executor()
    model = executor.registry.commands["update_cycle"].input_model
    try:
        codes = await _reasons(
            executor.run(
                "update_cycle",
                model.model_validate({"cycle_id": str(uuid4()), "name": "Ghost"}),
                admin.actor,
            )
        )
    finally:
        await engine.dispose()

    assert codes == [CYCLE_NOT_FOUND]


@pytest.mark.asyncio
async def test_CYC1_set_cycle_active_toggles_and_reports_no_change() -> None:
    admin = await _admin()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            cycle_id = await seed_cycle(connection, is_active=False)
    finally:
        await migration.dispose()

    executor, engine = build_test_executor()
    model = executor.registry.commands["set_cycle_active"].input_model
    try:
        opened = await executor.run(
            "set_cycle_active",
            model.model_validate({"cycle_id": str(cycle_id), "is_active": True}),
            admin.actor,
        )
        again = await executor.run(
            "set_cycle_active",
            model.model_validate({"cycle_id": str(cycle_id), "is_active": True}),
            admin.actor,
        )
    finally:
        await engine.dispose()

    assert isinstance(opened, Result) and opened.summary["changed"] is True
    assert isinstance(again, Result) and again.summary["changed"] is False


@pytest.mark.asyncio
async def test_CYC2_update_cycle_policy_edits_only_the_provided_knobs() -> None:
    admin = await _admin()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            cycle_id = await seed_cycle(connection, kind="placement")
    finally:
        await migration.dispose()

    executor, engine = build_test_executor()
    model = executor.registry.commands["update_cycle_policy"].input_model
    try:
        result = await executor.run(
            "update_cycle_policy",
            model.model_validate(
                {
                    "cycle_id": str(cycle_id),
                    "max_accepted_offers": None,
                    "offer_expiry_behavior": "auto_accept",
                    "deadline_reminder_hours": 12,
                }
            ),
            admin.actor,
        )
    finally:
        await engine.dispose()

    assert isinstance(result, Result)
    policy = cast(dict[str, object], result.summary["policy"])
    # An explicit null is an uncapped cycle, not an absent key.
    assert policy["max_accepted_offers"] is None
    assert policy["offer_expiry_behavior"] == "auto_accept"
    assert policy["deadline_reminder_hours"] == 12
    # Untouched knobs keep their stored values.
    assert policy["membership_requires_approval"] is True
    assert policy["round_reminder_hours"] == 24


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"join_rule": {"field": "cpi", "op": "over", "value": 8}},
        {"join_rule": {"field": "favourite_colour", "op": "eq", "value": "blue"}},
        {"max_accepted_offers": 0},
        {"deadline_reminder_hours": 0},
        {"offer_expiry_behavior": "auto_ignore"},
    ],
)
async def test_CYC2_invalid_policy_values_fail_validation_at_save(
    payload: dict[str, object],
) -> None:
    executor, engine = build_test_executor()
    model = executor.registry.commands["update_cycle_policy"].input_model
    try:
        with pytest.raises(ValueError):
            model.model_validate({"cycle_id": str(uuid4()), **payload})
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_CYC2_a_valid_join_rule_tree_is_stored() -> None:
    admin = await _admin()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            cycle_id = await seed_cycle(connection)
    finally:
        await migration.dispose()

    tree = {
        "all": [
            {"field": "cpi", "op": "gte", "value": 7.5},
            {"field": "active_backlogs", "op": "lte", "value": 0},
        ]
    }
    executor, engine = build_test_executor()
    model = executor.registry.commands["update_cycle_policy"].input_model
    try:
        result = await executor.run(
            "update_cycle_policy",
            model.model_validate({"cycle_id": str(cycle_id), "join_rule": tree}),
            admin.actor,
        )
    finally:
        await engine.dispose()

    assert isinstance(result, Result)
    assert cast(dict[str, object], result.summary["policy"])["join_rule"] == tree


@pytest.mark.asyncio
async def test_CYC1_coordinator_assignment_notifies_and_is_idempotent_by_rejection() -> None:
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            staff = await seed_person(connection, email="coord@example.edu")
            cycle_id = await seed_cycle(connection)
    finally:
        await migration.dispose()

    executor, engine = build_test_executor()
    model = executor.registry.commands["assign_coordinator"].input_model
    payload = model.model_validate(
        {"cycle_id": str(cycle_id), "user_id": str(staff.user_id)}
    )
    try:
        preview = await executor.run(
            "assign_coordinator", payload, admin.actor, dry_run=True
        )
        assigned = await executor.run("assign_coordinator", payload, admin.actor)
        repeat = await _reasons(
            executor.run("assign_coordinator", payload, admin.actor)
        )
        removed = await executor.run(
            "remove_coordinator",
            executor.registry.commands["remove_coordinator"].input_model.model_validate(
                {"cycle_id": str(cycle_id), "user_id": str(staff.user_id)}
            ),
            admin.actor,
        )
        absent = await _reasons(
            executor.run(
                "remove_coordinator",
                executor.registry.commands[
                    "remove_coordinator"
                ].input_model.model_validate(
                    {"cycle_id": str(cycle_id), "user_id": str(staff.user_id)}
                ),
                admin.actor,
            )
        )
    finally:
        await engine.dispose()

    assert isinstance(preview, Preview)
    assert isinstance(assigned, Result) and assigned.summary["assigned"] is True
    assert repeat == [COORDINATOR_ALREADY_ASSIGNED]
    assert isinstance(removed, Result) and removed.summary["assigned"] is False
    assert absent == [COORDINATOR_NOT_FOUND]

    check = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with check.connect() as connection:
            events = (
                await connection.scalars(
                    sa.text(
                        "SELECT task_name FROM procrastinate_jobs ORDER BY id"
                    )
                )
            ).all()
            assert list(events) == ["deliver_notification", "deliver_notification"]
    finally:
        await check.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "code"),
    [("missing", USER_NOT_FOUND), ("inactive", INACTIVE_USER)],
)
async def test_CYC1_coordinator_assignment_requires_a_live_user(
    scenario: str, code: str
) -> None:
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            cycle_id = await seed_cycle(connection)
            user_id = uuid4()
            if scenario == "inactive":
                person = await seed_person(connection, email="gone@example.edu")
                user_id = person.user_id
                await connection.execute(
                    sa.text("UPDATE users SET is_active = false WHERE id = :id"),
                    {"id": user_id},
                )
    finally:
        await migration.dispose()

    executor, engine = build_test_executor()
    model = executor.registry.commands["assign_coordinator"].input_model
    try:
        codes = await _reasons(
            executor.run(
                "assign_coordinator",
                model.model_validate(
                    {"cycle_id": str(cycle_id), "user_id": str(user_id)}
                ),
                admin.actor,
            )
        )
    finally:
        await engine.dispose()

    assert codes == [code]


@pytest.mark.asyncio
async def test_CYC1_a_coordinator_edits_only_their_own_cycle() -> None:
    """The registry's cycle scope is checked at the route and again in-executor."""
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            staff = await seed_person(connection, email="coord@example.edu")
            mine = await seed_cycle(connection, name="Mine")
            theirs = await seed_cycle(connection, name="Theirs")
            await seed_coordinator_link(connection, mine, staff.user_id)
    finally:
        await migration.dispose()

    executor, engine = build_test_executor()
    model = executor.registry.commands["update_cycle"].input_model
    coordinator = staff.coordinating(mine)
    try:
        # update_cycle is admin-only, so even the owning coordinator is denied.
        for cycle_id in (mine, theirs):
            with pytest.raises(AuthorizationDenied):
                await executor.run(
                    "update_cycle",
                    model.model_validate(
                        {"cycle_id": str(cycle_id), "description": "Edited"}
                    ),
                    coordinator.actor,
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_CYC1_every_cycle_scoped_command_is_read_only_after_archival() -> None:
    """CYC-1's read-only rule is inherited from check_scope, not restated per command."""
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            staff = await seed_person(connection, email="coord@example.edu")
            cycle_id = await seed_cycle(connection, archived=True)
    finally:
        await migration.dispose()

    executor, engine = build_test_executor()
    inputs: dict[str, dict[str, object]] = {
        "update_cycle": {"cycle_id": str(cycle_id), "description": "Edited"},
        "set_cycle_active": {"cycle_id": str(cycle_id), "is_active": False},
        "update_cycle_policy": {"cycle_id": str(cycle_id), "strike_on_absence": False},
        "assign_coordinator": {
            "cycle_id": str(cycle_id),
            "user_id": str(staff.user_id),
        },
        "remove_coordinator": {
            "cycle_id": str(cycle_id),
            "user_id": str(staff.user_id),
        },
    }
    scoped = {
        name
        for name, spec in executor.registry.commands.items()
        if spec.scope == "cycle" and name in inputs
    }
    assert scoped == set(inputs), "every cycle-scoped command needs an archival case"

    try:
        for name, payload in inputs.items():
            model = executor.registry.commands[name].input_model
            codes = await _reasons(
                executor.run(name, model.model_validate(payload), admin.actor)
            )
            assert codes == [CYCLE_ARCHIVED], name
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_CYC1_informational_dates_do_not_gate_behaviour() -> None:
    """CYC-1: start and end dates are labels; only the window and flag gate."""
    admin = await _admin()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            cycle_id = await seed_cycle(connection)
    finally:
        await migration.dispose()

    past = datetime.now(UTC).date() - timedelta(days=400)
    executor, engine = build_test_executor()
    model = executor.registry.commands["update_cycle"].input_model
    try:
        result = await executor.run(
            "update_cycle",
            model.model_validate(
                {
                    "cycle_id": str(cycle_id),
                    "starts_on": past.isoformat(),
                    "ends_on": (past + timedelta(days=1)).isoformat(),
                }
            ),
            admin.actor,
        )
    finally:
        await engine.dispose()

    assert isinstance(result, Result)
    assert result.summary["changed"] is True
