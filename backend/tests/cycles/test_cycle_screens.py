"""Cycle and membership screens (LLD section 11.3, Behavior CYC-1, CYC-3)."""

from __future__ import annotations

import os
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.domain.shared import RuleDomain
from app.modules.cycles.queries import (
    cycles_joinable,
    staff_cycle,
    staff_cycle_approvals,
    staff_cycles,
)
from tests.cycles.conftest import (
    Person,
    seed_admin,
    seed_application,
    seed_complete_profile,
    seed_coordinator_link,
    seed_cycle,
    seed_membership,
    seed_person,
    seed_taxonomy,
)
from tests.overrides.conftest import grant

pytestmark = pytest.mark.usefixtures("clean_cycles")


def _engine():  # noqa: ANN202 - test helper
    return create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])


async def _fixture() -> tuple[Person, Person, UUID, UUID, UUID]:
    engine = _engine()
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            program_id, branch_id = await seed_taxonomy(connection)
            staff = await seed_person(connection, email="coord@example.edu")
            student = await seed_person(connection, email="asha@example.edu")
            resume_id = await seed_complete_profile(
                connection, student, program_id=program_id, branch_id=branch_id
            )
            cycle_id = await seed_cycle(connection, kind="placement")
            archived_id = await seed_cycle(
                connection, name="Placement 2024", archived=True
            )
            await seed_coordinator_link(connection, cycle_id, staff.user_id)
            membership_id = await seed_membership(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status="pending",
                resume_id=resume_id,
            )
    finally:
        await engine.dispose()
    return admin, student, cycle_id, archived_id, membership_id


@pytest.mark.asyncio
async def test_CYC1_staff_cycles_hides_archived_cycles_by_default() -> None:
    _admin, _student, cycle_id, archived_id, _membership = await _fixture()

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        default = await staff_cycles(engine)
        with_archived = await staff_cycles(engine, include_archived=True)
        placements = await staff_cycles(engine, kind="placement")
    finally:
        await engine.dispose()

    listed = {row["id"] for row in cast(list[dict[str, object]], default["cycles"])}
    assert listed == {str(cycle_id)}
    assert len(cast(list[object], with_archived["cycles"])) == 2
    assert len(cast(list[object], placements["cycles"])) == 1
    row = cast(list[dict[str, object]], default["cycles"])[0]
    assert row["pending_count"] == 1
    assert row["active_count"] == 0
    assert row["job_count"] == 0


@pytest.mark.asyncio
async def test_CYC2_staff_cycle_reports_policy_with_provenance() -> None:
    _admin, _student, cycle_id, _archived, _membership = await _fixture()

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        detail = await staff_cycle(engine, cycle_id)
        missing = await staff_cycle(engine, uuid4())
    finally:
        await engine.dispose()

    assert missing is None
    assert detail is not None
    policy = cast(dict[str, dict[str, object]], detail["policy"])
    assert policy["max_accepted_offers"]["value"] == 1
    assert policy["max_accepted_offers"]["source"] == "cycle_policy"
    # Every CYC-2 knob is a real column, so a live cycle resolves all of them
    # from cycle_policy; the "default" provenance is what a cycle without a
    # policy row would report, which C6 makes unreachable.
    assert policy["offer_expiry_behavior"]["value"] == "auto_decline"
    assert {entry["source"] for entry in policy.values()} == {"cycle_policy"}
    assert detail["pending_approvals"] == 1
    assert cast(dict[str, object], detail["memberships"])["pending"] == 1
    coordinators = cast(list[dict[str, object]], detail["coordinators"])
    assert [row["email"] for row in coordinators] == ["coord@example.edu"]


@pytest.mark.asyncio
async def test_CYC1_staff_cycle_funnel_counts_applications_by_status() -> None:
    _admin, student, cycle_id, _archived, _membership = await _fixture()
    engine = _engine()
    try:
        async with engine.begin() as connection:
            await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status="in_progress",
            )
            await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status="rejected",
                title="Другая",
            )
    finally:
        await engine.dispose()

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        detail = await staff_cycle(engine, cycle_id)
    finally:
        await engine.dispose()

    assert detail is not None
    assert cast(dict[str, object], detail["applications"]) == {
        "in_progress": 1,
        "rejected": 1,
    }


