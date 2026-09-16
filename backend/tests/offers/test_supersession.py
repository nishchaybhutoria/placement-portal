"""Moving a student's single placement in one transaction (OFR-3/OFR-5, DER-1)."""

from __future__ import annotations

import os
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import (
    CYCLE_ARCHIVED,
    INVALID_TRANSITION,
    STALE_VIEW,
    DomainRejection,
)
from app.core.plan import ActorContext, Preview, Result
from tests.offers.conftest import (
    build_test_executor,
    seed_admin,
    seed_application,
    seed_cycle,
    seed_external_offer,
    seed_job,
    seed_person,
    seed_portal_offer,
)

pytestmark = pytest.mark.asyncio


async def _replace(
    actor: ActorContext, payload: dict[str, object], *, dry_run: bool = False
) -> Preview | Result:
    executor, engine = build_test_executor()
    spec = executor.registry.commands["replace_placement"]
    try:
        return await executor.run(
            "replace_placement",
            spec.input_model.model_validate(payload),
            actor,
            dry_run=dry_run,
        )
    finally:
        await engine.dispose()


def _side(result: Result, key: str) -> dict[str, object]:
    return cast("dict[str, object]", result.summary[key])


async def _accepted_placements(enrollment_id: UUID) -> int:
    """DER-1's own question: how many accepted placements does this student hold?"""
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            portal = await connection.scalar(
                sa.text(
                    "SELECT count(*) FROM offers o "
                    "JOIN applications a ON a.id = o.application_id "
                    "JOIN jobs j ON j.id = a.job_id "
                    "WHERE a.enrollment_id = :id AND o.response = 'accepted' "
                    "AND o.terminated_at IS NULL AND j.outcome = 'placement'"
                ),
                {"id": enrollment_id},
            )
            external = await connection.scalar(
                sa.text(
                    "SELECT count(*) FROM external_offers WHERE enrollment_id = :id "
                    "AND status = 'accepted' AND outcome = 'placement'"
                ),
                {"id": enrollment_id},
            )
    finally:
        await engine.dispose()
    return int(cast(int, portal)) + int(cast(int, external))


class _World:
    """One student, an accepted portal placement, and a live alternative of each kind."""

    def __init__(self) -> None:
        self.admin: ActorContext
        self.enrollment_id: UUID
        self.held_offer: UUID
        self.open_offer: UUID
        self.external_offer: UUID
        self.open_cycle: UUID
        self.held_cycle: UUID
        self.company: UUID


async def _world(*, open_cycle_archived: bool = False) -> _World:
    world = _World()
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="placed@example.edu")
            held_cycle = await seed_cycle(connection, name="Placements 2027")
            open_cycle = await seed_cycle(connection, name="Rolling roles", kind="open")

            held_job = await seed_job(connection, cycle_id=held_cycle, title="First role")
            held_application, _ = await seed_application(
                connection,
                cycle_id=held_cycle,
                enrollment_id=student.enrollment_id,
                status="accepted",
                job_id=held_job,
            )
            held_offer = await seed_portal_offer(
                connection, application_id=held_application, response="accepted"
            )

            open_job = await seed_job(
                connection,
                cycle_id=open_cycle,
                title="Rolling role",
                with_deadline=False,
            )
            open_application, _ = await seed_application(
                connection,
                cycle_id=open_cycle,
                enrollment_id=student.enrollment_id,
                status="offered",
                job_id=open_job,
            )
            open_offer = await seed_portal_offer(
                connection, application_id=open_application
            )

            company = uuid4()
            await connection.execute(
                sa.text("INSERT INTO companies (id, name) VALUES (:id, :name)"),
                {"id": company, "name": f"External Co {company}"},
            )
            external_offer = await seed_external_offer(
                connection,
                enrollment_id=student.enrollment_id,
                company_id=company,
                created_by=admin.user_id,
                source="ppo",
            )
            if open_cycle_archived:
                await connection.execute(
                    sa.text("UPDATE cycles SET archived_at = now() WHERE id = :id"),
                    {"id": open_cycle},
                )
    finally:
        await engine.dispose()

    world.admin = admin.actor
    world.enrollment_id = student.enrollment_id
    world.held_offer = held_offer
    world.open_offer = open_offer
    world.external_offer = external_offer
    world.open_cycle = open_cycle
    world.held_cycle = held_cycle
    world.company = company
    return world


