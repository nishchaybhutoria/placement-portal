"""The nightly consistency pass (Behavior section 16, LLD section 12).

One test body, parametrized over ``checker.INVARIANTS`` itself: plant the
corruption that invariant forbids, run the real command through the real
executor, and require a finding that names the invariant, the subject, and a
compensating command that *actually runs*.  The last part is the one that keeps
the screen honest -- a suggested fix nobody has ever dry-run is a button that
fails the first time an administrator is relying on it.

Parametrizing over the catalog rather than over a list written here makes the
suite a ratchet: an invariant added without a corruption fixture fails
immediately, with a message saying what to write.
"""

from __future__ import annotations

import json
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.errors import DomainRejection
from app.core.plan import ActorContext, Preview, Result
from app.domain.shared import RuleDomain
from app.modules.admin.checker import INVARIANTS, fix_payload
from app.modules.admin.commands import RunConsistencyCheckerInput
from tests.admin.conftest import (
    CheckerWorld,
    Corruption,
    build_checker_world,
    build_test_executor,
    finding_rows,
    past,
    read_engine,
    scalar,
    seed_application,
    seed_event,
    seed_offer,
    seed_round_state,
    subject_of,
    write_engine,
)
from tests.overrides.conftest import grant

pytestmark = pytest.mark.asyncio


async def _extra_job(
    connection: AsyncConnection, world: CheckerWorld, title: str
) -> UUID:
    """A second job in the placement cycle.

    Planting one corruption must not plant another by accident: reusing the
    world's job would give the student two active applications to it, which is
    a *different* invariant's violation and would make each test's finding count
    depend on the others.
    """
    job_id = await connection.scalar(
        sa.text(
            "INSERT INTO jobs (id, cycle_id, company_id, outcome, title, description, "
            "is_published, application_deadline) VALUES (gen_random_uuid(), :cycle, "
            ":company, 'placement', :title, 'Planted', true, "
            "now() + interval '30 days') RETURNING id"
        ),
        {"cycle": world.placement_cycle, "company": world.company_id, "title": title},
    )
    return cast_uuid(job_id)


async def _job_for(
    connection: AsyncConnection,
    world: CheckerWorld,
    *,
    cycle_id: UUID,
    outcome: str,
    title: str,
) -> UUID:
    job_id = await connection.scalar(
        sa.text(
            "INSERT INTO jobs (id, cycle_id, company_id, outcome, title, description, "
            "is_published, application_deadline) VALUES (gen_random_uuid(), :cycle, "
            ":company, CAST(:outcome AS outcome_t), :title, 'Checker proof', true, "
            "NULL) RETURNING id"
        ),
        {
            "cycle": cycle_id,
            "company": world.company_id,
            "outcome": outcome,
            "title": title,
        },
    )
    return cast_uuid(job_id)


async def _accepted_portal(
    connection: AsyncConnection,
    *,
    job_id: UUID,
    enrollment_id: UUID,
    applied_override_ids: tuple[UUID, ...] = (),
) -> tuple[UUID, UUID]:
    application_id = await seed_application(
        connection,
        job_id=job_id,
        enrollment_id=enrollment_id,
        status="accepted",
    )
    offer_id = await seed_offer(
        connection, application_id=application_id, response="accepted"
    )
    await seed_event(
        connection,
        application_id=application_id,
        event_type="accepted",
        to_status="accepted",
        payload=json.dumps(
            {
                "offer_id": str(offer_id),
                "applied_override_ids": [str(value) for value in applied_override_ids],
            }
        ),
    )
    return application_id, offer_id


async def _status_drift(
    connection: AsyncConnection, world: CheckerWorld
) -> dict[str, object]:
    await seed_event(
        connection,
        application_id=world.application_id,
        event_type="eliminated",
        from_status="in_progress",
        to_status="rejected",
    )
    return {
        "application_id": str(world.application_id),
        "stored_status": "in_progress",
        "expected_status": "rejected",
    }


async def _duplicate_application(
    connection: AsyncConnection, world: CheckerWorld
) -> dict[str, object]:
    duplicate = await seed_application(
        connection,
        job_id=world.job_id,
        enrollment_id=world.student.enrollment_id,
        status="in_progress",
    )
    return {
        "job_id": str(world.job_id),
        "enrollment_id": str(world.student.enrollment_id),
        "duplicate_application_id": str(max(duplicate, world.application_id, key=str)),
    }


async def _second_current_enrollment(
    connection: AsyncConnection, world: CheckerWorld
) -> dict[str, object]:
    await connection.execute(
        sa.text(
            "INSERT INTO enrollments (id, user_id, is_current) "
            "VALUES (gen_random_uuid(), :user_id, true)"
        ),
        {"user_id": world.student.user_id},
    )
    return {"user_id": str(world.student.user_id)}


