"""Applying to a job: gates, snapshot, form, duplicates (APP-1, APP-2, ELG-3)."""

from __future__ import annotations

import asyncio
import os
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import (
    ANSWER_INVALID,
    ANSWER_REQUIRED,
    CYCLE_ARCHIVED,
    DEADLINE_PASSED,
    DUPLICATE_APPLICATION,
    JOB_CANCELLED,
    JOB_UNPUBLISHED,
    MEMBERSHIP_NOT_ACTIVE,
    RESUME_NOT_FOUND,
    UNKNOWN_QUESTION,
    DomainRejection,
)
from app.core.plan import Result
from app.modules.profiles.fields import FIELDS
from tests.applications.conftest import (
    DRIVE_URL,
    World,
    build_test_executor,
    seed_question,
    seed_world,
)

pytestmark = pytest.mark.asyncio


async def _apply(
    world: World,
    *,
    answers: list[dict[str, object]] | None = None,
    resume_id: UUID | None = None,
    resume_url: str | None = None,
    dry_run: bool = False,
) -> Result:
    executor, engine = build_test_executor()
    model = executor.registry.commands["apply"].input_model
    payload: dict[str, object] = {
        "cycle_id": str(world.cycle_id),
        "job_id": str(world.job_id),
        "enrollment_id": str(world.student.enrollment_id),
        "answers": answers or [],
    }
    if resume_id is not None:
        payload["resume_id"] = str(resume_id)
    if resume_url is not None:
        payload["resume_url"] = resume_url
    try:
        result = await executor.run(
            "apply", model.model_validate(payload), world.student.actor, dry_run=dry_run
        )
        return cast(Result, result)
    finally:
        await engine.dispose()


async def _apply_codes(world: World, **kwargs: object) -> list[str]:
    with pytest.raises(DomainRejection) as error:
        await _apply(world, **kwargs)  # type: ignore[arg-type]
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


async def test_APP1_apply_files_the_application_at_round_one_with_its_event() -> None:
    world = await seed_world(with_rounds=True)

    result = await _apply(world)

    assert result.summary["status"] == "in_progress"
    assert result.summary["current_round_id"] == str(world.round_id)
    applications = await _rows(
        "SELECT * FROM applications WHERE enrollment_id = :id",
        {"id": world.student.enrollment_id},
    )
    assert len(applications) == 1
    assert applications[0]["resume_url"] == DRIVE_URL
    states = await _rows(
        "SELECT * FROM application_round_states WHERE application_id = :id",
        {"id": applications[0]["id"]},
    )
    assert [(row["result"], row["attendance"]) for row in states] == [("pending", "pending")]
    events = await _rows(
        "SELECT * FROM application_events WHERE application_id = :id",
        {"id": applications[0]["id"]},
    )
    assert [row["event_type"] for row in events] == ["created"]
    assert events[0]["to_status"] == "in_progress"
    assert events[0]["to_round_id"] == world.round_id


async def test_JOB6_an_open_cycle_application_holds_no_round_position() -> None:
    world = await seed_world(kind="open", outcome="internship", with_deadline=False)

    result = await _apply(world)

    assert result.summary["current_round_id"] is None
    states = await _rows(
        "SELECT * FROM application_round_states WHERE application_id = :id",
        {"id": UUID(cast(str, result.summary["application_id"]))},
    )
    assert states == []


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (None, MEMBERSHIP_NOT_ACTIVE),
        ("unpublish", JOB_UNPUBLISHED),
        ("cancel", JOB_CANCELLED),
        ("archive", CYCLE_ARCHIVED),
        ("deadline", DEADLINE_PASSED),
    ],
)
async def test_ELG3_each_standing_gate_refuses_the_application(
    mutate: str | None, code: str
) -> None:
    world = await seed_world(membership_status="pending" if mutate is None else "active")
    if mutate == "unpublish":
        await _execute("UPDATE jobs SET is_published = false WHERE id = :id", {"id": world.job_id})
    elif mutate == "cancel":
        await _execute("UPDATE jobs SET cancelled_at = now() WHERE id = :id", {"id": world.job_id})
    elif mutate == "archive":
        await _execute(
            "UPDATE cycles SET archived_at = now() WHERE id = :id", {"id": world.cycle_id}
        )
    elif mutate == "deadline":
        await _execute(
            "UPDATE jobs SET application_deadline = now() - interval '1 day' WHERE id = :id",
            {"id": world.job_id},
        )

    assert code in await _apply_codes(world)
    assert await _rows(
        "SELECT * FROM applications WHERE enrollment_id = :id",
        {"id": world.student.enrollment_id},
    ) == []


async def test_INT2_an_override_that_opens_the_deadline_is_stamped_on_the_event() -> None:
    """The application is allowed, and the event records that it was not ordinary."""
    world = await seed_world()
    await _execute(
        "UPDATE jobs SET application_deadline = now() - interval '1 day' WHERE id = :id",
        {"id": world.job_id},
    )
    override_id = uuid4()
    await _execute(
        "INSERT INTO overrides (id, rule_domain, enrollment_id, job_id, allow, reason, "
        "granted_by, created_at) SELECT :id, 'application_deadline', :enrollment, :job, "
        "true, 'Late, agreed with the company', u.id, now() FROM users u "
        "WHERE u.role = 'admin' LIMIT 1",
        {"id": override_id, "enrollment": world.student.enrollment_id, "job": world.job_id},
    )

    result = await _apply(world)

    events = await _rows(
        "SELECT * FROM application_events WHERE application_id = :id",
        {"id": UUID(cast(str, result.summary["application_id"]))},
    )
    payload = cast("dict[str, object]", events[0]["payload"])
    assert payload["applied_override_ids"] == [str(override_id)]