async def test_OFR5_replacing_a_portal_placement_with_an_open_cycle_offer() -> None:
    """The reported case: placed already, then chosen for a rolling role."""
    world = await _world()

    result = await _replace(
        world.admin,
        {
            "enrollment_id": str(world.enrollment_id),
            "current_offer_id": str(world.held_offer),
            "new_offer_id": str(world.open_offer),
            "reason": "Student accepted the rolling role instead",
        },
    )

    assert isinstance(result, Result)
    assert _side(result, "from_placement")["kind"] == "portal"
    assert _side(result, "to_placement")["kind"] == "portal"
    # The whole point: one placement in, one placement out, never two and never
    # a window with none.
    assert await _accepted_placements(world.enrollment_id) == 1

    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    sa.text(
                        "SELECT id, response, terminated_at, termination_kind "
                        "FROM offers WHERE id = ANY(:ids)"
                    ),
                    {"ids": [world.held_offer, world.open_offer]},
                )
            ).mappings().all()
    finally:
        await engine.dispose()
    state = {row["id"]: row for row in rows}
    assert state[world.held_offer]["terminated_at"] is not None
    assert state[world.held_offer]["termination_kind"] == "admin_correction"
    assert state[world.open_offer]["response"] == "accepted"
    assert state[world.open_offer]["terminated_at"] is None


async def test_OFR5_replacing_a_portal_placement_with_an_unattached_ppo() -> None:
    """A PPO is a placement like any other, and needs no cycle to become one."""
    world = await _world()

    result = await _replace(
        world.admin,
        {
            "enrollment_id": str(world.enrollment_id),
            "current_offer_id": str(world.held_offer),
            "new_external_offer_id": str(world.external_offer),
            "reason": "PPO confirmed",
        },
    )

    assert isinstance(result, Result)
    assert _side(result, "to_placement")["kind"] == "external"
    assert await _accepted_placements(world.enrollment_id) == 1


async def test_OFR5_replacing_an_accepted_ppo_with_a_portal_offer() -> None:
    """And the other direction, which is the asymmetry this command removes."""
    world = await _world()
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            # Make the PPO the held placement instead of the portal offer.
            await connection.execute(
                sa.text(
                    "UPDATE external_offers SET status = 'accepted', "
                    "responded_on = CURRENT_DATE WHERE id = :id"
                ),
                {"id": world.external_offer},
            )
            await connection.execute(
                sa.text(
                    "UPDATE offers SET response = NULL, responded_at = NULL "
                    "WHERE id = :id"
                ),
                {"id": world.held_offer},
            )
            await connection.execute(
                sa.text(
                    "UPDATE applications SET status = 'offered' WHERE id = "
                    "(SELECT application_id FROM offers WHERE id = :id)"
                ),
                {"id": world.held_offer},
            )
    finally:
        await engine.dispose()

    result = await _replace(
        world.admin,
        {
            "enrollment_id": str(world.enrollment_id),
            "current_external_offer_id": str(world.external_offer),
            "new_offer_id": str(world.held_offer),
            "reason": "PPO withdrawn; portal offer stands",
        },
    )

    assert isinstance(result, Result)
    assert _side(result, "from_placement")["kind"] == "external"
    assert await _accepted_placements(world.enrollment_id) == 1