@pytest.mark.asyncio
async def test_CYC3_the_approvals_queue_carries_what_an_approver_needs() -> None:
    admin, _student, cycle_id, _archived, membership_id = await _fixture()

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        queue = await staff_cycle_approvals(engine, admin.actor, cycle_id)
        missing = await staff_cycle_approvals(engine, admin.actor, uuid4())
    finally:
        await engine.dispose()

    assert missing is None
    assert queue is not None
    rows = cast(list[dict[str, object]], queue["rows"])
    assert len(rows) == 1
    row = rows[0]
    assert row["membership_id"] == str(membership_id)
    assert row["roll_number"] == "21110001"
    assert row["program"] == "BTech"
    assert row["branch"] == "CSE"
    assert row["cpi"] == "8.40"
    assert row["consented_at"] is not None
    assert cast(dict[str, object], row["resume"])["label"] == "Primary"


@pytest.mark.asyncio
async def test_CYC3_the_approvals_queue_shows_rejected_rows_for_the_loop() -> None:
    admin, _student, cycle_id, _archived, membership_id = await _fixture()
    engine = _engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "UPDATE cycle_memberships SET status = 'rejected', "
                    "rejection_reason = 'Incomplete' WHERE id = :id"
                ),
                {"id": membership_id},
            )
    finally:
        await engine.dispose()

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        pending = await staff_cycle_approvals(engine, admin.actor, cycle_id)
        rejected = await staff_cycle_approvals(
            engine, admin.actor, cycle_id, status="rejected"
        )
    finally:
        await engine.dispose()

    assert pending is not None and rejected is not None
    assert cast(list[object], pending["rows"]) == []
    rows = cast(list[dict[str, object]], rejected["rows"])
    assert rows[0]["rejection_reason"] == "Incomplete"


@pytest.mark.asyncio
async def test_CYC3_a_pending_member_sees_only_their_status() -> None:
    """CYC-3: a pending member gets a status screen, not the cycle's contents."""
    _admin, student, cycle_id, _archived, membership_id = await _fixture()

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        screen = await cycles_joinable(engine, student.enrollment_id)
    finally:
        await engine.dispose()

    cycles = cast(list[dict[str, object]], screen["cycles"])
    assert len(cycles) == 1
    entry = cycles[0]
    membership = cast(dict[str, object], entry["membership"])
    assert membership["status"] == "pending"
    assert membership["membership_id"] == str(membership_id)
    assert entry["can_join"] is False
    assert entry["reasons"] == []


@pytest.mark.asyncio
async def test_CYC3_a_rejected_member_sees_the_reason() -> None:
    _admin, student, cycle_id, _archived, membership_id = await _fixture()
    engine = _engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "UPDATE cycle_memberships SET status = 'rejected', "
                    "rejection_reason = 'Missing transcript' WHERE id = :id"
                ),
                {"id": membership_id},
            )
    finally:
        await engine.dispose()

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        screen = await cycles_joinable(engine, student.enrollment_id)
    finally:
        await engine.dispose()

    entry = cast(list[dict[str, object]], screen["cycles"])[0]
    membership = cast(dict[str, object], entry["membership"])
    assert membership["status"] == "rejected"
    assert membership["rejection_reason"] == "Missing transcript"


@pytest.mark.asyncio
async def test_CYC3_joinable_reports_every_blocking_reason_for_a_non_member() -> None:
    engine = _engine()
    try:
        async with engine.begin() as connection:
            await seed_admin(connection)
            program_id, branch_id = await seed_taxonomy(connection)
            student = await seed_person(connection, email="asha@example.edu")
            await seed_complete_profile(
                connection,
                student,
                program_id=program_id,
                branch_id=branch_id,
                cpi="7.00",
                declared=False,
            )
            await seed_cycle(
                connection,
                kind="placement",
                join_rule='{"all": [{"field": "cpi", "op": "gte", "value": 8.0}]}',
            )
    finally:
        await engine.dispose()

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        screen = await cycles_joinable(engine, student.enrollment_id)
    finally:
        await engine.dispose()

    entry = cast(list[dict[str, object]], screen["cycles"])[0]
    reasons = cast(list[dict[str, object]], entry["reasons"])
    assert entry["can_join"] is False
    assert screen["profile_complete"] is False
    # The undeclared profile and the failing rule are both surfaced at once.
    assert {reason["code"] for reason in reasons} == {
        "profile_incomplete",
        "join_rule_failed",
    }


@pytest.mark.asyncio
async def test_CYC3_a_ready_student_sees_a_joinable_cycle() -> None:
    engine = _engine()
    try:
        async with engine.begin() as connection:
            await seed_admin(connection)
            program_id, branch_id = await seed_taxonomy(connection)
            student = await seed_person(connection, email="asha@example.edu")
            await seed_complete_profile(
                connection, student, program_id=program_id, branch_id=branch_id
            )
            await seed_cycle(connection, kind="open")
    finally:
        await engine.dispose()

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        screen = await cycles_joinable(engine, student.enrollment_id)
    finally:
        await engine.dispose()

    entry = cast(list[dict[str, object]], screen["cycles"])[0]
    assert screen["profile_complete"] is True
    assert entry["can_join"] is True
    assert entry["reasons"] == []
    assert entry["requires_approval"] is False


