"""Bulk approval, rejection, and the re-request loop (Behavior CYC-3, RND-2)."""

from __future__ import annotations

import os
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.authz import Authorizer
from app.core.db import create_engine
from app.core.errors import (
    DUPLICATE_ROW,
    INVALID_TRANSITION,
    MEMBERSHIP_NOT_FOUND,
    UNMATCHED_IDENTIFIER,
    AuthorizationDenied,
    DomainRejection,
)
from app.core.plan import ActorContext, Preview, Result
from app.modules.cycles.queries import staff_cycle_approvals
from tests.cycles.conftest import (
    Person,
    build_test_executor,
    seed_admin,
    seed_complete_profile,
    seed_coordinator_link,
    seed_cycle,
    seed_membership,
    seed_person,
    seed_taxonomy,
)

pytestmark = pytest.mark.usefixtures("clean_cycles")


async def _queue(count: int = 2) -> tuple[Person, Person, UUID, list[tuple[Person, UUID]]]:
    """A cycle with a coordinator and `count` pending memberships."""
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            program_id, branch_id = await seed_taxonomy(connection)
            staff = await seed_person(connection, email="coord@example.edu")
            cycle_id = await seed_cycle(connection, kind="placement")
            await seed_coordinator_link(connection, cycle_id, staff.user_id)
            queue: list[tuple[Person, UUID]] = []
            for index in range(count):
                student = await seed_person(
                    connection, email=f"student{index}@example.edu"
                )
                resume_id = await seed_complete_profile(
                    connection,
                    student,
                    program_id=program_id,
                    branch_id=branch_id,
                    roll_number=f"2111000{index}",
                )
                membership_id = await seed_membership(
                    connection,
                    cycle_id=cycle_id,
                    enrollment_id=student.enrollment_id,
                    status="pending",
                    resume_id=resume_id,
                )
                queue.append((student, membership_id))
    finally:
        await engine.dispose()
    return admin, staff.coordinating(cycle_id), cycle_id, queue


async def _default_resume(membership_id: UUID) -> UUID:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            return cast(
                UUID,
                await connection.scalar(
                    sa.text(
                        "SELECT default_resume_id FROM cycle_memberships WHERE id = :id"
                    ),
                    {"id": membership_id},
                ),
            )
    finally:
        await engine.dispose()


async def _approve(
    actor: Person,
    cycle_id: UUID,
    rows: list[dict[str, str]],
    *,
    batch_key: str = "approvals-1",
    dry_run: bool = False,
) -> Preview | Result:
    executor, engine = build_test_executor()
    try:
        return await executor.run_bulk(
            "approve_memberships",
            cast(list[dict[str, object]], rows),
            batch_key,
            actor.actor,
            dry_run=dry_run,
            batch_fields={"cycle_id": cycle_id},
        )
    finally:
        await engine.dispose()


async def _statuses(cycle_id: UUID) -> dict[UUID, str]:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    sa.text(
                        "SELECT id, status FROM cycle_memberships WHERE cycle_id = :id"
                    ),
                    {"id": cycle_id},
                )
            ).mappings().all()
    finally:
        await engine.dispose()
    return {cast(UUID, row["id"]): str(row["status"]) for row in rows}


@pytest.mark.asyncio
async def test_CYC3_bulk_approval_by_selection_activates_every_row() -> None:
    _admin, coordinator, cycle_id, queue = await _queue()
    rows = [{"membership_id": str(membership_id)} for _, membership_id in queue]

    result = await _approve(coordinator, cycle_id, rows)

    assert isinstance(result, Result)
    reported = cast(list[dict[str, object]], result.summary["rows"])
    assert [row["status"] for row in reported] == ["applied", "applied"]
    assert set((await _statuses(cycle_id)).values()) == {"active"}


@pytest.mark.asyncio
async def test_CYC3_bulk_approval_by_pasted_rolls_and_emails_resolves_both() -> None:
    _admin, coordinator, cycle_id, queue = await _queue()
    rows = [{"identifier": "21110000"}, {"identifier": "STUDENT1@EXAMPLE.EDU"}]

    result = await _approve(coordinator, cycle_id, rows)

    assert isinstance(result, Result)
    reported = cast(list[dict[str, object]], result.summary["rows"])
    # Roll and email both resolve, case-insensitively.
    assert [row["status"] for row in reported] == ["applied", "applied"]
    assert set((await _statuses(cycle_id)).values()) == {"active"}