async def test_OFR5_replacement_preview_matches_execution() -> None:
    world = await _world()
    payload: dict[str, object] = {
        "enrollment_id": str(world.enrollment_id),
        "current_offer_id": str(world.held_offer),
        "new_offer_id": str(world.open_offer),
        "reason": "Parity",
    }

    preview = await _replace(world.admin, payload, dry_run=True)
    executed = await _replace(world.admin, payload)

    assert isinstance(preview, Preview) and isinstance(executed, Result)
    assert preview.events == executed.events
    assert preview.summary == executed.summary


async def test_OFR5_the_outgoing_and_incoming_events_name_each_other() -> None:
    """Two months later, the audit trail still reads as one decision."""
    world = await _world()

    await _replace(
        world.admin,
        {
            "enrollment_id": str(world.enrollment_id),
            "current_offer_id": str(world.held_offer),
            "new_offer_id": str(world.open_offer),
            "reason": "Linked pair",
        },
    )

    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            payloads = {
                str(row["event_type"]): dict(row["payload"] or {})
                for row in (
                    await connection.execute(
                        sa.text(
                            "SELECT ev.event_type, ev.payload FROM application_events ev "
                            "JOIN applications a ON a.id = ev.application_id "
                            "WHERE a.enrollment_id = :id AND ev.event_type = ANY("
                            "ARRAY['offer_terminated','accepted']::event_type_t[])"
                        ),
                        {"id": world.enrollment_id},
                    )
                ).mappings().all()
            }
            audit = (
                await connection.execute(
                    sa.text(
                        "SELECT details FROM audit_log WHERE action = 'replace_placement'"
                    )
                )
            ).mappings().all()
    finally:
        await engine.dispose()

    assert payloads["offer_terminated"]["superseded_by_offer_id"] == str(world.open_offer)
    assert payloads["accepted"]["supersedes_offer_id"] == str(world.held_offer)
    assert len(audit) == 1
    details = cast("dict[str, object]", audit[0]["details"])
    assert details["operation"] == "replace_placement"
    assert details["reason"] == "Linked pair"


async def test_OFR5_a_restoration_the_new_placement_would_undo_is_refused() -> None:
    """A restore and its undo do not both belong in one transaction.

    The student is placed before and after, so an application the outgoing
    acceptance withdrew for competing with it still competes. Restoring it
    would write a reinstatement and an auto-withdrawal into the same commit and
    leave the record reading as though something had happened.
    """
    world = await _world()
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            # A dedicated-cycle placement application the held offer's
            # acceptance auto-withdrew, exactly as OFR-3 would have left it.
            other_cycle = await seed_cycle(connection, name="Placements elsewhere")
            other_job = await seed_job(
                connection, cycle_id=other_cycle, title="Competing role"
            )
            competing, _ = await seed_application(
                connection,
                cycle_id=other_cycle,
                enrollment_id=world.enrollment_id,
                status="auto_withdrawn",
                job_id=other_job,
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO application_events (application_id, event_type, "
                    "from_status, to_status, reason, payload) VALUES "
                    "(:application, 'auto_withdrawn', 'in_progress', 'auto_withdrawn', "
                    "'Accepted another offer', CAST(:payload AS jsonb))"
                ),
                {
                    "application": competing,
                    "payload": (
                        '{"trigger": "acceptance", "acceptance_offer_id": "'
                        + str(world.held_offer)
                        + '"}'
                    ),
                },
            )
    finally:
        await engine.dispose()

    with pytest.raises(DomainRejection) as error:
        await _replace(
            world.admin,
            {
                "enrollment_id": str(world.enrollment_id),
                "current_offer_id": str(world.held_offer),
                "new_offer_id": str(world.open_offer),
                "reason": "Restoring what cannot come back",
                "restore": [{"application_id": str(competing)}],
            },
        )

    reasons = error.value.rejection.reasons
    assert [reason.code for reason in reasons] == [INVALID_TRANSITION]
    assert reasons[0].path == f"restore.{competing}"
    assert await _accepted_placements(world.enrollment_id) == 1