async def _duplicate_roll(
    connection: AsyncConnection, world: CheckerWorld
) -> dict[str, object]:
    roll = await connection.scalar(
        sa.text("SELECT roll_number FROM enrollments WHERE id = :id"),
        {"id": world.student.enrollment_id},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO users (id, email, full_name, role) "
            "VALUES (gen_random_uuid(), :email, 'Twin Student', 'student')"
        ),
        {"email": f"twin-{roll}@example.edu"},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO enrollments (id, user_id, is_current, roll_number) "
            "SELECT gen_random_uuid(), id, true, :roll FROM users WHERE email = :email"
        ),
        {"roll": roll, "email": f"twin-{roll}@example.edu"},
    )
    return {"roll_number": str(roll)}


async def _second_default_resume(
    connection: AsyncConnection, world: CheckerWorld
) -> dict[str, object]:
    await connection.execute(
        sa.text(
            "INSERT INTO resumes (id, enrollment_id, label, drive_url, is_default) "
            "VALUES (gen_random_uuid(), :enrollment_id, 'Second', :url, true)"
        ),
        {
            "enrollment_id": world.student.enrollment_id,
            "url": "https://drive.google.com/file/d/1SecondResume000000000000000000/view",
        },
    )
    return {"enrollment_id": str(world.student.enrollment_id)}


async def _second_primary_contact(
    connection: AsyncConnection, world: CheckerWorld
) -> dict[str, object]:
    await connection.execute(
        sa.text(
            "INSERT INTO company_contacts (id, company_id, name, email, is_primary) "
            "VALUES (gen_random_uuid(), :company_id, 'Second Primary', :email, true)"
        ),
        {"company_id": world.company_id, "email": "second.primary@example.com"},
    )
    return {"company_id": str(world.company_id)}


async def _over_cap(connection: AsyncConnection, world: CheckerWorld) -> dict[str, object]:
    """Two accepted offers in a cycle whose policy caps acceptance at one."""
    first = await seed_application(
        connection,
        job_id=world.internship_job_id,
        enrollment_id=world.student.enrollment_id,
        status="accepted",
    )
    await seed_offer(connection, application_id=first, response="accepted")
    second_job = await connection.scalar(
        sa.text(
            "INSERT INTO jobs (id, cycle_id, company_id, outcome, title, description, "
            "is_published, application_deadline) VALUES (gen_random_uuid(), :cycle, "
            ":company, 'internship', 'Second Intern', 'Planted', true, now() + interval "
            "'30 days') RETURNING id"
        ),
        {"cycle": world.internship_cycle, "company": world.company_id},
    )
    second = await seed_application(
        connection,
        job_id=cast_uuid(second_job),
        enrollment_id=world.student.enrollment_id,
        status="accepted",
    )
    await seed_offer(connection, application_id=second, response="accepted")
    return {
        "cycle_id": str(world.internship_cycle),
        "enrollment_id": str(world.student.enrollment_id),
        "accepted_count": 2,
        "cap": 1,
    }


async def _two_placements(
    connection: AsyncConnection, world: CheckerWorld
) -> dict[str, object]:
    """DER-1 allows one accepted placement offer per enrollment, portal-wide."""
    first = await seed_application(
        connection,
        job_id=await _extra_job(connection, world, "Accepted Placement"),
        enrollment_id=world.student.enrollment_id,
        status="accepted",
    )
    await seed_offer(connection, application_id=first, response="accepted")
    await connection.execute(
        sa.text(
            "INSERT INTO external_offers (id, enrollment_id, company_id, outcome, "
            "source, status, created_by) VALUES (gen_random_uuid(), :enrollment_id, "
            ":company_id, 'placement', 'off_campus', 'accepted', :admin)"
        ),
        {
            "enrollment_id": world.student.enrollment_id,
            "company_id": world.company_id,
            "admin": world.admin.user_id,
        },
    )
    return {
        "enrollment_id": str(world.student.enrollment_id),
        "accepted_count": 2,
    }


async def _accepted_without_offer(
    connection: AsyncConnection, world: CheckerWorld
) -> dict[str, object]:
    application_id = await seed_application(
        connection,
        job_id=await _extra_job(connection, world, "Terminated Acceptance"),
        enrollment_id=world.student.enrollment_id,
        status="accepted",
    )
    await seed_offer(
        connection, application_id=application_id, response="accepted", terminated=True
    )
    return {
        "application_id": str(application_id),
        "stored_status": "accepted",
        "expected_status": "offer_terminated",
    }


async def _orphan_open_offer(
    connection: AsyncConnection, world: CheckerWorld
) -> dict[str, object]:
    application_id = await seed_application(
        connection,
        job_id=await _extra_job(connection, world, "Orphan Offer"),
        enrollment_id=world.student.enrollment_id,
        status="rejected",
    )
    offer_id = await seed_offer(connection, application_id=application_id)
    return {
        "offer_id": str(offer_id),
        "application_id": str(application_id),
        "stored_status": "rejected",
        "expected_status": "offered",
    }


