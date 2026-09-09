"""Round and question locks in the builder (Behavior JOB-2, JOB-3, JOB-6).

JOB-3's rule is that a job edit never invalidates what is already recorded.
Everything here is a test of where that bites: a round somebody has entered, a
question somebody has answered.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import DomainRejection
from app.core.executor import Executor
from tests.cycles.conftest import Person
from tests.jobs.conftest import (
    build_test_executor,
    seed_admin,
    seed_answer,
    seed_application,
    seed_complete_profile,
    seed_cycle,
    seed_job,
    seed_person,
    seed_round_state,
    seed_round_type,
    seed_taxonomy,
)


async def _job_fixture(kind: str = "placement") -> tuple[Person, UUID, UUID, UUID, UUID]:
    """A job with one applicant, so the JOB-3 locks have something to protect."""
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            program_id, branch_id = await seed_taxonomy(connection)
            student = await seed_person(connection, email="asha@example.edu")
            await seed_complete_profile(
                connection, student, program_id=program_id, branch_id=branch_id
            )
            cycle_id = await seed_cycle(connection, kind=kind)
            job_id = await seed_job(connection, cycle_id=cycle_id)
            application_id, _round = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                job_id=job_id,
            )
            round_type_id = await seed_round_type(connection)
    finally:
        await engine.dispose()
    return admin, cycle_id, job_id, application_id, round_type_id


async def _run(
    executor: Executor, name: str, payload: dict[str, object], actor: Person
) -> object:
    model = executor.registry.commands[name].input_model
    return await executor.run(name, model.model_validate(payload), actor.actor)


async def _reject(
    executor: Executor, name: str, payload: dict[str, object], actor: Person
) -> list[str]:
    with pytest.raises(DomainRejection) as error:
        await _run(executor, name, payload, actor)
    return [reason.code for reason in error.value.rejection.reasons]


async def _rounds(job_id: UUID) -> list[tuple[str, int]]:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            rows = (
                await connection.execute(
                    sa.text(
                        "SELECT name, ord FROM job_rounds WHERE job_id = :id ORDER BY ord"
                    ),
                    {"id": job_id},
                )
            ).mappings().all()
            return [(str(row["name"]), int(row["ord"])) for row in rows]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_JOB3_a_round_an_application_has_entered_cannot_be_deleted() -> None:
    admin, cycle_id, job_id, application_id, round_type_id = await _job_fixture()
    executor, engine = build_test_executor()
    try:
        created = await _run(
            executor,
            "upsert_job_rounds",
            {
                "cycle_id": str(cycle_id),
                "job_id": str(job_id),
                "rounds": [
                    {"round_type_id": str(round_type_id), "name": "Screening"},
                    {"round_type_id": str(round_type_id), "name": "Technical"},
                ],
            },
            admin,
        )
        assert created.summary["added"] == 2  # type: ignore[attr-defined]
    finally:
        await engine.dispose()

    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            rows = (
                await connection.execute(
                    sa.text(
                        "SELECT id, name FROM job_rounds WHERE job_id = :id ORDER BY ord"
                    ),
                    {"id": job_id},
                )
            ).mappings().all()
            screening, technical = rows[0], rows[1]
            await seed_round_state(
                connection,
                application_id=application_id,
                round_id=cast_uuid(screening["id"]),
            )
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    try:
        blocked = await _reject(
            executor,
            "upsert_job_rounds",
            {
                "cycle_id": str(cycle_id),
                "job_id": str(job_id),
                "rounds": [
                    {
                        "round_id": str(cast_uuid(technical["id"])),
                        "round_type_id": str(round_type_id),
                        "name": "Technical",
                    }
                ],
            },
            admin,
        )
        # Renaming and rescheduling the same round stays free: neither
        # invalidates the attendance or result already recorded against it.
        renamed = await _run(
            executor,
            "upsert_job_rounds",
            {
                "cycle_id": str(cycle_id),
                "job_id": str(job_id),
                "rounds": [
                    {
                        "round_id": str(cast_uuid(screening["id"])),
                        "round_type_id": str(round_type_id),
                        "name": "Online Screening",
                        "venue": "Lab 1",
                    },
                    {
                        "round_id": str(cast_uuid(technical["id"])),
                        "round_type_id": str(round_type_id),
                        "name": "Technical",
                    },
                ],
            },
            admin,
        )
    finally:
        await engine.dispose()

    assert blocked == ["field_not_editable"]
    assert renamed.summary["changed"] is True  # type: ignore[attr-defined]
    assert await _rounds(job_id) == [("Online Screening", 1), ("Technical", 2)]


def cast_uuid(value: object) -> UUID:
    assert isinstance(value, UUID)
    return value


@pytest.mark.asyncio
async def test_JOB3_reordering_and_inserting_rounds_notifies_in_flight_applicants() -> None:
    admin, cycle_id, job_id, _application, round_type_id = await _job_fixture()
    executor, engine = build_test_executor()
    payload: dict[str, object] = {
        "cycle_id": str(cycle_id),
        "job_id": str(job_id),
        "rounds": [
            {"round_type_id": str(round_type_id), "name": "Screening"},
            {"round_type_id": str(round_type_id), "name": "Technical"},
        ],
    }
    try:
        inserted = await _run(executor, "upsert_job_rounds", payload, admin)
    finally:
        await engine.dispose()

    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            rows = (
                await connection.execute(
                    sa.text(
                        "SELECT id, name FROM job_rounds WHERE job_id = :id ORDER BY ord"
                    ),
                    {"id": job_id},
                )
            ).mappings().all()
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    try:
        # Same two rounds, swapped: the deferrable unique on (job_id, ord) is
        # what lets both updates land inside one transaction.
        reordered = await _run(
            executor,
            "upsert_job_rounds",
            {
                "cycle_id": str(cycle_id),
                "job_id": str(job_id),
                "rounds": [
                    {
                        "round_id": str(cast_uuid(rows[1]["id"])),
                        "round_type_id": str(round_type_id),
                        "name": "Technical",
                    },
                    {
                        "round_id": str(cast_uuid(rows[0]["id"])),
                        "round_type_id": str(round_type_id),
                        "name": "Screening",
                    },
                ],
            },
            admin,
        )
    finally:
        await engine.dispose()

    assert inserted.summary["notified_applicants"] == 1  # type: ignore[attr-defined]
    assert reordered.summary["reordered"] is True  # type: ignore[attr-defined]
    assert reordered.summary["notified_applicants"] == 1  # type: ignore[attr-defined]
    assert await _rounds(job_id) == [("Technical", 1), ("Screening", 2)]


@pytest.mark.asyncio
async def test_JOB6_an_open_cycle_job_carries_no_rounds_at_all() -> None:
    admin, cycle_id, job_id, _application, round_type_id = await _job_fixture("open")
    executor, engine = build_test_executor()
    try:
        codes = await _reject(
            executor,
            "upsert_job_rounds",
            {
                "cycle_id": str(cycle_id),
                "job_id": str(job_id),
                "rounds": [{"round_type_id": str(round_type_id), "name": "Screening"}],
            },
            admin,
        )
    finally:
        await engine.dispose()

    assert codes == ["field_not_editable"]


@pytest.mark.asyncio
async def test_JOB3_an_answered_question_cannot_be_removed_retyped_or_narrowed() -> None:
    admin, cycle_id, job_id, application_id, _round_type = await _job_fixture()
    executor, engine = build_test_executor()
    try:
        await _run(
            executor,
            "upsert_job_questions",
            {
                "cycle_id": str(cycle_id),
                "job_id": str(job_id),
                "questions": [
                    {"text": "Preferred location?", "qtype": "single",
                     "options": ["Bengaluru", "Pune", "Remote"]},
                    {"text": "Why this role?", "qtype": "longtext", "required": True},
                ],
            },
            admin,
        )
    finally:
        await engine.dispose()

    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            rows = (
                await connection.execute(
                    sa.text(
                        "SELECT id, text FROM job_questions WHERE job_id = :id ORDER BY ord"
                    ),
                    {"id": job_id},
                )
            ).mappings().all()
            location, essay = rows[0], rows[1]
            await seed_answer(
                connection,
                application_id=application_id,
                question_id=cast_uuid(location["id"]),
                value="Pune",
            )
    finally:
        await engine.dispose()

    keep_location: dict[str, object] = {
        "question_id": str(cast_uuid(location["id"])),
        "text": "Preferred location?",
        "qtype": "single",
        "options": ["Bengaluru", "Pune", "Remote"],
    }
    essay_row: dict[str, object] = {
        "question_id": str(cast_uuid(essay["id"])),
        "text": "Why this role?",
        "qtype": "longtext",
        "required": True,
    }

    executor, engine = build_test_executor()
    base: dict[str, object] = {"cycle_id": str(cycle_id), "job_id": str(job_id)}
    try:
        removed = await _reject(
            executor, "upsert_job_questions", base | {"questions": [essay_row]}, admin
        )
        retyped = await _reject(
            executor,
            "upsert_job_questions",
            base | {"questions": [keep_location | {"qtype": "text", "options": []}]},
            admin,
        )
        narrowed = await _reject(
            executor,
            "upsert_job_questions",
            base | {"questions": [keep_location | {"options": ["Bengaluru", "Pune"]}]},
            admin,
        )
        # Renaming, reordering, and *adding* an option are all free: none of
        # them changes what an existing answer means.
        allowed = await _run(
            executor,
            "upsert_job_questions",
            base
            | {
                "questions": [
                    essay_row,
                    keep_location
                    | {
                        "text": "Which office would you prefer?",
                        "options": ["Bengaluru", "Pune", "Remote", "Hyderabad"],
                    },
                ]
            },
            admin,
        )
        # An unanswered question is still freely removable.
        dropped = await _run(
            executor,
            "upsert_job_questions",
            base
            | {
                "questions": [
                    keep_location
                    | {
                        "text": "Which office would you prefer?",
                        "options": ["Bengaluru", "Pune", "Remote", "Hyderabad"],
                    }
                ]
            },
            admin,
        )
    finally:
        await engine.dispose()

    assert removed == ["field_not_editable"]
    assert retyped == ["field_not_editable"]
    assert narrowed == ["field_not_editable"]
    assert allowed.summary["question_count"] == 2  # type: ignore[attr-defined]
    assert dropped.summary["removed"] == 1  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_JOB2_a_select_question_needs_distinct_options_and_others_take_none() -> None:
    admin, cycle_id, job_id, _application, _round_type = await _job_fixture()
    executor, _engine = build_test_executor()
    model = executor.registry.commands["upsert_job_questions"].input_model
    base: dict[str, object] = {"cycle_id": str(cycle_id), "job_id": str(job_id)}

    with pytest.raises(ValueError):
        model.model_validate(
            base | {"questions": [{"text": "Pick", "qtype": "single", "options": ["A"]}]}
        )
    with pytest.raises(ValueError):
        model.model_validate(
            base
            | {
                "questions": [
                    {"text": "Pick", "qtype": "multi", "options": ["A", "A"]}
                ]
            }
        )
    with pytest.raises(ValueError):
        model.model_validate(
            base
            | {"questions": [{"text": "Name", "qtype": "text", "options": ["A", "B"]}]}
        )


async def _round_rows(job_id: UUID) -> list[sa.RowMapping]:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            return list(
                (
                    await connection.execute(
                        sa.text(
                            "SELECT id, venue, scheduled_at FROM job_rounds "
                            "WHERE job_id = :id ORDER BY ord"
                        ),
                        {"id": job_id},
                    )
                ).mappings().all()
            )
    finally:
        await engine.dispose()


async def _venue_notices() -> list[dict[str, Any]]:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    sa.text(
                        "SELECT args FROM procrastinate_jobs "
                        "WHERE task_name = 'deliver_notification' ORDER BY id"
                    )
                )
            ).mappings().all()
    finally:
        await engine.dispose()
    parsed = [
        cast(
            "dict[str, Any]",
            json.loads(row["args"]) if isinstance(row["args"], str) else row["args"],
        )
        for row in rows
    ]
    return [item for item in parsed if item["event_key"] == "venue_timing"]


async def _seed_state_in_round(application_id: UUID, round_id: UUID) -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await seed_round_state(
                connection, application_id=application_id, round_id=round_id
            )
    finally:
        await engine.dispose()


async def _save_rounds(
    admin: Person,
    *,
    cycle_id: UUID,
    job_id: UUID,
    rounds: list[dict[str, object]],
) -> object:
    executor, engine = build_test_executor()
    try:
        return await _run(
            executor,
            "upsert_job_rounds",
            {"cycle_id": str(cycle_id), "job_id": str(job_id), "rounds": rounds},
            admin,
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_RND4_moving_a_rounds_own_venue_tells_the_students_sitting_in_it() -> None:
    """the design review 4.46: the default is what a student without an override sees."""
    admin, cycle_id, job_id, application_id, round_type_id = await _job_fixture()
    await _save_rounds(
        admin,
        cycle_id=cycle_id,
        job_id=job_id,
        rounds=[{"round_type_id": str(round_type_id), "name": "Screening", "venue": "LT 1"}],
    )
    round_id = cast_uuid((await _round_rows(job_id))[0]["id"])
    await _seed_state_in_round(application_id, round_id)

    moved = await _save_rounds(
        admin,
        cycle_id=cycle_id,
        job_id=job_id,
        rounds=[
            {
                "round_id": str(round_id),
                "round_type_id": str(round_type_id),
                "name": "Screening",
                "venue": "LT 3",
            }
        ],
    )

    assert moved.summary["rescheduled_applicants"] == 1  # type: ignore[attr-defined]
    # Nothing about the process changed, so the JOB-3 notice does not fire.
    assert moved.summary["notified_applicants"] == 0  # type: ignore[attr-defined]
    notices = await _venue_notices()
    assert len(notices) == 1
    assert notices[0]["context"]["venue"] == "LT 3"
    assert notices[0]["context"]["round"] == "Screening"


@pytest.mark.asyncio
async def test_RND4_a_student_with_their_own_venue_hears_nothing_when_the_default_moves() -> None:
    """Their effective venue did not move, so there is nothing to tell them."""
    admin, cycle_id, job_id, application_id, round_type_id = await _job_fixture()
    await _save_rounds(
        admin,
        cycle_id=cycle_id,
        job_id=job_id,
        rounds=[{"round_type_id": str(round_type_id), "name": "Screening", "venue": "LT 1"}],
    )
    round_id = cast_uuid((await _round_rows(job_id))[0]["id"])
    await _seed_state_in_round(application_id, round_id)
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "UPDATE application_round_states SET venue_override = 'AB 5 / 201' "
                    "WHERE application_id = :id"
                ),
                {"id": application_id},
            )
    finally:
        await engine.dispose()

    moved = await _save_rounds(
        admin,
        cycle_id=cycle_id,
        job_id=job_id,
        rounds=[
            {
                "round_id": str(round_id),
                "round_type_id": str(round_type_id),
                "name": "Screening",
                "venue": "LT 3",
            }
        ],
    )

    assert moved.summary["rescheduled_applicants"] == 0  # type: ignore[attr-defined]
    assert await _venue_notices() == []


@pytest.mark.asyncio
async def test_JOB3_a_save_that_omits_the_schedule_leaves_the_rounds_default_alone() -> None:
    """The rounds tab has no schedule input; omission must not mean "clear it"."""
    admin, cycle_id, job_id, _application, round_type_id = await _job_fixture()
    await _save_rounds(
        admin,
        cycle_id=cycle_id,
        job_id=job_id,
        rounds=[{"round_type_id": str(round_type_id), "name": "Screening"}],
    )
    round_id = cast_uuid((await _round_rows(job_id))[0]["id"])
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text("UPDATE job_rounds SET scheduled_at = :when WHERE id = :id"),
                {"id": round_id, "when": datetime(2027, 7, 1, 4, 0, tzinfo=UTC)},
            )
    finally:
        await engine.dispose()

    # A rename, sent the way the builder screen sends it: no schedule field.
    await _save_rounds(
        admin,
        cycle_id=cycle_id,
        job_id=job_id,
        rounds=[
            {
                "round_id": str(round_id),
                "round_type_id": str(round_type_id),
                "name": "Online Assessment",
            }
        ],
    )

    assert (await _round_rows(job_id))[0]["scheduled_at"] == datetime(
        2027, 7, 1, 4, 0, tzinfo=UTC
    )
    # Nothing moved, so nobody is told a schedule changed.
    assert await _venue_notices() == []


@pytest.mark.asyncio
async def test_JOB3_an_explicit_null_schedule_still_clears_the_rounds_default() -> None:
    admin, cycle_id, job_id, _application, round_type_id = await _job_fixture()
    await _save_rounds(
        admin,
        cycle_id=cycle_id,
        job_id=job_id,
        rounds=[{"round_type_id": str(round_type_id), "name": "Screening"}],
    )
    round_id = cast_uuid((await _round_rows(job_id))[0]["id"])
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text("UPDATE job_rounds SET scheduled_at = :when WHERE id = :id"),
                {"id": round_id, "when": datetime(2027, 7, 1, 4, 0, tzinfo=UTC)},
            )
    finally:
        await engine.dispose()

    await _save_rounds(
        admin,
        cycle_id=cycle_id,
        job_id=job_id,
        rounds=[
            {
                "round_id": str(round_id),
                "round_type_id": str(round_type_id),
                "name": "Screening",
                "scheduled_at": None,
            }
        ],
    )

    assert (await _round_rows(job_id))[0]["scheduled_at"] is None