@pytest.mark.asyncio
async def test_CYC3_unmatched_identifiers_are_reported_per_row() -> None:
    _admin, coordinator, cycle_id, queue = await _queue()
    rows = [
        {"identifier": "21110000"},
        {"identifier": "nobody@example.edu"},
        {"membership_id": str(uuid4())},
    ]

    result = await _approve(coordinator, cycle_id, rows)

    assert isinstance(result, Result)
    reported = cast(list[dict[str, object]], result.summary["rows"])
    assert [row["status"] for row in reported] == ["applied", "error", "error"]
    assert {row["reason"] for row in reported if row["status"] == "error"} == {
        UNMATCHED_IDENTIFIER
    }


@pytest.mark.asyncio
async def test_CYC3_already_active_and_duplicate_rows_are_skipped_not_failed() -> None:
    _admin, coordinator, cycle_id, queue = await _queue()
    (_first, first_id), (_second, second_id) = queue
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "UPDATE cycle_memberships SET status = 'active' WHERE id = :id"
                ),
                {"id": first_id},
            )
    finally:
        await engine.dispose()

    result = await _approve(
        coordinator,
        cycle_id,
        [
            {"membership_id": str(first_id)},
            {"membership_id": str(second_id)},
            {"membership_id": str(second_id)},
        ],
    )

    assert isinstance(result, Result)
    reported = cast(list[dict[str, object]], result.summary["rows"])
    assert [row["status"] for row in reported] == ["skipped", "applied", "skipped"]
    assert reported[0]["reason"] == INVALID_TRANSITION
    assert reported[2]["reason"] == DUPLICATE_ROW


@pytest.mark.asyncio
async def test_CYC3_bulk_approval_preview_matches_execution() -> None:
    _admin, coordinator, cycle_id, queue = await _queue()
    rows = [{"membership_id": str(membership_id)} for _, membership_id in queue]

    preview = await _approve(coordinator, cycle_id, rows, dry_run=True)
    executed = await _approve(coordinator, cycle_id, rows)

    assert isinstance(preview, Preview) and isinstance(executed, Result)
    assert preview.events == executed.events
    assert preview.summary["rows"] == executed.summary["rows"]


@pytest.mark.asyncio
async def test_CYC3_approval_notifies_each_approved_student() -> None:
    _admin, coordinator, cycle_id, queue = await _queue()
    rows = [{"membership_id": str(membership_id)} for _, membership_id in queue]

    await _approve(coordinator, cycle_id, rows)

    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            jobs = (
                await connection.execute(
                    sa.text("SELECT args FROM procrastinate_jobs ORDER BY id")
                )
            ).scalars().all()
    finally:
        await engine.dispose()

    keys = [cast(dict[str, object], job)["event_key"] for job in jobs]
    assert keys == ["membership_approved", "membership_approved"]