async def _unsupported_penalty(
    connection: AsyncConnection, world: CheckerWorld
) -> dict[str, object]:
    await connection.execute(
        sa.text(
            "INSERT INTO settings (key, value) VALUES "
            "('strikes_per_penalty', '2'::jsonb) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        )
    )
    penalty_id = await connection.scalar(
        sa.text(
            "INSERT INTO penalties (id, enrollment_id, reasons, from_strikes, is_active) "
            "VALUES (gen_random_uuid(), :enrollment_id, 'Converted from strikes', "
            "true, true) RETURNING id"
        ),
        {"enrollment_id": world.student.enrollment_id},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO strikes (id, enrollment_id, reason, source, is_active, "
            "consumed_by_penalty_id) VALUES (gen_random_uuid(), :enrollment_id, "
            "'Only support', 'manual', true, :penalty_id)"
        ),
        {"enrollment_id": world.student.enrollment_id, "penalty_id": penalty_id},
    )
    return {
        "penalty_id": str(cast_uuid(penalty_id)),
        "supporting_strikes": 1,
        "threshold": 2,
    }


async def _live_application_without_membership(
    connection: AsyncConnection, world: CheckerWorld
) -> dict[str, object]:
    await connection.execute(
        sa.text(
            "UPDATE cycle_memberships SET status = 'removed' WHERE id = :id"
        ),
        {"id": world.membership_id},
    )
    return {
        "application_id": str(world.application_id),
        "membership_id": str(world.membership_id),
        "membership_status": "removed",
    }


async def _broken_round_ledger(
    connection: AsyncConnection, world: CheckerWorld
) -> dict[str, object]:
    """A live application sitting in round 1 with a state for round 2 as well."""
    await seed_round_state(
        connection, application_id=world.application_id, round_id=world.rounds[1]
    )
    return {
        "application_id": str(world.application_id),
        "extra_states": 1,
    }


async def _mismatched_attachment(
    connection: AsyncConnection, world: CheckerWorld
) -> dict[str, object]:
    external_id = await connection.scalar(
        sa.text(
            "INSERT INTO external_offers (id, enrollment_id, company_id, outcome, "
            "source, status, attached_cycle_id, created_by) VALUES "
            "(gen_random_uuid(), :enrollment_id, :company_id, 'internship', 'ppo', "
            "'offered', :cycle_id, :admin) RETURNING id"
        ),
        {
            "enrollment_id": world.student.enrollment_id,
            "company_id": world.company_id,
            "cycle_id": world.placement_cycle,
            "admin": world.admin.user_id,
        },
    )
    return {
        "external_offer_id": str(cast_uuid(external_id)),
        "cycle_id": str(world.placement_cycle),
        "outcome": "internship",
        "cycle_kind": "placement",
    }


async def _missing_application_deadline(
    connection: AsyncConnection, world: CheckerWorld
) -> dict[str, object]:
    await connection.execute(
        sa.text("UPDATE jobs SET application_deadline = NULL WHERE id = :id"),
        {"id": world.job_id},
    )
    return {"job_id": str(world.job_id), "cycle_kind": "placement"}


async def _open_cycle_acceptance_deadline(
    connection: AsyncConnection, world: CheckerWorld
) -> dict[str, object]:
    await connection.execute(
        sa.text(
            "UPDATE jobs SET offer_acceptance_deadline = now() + interval '10 days' "
            "WHERE id = :id"
        ),
        {"id": world.open_job_id},
    )
    return {"job_id": str(world.open_job_id), "cycle_kind": "open"}


async def _override_credited_after_expiry(
    connection: AsyncConnection, world: CheckerWorld
) -> dict[str, object]:
    override_id = await connection.scalar(
        sa.text(
            "INSERT INTO overrides (id, rule_domain, allow, cycle_id, reason, "
            "granted_by, expires_at, is_active) VALUES (gen_random_uuid(), "
            "'application_deadline', true, :cycle_id, 'Late window', :admin, "
            ":expires_at, true) RETURNING id"
        ),
        {
            "cycle_id": world.placement_cycle,
            "admin": world.admin.user_id,
            "expires_at": past(days=2),
        },
    )
    await seed_event(
        connection,
        application_id=world.application_id,
        event_type="edited",
        to_status=None,
        payload=f'{{"applied_override_ids": ["{override_id}"]}}',
    )
    return {
        "override_id": str(cast_uuid(override_id)),
        "application_id": str(world.application_id),
    }


def cast_uuid(value: object) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


CORRUPTIONS: dict[str, Corruption] = {
    "application_status_matches_latest_event": Corruption(
        _status_drift, "force_transition"
    ),
    "one_active_application_per_pair": Corruption(
        _duplicate_application,
        "force_transition",
        drop_index="uq_applications_active_job_enrollment",
        # Delete the planted row precisely -- the one with no history -- so the
        # index can be rebuilt without taking the world's real application with it.
        cleanup=(
            "DELETE FROM applications a WHERE NOT EXISTS "
            "(SELECT 1 FROM application_round_states s WHERE s.application_id = a.id) "
            "AND NOT EXISTS "
            "(SELECT 1 FROM application_events e WHERE e.application_id = a.id) "
            "AND EXISTS (SELECT 1 FROM applications b WHERE b.job_id = a.job_id "
            "AND b.enrollment_id = a.enrollment_id AND b.id <> a.id "
            "AND b.status NOT IN ('withdrawn', 'auto_withdrawn'))",
        ),
    ),
    "one_current_enrollment_per_user": Corruption(
        _second_current_enrollment,
        "start_new_enrollment",
        drop_index="uq_enrollments_current_user_id",
        # The planted enrollment carries nothing; the real one carries a
        # profile, so "has no profile" identifies the row to remove.
        cleanup=(
            "DELETE FROM enrollments e WHERE e.is_current AND NOT EXISTS "
            "(SELECT 1 FROM profiles p WHERE p.enrollment_id = e.id) "
            "AND EXISTS (SELECT 1 FROM enrollments f WHERE f.user_id = e.user_id "
            "AND f.id <> e.id AND f.is_current)",
        ),
        fix_is_runnable=False,
    ),
    "one_current_roll_number": Corruption(
        _duplicate_roll,
        "admin_update_profile",
        drop_index="uq_enrollments_current_roll_number",
        cleanup=("DELETE FROM enrollments WHERE user_id IN "
                 "(SELECT id FROM users WHERE full_name = 'Twin Student')",
                 "DELETE FROM users WHERE full_name = 'Twin Student'"),
        fix_is_runnable=False,
    ),
    "one_default_resume_per_enrollment": Corruption(
        _second_default_resume,
        "set_default_resume",
        drop_index="uq_resumes_default_enrollment_id",
        cleanup=("DELETE FROM resumes WHERE label = 'Second'",),
        fix_is_runnable=False,
    ),
    "one_primary_contact_per_company": Corruption(
        _second_primary_contact,
        "contact_update",
        drop_index="uq_company_contacts_primary_company_id",
        cleanup=("DELETE FROM company_contacts WHERE name = 'Second Primary'",),
    ),
    "accepted_offers_within_cycle_cap": Corruption(_over_cap, "terminate_offer"),
    "one_accepted_placement_offer_globally": Corruption(
        _two_placements, "terminate_offer"
    ),
    "placement_derivation_matches_accepted_rows": Corruption(
        _accepted_without_offer, "force_transition"
    ),
    "no_open_offer_on_unoffered_application": Corruption(
        _orphan_open_offer, "force_transition"
    ),
    "converted_penalties_keep_their_strikes": Corruption(
        _unsupported_penalty, "revoke_penalty"
    ),
    "no_live_application_without_active_membership": Corruption(
        _live_application_without_membership, "restore_membership"
    ),
    "round_states_exist_up_to_current_round": Corruption(
        _broken_round_ledger, "reinstate_application", fix_is_runnable=False
    ),
    "external_attachments_match_cycle_kind": Corruption(
        _mismatched_attachment, "detach_external_offer"
    ),
    "dedicated_cycle_jobs_carry_an_application_deadline": Corruption(
        _missing_application_deadline, "update_job_basics", fix_is_runnable=False
    ),
    "open_cycle_jobs_carry_no_acceptance_deadline": Corruption(
        _open_cycle_acceptance_deadline, "update_job_basics", fix_is_runnable=False
    ),
    "no_override_credited_after_expiry": Corruption(
        _override_credited_after_expiry, "deactivate_override"
    ),
}

INVARIANT_IDS = [invariant.id for invariant in INVARIANTS]


def _corruption(invariant_id: str) -> Corruption:
    corruption = CORRUPTIONS.get(invariant_id)
    assert corruption is not None, (
        f"Invariant {invariant_id!r} has no corruption fixture. Add one to "
        "CORRUPTIONS in tests/admin/test_consistency_checker.py -- an invariant "
        "nobody has ever seen fail is an invariant whose query has never been "
        "proven to detect anything."
    )
    return corruption


async def _run_checker() -> Result:
    executor, _engine = build_test_executor()
    result = await executor.run(
        "run_consistency_checker",
        RunConsistencyCheckerInput(),
        ActorContext(principal_id="system", is_system=True),
    )
    assert isinstance(result, Result)
    return result


#: The definition of the index a corruption dropped, so it can be rebuilt
#: exactly as the migration wrote it.
_DROPPED: dict[str, str] = {}


async def _inject(
    corruption: Corruption, world: CheckerWorld
) -> dict[str, object]:
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            if corruption.drop_index is not None:
                definition = await connection.scalar(
                    sa.text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE schemaname = 'public' AND indexname = :name"
                    ),
                    {"name": corruption.drop_index},
                )
                assert definition is not None, (
                    f"{corruption.drop_index} is missing before this test planted "
                    "anything, which means an earlier test dropped it and never "
                    "put it back"
                )
                _DROPPED[corruption.drop_index] = str(definition)
                await connection.execute(sa.text(f"DROP INDEX {corruption.drop_index}"))
            return await corruption.inject(connection, world)
    finally:
        await engine.dispose()