@pytest.mark.asyncio
async def test_INT2_joinable_screen_honours_the_student_cycle_window_override() -> None:
    engine = _engine()
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            program_id, branch_id = await seed_taxonomy(connection)
            student = await seed_person(connection, email="late@example.edu")
            await seed_complete_profile(
                connection,
                student,
                program_id=program_id,
                branch_id=branch_id,
            )
            cycle_id = await seed_cycle(connection, registration_open=False)
    finally:
        await engine.dispose()

    read = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        before = await cycles_joinable(read, student.enrollment_id)
    finally:
        await read.dispose()
    entry = cast("list[dict[str, object]]", before["cycles"])[0]
    assert entry["can_join"] is False
    assert [
        row["code"] for row in cast("list[dict[str, object]]", entry["reasons"])
    ] == ["registration_closed"]

    engine = _engine()
    try:
        async with engine.begin() as connection:
            await grant(
                connection,
                domain=RuleDomain.CYCLE_REGISTRATION_WINDOW,
                granted_by=admin.user_id,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
            )
    finally:
        await engine.dispose()
    read = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        after = await cycles_joinable(read, student.enrollment_id)
    finally:
        await read.dispose()
    entry = cast("list[dict[str, object]]", after["cycles"])[0]
    assert entry["can_join"] is True
    assert entry["reasons"] == []


@pytest.mark.asyncio
async def test_CYC3_a_withdrawn_member_gets_the_checklist_with_their_status() -> None:
    """A card offering "Register again" must say what still fails.

    the design review section 4.34 gives a withdrawn member the way back in, and the
    checks are the same ones a first join runs -- so the screen owes them the
    same list.  A pending member still gets a status and nothing else: CYC-3
    says they see a status screen, not a cycle they have not been admitted to.
    """
    engine = _engine()
    try:
        async with engine.begin() as connection:
            await seed_admin(connection)
            program_id, branch_id = await seed_taxonomy(connection)
            student = await seed_person(connection, email="asha@example.edu")
            resume_id = await seed_complete_profile(
                connection,
                student,
                program_id=program_id,
                branch_id=branch_id,
                cpi="7.00",
            )
            cycle_id = await seed_cycle(
                connection,
                kind="placement",
                join_rule='{"all": [{"field": "cpi", "op": "gte", "value": 8.0}]}',
            )
            await seed_membership(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status="withdrawn",
                resume_id=resume_id,
            )
    finally:
        await engine.dispose()

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        screen = await cycles_joinable(engine, student.enrollment_id)
    finally:
        await engine.dispose()

    entry = cast(list[dict[str, object]], screen["cycles"])[0]
    membership = cast(dict[str, object], entry["membership"])
    reasons = cast(list[dict[str, object]], entry["reasons"])

    assert membership["status"] == "withdrawn"
    # `can_join` is the join button's question, and a member is past that; the
    # re-request control reads the reasons instead.
    assert entry["can_join"] is False
    assert {reason["code"] for reason in reasons} == {"join_rule_failed"}
    assert entry["requires_approval"] is True


@pytest.mark.asyncio
async def test_CYC1_an_archived_cycle_never_appears_as_joinable() -> None:
    _admin, student, _cycle, _archived, _membership = await _fixture()

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        screen = await cycles_joinable(engine, student.enrollment_id)
    finally:
        await engine.dispose()

    assert len(cast(list[object], screen["cycles"])) == 1


@pytest.mark.asyncio
async def test_CYC1_an_inactive_cycle_is_listed_but_not_joinable() -> None:
    engine = _engine()
    try:
        async with engine.begin() as connection:
            await seed_admin(connection)
            program_id, branch_id = await seed_taxonomy(connection)
            student = await seed_person(connection, email="asha@example.edu")
            await seed_complete_profile(
                connection, student, program_id=program_id, branch_id=branch_id
            )
            await seed_cycle(connection, kind="open", is_active=False)
    finally:
        await engine.dispose()

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        screen = await cycles_joinable(engine, student.enrollment_id)
    finally:
        await engine.dispose()

    entry = cast(list[dict[str, object]], screen["cycles"])[0]
    reasons = cast(list[dict[str, object]], entry["reasons"])
    assert entry["can_join"] is False
    assert reasons[0]["code"] == "cycle_inactive"
