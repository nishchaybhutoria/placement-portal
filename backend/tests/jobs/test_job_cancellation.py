"""Cancelling a job and what it must leave alone (Behavior JOB-5, APP-4).

Cancellation is the widest-reaching thing the builder can do: it reaches every
application on the job at once.  The tests here are mostly about its edges --
the offer it has to pull, the accepted application it must not touch, and the
replay that must not undo the flag it already set.
"""

from __future__ import annotations

import os
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import DUPLICATE_ROW, INVALID_TRANSITION, UNMATCHED_IDENTIFIER
from app.core.plan import Preview, Result
from app.modules.jobs.cancel import cancellation_targets
from tests.cycles.conftest import Person
from tests.jobs.conftest import (
    build_test_executor,
    job_row,
    offer_row,
    seed_admin,
    seed_application,
    seed_complete_profile,
    seed_cycle,
    seed_job,
    seed_offer,
    seed_person,
    seed_taxonomy,
)

REASON = "The company withdrew the role"


class Applicant:
    """One seeded application, kept with the offer and person it belongs to."""

    def __init__(
        self, *, application_id: UUID, email: str, offer_id: UUID | None
    ) -> None:
        self.application_id = application_id
        self.email = email
        self.offer_id = offer_id

    @property
    def row(self) -> dict[str, str]:
        return {"application_id": str(self.application_id)}


async def _job_with_applicants(
    statuses: dict[str, str], *, with_offer: frozenset[str] = frozenset()
) -> tuple[Person, UUID, UUID, dict[str, Applicant]]:
    """A published job carrying one application per named status."""
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    applicants: dict[str, Applicant] = {}
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            program_id, branch_id = await seed_taxonomy(connection)
            cycle_id = await seed_cycle(connection)
            job_id = await seed_job(connection, cycle_id=cycle_id)
            await connection.execute(
                sa.text("UPDATE jobs SET is_published = true WHERE id = :id"),
                {"id": job_id},
            )
            for index, (name, status) in enumerate(statuses.items()):
                email = f"{name}@example.edu"
                student = await seed_person(connection, email=email)
                await seed_complete_profile(
                    connection,
                    student,
                    program_id=program_id,
                    branch_id=branch_id,
                    roll_number=f"2111{index:04d}",
                )
                application_id, _round = await seed_application(
                    connection,
                    cycle_id=cycle_id,
                    enrollment_id=student.enrollment_id,
                    job_id=job_id,
                    status=status,
                )
                offer_id = (
                    await seed_offer(
                        connection,
                        application_id=application_id,
                        responded=status == "accepted",
                    )
                    if name in with_offer
                    else None
                )
                applicants[name] = Applicant(
                    application_id=application_id, email=email, offer_id=offer_id
                )
    finally:
        await engine.dispose()
    return admin, cycle_id, job_id, applicants


async def _cancel(
    actor: Person,
    cycle_id: UUID,
    job_id: UUID,
    rows: list[dict[str, str]],
    *,
    batch_key: str = "cancel-1",
    dry_run: bool = False,
) -> Preview | Result:
    executor, engine = build_test_executor()
    try:
        return await executor.run_bulk(
            "cancel_job",
            cast(list[dict[str, object]], rows),
            batch_key,
            actor.actor,
            dry_run=dry_run,
            batch_fields={"cycle_id": cycle_id, "job_id": job_id, "reason": REASON},
        )
    finally:
        await engine.dispose()


def _by_application(result: Preview | Result) -> dict[str, dict[str, object]]:
    rows = cast(list[dict[str, object]], result.summary["rows"])
    return {str(row["application_id"]): row for row in rows}


async def _statuses(job_id: UUID) -> dict[UUID, str]:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    sa.text("SELECT id, status FROM applications WHERE job_id = :id"),
                    {"id": job_id},
                )
            ).mappings().all()
    finally:
        await engine.dispose()
    return {cast(UUID, row["id"]): str(row["status"]) for row in rows}