async def _restore(corruption: Corruption) -> None:
    """Undo the corruption and rebuild the index, so later tests see a clean schema.

    Rebuilding is not tidiness: the dropped index is a constraint the rest of
    the suite relies on, and leaving it off would let a later test plant a state
    the database is supposed to refuse without anybody noticing.
    """
    if corruption.drop_index is None:
        return
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            for statement in corruption.cleanup:
                await connection.execute(sa.text(statement))
            definition = _DROPPED.pop(corruption.drop_index, None)
            if definition is not None:
                await connection.execute(sa.text(definition))
    finally:
        await engine.dispose()


async def test_S16_a_clean_seeded_world_yields_zero_findings(
    clean_findings: None,
) -> None:
    """The backstop must be silent on a consistent world, or it is noise.

    This is its own test rather than a line in another one: a checker that
    reported drift in a world every command built correctly would be trained out
    of existence within a week.
    """
    del clean_findings
    await build_checker_world()

    result = await _run_checker()
    assert result.summary["violations"] == 0
    assert result.summary["findings_opened"] == 0
    assert await finding_rows() == []
    assert result.summary["checked_invariants"] == len(INVARIANTS)


async def test_S16_an_offer_cap_override_authorises_each_credited_acceptance(
    clean_findings: None,
) -> None:
    del clean_findings
    world = await build_checker_world()
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "UPDATE cycle_policies SET max_accepted_offers = 1 "
                    "WHERE cycle_id = :cycle"
                ),
                {"cycle": world.open_cycle},
            )
            first_job = await _job_for(
                connection,
                world,
                cycle_id=world.open_cycle,
                outcome="internship",
                title="First open internship",
            )
            await _accepted_portal(
                connection,
                job_id=first_job,
                enrollment_id=world.student.enrollment_id,
            )
            target_job = await _job_for(
                connection,
                world,
                cycle_id=world.open_cycle,
                outcome="internship",
                title="Override open internship",
            )
            target_application = await seed_application(
                connection,
                job_id=target_job,
                enrollment_id=world.student.enrollment_id,
                status="in_progress",
            )
            await seed_event(
                connection,
                application_id=target_application,
                event_type="created",
                to_status="in_progress",
            )
            override_id = await grant(
                connection,
                domain=RuleDomain.OFFER_CAP,
                granted_by=world.admin.user_id,
                application_id=target_application,
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    try:
        result = await executor.run_bulk(
            "record_open_outcome",
            [
                {
                    "application_id": str(target_application),
                    "expected_status": "in_progress",
                }
            ],
            "checker-offer-cap-override",
            world.admin.actor,
            batch_fields={
                "cycle_id": world.open_cycle,
                "job_id": target_job,
                "target_status": "accepted",
            },
        )
    finally:
        await command_engine.dispose()
    assert isinstance(result, Result)
    accepted = next(event for event in result.events if event.event_type.value == "accepted")
    assert accepted.payload["applied_override_ids"] == [str(override_id)]

    # Authorization is attached to this decision, not consumed by it.  Later
    # deactivation or expiry must not rewrite the historical verdict.
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "UPDATE overrides SET is_active = false, expires_at = "
                    "(SELECT created_at + interval '1 microsecond' "
                    "FROM application_events WHERE application_id = :application "
                    "AND event_type = 'accepted' ORDER BY event_seq DESC LIMIT 1) "
                    "WHERE id = :override"
                ),
                {"application": target_application, "override": override_id},
            )
    finally:
        await engine.dispose()

    checked = await _run_checker()
    assert checked.summary["violations"] == 0
    assert await finding_rows("accepted_offers_within_cycle_cap") == []


