"""Membership exits and the CYC-4 cascade (Behavior CYC-3, CYC-4, APP-4.13)."""

from __future__ import annotations

import os
from typing import cast
from uuid import UUID

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import INVALID_TRANSITION, DomainRejection
from app.core.plan import Preview, Result
from tests.cycles.conftest import (
    Person,
    application_status,
    build_test_executor,
    membership_row,
    seed_admin,
    seed_application,
    seed_complete_profile,
    seed_cycle,
    seed_membership,
    seed_person,
    seed_taxonomy,
)

pytestmark = pytest.mark.usefixtures("clean_cycles")


async def _member_with_applications(
    statuses: tuple[str, ...], *, membership_status: str = "active"
) -> tuple[Person, Person, UUID, UUID, dict[str, UUID], UUID | None]:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            program_id, branch_id = await seed_taxonomy(connection)
            student = await seed_person(connection, email="asha@example.edu")
            resume_id = await seed_complete_profile(
                connection, student, program_id=program_id, branch_id=branch_id
            )
            cycle_id = await seed_cycle(connection, kind="placement")
            membership_id = await seed_membership(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status=membership_status,
                resume_id=resume_id,
            )
            applications: dict[str, UUID] = {}
            round_id: UUID | None = None
            for status in statuses:
                application_id, created_round = await seed_application(
                    connection,
                    cycle_id=cycle_id,
                    enrollment_id=student.enrollment_id,
                    status=status,
                    title=f"Job {status}",
                    with_round=status == "in_progress",
                )
                applications[status] = application_id
                round_id = created_round or round_id
    finally:
        await engine.dispose()
    return admin, student, cycle_id, membership_id, applications, round_id


@pytest.mark.asyncio
async def test_CYC4_student_withdrawal_auto_withdraws_in_flight_applications() -> None:
    _admin, student, cycle_id, membership_id, applications, round_id = (
        await _member_with_applications(("in_progress", "pending_offer", "rejected"))
    )

    executor, engine = build_test_executor()
    model = executor.registry.commands["withdraw_membership"].input_model
    payload = model.model_validate(
        {"cycle_id": str(cycle_id), "enrollment_id": str(student.enrollment_id)}
    )
    try:
        preview = await executor.run(
            "withdraw_membership", payload, student.actor, dry_run=True
        )
        result = await executor.run("withdraw_membership", payload, student.actor)
    finally:
        await engine.dispose()

    assert isinstance(preview, Preview) and isinstance(result, Result)
    assert preview.events == result.events
    assert len(cast(list[object], result.summary["auto_withdrawn"])) == 2

    check = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with check.connect() as connection:
            assert (await membership_row(connection, membership_id))[
                "status"
            ] == "withdrawn"
            assert (
                await application_status(connection, applications["in_progress"])
            ) == "auto_withdrawn"
            assert (
                await application_status(connection, applications["pending_offer"])
            ) == "auto_withdrawn"
            # A terminal application is left exactly as it was.
            assert (
                await application_status(connection, applications["rejected"])
            ) == "rejected"
            events = (
                await connection.execute(
                    sa.text(
                        "SELECT application_id, event_type, from_status, to_status, "
                        "from_round_id, payload FROM application_events ORDER BY id"
                    )
                )
            ).mappings().all()
            preserved = await connection.scalar(
                sa.text("SELECT current_round_id FROM applications WHERE id = :id"),
                {"id": applications["in_progress"]},
            )
    finally:
        await check.dispose()

    assert {row["event_type"] for row in events} == {"auto_withdrawn"}
    assert {row["to_status"] for row in events} == {"auto_withdrawn"}
    assert {
        cast(dict[str, object], row["payload"])["trigger"] for row in events
    } == {"membership_exit"}
    # CYC-4: the position survives underneath so reinstatement can restore it.
    assert preserved == round_id
    in_flight = next(
        row for row in events if row["application_id"] == applications["in_progress"]
    )
    assert in_flight["from_round_id"] == round_id


@pytest.mark.asyncio
async def test_CYC4_offered_and_accepted_applications_are_listed_untouched() -> None:
    """APP-4.13 cannot move them; the preview names terminate_offer instead."""
    admin, _student, cycle_id, membership_id, applications, _round = (
        await _member_with_applications(("in_progress", "offered", "accepted"))
    )

    executor, engine = build_test_executor()
    model = executor.registry.commands["remove_membership"].input_model
    try:
        result = await executor.run(
            "remove_membership",
            model.model_validate(
                {
                    "cycle_id": str(cycle_id),
                    "membership_id": str(membership_id),
                    "reason": "Disciplinary",
                }
            ),
            admin.actor,
        )
    finally:
        await engine.dispose()

    assert isinstance(result, Result)
    untouched = cast(list[dict[str, object]], result.summary["untouched"])
    assert {row["status"] for row in untouched} == {"offered", "accepted"}
    assert {row["suggested_command"] for row in untouched} == {"terminate_offer"}

    check = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with check.connect() as connection:
            assert (
                await application_status(connection, applications["offered"])
            ) == "offered"
            assert (
                await application_status(connection, applications["accepted"])
            ) == "accepted"
            assert (
                await application_status(connection, applications["in_progress"])
            ) == "auto_withdrawn"
    finally:
        await check.dispose()