@pytest.mark.asyncio
async def test_JOB5_cancelling_rejects_every_in_flight_application_and_pulls_its_offer(
) -> None:
    admin, cycle_id, job_id, applicants = await _job_with_applicants(
        {
            "asha": "in_progress",
            "bikram": "pending_offer",
            "chitra": "offered",
        },
        with_offer=frozenset({"chitra"}),
    )

    result = await _cancel(
        admin, cycle_id, job_id, [person.row for person in applicants.values()]
    )

    assert isinstance(result, Result)
    reported = _by_application(result)
    assert {
        str(person.application_id): reported[str(person.application_id)]["status"]
        for person in applicants.values()
    } == {str(person.application_id): "applied" for person in applicants.values()}
    # The from_status is carried back per row, so staff see what each student
    # was actually pulled out of rather than a bare count.
    assert reported[str(applicants["bikram"].application_id)]["from_status"] == (
        "pending_offer"
    )
    assert reported[str(applicants["chitra"].application_id)]["terminated_offers"] == 1
    assert reported[str(applicants["asha"].application_id)]["terminated_offers"] == 0

    assert set((await _statuses(job_id)).values()) == {"rejected"}

    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            job = await job_row(connection, job_id)
            # An unresponded offer left standing would sit there for the expiry
            # job to trip over, so cancelling revokes it (JOB-5).
            offer = await offer_row(
                connection, cast(UUID, applicants["chitra"].offer_id)
            )
            events = (
                await connection.execute(
                    sa.text(
                        "SELECT event_type, to_status, reason FROM application_events "
                        "WHERE application_id = ANY(:ids)"
                    ),
                    {"ids": [p.application_id for p in applicants.values()]},
                )
            ).mappings().all()
    finally:
        await engine.dispose()

    assert job["cancelled_at"] is not None
    assert job["is_published"] is False
    assert offer["terminated_at"] is not None
    assert str(offer["termination_kind"]) == "company_revoked"
    assert str(offer["termination_reason"]) == "job_cancelled"
    assert {str(event["event_type"]) for event in events} == {"eliminated"}
    assert {str(event["to_status"]) for event in events} == {"rejected"}


@pytest.mark.asyncio
async def test_JOB5_an_accepted_application_is_listed_untouched_not_cancelled() -> None:
    admin, cycle_id, job_id, applicants = await _job_with_applicants(
        {"asha": "in_progress", "deepa": "accepted"},
        with_offer=frozenset({"deepa"}),
    )
    accepted = applicants["deepa"]

    result = await _cancel(
        admin, cycle_id, job_id, [person.row for person in applicants.values()]
    )

    assert isinstance(result, Result)
    row = _by_application(result)[str(accepted.application_id)]
    # A student holding an accepted offer has made plans; unwinding that is
    # terminate_offer's job, with its own restore choices (JOB-5).
    assert row["status"] == "skipped"
    assert row["reason"] == INVALID_TRANSITION
    assert row["suggested_command"] == "terminate_offer"

    statuses = await _statuses(job_id)
    assert statuses[accepted.application_id] == "accepted"
    assert statuses[applicants["asha"].application_id] == "rejected"

    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            offer = await offer_row(connection, cast(UUID, accepted.offer_id))
            events = await connection.scalar(
                sa.text(
                    "SELECT count(*) FROM application_events "
                    "WHERE application_id = :id"
                ),
                {"id": accepted.application_id},
            )
    finally:
        await engine.dispose()

    # Untouched means untouched: no termination, and no event claiming one.
    assert offer["terminated_at"] is None
    assert events == 0