@pytest.mark.asyncio
async def test_IDN3_a_wrong_cycle_coordinator_cannot_approve() -> None:
    _admin, coordinator, cycle_id, queue = await _queue()
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            other_cycle = await seed_cycle(connection, name="Other 2026")
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    stranger = coordinator.coordinating(other_cycle)
    spec = executor.registry.commands["approve_memberships"]
    rows = [{"membership_id": str(queue[0][1])}]
    try:
        # Stage one: the route authorizer reads cycle_id off the batch input,
        # which is only possible because run_bulk carries batch fields.
        with pytest.raises(AuthorizationDenied):
            Authorizer().check(
                spec,
                stranger.actor,
                spec.input_model.model_validate(
                    {
                        "cycle_id": str(cycle_id),
                        "rows": rows,
                        "batch_key": "wrong-cycle",
                    }
                ),
            )
        # Stage two: even reaching the executor, check_scope denies -- and
        # run_bulk surfaces the denial itself rather than wrapping it in an
        # interrupted batch, which would claim some rows applied and offer
        # coordinates to resume from (the design review section 4.23).
        with pytest.raises(AuthorizationDenied):
            await executor.run_bulk(
                "approve_memberships",
                cast(list[dict[str, object]], rows),
                "wrong-cycle",
                stranger.actor,
                batch_fields={"cycle_id": cycle_id},
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_CYC3_rejection_requires_a_reason_and_is_re_requestable() -> None:
    admin, _coordinator, cycle_id, queue = await _queue(count=1)
    student, membership_id = queue[0]

    executor, engine = build_test_executor()
    reject_model = executor.registry.commands["reject_membership"].input_model
    try:
        with pytest.raises(ValueError):
            reject_model.model_validate(
                {
                    "cycle_id": str(cycle_id),
                    "membership_id": str(membership_id),
                    "reason": "   ",
                }
            )
        rejected = await executor.run(
            "reject_membership",
            reject_model.model_validate(
                {
                    "cycle_id": str(cycle_id),
                    "membership_id": str(membership_id),
                    "reason": "Incomplete documents",
                }
            ),
            admin.actor,
        )
        # Re-entry re-runs every join check (the design review section 4.34), so it
        # carries the consent and the resume choice a first join carries.
        resume_id = await _default_resume(membership_id)
        rerequested = await executor.run(
            "rerequest_membership",
            executor.registry.commands[
                "rerequest_membership"
            ].input_model.model_validate(
                {
                    "cycle_id": str(cycle_id),
                    "enrollment_id": str(student.enrollment_id),
                    "default_resume_id": str(resume_id),
                    "consent": True,
                }
            ),
            student.actor,
        )
        # A second rejection of a now-pending row is legal again; rejecting an
        # already-rejected one is not.
        await executor.run(
            "reject_membership",
            reject_model.model_validate(
                {
                    "cycle_id": str(cycle_id),
                    "membership_id": str(membership_id),
                    "reason": "Still incomplete",
                }
            ),
            admin.actor,
        )
        with pytest.raises(DomainRejection) as error:
            await executor.run(
                "reject_membership",
                reject_model.model_validate(
                    {
                        "cycle_id": str(cycle_id),
                        "membership_id": str(membership_id),
                        "reason": "Once more",
                    }
                ),
                admin.actor,
            )
    finally:
        await engine.dispose()

    assert isinstance(rejected, Result) and rejected.summary["status"] == "rejected"
    assert isinstance(rerequested, Result) and rerequested.summary["status"] == "pending"
    assert [reason.code for reason in error.value.rejection.reasons] == [
        INVALID_TRANSITION
    ]


@pytest.mark.asyncio
async def test_CYC3_rejection_carries_the_reason_to_the_student() -> None:
    admin, _coordinator, cycle_id, queue = await _queue(count=1)
    _student, membership_id = queue[0]

    executor, engine = build_test_executor()
    model = executor.registry.commands["reject_membership"].input_model
    try:
        await executor.run(
            "reject_membership",
            model.model_validate(
                {
                    "cycle_id": str(cycle_id),
                    "membership_id": str(membership_id),
                    "reason": "Missing transcript",
                }
            ),
            admin.actor,
        )
    finally:
        await engine.dispose()

    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    sa.text("SELECT * FROM cycle_memberships WHERE id = :id"),
                    {"id": membership_id},
                )
            ).mappings().one()
            args = cast(
                dict[str, object],
                await connection.scalar(
                    sa.text("SELECT args FROM procrastinate_jobs ORDER BY id LIMIT 1")
                ),
            )
    finally:
        await engine.dispose()

    assert row["rejection_reason"] == "Missing transcript"
    assert row["decided_by"] == admin.user_id
    assert row["decided_at"] is not None
    assert args["event_key"] == "membership_rejected"
    assert cast(dict[str, object], args["context"])["reason"] == "Missing transcript"


@pytest.mark.asyncio
async def test_CYC3_rejecting_a_membership_from_another_cycle_is_not_found() -> None:
    admin, _coordinator, cycle_id, queue = await _queue(count=1)
    _student, membership_id = queue[0]
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            other_cycle = await seed_cycle(connection, name="Other 2026")
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    model = executor.registry.commands["reject_membership"].input_model
    try:
        with pytest.raises(DomainRejection) as error:
            await executor.run(
                "reject_membership",
                model.model_validate(
                    {
                        "cycle_id": str(other_cycle),
                        "membership_id": str(membership_id),
                        "reason": "Wrong cycle",
                    }
                ),
                admin.actor,
            )
    finally:
        await engine.dispose()

    assert [reason.code for reason in error.value.rejection.reasons] == [
        MEMBERSHIP_NOT_FOUND
    ]