async def test_S16_wrong_denied_and_late_credits_do_not_authorise_excess(
    clean_findings: None,
) -> None:
    del clean_findings
    world = await build_checker_world()
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "UPDATE cycle_policies SET max_accepted_offers = 1 "
                    "WHERE cycle_id = :cycle"
                ),
                {"cycle": world.open_cycle},
            )
            first_job = await _job_for(
                connection,
                world,
                cycle_id=world.open_cycle,
                outcome="internship",
                title="Uncredited internship",
            )
            await _accepted_portal(
                connection,
                job_id=first_job,
                enrollment_id=world.student.enrollment_id,
            )
            wrong_domain = await grant(
                connection,
                domain=RuleDomain.OUTCOME_GATE,
                granted_by=world.admin.user_id,
                enrollment_id=world.student.enrollment_id,
            )
            denied = await grant(
                connection,
                domain=RuleDomain.OFFER_CAP,
                granted_by=world.admin.user_id,
                enrollment_id=world.student.enrollment_id,
                allow=False,
            )
            credited_too_late = await grant(
                connection,
                domain=RuleDomain.OFFER_CAP,
                granted_by=world.admin.user_id,
                enrollment_id=world.student.enrollment_id,
                expires_at=past(),
            )
            second_job = await _job_for(
                connection,
                world,
                cycle_id=world.open_cycle,
                outcome="internship",
                title="Invalidly credited internship",
            )
            await _accepted_portal(
                connection,
                job_id=second_job,
                enrollment_id=world.student.enrollment_id,
                applied_override_ids=(wrong_domain, denied, credited_too_late),
            )
    finally:
        await engine.dispose()

    await _run_checker()
    rows = await finding_rows("accepted_offers_within_cycle_cap")
    assert len(rows) == 1
    assert subject_of(rows[0])["accepted_count"] == 2