async def test_ELG4_a_later_profile_edit_does_not_move_the_snapshot() -> None:
    """Whoever got in validly stays in, on the data they were judged on."""
    world = await seed_world(cpi="8.40")
    result = await _apply(world)

    await _execute(
        "UPDATE profiles SET cpi = 5.00 WHERE enrollment_id = :id",
        {"id": world.student.enrollment_id},
    )

    applications = await _rows(
        "SELECT * FROM applications WHERE id = :id",
        {"id": UUID(cast(str, result.summary["application_id"]))},
    )
    snapshot = cast("dict[str, object]", applications[0]["profile_snapshot"])
    assert snapshot["cpi"] == "8.40"
    # APP-1's snapshot is the *registry* fields, which span three tables
    # (the design review section 4.1): an application must be able to say whose it was.
    assert snapshot["full_name"] == world.student_name
    assert snapshot["roll_number"] == world.roll_number
    assert applications[0]["status"] == "in_progress"


async def test_APP1_the_snapshot_carries_every_registry_field() -> None:
    """Pinned against the PRO-1 registry, not against a hand-written list.

    ``full_name`` and ``roll_number`` fell out of the first version of this
    snapshot because the registry spans three tables (the design review section 4.1)
    while the query read one.  Deriving the expectation from ``FIELDS`` means a
    field added to the registry in any home fails here until the snapshot
    carries it, rather than going missing in silence.
    """
    world = await seed_world()
    result = await _apply(world)

    applications = await _rows(
        "SELECT profile_snapshot FROM applications WHERE id = :id",
        {"id": UUID(cast(str, result.summary["application_id"]))},
    )
    snapshot = cast("dict[str, object]", applications[0]["profile_snapshot"])

    expected = {field.key for field in FIELDS} | {
        # A program property the rule engine reads as a field (section 4.18),
        # so it is judged on and therefore snapshotted.
        "is_dual_major"
    }
    assert set(snapshot) == expected


async def test_APP1_parallel_applications_for_one_pair_produce_exactly_one_row() -> None:
    """The duplicate race, settled by the lock with the index behind it."""
    world = await seed_world()

    outcomes = await asyncio.gather(
        _apply(world), _apply(world), return_exceptions=True
    )

    succeeded = [item for item in outcomes if isinstance(item, Result)]
    refused = [item for item in outcomes if isinstance(item, DomainRejection)]
    assert len(succeeded) == 1
    assert len(refused) == 1
    assert DUPLICATE_APPLICATION in [
        reason.code for reason in refused[0].rejection.reasons
    ]
    assert len(
        await _rows(
            "SELECT * FROM applications WHERE enrollment_id = :id",
            {"id": world.student.enrollment_id},
        )
    ) == 1


async def test_APP2_reapplying_is_allowed_after_withdrawal_only() -> None:
    world = await seed_world()
    first = await _apply(world)
    application_id = UUID(cast(str, first.summary["application_id"]))

    assert DUPLICATE_APPLICATION in await _apply_codes(world)

    await _execute(
        "UPDATE applications SET status = 'withdrawn' WHERE id = :id",
        {"id": application_id},
    )
    again = await _apply(world)
    assert again.summary["application_id"] != str(application_id)

    # A rejection is not a way back in: only staff reinstatement (INT-1) is.
    await _execute(
        "UPDATE applications SET status = 'rejected' WHERE id = :id",
        {"id": UUID(cast(str, again.summary["application_id"]))},
    )
    assert DUPLICATE_APPLICATION in await _apply_codes(world)


async def test_APP1_the_form_is_validated_against_the_job_s_questions() -> None:
    world = await seed_world()
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            required = await seed_question(
                connection, job_id=world.job_id, text="Why this role?", ord=1
            )
            choice = await seed_question(
                connection,
                job_id=world.job_id,
                text="Preferred location",
                qtype="single",
                required=False,
                ord=2,
                options=("Bengaluru", "Pune"),
            )
    finally:
        await engine.dispose()

    assert ANSWER_REQUIRED in await _apply_codes(world)
    assert ANSWER_INVALID in await _apply_codes(
        world,
        answers=[
            {"question_id": str(required), "value": "Because"},
            {"question_id": str(choice), "value": "Mumbai"},
        ],
    )
    assert UNKNOWN_QUESTION in await _apply_codes(
        world,
        answers=[
            {"question_id": str(required), "value": "Because"},
            {"question_id": str(uuid4()), "value": "stale"},
        ],
    )

    result = await _apply(
        world,
        answers=[
            {"question_id": str(required), "value": "Because"},
            {"question_id": str(choice), "value": "Pune"},
        ],
    )

    assert result.summary["answer_count"] == 2
    stored = await _rows(
        "SELECT question_id, value FROM application_answers WHERE application_id = :id",
        {"id": UUID(cast(str, result.summary["application_id"]))},
    )
    assert {row["question_id"]: row["value"] for row in stored} == {
        required: "Because",
        choice: "Pune",
    }


async def test_PRO3_the_resume_is_the_cycle_default_a_library_entry_or_a_drive_link() -> None:
    world = await seed_world()

    # A resume belonging to somebody else is not a resume this student has.
    assert RESUME_NOT_FOUND in await _apply_codes(world, resume_id=uuid4())
    assert RESUME_NOT_FOUND in await _apply_codes(world, resume_url="https://example.com/cv.pdf")

    one_off = "https://drive.google.com/file/d/1ZzYyXxWwVvUuTtSsRrQqPpOoNnMmLlKk/view"
    result = await _apply(world, resume_url=one_off)

    assert result.summary["resume_url"] == one_off
