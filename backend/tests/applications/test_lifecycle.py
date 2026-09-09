"""Editing and withdrawing one's own application (Behavior APP-3, APP-4.12)."""

from __future__ import annotations

import os
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import (
    ANSWER_REQUIRED,
    APPLICATION_NOT_EDITABLE,
    APPLICATION_NOT_FOUND,
    DUPLICATE_APPLICATION,
    WINDOW_CLOSED,
    AuthorizationDenied,
    DomainRejection,
)
from app.core.plan import Result
from tests.applications.conftest import (
    DRIVE_URL,
    World,
    build_test_executor,
    seed_person,
    seed_question,
    seed_world,
)

pytestmark = pytest.mark.asyncio

OTHER_DRIVE_URL = "https://drive.google.com/file/d/1ZzYyXxWwVvUuTtSsRrQqPpOoNnMmLlKk/view"


async def _run(name: str, payload: dict[str, object], world: World) -> Result:
    executor, engine = build_test_executor()
    model = executor.registry.commands[name].input_model
    try:
        return cast(
            Result,
            await executor.run(name, model.model_validate(payload), world.student.actor),
        )
    finally:
        await engine.dispose()


async def _codes(name: str, payload: dict[str, object], world: World) -> list[str]:
    with pytest.raises(DomainRejection) as error:
        await _run(name, payload, world)
    return [reason.code for reason in error.value.rejection.reasons]


async def _rows(query: str, params: dict[str, object]) -> list[sa.RowMapping]:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            return list((await connection.execute(sa.text(query), params)).mappings().all())
    finally:
        await engine.dispose()


async def _execute(statement: str, params: dict[str, object]) -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(sa.text(statement), params)
    finally:
        await engine.dispose()


async def _applied(world: World, answers: list[dict[str, object]] | None = None) -> UUID:
    result = await _run(
        "apply",
        {
            "cycle_id": str(world.cycle_id),
            "job_id": str(world.job_id),
            "enrollment_id": str(world.student.enrollment_id),
            "answers": answers or [],
        },
        world,
    )
    return UUID(cast(str, result.summary["application_id"]))


def _edit(world: World, application_id: UUID, **extra: object) -> dict[str, object]:
    return {
        "cycle_id": str(world.cycle_id),
        "enrollment_id": str(world.student.enrollment_id),
        "application_id": str(application_id),
        **extra,
    }


async def test_APP3_an_edit_replaces_the_answer_set_wholesale() -> None:
    world = await seed_world()
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            first = await seed_question(connection, job_id=world.job_id, text="Why?", ord=1)
            second = await seed_question(
                connection,
                job_id=world.job_id,
                text="Anything else?",
                required=False,
                ord=2,
            )
    finally:
        await engine.dispose()

    application_id = await _applied(
        world,
        [
            {"question_id": str(first), "value": "Because"},
            {"question_id": str(second), "value": "Also this"},
        ],
    )

    # The optional answer is omitted, so it is gone -- not merged, not kept.
    result = await _run(
        "edit_application",
        _edit(
            world,
            application_id,
            answers=[{"question_id": str(first), "value": "Revised reason"}],
        ),
        world,
    )

    assert result.summary["answer_count"] == 1
    stored = await _rows(
        "SELECT question_id, value FROM application_answers WHERE application_id = :id",
        {"id": application_id},
    )
    assert {row["question_id"]: row["value"] for row in stored} == {first: "Revised reason"}
    events = await _rows(
        "SELECT event_type, payload FROM application_events WHERE application_id = :id "
        "ORDER BY created_at",
        {"id": application_id},
    )
    assert [row["event_type"] for row in events] == ["created", "edited"]
    # An edit is not a transition, and the event must not claim one.
    edited = await _rows(
        "SELECT from_status, to_status FROM application_events "
        "WHERE application_id = :id AND event_type = 'edited'",
        {"id": application_id},
    )
    assert edited[0]["from_status"] is None
    assert edited[0]["to_status"] is None


async def test_APP3_an_edit_is_revalidated_against_the_form() -> None:
    world = await seed_world()
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            required = await seed_question(connection, job_id=world.job_id, text="Why?")
    finally:
        await engine.dispose()
    application_id = await _applied(
        world, [{"question_id": str(required), "value": "Because"}]
    )

    assert ANSWER_REQUIRED in await _codes(
        "edit_application", _edit(world, application_id, answers=[]), world
    )


async def test_APP3_an_edit_keeps_the_filed_resume_when_none_is_named() -> None:
    world = await seed_world()
    application_id = await _applied(world)

    unchanged = await _run("edit_application", _edit(world, application_id), world)
    swapped = await _run(
        "edit_application",
        _edit(world, application_id, resume_url=OTHER_DRIVE_URL),
        world,
    )

    assert unchanged.summary["resume_url"] == DRIVE_URL
    assert unchanged.summary["resume_changed"] is False
    assert swapped.summary["resume_url"] == OTHER_DRIVE_URL
    assert swapped.summary["resume_changed"] is True
    rows = await _rows(
        "SELECT resume_url FROM applications WHERE id = :id", {"id": application_id}
    )
    assert rows[0]["resume_url"] == OTHER_DRIVE_URL