async def test_S16_an_outcome_gate_override_authorises_the_credited_placement(
    clean_findings: None,
) -> None:
    del clean_findings
    world = await build_checker_world()
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            first_job = await _extra_job(connection, world, "First accepted placement")
            await _accepted_portal(
                connection,
                job_id=first_job,
                enrollment_id=world.student.enrollment_id,
            )
            target_application = await seed_application(
                connection,
                job_id=world.open_job_id,
                enrollment_id=world.student.enrollment_id,
                status="in_progress",
            )
            await seed_event(
                connection,
                application_id=target_application,
                event_type="created",
                to_status="in_progress",
            )
            override_id = await grant(
                connection,
                domain=RuleDomain.OUTCOME_GATE,
                granted_by=world.admin.user_id,
                application_id=target_application,
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    try:
        result = await executor.run_bulk(
            "record_open_outcome",
            [
                {
                    "application_id": str(target_application),
                    "expected_status": "in_progress",
                }
            ],
            "checker-outcome-override",
            world.admin.actor,
            batch_fields={
                "cycle_id": world.open_cycle,
                "job_id": world.open_job_id,
                "target_status": "accepted",
            },
        )
    finally:
        await command_engine.dispose()
    assert isinstance(result, Result)
    accepted = next(event for event in result.events if event.event_type.value == "accepted")
    assert accepted.payload["applied_override_ids"] == [str(override_id)]

    checked = await _run_checker()
    assert checked.summary["violations"] == 0
    assert await finding_rows("one_accepted_placement_offer_globally") == []


async def test_S16_external_acceptance_reads_its_outcome_credit_from_audit(
    clean_findings: None,
) -> None:
    del clean_findings
    world = await build_checker_world()
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            first_job = await _extra_job(connection, world, "Portal placement")
            await _accepted_portal(
                connection,
                job_id=first_job,
                enrollment_id=world.student.enrollment_id,
            )
            external_offer_id = cast_uuid(
                await connection.scalar(
                    sa.text(
                        "INSERT INTO external_offers (id, enrollment_id, company_id, "
                        "outcome, source, status, created_by) VALUES (gen_random_uuid(), "
                        ":enrollment, :company, 'placement', 'off_campus', 'offered', "
                        ":admin) RETURNING id"
                    ),
                    {
                        "enrollment": world.student.enrollment_id,
                        "company": world.company_id,
                        "admin": world.admin.user_id,
                    },
                )
            )
            override_id = await grant(
                connection,
                domain=RuleDomain.OUTCOME_GATE,
                granted_by=world.admin.user_id,
                enrollment_id=world.student.enrollment_id,
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    spec = executor.registry.commands["update_external_offer"]
    try:
        result = await executor.run(
            "update_external_offer",
            spec.input_model.model_validate(
                {
                    "external_offer_id": external_offer_id,
                    "expected_status": "offered",
                    "status": "accepted",
                    "reason": "Second placement explicitly approved",
                }
            ),
            world.admin.actor,
        )
    finally:
        await command_engine.dispose()
    assert isinstance(result, Result)
    details = await scalar(
        "SELECT details FROM audit_log WHERE action = 'update_external_offer'"
    )
    assert details["applied_override_ids"] == [str(override_id)]  # type: ignore[index]

    checked = await _run_checker()
    assert checked.summary["violations"] == 0
    assert await finding_rows("one_accepted_placement_offer_globally") == []


async def test_S16_external_attachment_reads_its_offer_cap_credit_from_audit(
    clean_findings: None,
) -> None:
    del clean_findings
    world = await build_checker_world()
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            await _accepted_portal(
                connection,
                job_id=world.internship_job_id,
                enrollment_id=world.student.enrollment_id,
            )
            external_offer_id = cast_uuid(
                await connection.scalar(
                    sa.text(
                        "INSERT INTO external_offers (id, enrollment_id, company_id, "
                        "outcome, source, status, created_by) VALUES (gen_random_uuid(), "
                        ":enrollment, :company, 'internship', 'ppo', 'accepted', "
                        ":admin) RETURNING id"
                    ),
                    {
                        "enrollment": world.student.enrollment_id,
                        "company": world.company_id,
                        "admin": world.admin.user_id,
                    },
                )
            )
            override_id = await grant(
                connection,
                domain=RuleDomain.OFFER_CAP,
                granted_by=world.admin.user_id,
                enrollment_id=world.student.enrollment_id,
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    spec = executor.registry.commands["attach_external_offer"]
    try:
        result = await executor.run(
            "attach_external_offer",
            spec.input_model.model_validate(
                {
                    "cycle_id": world.internship_cycle,
                    "external_offer_id": external_offer_id,
                    "reason": "Additional accepted internship approved",
                }
            ),
            world.admin.actor,
        )
    finally:
        await command_engine.dispose()
    assert isinstance(result, Result)
    assert result.summary["applied_override_ids"] == [str(override_id)]

    checked = await _run_checker()
    assert checked.summary["violations"] == 0
    assert await finding_rows("accepted_offers_within_cycle_cap") == []


@pytest.mark.parametrize("invariant_id", INVARIANT_IDS)
async def test_S16_each_corruption_raises_its_finding_and_a_fix_that_runs(
    invariant_id: str, clean_findings: None
) -> None:
    del clean_findings
    corruption = _corruption(invariant_id)
    world = await build_checker_world()
    expected_subject = await _inject(corruption, world)

    try:
        result = await _run_checker()
        rows = await finding_rows(invariant_id)
        assert len(rows) == 1, (
            f"{invariant_id} raised {len(rows)} findings; the checker reported "
            f"{result.summary['by_invariant']}"
        )
        row = rows[0]
        assert row["status"] == "open"
        assert str(row["detail"]).strip()
        assert row["suggested_fix"] == corruption.suggested_fix

        subject = subject_of(row)
        for key, value in expected_subject.items():
            assert subject.get(key) == value, (
                f"{invariant_id} finding subject {subject} does not carry "
                f"{key}={value!r}"
            )

        payload = fix_payload(invariant_id, subject)
        assert payload is not None
        assert payload["command"] == corruption.suggested_fix
        if corruption.fix_is_runnable:
            # The button on admin/findings sends exactly this, so exactly this
            # is dry-run through the real executor.
            assert payload["input"] is not None
            await _dry_run_fix(str(payload["command"]), payload["input"], world)
        else:
            assert payload["input"] is None
    finally:
        await _restore(corruption)


async def _dry_run_fix(command: str, payload: object, world: CheckerWorld) -> None:
    executor, _engine = build_test_executor()
    spec = executor.registry.commands[command]
    input_value = spec.input_model.model_validate(payload)
    try:
        preview = await executor.run(
            command, input_value, world.admin_actor, dry_run=True
        )
    except DomainRejection as rejection:
        codes = [reason.code for reason in rejection.rejection.reasons]
        raise AssertionError(
            f"the suggested fix {command} refused its own prefilled input: {codes}"
        ) from rejection
    assert isinstance(preview, Preview)


async def test_S16_a_second_run_neither_duplicates_nor_loses_an_open_finding(
    clean_findings: None,
) -> None:
    """A finding's identity is its invariant and subject, so a nightly run is
    idempotent by construction rather than by a deduplication pass."""
    del clean_findings
    world = await build_checker_world()
    await _inject(CORRUPTIONS["no_open_offer_on_unoffered_application"], world)

    first = await _run_checker()
    second = await _run_checker()
    assert first.summary["findings_opened"] == 1
    assert second.summary["findings_opened"] == 0
    assert len(await finding_rows("no_open_offer_on_unoffered_application")) == 1


async def test_S16_a_resolved_finding_reopens_when_the_drift_is_still_there(
    clean_findings: None,
) -> None:
    """Resolving records a belief; the next run checks it."""
    del clean_findings
    world = await build_checker_world()
    await _inject(CORRUPTIONS["no_open_offer_on_unoffered_application"], world)
    await _run_checker()

    rows = await finding_rows("no_open_offer_on_unoffered_application")
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "UPDATE consistency_findings SET status = 'resolved', "
                    "resolved_at = now() WHERE id = :id"
                ),
                {"id": rows[0]["id"]},
            )
    finally:
        await engine.dispose()

    result = await _run_checker()
    assert result.summary["findings_reopened"] == 1
    after = await finding_rows("no_open_offer_on_unoffered_application")
    assert after[0]["status"] == "open"


async def test_S16_a_dismissed_finding_stays_quiet_then_closes_when_it_heals(
    clean_findings: None,
) -> None:
    """Dismissing means "this is fine", not "never tell me about this subject".

    While the corruption persists the row stays dismissed and silent.  Once the
    invariant holds again it is marked resolved, so a *later* independent
    corruption of the same subject raises a fresh finding rather than being
    swallowed by a verdict about a different occurrence.
    """
    del clean_findings
    world = await build_checker_world()
    await _inject(CORRUPTIONS["no_open_offer_on_unoffered_application"], world)
    await _run_checker()

    rows = await finding_rows("no_open_offer_on_unoffered_application")
    finding_id = rows[0]["id"]
    subject = subject_of(rows[0])
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "UPDATE consistency_findings SET status = 'dismissed' WHERE id = :id"
                ),
                {"id": finding_id},
            )
    finally:
        await engine.dispose()

    quiet = await _run_checker()
    assert quiet.summary["findings_opened"] == 0
    assert quiet.summary["findings_auto_resolved"] == 0
    assert (await finding_rows("no_open_offer_on_unoffered_application"))[0][
        "status"
    ] == "dismissed"

    # The offer is terminated, so the invariant holds again for this subject.
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "UPDATE offers SET terminated_at = now(), "
                    "termination_kind = 'admin_correction', "
                    "termination_reason = 'Reconciled' WHERE id = :id"
                ),
                {"id": subject["offer_id"]},
            )
    finally:
        await engine.dispose()

    healed = await _run_checker()
    assert healed.summary["findings_auto_resolved"] == 1
    assert (await finding_rows("no_open_offer_on_unoffered_application"))[0][
        "status"
    ] == "resolved"

    # A genuinely new occurrence on the same subject is not swallowed.
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "UPDATE offers SET terminated_at = NULL, termination_kind = NULL, "
                    "termination_reason = NULL WHERE id = :id"
                ),
                {"id": subject["offer_id"]},
            )
    finally:
        await engine.dispose()

    again = await _run_checker()
    assert again.summary["findings_reopened"] == 1
    assert (await finding_rows("no_open_offer_on_unoffered_application"))[0][
        "status"
    ] == "open"


