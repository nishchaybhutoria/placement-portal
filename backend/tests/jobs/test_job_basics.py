"""Job creation, editing, and publishing (Behavior JOB-1, JOB-2, JOB-3, JOB-6)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import create_engine
from app.core.errors import DomainRejection
from app.core.executor import Executor
from app.core.plan import Preview, Result
from tests.cycles.conftest import Person
from tests.jobs.conftest import (
    build_test_executor,
    job_row,
    seed_admin,
    seed_application,
    seed_company,
    seed_complete_profile,
    seed_cycle,
    seed_job,
    seed_person,
    seed_sector,
    seed_taxonomy,
)

DEADLINE = datetime(2030, 6, 1, tzinfo=UTC)
LATER = datetime(2030, 7, 1, tzinfo=UTC)


async def _fixture(kind: str = "placement") -> tuple[Person, UUID, UUID]:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            cycle_id = await seed_cycle(connection, kind=kind, name=f"Cycle {kind}")
            company_id = await seed_company(connection)
    finally:
        await engine.dispose()
    return admin, cycle_id, company_id


async def _run(
    executor: Executor, name: str, payload: dict[str, object], actor: Person, **kwargs: object
) -> Preview | Result:
    model = executor.registry.commands[name].input_model
    return await executor.run(name, model.model_validate(payload), actor.actor, **kwargs)  # type: ignore[arg-type]


async def _reject(
    executor: Executor, name: str, payload: dict[str, object], actor: Person
) -> list[str]:
    with pytest.raises(DomainRejection) as error:
        await _run(executor, name, payload, actor)
    return [reason.code for reason in error.value.rejection.reasons]


@pytest.mark.asyncio
async def test_JOB1_a_dedicated_cycle_forces_the_outcome_and_refuses_the_other_one() -> None:
    admin, cycle_id, company_id = await _fixture("placement")
    executor, engine = build_test_executor()
    base: dict[str, object] = {
        "cycle_id": str(cycle_id),
        "company_id": str(company_id),
        "title": "Backend Engineer",
        "description": "Build things",
        "application_deadline": DEADLINE.isoformat(),
    }
    try:
        forced = await _run(executor, "create_job", base, admin)
        echoed = await _run(
            executor, "create_job", base | {"outcome": "placement", "title": "Echoed"}, admin
        )
        codes = await _reject(
            executor,
            "create_job",
            base | {"outcome": "internship", "title": "Wrong"},
            admin,
        )
    finally:
        await engine.dispose()

    assert forced.summary["outcome"] == "placement"
    assert echoed.summary["outcome"] == "placement"
    assert codes == ["invalid_field_value"]


@pytest.mark.asyncio
async def test_JOB1_an_open_cycle_demands_an_explicit_outcome() -> None:
    admin, cycle_id, company_id = await _fixture("open")
    executor, engine = build_test_executor()
    base: dict[str, object] = {
        "cycle_id": str(cycle_id),
        "company_id": str(company_id),
        "title": "Summer Intern",
        "description": "Build things",
    }
    try:
        codes = await _reject(executor, "create_job", base, admin)
        chosen = await _run(executor, "create_job", base | {"outcome": "internship"}, admin)
    finally:
        await engine.dispose()

    assert codes == ["invalid_field_value"]
    assert chosen.summary["outcome"] == "internship"


@pytest.mark.asyncio
async def test_JOB1_the_outcome_is_immutable_but_an_unchanged_echo_is_accepted() -> None:
    admin, cycle_id, _company = await _fixture("placement")
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            job_id = await seed_job(connection, cycle_id=cycle_id)
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    payload: dict[str, object] = {"cycle_id": str(cycle_id), "job_id": str(job_id)}
    try:
        echoed = await _run(
            executor, "update_job_basics", payload | {"outcome": "placement"}, admin
        )
        codes = await _reject(
            executor, "update_job_basics", payload | {"outcome": "internship"}, admin
        )
    finally:
        await engine.dispose()

    assert echoed.summary["outcome"] == "placement"
    assert codes == ["field_not_editable"]


@pytest.mark.asyncio
async def test_JOB6_the_application_deadline_is_optional_only_in_an_open_cycle() -> None:
    admin, placement, company_id = await _fixture("placement")
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            open_cycle = await seed_cycle(connection, kind="open", name="Rolling board")
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    dedicated: dict[str, object] = {
        "cycle_id": str(placement),
        "company_id": str(company_id),
        "title": "Backend Engineer",
        "description": "Build things",
    }
    rolling: dict[str, object] = {
        "cycle_id": str(open_cycle),
        "company_id": str(company_id),
        "title": "Rolling Intern",
        "description": "Build things",
        "outcome": "internship",
    }
    try:
        missing = await _reject(executor, "create_job", dedicated, admin)
        allowed = await _run(executor, "create_job", rolling, admin)
        # JOB-6: an open cycle records outcomes directly, so there is no offer
        # to accept and no deadline for accepting one.
        forbidden = await _reject(
            executor,
            "create_job",
            rolling
            | {
                "title": "With deadline",
                "offer_acceptance_deadline": LATER.isoformat(),
            },
            admin,
        )
    finally:
        await engine.dispose()

    assert missing == ["invalid_field_value"]
    assert allowed.summary["changed"] is True
    assert forbidden == ["field_not_editable"]


@pytest.mark.asyncio
async def test_JOB2_the_offer_acceptance_deadline_must_follow_the_application_one() -> None:
    admin, cycle_id, company_id = await _fixture("placement")
    executor, engine = build_test_executor()
    try:
        codes = await _reject(
            executor,
            "create_job",
            {
                "cycle_id": str(cycle_id),
                "company_id": str(company_id),
                "title": "Backend Engineer",
                "description": "Build things",
                "application_deadline": LATER.isoformat(),
                "offer_acceptance_deadline": DEADLINE.isoformat(),
            },
            admin,
        )
    finally:
        await engine.dispose()

    assert codes == ["invalid_field_value"]


@pytest.mark.asyncio
async def test_JOB2_per_program_ctc_rows_are_replaced_wholesale() -> None:
    admin, cycle_id, company_id = await _fixture("placement")
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            btech = uuid4()
            mtech = uuid4()
            for program_id, name in ((btech, "B.Tech"), (mtech, "M.Tech")):
                await connection.execute(
                    sa.text(
                        "INSERT INTO programs (id, name, is_active) "
                        "VALUES (:id, :name, true)"
                    ),
                    {"id": program_id, "name": name},
                )
            sector_id = await seed_sector(connection)
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    try:
        created = await _run(
            executor,
            "create_job",
            {
                "cycle_id": str(cycle_id),
                "company_id": str(company_id),
                "title": "Backend Engineer",
                "description": "Build things",
                "sector_id": str(sector_id),
                "application_deadline": DEADLINE.isoformat(),
                "program_ctc": [
                    {"program_id": str(btech), "ctc_lpa": "24.00"},
                    {"program_id": str(mtech), "ctc_lpa": "26.00"},
                ],
            },
            admin,
        )
        job_id = UUID(str(created.summary["job_id"]))
        await _run(
            executor,
            "update_job_basics",
            {
                "cycle_id": str(cycle_id),
                "job_id": str(job_id),
                "program_ctc": [{"program_id": str(btech), "ctc_lpa": "28.00"}],
            },
            admin,
        )
    finally:
        await engine.dispose()

    check = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with check.begin() as connection:
            rows = (
                await connection.execute(
                    sa.text(
                        "SELECT program_id, ctc_lpa FROM job_program_ctc "
                        "WHERE job_id = :id"
                    ),
                    {"id": job_id},
                )
            ).mappings().all()
    finally:
        await check.dispose()

    assert [(row["program_id"], str(row["ctc_lpa"])) for row in rows] == [
        (btech, "28.00")
    ]


@pytest.mark.asyncio
async def test_JOB3_a_deadline_move_notifies_in_flight_applicants_including_a_shortening() -> None:
    admin, cycle_id, _company = await _fixture("placement")
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            program_id, branch_id = await seed_taxonomy(connection)
            student = await seed_person(connection, email="asha@example.edu")
            await seed_complete_profile(
                connection,
                student,
                program_id=program_id,
                branch_id=branch_id,
                roll_number="21110001",
            )
            job_id = await seed_job(connection, cycle_id=cycle_id)
            await connection.execute(
                sa.text(
                    "UPDATE jobs SET application_deadline = :deadline WHERE id = :id"
                ),
                {"deadline": LATER, "id": job_id},
            )
            await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                job_id=job_id,
            )
            withdrawn = await seed_person(connection, email="gone@example.edu")
            await seed_complete_profile(
                connection,
                withdrawn,
                program_id=program_id,
                branch_id=branch_id,
                roll_number="21110002",
            )
            await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=withdrawn.enrollment_id,
                job_id=job_id,
                status="withdrawn",
            )
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    try:
        # Shortening into the past is allowed (JOB-3) and the notification is
        # the warning students get that applying just closed.
        result = await _run(
            executor,
            "update_job_basics",
            {
                "cycle_id": str(cycle_id),
                "job_id": str(job_id),
                "application_deadline": (
                    datetime.now(UTC) - timedelta(days=1)
                ).isoformat(),
            },
            admin,
        )
        renamed = await _run(
            executor,
            "update_job_basics",
            {"cycle_id": str(cycle_id), "job_id": str(job_id), "title": "Renamed"},
            admin,
        )
    finally:
        await engine.dispose()

    assert result.summary["notified_applicants"] == 1
    # A copy edit is not a process change, so nobody is emailed for it.
    assert renamed.summary["notified_applicants"] == 0

    check = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with check.begin() as connection:
            recipients = (
                await connection.execute(
                    sa.text(
                        "SELECT args->>'recipient' AS recipient, "
                        "args->'context'->>'student' AS student, "
                        "args->'context'->>'cycle_id' AS cycle_id "
                        "FROM procrastinate_jobs "
                        "WHERE args->>'event_key' = 'deadline_changed'"
                    )
                )
            ).mappings().all()
    finally:
        await check.dispose()

    assert [dict(row) for row in recipients] == [
        {
            "recipient": "asha@example.edu",
            "student": "Asha Rao",
            "cycle_id": str(cycle_id),
        }
    ]


@pytest.mark.asyncio
async def test_JOB2_publishing_stamps_once_and_survives_an_unpublish() -> None:
    admin, cycle_id, _company = await _fixture("placement")
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            job_id = await seed_job(connection, cycle_id=cycle_id)
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    payload: dict[str, object] = {"cycle_id": str(cycle_id), "job_id": str(job_id)}
    try:
        await _run(executor, "publish_job", payload, admin)
        first = await _published_at(job_id)
        await _run(executor, "unpublish_job", payload, admin)
        republished = await _run(executor, "publish_job", payload, admin)
        second = await _published_at(job_id)
        idempotent = await _run(executor, "publish_job", payload, admin)
    finally:
        await engine.dispose()

    assert first is not None
    assert second == first, "published_at records the first publication, not the latest"
    assert republished.summary["changed"] is True
    assert idempotent.summary["changed"] is False


async def _published_at(job_id: UUID) -> datetime | None:
    engine: AsyncEngine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            row = await job_row(connection, job_id)
            return row["published_at"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_JOB2_a_job_in_another_cycle_is_not_reachable_by_naming_it() -> None:
    """Two-stage authorization: the loader scopes the job to the authorized cycle."""
    admin, cycle_id, _company = await _fixture("placement")
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            other = await seed_cycle(connection, kind="placement", name="Other cycle")
            elsewhere = await seed_job(connection, cycle_id=other)
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    try:
        codes = await _reject(
            executor,
            "update_job_basics",
            {"cycle_id": str(cycle_id), "job_id": str(elsewhere), "title": "Stolen"},
            admin,
        )
    finally:
        await engine.dispose()

    assert codes == ["job_not_found"]