@pytest.mark.asyncio
async def test_ANA3_outcome_tags_are_set_and_cleared() -> None:
    admin, _coordinator, cycle_id, queue = await _queue(count=1)
    _student, membership_id = queue[0]

    executor, engine = build_test_executor()
    model = executor.registry.commands["set_outcome_tag"].input_model
    try:
        tagged = await executor.run(
            "set_outcome_tag",
            model.model_validate(
                {
                    "cycle_id": str(cycle_id),
                    "membership_id": str(membership_id),
                    "outcome_tag": "higher_studies",
                }
            ),
            admin.actor,
        )
        cleared = await executor.run(
            "set_outcome_tag",
            model.model_validate(
                {
                    "cycle_id": str(cycle_id),
                    "membership_id": str(membership_id),
                    "outcome_tag": None,
                }
            ),
            admin.actor,
        )
    finally:
        await engine.dispose()

    assert isinstance(tagged, Result)
    assert tagged.summary["outcome_tag"] == "higher_studies"
    assert isinstance(cleared, Result)
    assert cleared.summary["outcome_tag"] is None
    assert cleared.summary["changed"] is True


@pytest.mark.asyncio
async def test_ANA3_what_the_queue_offers_is_what_the_tag_command_allows() -> None:
    """the design review section 4.22: the row's control and the command agree.

    ANA-3's seeking-adjusted denominator is only as good as the tags somebody
    can actually set, so the failure that matters here is the quiet one -- a
    control that never appears for a coordinator who is allowed to use it.
    Four states, each asserted from both ends.
    """
    admin, coordinator, cycle_id, queue = await _queue(count=1)
    student, membership_id = queue[0]
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            other_cycle = await seed_cycle(connection, name="Other 2026")
            archived_cycle = await seed_cycle(
                connection, name="Placement 2024", archived=True
            )
            archived_membership = await seed_membership(
                connection,
                cycle_id=archived_cycle,
                enrollment_id=student.enrollment_id,
                status="active",
            )
    finally:
        await engine.dispose()

    async def offered(actor: ActorContext, cycle: UUID, status: str) -> bool:
        read = create_engine(os.environ["TEST_DATABASE_URL"])
        try:
            queue_body = await staff_cycle_approvals(read, actor, cycle, status=status)
        finally:
            await read.dispose()
        assert queue_body is not None
        rows = cast("list[dict[str, object]]", queue_body["rows"])
        assert rows, "the fixture seeds a row in every state under test"
        actions = cast("dict[str, dict[str, object]]", rows[0]["actions"])
        return bool(actions["set_outcome_tag"]["allowed"])

    async def allowed(actor: ActorContext, cycle: UUID, membership: UUID) -> bool:
        executor, write = build_test_executor()
        spec = executor.registry.commands["set_outcome_tag"]
        input_value = spec.input_model.model_validate(
            {
                "cycle_id": str(cycle),
                "membership_id": str(membership),
                "outcome_tag": "not_seeking",
            }
        )
        try:
            await executor.run("set_outcome_tag", input_value, actor)
        except (AuthorizationDenied, DomainRejection):
            return False
        finally:
            await write.dispose()
        return True

    in_cycle = coordinator.coordinating(cycle_id)
    stranger = coordinator.coordinating(other_cycle)

    # 1. An administrator, anywhere.
    assert await offered(admin.actor, cycle_id, "pending") is True
    assert await allowed(admin.actor, cycle_id, membership_id) is True

    # 2. The cycle's own coordinator.
    assert await offered(in_cycle.actor, cycle_id, "pending") is True
    assert await allowed(in_cycle.actor, cycle_id, membership_id) is True

    # 3. A coordinator of some other cycle sees the row and no control.
    assert await offered(stranger.actor, cycle_id, "pending") is False
    assert await allowed(stranger.actor, cycle_id, membership_id) is False

    # 4. An archived season is read-only for every cycle-scoped command, so
    #    even an administrator is offered nothing (CYC-1).
    assert await offered(admin.actor, archived_cycle, "active") is False
    assert await allowed(admin.actor, archived_cycle, archived_membership) is False