async def test_S16_the_nightly_run_purges_dead_sessions_and_stale_reminders(
    clean_findings: None,
) -> None:
    """the design review section 4.11 housekeeping, reported apart from correctness."""
    del clean_findings
    world = await build_checker_world()
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "INSERT INTO sessions (id, token_hash, user_id, expires_at) "
                    "VALUES (gen_random_uuid(), 'expired-token', :user_id, "
                    "now() - interval '1 day')"
                ),
                {"user_id": world.admin.user_id},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO reminder_sends (id, kind, dedup_key, created_at) "
                    "VALUES (gen_random_uuid(), 'deadline', 'stale-key', "
                    "now() - interval '200 days')"
                )
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO reminder_sends (id, kind, dedup_key, created_at) "
                    "VALUES (gen_random_uuid(), 'deadline', 'recent-key', now())"
                )
            )
    finally:
        await engine.dispose()

    result = await _run_checker()
    assert result.summary["sessions_purged"] == 1
    assert result.summary["reminder_sends_purged"] == 1
    assert result.summary["violations"] == 0

    assert await scalar("SELECT count(*) FROM reminder_sends") == 1
    assert (
        await scalar(
            "SELECT count(*) FROM sessions WHERE token_hash = 'expired-token'"
        )
        == 0
    )
    # The live session the world seeded is untouched.
    assert await scalar("SELECT count(*) FROM sessions") == 2