@pytest.mark.asyncio
async def test_CYC4_the_cascade_notifies_each_affected_student() -> None:
    _admin, student, cycle_id, _membership, _applications, _round = (
        await _member_with_applications(("in_progress", "pending_offer"))
    )

    executor, engine = build_test_executor()
    model = executor.registry.commands["withdraw_membership"].input_model
    try:
        await executor.run(
            "withdraw_membership",
            model.model_validate(
                {"cycle_id": str(cycle_id), "enrollment_id": str(student.enrollment_id)}
            ),
            student.actor,
        )
    finally:
        await engine.dispose()

    check = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with check.connect() as connection:
            jobs = (
                await connection.execute(
                    sa.text("SELECT args FROM procrastinate_jobs ORDER BY id")
                )
            ).scalars().all()
    finally:
        await check.dispose()

    keys = [cast(dict[str, object], job)["event_key"] for job in jobs]
    # A self-withdrawal has no membership notification of its own; only the
    # applications it took down are announced.
    assert keys == ["auto_withdrawn", "auto_withdrawn"]


@pytest.mark.asyncio
async def test_CYC3_a_pending_member_may_withdraw_with_nothing_to_cascade() -> None:
    _admin, student, cycle_id, membership_id, _applications, _round = (
        await _member_with_applications((), membership_status="pending")
    )

    executor, engine = build_test_executor()
    model = executor.registry.commands["withdraw_membership"].input_model
    try:
        result = await executor.run(
            "withdraw_membership",
            model.model_validate(
                {"cycle_id": str(cycle_id), "enrollment_id": str(student.enrollment_id)}
            ),
            student.actor,
        )
    finally:
        await engine.dispose()

    assert isinstance(result, Result)
    assert result.summary["status"] == "withdrawn"
    assert result.summary["auto_withdrawn"] == []


@pytest.mark.asyncio
async def test_CYC3_removal_requires_a_reason_and_records_the_decider() -> None:
    admin, _student, cycle_id, membership_id, _applications, _round = (
        await _member_with_applications(())
    )

    executor, engine = build_test_executor()
    model = executor.registry.commands["remove_membership"].input_model
    try:
        with pytest.raises(ValueError):
            model.model_validate(
                {
                    "cycle_id": str(cycle_id),
                    "membership_id": str(membership_id),
                    "reason": "  ",
                }
            )
        await executor.run(
            "remove_membership",
            model.model_validate(
                {
                    "cycle_id": str(cycle_id),
                    "membership_id": str(membership_id),
                    "reason": "Code of conduct",
                }
            ),
            admin.actor,
        )
    finally:
        await engine.dispose()

    check = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with check.connect() as connection:
            row = await membership_row(connection, membership_id)
    finally:
        await check.dispose()

    assert row["status"] == "removed"
    assert row["decided_by"] == admin.user_id
    assert row["decided_at"] is not None


@pytest.mark.asyncio
async def test_CYC3_restore_reactivates_without_reinstating_applications() -> None:
    """CYC-3: applications are reinstated separately, per application (INT-1)."""
    admin, student, cycle_id, membership_id, applications, _round = (
        await _member_with_applications(("in_progress",))
    )

    executor, engine = build_test_executor()
    try:
        await executor.run(
            "withdraw_membership",
            executor.registry.commands[
                "withdraw_membership"
            ].input_model.model_validate(
                {"cycle_id": str(cycle_id), "enrollment_id": str(student.enrollment_id)}
            ),
            student.actor,
        )
        restored = await executor.run(
            "restore_membership",
            executor.registry.commands[
                "restore_membership"
            ].input_model.model_validate(
                {"cycle_id": str(cycle_id), "membership_id": str(membership_id)}
            ),
            admin.actor,
        )
    finally:
        await engine.dispose()

    assert isinstance(restored, Result)
    assert restored.summary["status"] == "active"
    assert restored.summary["auto_withdrawn"] == []

    check = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with check.connect() as connection:
            assert (await membership_row(connection, membership_id))["status"] == "active"
            assert (
                await application_status(connection, applications["in_progress"])
            ) == "auto_withdrawn"
    finally:
        await check.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "membership_status"),
    [
        ("withdraw_membership", "rejected"),
        ("remove_membership", "pending"),
        ("restore_membership", "active"),
    ],
)
async def test_CYC3_exits_reject_illegal_starting_statuses(
    command: str, membership_status: str
) -> None:
    admin, student, cycle_id, membership_id, _applications, _round = (
        await _member_with_applications((), membership_status=membership_status)
    )

    executor, engine = build_test_executor()
    model = executor.registry.commands[command].input_model
    payload: dict[str, object] = {"cycle_id": str(cycle_id)}
    if command == "withdraw_membership":
        payload["enrollment_id"] = str(student.enrollment_id)
        actor = student.actor
    else:
        payload["membership_id"] = str(membership_id)
        actor = admin.actor
    if command == "remove_membership":
        payload["reason"] = "Not allowed here"

    try:
        with pytest.raises(DomainRejection) as error:
            await executor.run(command, model.model_validate(payload), actor)
    finally:
        await engine.dispose()

    assert [reason.code for reason in error.value.rejection.reasons] == [
        INVALID_TRANSITION
    ]