@pytest.mark.asyncio
async def test_CYC3_what_the_roster_offers_is_what_the_exit_commands_allow() -> None:
    """the design review section 4.22, for the two exits that had no surface at all.

    The tag control's own proof (above) covers scope. These two add the third
    answer the exits have and the tag does not: the CYC-3 transition table,
    which allows `remove` only from `active` and `restore` only from
    `withdrawn` or `removed`. Every combination is asserted from both ends,
    because the failure that matters is the quiet one -- a control that never
    appears for a coordinator entitled to use it, or one that appears and is
    then refused by the executor that was asked to run it.
    """
    admin, coordinator, cycle_id, queue = await _queue(count=1)
    student, _pending_membership = queue[0]
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            other_cycle = await seed_cycle(connection, name="Other 2026")
            archived_cycle = await seed_cycle(
                connection, name="Placement 2024", archived=True
            )
            await seed_membership(
                connection,
                cycle_id=archived_cycle,
                enrollment_id=student.enrollment_id,
                status="active",
            )
            # One membership per status the roster can hold, each its own
            # student so no row masks another. The taxonomy `_queue` already
            # seeded is reused: its names are unique by constraint.
            program_id = cast(
                UUID, await connection.scalar(sa.text("SELECT id FROM programs LIMIT 1"))
            )
            branch_id = cast(
                UUID, await connection.scalar(sa.text("SELECT id FROM branches LIMIT 1"))
            )
            by_status: dict[str, UUID] = {}
            for index, status in enumerate(("active", "withdrawn", "removed")):
                person = await seed_person(
                    connection, email=f"{status}@example.edu"
                )
                await seed_complete_profile(
                    connection,
                    person,
                    program_id=program_id,
                    branch_id=branch_id,
                    roll_number=f"2112000{index}",
                )
                by_status[status] = await seed_membership(
                    connection,
                    cycle_id=cycle_id,
                    enrollment_id=person.enrollment_id,
                    status=status,
                )
    finally:
        await engine.dispose()

    async def offered(
        actor: ActorContext, cycle: UUID, status: str, command: str
    ) -> bool:
        read = create_engine(os.environ["TEST_DATABASE_URL"])
        try:
            body = await staff_cycle_approvals(read, actor, cycle, status=status)
        finally:
            await read.dispose()
        assert body is not None
        rows = cast("list[dict[str, object]]", body["rows"])
        assert rows, f"the fixture seeds a {status} membership"
        actions = cast("dict[str, dict[str, object]]", rows[0]["actions"])
        return bool(actions[command]["allowed"])

    async def allowed(
        actor: ActorContext, cycle: UUID, membership: UUID, command: str
    ) -> bool:
        executor, write = build_test_executor()
        spec = executor.registry.commands[command]
        payload: dict[str, object] = {
            "cycle_id": str(cycle),
            "membership_id": str(membership),
        }
        if command == "remove_membership":
            payload["reason"] = "Left the institute"
        try:
            await executor.run(command, spec.input_model.model_validate(payload), actor)
        except (AuthorizationDenied, DomainRejection):
            return False
        finally:
            await write.dispose()
        return True

    in_cycle = coordinator.coordinating(cycle_id)
    stranger = coordinator.coordinating(other_cycle)

    # 1. The transition table, from both ends: remove needs active, restore
    #    needs withdrawn or removed, and neither touches a pending row.
    for status, removable, restorable in (
        ("pending", False, False),
        ("active", True, False),
        ("withdrawn", False, True),
        ("removed", False, True),
    ):
        assert await offered(admin.actor, cycle_id, status, "remove_membership") is removable
        assert await offered(admin.actor, cycle_id, status, "restore_membership") is restorable

    # 2. And the executor agrees for each legal one.
    assert await allowed(admin.actor, cycle_id, by_status["active"], "remove_membership")
    assert await allowed(
        in_cycle.actor, cycle_id, by_status["withdrawn"], "restore_membership"
    )
    assert await allowed(
        admin.actor, cycle_id, by_status["removed"], "restore_membership"
    )

    # 3. A coordinator of some other cycle sees the row and no control.
    assert await offered(stranger.actor, cycle_id, "active", "remove_membership") is False
    assert (
        await allowed(
            stranger.actor, cycle_id, by_status["active"], "remove_membership"
        )
        is False
    )

    # 4. An archived season is read-only for every cycle-scoped command (CYC-1).
    assert await offered(admin.actor, archived_cycle, "active", "remove_membership") is False
    assert await offered(admin.actor, archived_cycle, "active", "restore_membership") is False