async def test_APP3_withdrawing_frees_the_slot_and_keeps_the_position() -> None:
    world = await seed_world(with_rounds=True)
    application_id = await _applied(world)

    result = await _run(
        "withdraw_application",
        {
            "cycle_id": str(world.cycle_id),
            "enrollment_id": str(world.student.enrollment_id),
            "application_id": str(application_id),
        },
        world,
    )

    assert result.summary["status"] == "withdrawn"
    rows = await _rows(
        "SELECT status, current_round_id FROM applications WHERE id = :id",
        {"id": application_id},
    )
    assert rows[0]["status"] == "withdrawn"
    # The position survives: a reinstatement has to have something to restore.
    assert rows[0]["current_round_id"] == world.round_id
    events = await _rows(
        "SELECT event_type, from_status, to_status FROM application_events "
        "WHERE application_id = :id ORDER BY created_at",
        {"id": application_id},
    )
    assert [row["event_type"] for row in events] == ["created", "withdrawn"]
    assert (events[1]["from_status"], events[1]["to_status"]) == ("in_progress", "withdrawn")

    # The freed slot is the point: re-applying is allowed again (APP-2).
    again = await _applied(world)
    assert again != application_id


@pytest.mark.parametrize("command", ["edit_application", "withdraw_application"])
async def test_APP3_neither_action_survives_the_deadline_by_default(command: str) -> None:
    world = await seed_world()
    application_id = await _applied(world)
    await _execute(
        "UPDATE jobs SET application_deadline = now() - interval '1 day' WHERE id = :id",
        {"id": world.job_id},
    )

    assert await _codes(command, _edit(world, application_id), world) == [WINDOW_CLOSED]


@pytest.mark.parametrize(
    ("command", "flag"),
    [
        ("edit_application", "allow_edit_after_deadline"),
        ("withdraw_application", "allow_withdrawal_after_deadline"),
    ],
)
async def test_CYC2_the_cycle_policy_can_hold_the_window_open(
    command: str, flag: str
) -> None:
    """Each action reads its own flag: they are separate knobs in CYC-2."""
    world = await seed_world()
    application_id = await _applied(world)
    await _execute(
        "UPDATE jobs SET application_deadline = now() - interval '1 day' WHERE id = :id",
        {"id": world.job_id},
    )
    await _execute(
        f"UPDATE cycle_policies SET {flag} = true WHERE cycle_id = :id",  # noqa: S608
        {"id": world.cycle_id},
    )

    result = await _run(command, _edit(world, application_id), world)

    assert result.summary["application_id"] == str(application_id)


async def test_JOB6_a_job_with_no_deadline_has_no_window_to_miss() -> None:
    world = await seed_world(kind="open", outcome="internship", with_deadline=False)
    application_id = await _applied(world)

    result = await _run("edit_application", _edit(world, application_id), world)

    assert result.summary["application_id"] == str(application_id)


async def test_INT2_a_withdraw_override_reopens_only_the_exit_window() -> None:
    world = await seed_world()
    application_id = await _applied(world)
    await _execute(
        "UPDATE jobs SET application_deadline = now() - interval '1 day' WHERE id = :id",
        {"id": world.job_id},
    )
    override_id = uuid4()
    await _execute(
        "INSERT INTO overrides (id, rule_domain, application_id, allow, reason, "
        "granted_by, created_at) SELECT :id, 'withdraw_window', :application, "
        "true, 'Agreed with the coordinator', u.id, now() FROM users u "
        "WHERE u.role = 'admin' LIMIT 1",
        {"id": override_id, "application": application_id},
    )

    assert await _codes(
        "edit_application", _edit(world, application_id), world
    ) == [WINDOW_CLOSED]
    result = await _run("withdraw_application", _edit(world, application_id), world)

    assert result.summary["status"] == "withdrawn"
    events = await _rows(
        "SELECT payload FROM application_events WHERE application_id = :id "
        "AND event_type = 'withdrawn'",
        {"id": application_id},
    )
    payload = cast("dict[str, object]", events[0]["payload"])
    assert payload["applied_override_ids"] == [str(override_id)]


@pytest.mark.parametrize("command", ["edit_application", "withdraw_application"])
async def test_APP3_only_a_live_application_can_be_touched(command: str) -> None:
    world = await seed_world()
    application_id = await _applied(world)

    assert await _codes(command, _edit(world, uuid4()), world) == [APPLICATION_NOT_FOUND]

    await _execute(
        "UPDATE applications SET status = 'rejected' WHERE id = :id",
        {"id": application_id},
    )
    assert await _codes(command, _edit(world, application_id), world) == [
        APPLICATION_NOT_EDITABLE
    ]


@pytest.mark.parametrize("command", ["edit_application", "withdraw_application"])
async def test_IDN3_a_student_cannot_touch_another_student_s_application(
    command: str,
) -> None:
    """The enrollment in the input is checked against the actor's own (4.15)."""
    world = await seed_world()
    application_id = await _applied(world)
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            intruder = await seed_person(connection, email="mallory@example.edu")
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    model = executor.registry.commands[command].input_model
    try:
        with pytest.raises(AuthorizationDenied):
            await executor.run(
                command,
                model.model_validate(
                    {
                        "cycle_id": str(world.cycle_id),
                        # Claiming the victim's enrollment is what the check
                        # catches; claiming their own would not find the row.
                        "enrollment_id": str(world.student.enrollment_id),
                        "application_id": str(application_id),
                    }
                ),
                intruder.actor,
            )
    finally:
        await engine.dispose()

    assert (
        await _rows(
            "SELECT status FROM applications WHERE id = :id", {"id": application_id}
        )
    )[0]["status"] == "in_progress"


async def test_APP2_a_withdrawn_application_is_not_editable() -> None:
    """Withdrawal is final for the student: coming back means applying again."""
    world = await seed_world()
    application_id = await _applied(world)
    await _run("withdraw_application", _edit(world, application_id), world)

    assert await _codes("edit_application", _edit(world, application_id), world) == [
        APPLICATION_NOT_EDITABLE
    ]
    assert DUPLICATE_APPLICATION not in await _codes(
        "edit_application", _edit(world, application_id), world
    )