async def test_S16_every_invariant_has_a_corruption_fixture() -> None:
    """The ratchet: the catalog and the fixtures cannot drift apart."""
    assert set(CORRUPTIONS) == set(INVARIANT_IDS), (
        "CORRUPTIONS and checker.INVARIANTS disagree: "
        f"{set(CORRUPTIONS) ^ set(INVARIANT_IDS)}"
    )


async def test_S16_the_checker_writes_nothing_but_findings_and_housekeeping(
    clean_findings: None,
) -> None:
    """The backstop is not a repair pass: it never rewrites the domain.

    A checker that corrected what it found would be a write path around every
    preview and every event, at three in the morning, with nobody watching.
    """
    del clean_findings
    world = await build_checker_world()
    await _inject(CORRUPTIONS["no_live_application_without_active_membership"], world)

    before = await _domain_snapshot()
    await _run_checker()
    assert await _domain_snapshot() == before


async def _domain_snapshot() -> list[tuple[str, int]]:
    engine = read_engine()
    tables = (
        "applications",
        "application_round_states",
        "offers",
        "external_offers",
        "cycle_memberships",
        "strikes",
        "penalties",
        "overrides",
        "jobs",
    )
    try:
        async with engine.connect() as connection:
            return [
                (
                    table,
                    int(
                        await connection.scalar(  # type: ignore[arg-type]
                            sa.text(f"SELECT count(*) FROM {table}")  # noqa: S608
                        )
                    ),
                )
                for table in tables
            ]
    finally:
        await engine.dispose()