@pytest.mark.asyncio
async def test_JOB5_the_preview_separates_what_moves_from_what_it_leaves_behind(
) -> None:
    _admin, _cycle_id, job_id, applicants = await _job_with_applicants(
        {
            "asha": "in_progress",
            "chitra": "offered",
            "deepa": "accepted",
            "esha": "withdrawn",
        },
        with_offer=frozenset({"chitra", "deepa"}),
    )

    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            targets, untouched = await cancellation_targets(connection, job_id)
    finally:
        await engine.dispose()

    assert {str(row["application_id"]) for row in targets} == {
        str(applicants["asha"].application_id),
        str(applicants["chitra"].application_id),
    }
    # The count of open offers is on the preview because it is what staff are
    # really being asked to approve: pulling live offers, not moving rows.
    assert {
        str(row["application_id"]): row["open_offers"] for row in targets
    }[str(applicants["chitra"].application_id)] == 1
    assert [str(row["application_id"]) for row in untouched] == [
        str(applicants["deepa"].application_id)
    ]
    assert untouched[0]["suggested_command"] == "terminate_offer"
    # An already-terminal application is neither moved nor flagged for staff.
    assert str(applicants["esha"].application_id) not in {
        str(row["application_id"]) for row in targets + untouched
    }


@pytest.mark.asyncio
async def test_JOB5_replaying_the_batch_does_not_republish_the_cancelled_job() -> None:
    admin, cycle_id, job_id, applicants = await _job_with_applicants(
        {"asha": "in_progress"}
    )
    rows = [person.row for person in applicants.values()]

    first = await _cancel(admin, cycle_id, job_id, rows)
    replay = await _cancel(admin, cycle_id, job_id, rows)

    assert isinstance(first, Result)
    assert isinstance(replay, Result)
    # The batch key makes the replay a no-op read of the recorded result, so
    # the second run must not re-decide against a now-rejected application.
    assert _by_application(replay) == _by_application(first)

    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            job = await job_row(connection, job_id)
            events = await connection.scalar(
                sa.text(
                    "SELECT count(*) FROM application_events WHERE application_id = :id"
                ),
                {"id": applicants["asha"].application_id},
            )
    finally:
        await engine.dispose()

    assert job["is_published"] is False
    assert job["cancelled_at"] is not None
    assert events == 1


@pytest.mark.asyncio
async def test_JOB5_a_stranger_row_and_a_repeated_row_are_reported_not_applied() -> None:
    admin, cycle_id, job_id, applicants = await _job_with_applicants(
        {"asha": "in_progress"}
    )
    stranger = uuid4()
    asha = applicants["asha"]

    result = await _cancel(
        admin,
        cycle_id,
        job_id,
        [asha.row, asha.row, {"application_id": str(stranger)}],
    )

    assert isinstance(result, Result)
    rows = cast(list[dict[str, object]], result.summary["rows"])
    # One result row per submitted row, in order, so staff can line the report
    # up against the list they sent (RND-2).
    assert [row["status"] for row in rows] == ["applied", "skipped", "error"]
    assert rows[1]["reason"] == DUPLICATE_ROW
    assert rows[2]["reason"] == UNMATCHED_IDENTIFIER
    assert (await _statuses(job_id))[asha.application_id] == "rejected"


@pytest.mark.asyncio
async def test_JOB5_a_dry_run_reports_the_same_rows_and_changes_nothing() -> None:
    admin, cycle_id, job_id, applicants = await _job_with_applicants(
        {"asha": "in_progress", "chitra": "offered"},
        with_offer=frozenset({"chitra"}),
    )
    rows = [person.row for person in applicants.values()]

    preview = await _cancel(admin, cycle_id, job_id, rows, dry_run=True)

    assert isinstance(preview, Preview)
    assert [row["status"] for row in _by_application(preview).values()] == [
        "applied",
        "applied",
    ]

    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            job = await job_row(connection, job_id)
            offer = await offer_row(
                connection, cast(UUID, applicants["chitra"].offer_id)
            )
    finally:
        await engine.dispose()

    assert set((await _statuses(job_id)).values()) == {"in_progress", "offered"}
    assert job["cancelled_at"] is None
    assert job["is_published"] is True
    assert offer["terminated_at"] is None