async def test_OFR5_an_open_cycle_restoration_survives_the_new_acceptance() -> None:
    """What the incoming acceptance does not reach is restorable as usual."""
    world = await _world()
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            # A rolling application withdrawn by an older acceptance -- the
            # state a database carries from before open cycles were exempt.
            rolling_job = await seed_job(
                connection,
                cycle_id=world.open_cycle,
                title="Another rolling role",
                with_deadline=False,
            )
            rolling, _ = await seed_application(
                connection,
                cycle_id=world.open_cycle,
                enrollment_id=world.enrollment_id,
                status="auto_withdrawn",
                job_id=rolling_job,
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO application_events (application_id, event_type, "
                    "from_status, to_status, reason, payload) VALUES "
                    "(:application, 'auto_withdrawn', 'in_progress', 'auto_withdrawn', "
                    "'Accepted another offer', CAST(:payload AS jsonb))"
                ),
                {
                    "application": rolling,
                    "payload": (
                        '{"trigger": "acceptance", "acceptance_offer_id": "'
                        + str(world.held_offer)
                        + '"}'
                    ),
                },
            )
    finally:
        await engine.dispose()

    result = await _replace(
        world.admin,
        {
            "enrollment_id": str(world.enrollment_id),
            "current_offer_id": str(world.held_offer),
            "new_external_offer_id": str(world.external_offer),
            "reason": "Restoring the rolling application",
            "restore": [{"application_id": str(rolling)}],
        },
    )

    assert isinstance(result, Result)
    restored = cast("list[dict[str, object]]", result.summary["restored"])
    assert [row["application_id"] for row in restored] == [str(rolling)]

    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            status = await connection.scalar(
                sa.text("SELECT status FROM applications WHERE id = :id"),
                {"id": rolling},
            )
    finally:
        await engine.dispose()
    assert str(status) == "in_progress"
    assert await _accepted_placements(world.enrollment_id) == 1


async def test_OFR5_a_stale_outgoing_offer_is_rejected_not_silently_corrected() -> None:
    """The named placement is the compare-and-set, so a moved one is a rejection."""
    world = await _world()

    with pytest.raises(DomainRejection) as error:
        await _replace(
            world.admin,
            {
                "enrollment_id": str(world.enrollment_id),
                # Live, but never accepted: not this student's placement.
                "current_offer_id": str(world.open_offer),
                "new_offer_id": str(world.held_offer),
                "reason": "Stale",
            },
        )

    assert [reason.code for reason in error.value.rejection.reasons] == [STALE_VIEW]
    assert await _accepted_placements(world.enrollment_id) == 1


async def test_OFR5_an_archived_cycle_blocks_the_incoming_offer_only() -> None:
    """Last season stays read-only for new work, and correctable for old work.

    A placement recorded in an archived cycle is exactly the one most likely to
    need correcting, so the outgoing side is deliberately exempt. Nothing new is
    written into an archived cycle, which is what the rule is actually for.
    """
    world = await _world(open_cycle_archived=True)

    with pytest.raises(DomainRejection) as error:
        await _replace(
            world.admin,
            {
                "enrollment_id": str(world.enrollment_id),
                "current_offer_id": str(world.held_offer),
                "new_offer_id": str(world.open_offer),
                "reason": "Into an archived cycle",
            },
        )
    assert [reason.code for reason in error.value.rejection.reasons] == [CYCLE_ARCHIVED]

    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text("UPDATE cycles SET archived_at = now() WHERE id = :id"),
                {"id": world.held_cycle},
            )
    finally:
        await engine.dispose()

    # The outgoing offer now lives in an archived cycle, and the replacement
    # still goes through -- which `terminate_offer` alone cannot do at all.
    result = await _replace(
        world.admin,
        {
            "enrollment_id": str(world.enrollment_id),
            "current_offer_id": str(world.held_offer),
            "new_external_offer_id": str(world.external_offer),
            "reason": "Correcting an archived season's placement",
        },
    )
    assert isinstance(result, Result)
    assert await _accepted_placements(world.enrollment_id) == 1
