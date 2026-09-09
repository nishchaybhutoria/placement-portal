"""The dispute screen: staff/student/{enrollment_id} (LLD section 11.3).

Two things are asserted harder than the rest, because they are the reasons this
screen exists at all: the timeline reads in order with an actor and a reason on
every row, and the record includes what no application event can carry -- a
strike's revoker (the design review section 4.25) and an off-campus offer recorded for a
student who never applied (section 4.26).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.errors import (
    DUPLICATE_APPLICATION,
    INVALID_TRANSITION,
    MEMBERSHIP_NOT_ACTIVE,
    AuthorizationDenied,
    DomainRejection,
)
from app.core.plan import ActorContext, Preview
from app.domain.shared import ApplicationStatus, RuleDomain, domains_for_scope
from app.modules.interventions.commands import (
    ForceTransitionInput,
    ReinstateApplicationInput,
)
from app.modules.interventions.queries import staff_student_record
from app.modules.overrides.commands import CreateOverrideInput
from app.modules.profiles.fields import ADMIN_FIELDS
from tests.interventions.conftest import (
    PipelineWorld,
    build_pipeline_world,
    build_test_executor,
    read_engine,
    seed_application_row,
    write_engine,
)
from tests.overrides.conftest import grant

pytestmark = pytest.mark.asyncio


async def _record(actor: ActorContext, enrollment_id: UUID) -> dict[str, object]:
    engine = read_engine()
    try:
        return await staff_student_record(engine, actor, enrollment_id)
    finally:
        await engine.dispose()


def _applications(body: dict[str, object]) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", body["applications"])


def _application(body: dict[str, object], application_id: UUID) -> dict[str, object]:
    """One named application, since a student may hold several to one job."""
    match = next(
        (row for row in _applications(body) if row["id"] == str(application_id)), None
    )
    assert match is not None, f"{application_id} is missing from the record"
    return match


async def _history(world: PipelineWorld) -> None:
    """Three events, an offer, an external record, a strike and its revocation."""
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            for index, (event_type, from_status, to_status, reason, actor) in enumerate(
                (
                    ("created", None, "in_progress", None, None),
                    ("advanced", "in_progress", "in_progress", None, world.coordinator.user_id),
                    (
                        "eliminated",
                        "in_progress",
                        "rejected",
                        "Did not clear the technical round",
                        world.coordinator.user_id,
                    ),
                )
            ):
                await connection.execute(
                    sa.text(
                        "INSERT INTO application_events (id, application_id, event_type, "
                        "from_status, to_status, actor_user_id, reason, created_at) VALUES "
                        "(:id, :application_id, CAST(:event_type AS event_type_t), "
                        "CAST(:from_status AS application_status_t), "
                        "CAST(:to_status AS application_status_t), :actor, :reason, "
                        "now() - make_interval(mins => :offset))"
                    ),
                    {
                        "id": uuid4(),
                        "application_id": world.application_id,
                        "event_type": event_type,
                        "from_status": from_status,
                        "to_status": to_status,
                        "actor": actor,
                        "reason": reason,
                        "offset": 30 - index * 10,
                    },
                )
            company_id = uuid4()
            await connection.execute(
                sa.text(
                    "INSERT INTO companies (id, name, is_active) "
                    "VALUES (:id, :name, true)"
                ),
                {"id": company_id, "name": f"Off Campus {uuid4().hex[:6]}"},
            )
            external_id = uuid4()
            await connection.execute(
                sa.text(
                    "INSERT INTO external_offers (id, enrollment_id, company_id, "
                    "outcome, source, status, created_by) VALUES (:id, :enrollment_id, "
                    ":company_id, 'placement', 'off_campus', 'accepted', :admin)"
                ),
                {
                    "id": external_id,
                    "enrollment_id": world.student.enrollment_id,
                    "company_id": company_id,
                    "admin": world.admin.user_id,
                },
            )
            # Section 4.26: the mutation audits the *enrollment*, because an
            # off-campus offer has no application to hang an event on.
            await connection.execute(
                sa.text(
                    "INSERT INTO audit_log (id, actor_user_id, action, subject_type, "
                    "subject_id, details) VALUES (:id, :admin, 'create_external_offer', "
                    "'enrollment', :enrollment_id, CAST(:details AS jsonb))"
                ),
                {
                    "id": uuid4(),
                    "admin": world.admin.user_id,
                    "enrollment_id": world.student.enrollment_id,
                    "details": '{"outcome": "placement", "source": "off_campus"}',
                },
            )
            strike_id = uuid4()
            await connection.execute(
                sa.text(
                    "INSERT INTO strikes (id, enrollment_id, reason, source, "
                    "awarded_by, is_active) VALUES (:id, :enrollment_id, "
                    "'Missed the coordinator follow-up', 'manual', :admin, false)"
                ),
                {
                    "id": strike_id,
                    "enrollment_id": world.student.enrollment_id,
                    "admin": world.admin.user_id,
                },
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO audit_log (id, actor_user_id, action, subject_type, "
                    "subject_id, details) VALUES (:id, :admin, 'revoke_strike', "
                    "'strike', :strike_id, CAST(:details AS jsonb))"
                ),
                {
                    "id": uuid4(),
                    "admin": world.admin.user_id,
                    "strike_id": strike_id,
                    "details": '{"reason": "Corrected against the signed sheet"}',
                },
            )
    finally:
        await engine.dispose()


async def test_INT1_the_timeline_reads_in_order_with_an_actor_and_reason_per_row(
    clean_interventions: None,
) -> None:
    del clean_interventions
    world = await build_pipeline_world(status="rejected")
    await _history(world)

    body = await _record(world.admin.actor, world.student.enrollment_id)
    timeline = cast("list[dict[str, object]]", body["timeline"])
    assert [item["event_type"] for item in timeline] == [
        "created",
        "advanced",
        "eliminated",
    ]
    assert [item["created_at"] for item in timeline] == sorted(
        [str(item["created_at"]) for item in timeline]
    )
    for item in timeline:
        assert "actor" in item and "reason" in item
    # A system-written row says so by carrying no actor, rather than by being
    # indistinguishable from a staff action.
    assert timeline[0]["actor"] is None
    assert timeline[2]["actor"] == "Asha Mehta" or timeline[2]["actor"] is not None
    assert timeline[2]["reason"] == "Did not clear the technical round"
    assert timeline[2]["from_status"] == "in_progress"
    assert timeline[2]["to_status"] == "rejected"

    application = _applications(body)[0]
    events = cast("list[dict[str, object]]", application["events"])
    assert [item["event_type"] for item in events] == [
        "created",
        "advanced",
        "eliminated",
    ]


async def test_INT2_an_events_applied_overrides_are_resolved_for_the_reader(
    clean_interventions: None,
) -> None:
    """The stamp INT-2 requires is read back as the grant it names.

    The event keeps ids because an append-only row must, and the screen is
    asked the other question -- *why was this person allowed in* -- which is
    answered by the domain, the granter, the date and the reason. So the ids
    are resolved on read here, the way ``admin/findings`` resolves its subject
    labels (the design review section 4.35).
    """
    del clean_interventions
    world = await build_pipeline_world(status="in_progress")
    override_id = uuid4()
    missing_id = uuid4()
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "INSERT INTO overrides (id, rule_domain, allow, enrollment_id, "
                    "reason, granted_by, is_active) VALUES "
                    "(:id, CAST(:domain AS rule_domain_t), true, :enrollment_id, "
                    ":reason, :admin, true)"
                ),
                {
                    "id": override_id,
                    "domain": "eligibility",
                    "enrollment_id": world.student.enrollment_id,
                    "reason": "Company asked for her by name",
                    "admin": world.admin.user_id,
                },
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO application_events (id, application_id, event_type, "
                    "to_status, actor_user_id, payload) VALUES (:id, :application_id, "
                    "'created', 'in_progress', :actor, CAST(:payload AS jsonb))"
                ),
                {
                    "id": uuid4(),
                    "application_id": world.application_id,
                    "actor": world.student.user_id,
                    "payload": (
                        '{"applied_override_ids": '
                        f'["{override_id}", "{missing_id}"]}}'
                    ),
                },
            )
    finally:
        await engine.dispose()

    body = await _record(world.admin.actor, world.student.enrollment_id)
    events = cast("list[dict[str, object]]", _applications(body)[0]["events"])
    labels = cast("dict[str, object]", events[0]["payload_labels"])
    applied = cast("list[dict[str, object]]", labels["applied_override_ids"])
    # The ids stay on the payload: they are what the row actually recorded.
    payload = cast("dict[str, object]", events[0]["payload"])
    assert payload["applied_override_ids"] == [str(override_id), str(missing_id)]
    granted = next(item for item in applied if item["id"] == str(override_id))
    assert granted["rule_domain"] == "eligibility"
    assert granted["allow"] is True
    assert granted["reason"] == "Company asked for her by name"
    assert granted["granted_by"] == "Administrator"
    assert granted["granted_at"] is not None
    # A grant that is no longer there keeps its place with nothing invented,
    # so the screen can say so rather than print the id it could not resolve.
    gone = next(item for item in applied if item["id"] == str(missing_id))
    assert gone["rule_domain"] is None and gone["granted_by"] is None


async def test_INT1_the_record_shows_memberships_offers_and_external_offers(
    clean_interventions: None,
) -> None:
    del clean_interventions
    world = await build_pipeline_world(status="rejected")
    await _history(world)

    body = await _record(world.admin.actor, world.student.enrollment_id)
    memberships = cast("list[dict[str, object]]", body["memberships"])
    assert len(memberships) == 1
    assert memberships[0]["status"] == "active"

    external = cast("list[dict[str, object]]", body["external_offers"])
    assert len(external) == 1
    assert external[0]["source"] == "off_campus"
    assert external[0]["status"] == "accepted"

    # Section 4.26: the audit row is what makes an offer for a student who never
    # applied visible at all.
    audit = cast("list[dict[str, object]]", body["audit"])
    assert any(item["action"] == "create_external_offer" for item in audit)


async def test_INT1_a_strike_revocation_is_read_from_the_audit_log(
    clean_interventions: None,
) -> None:
    """Section 4.25: ``strikes`` records no revoker, so the record reads the trail.

    The asymmetry is visible in the payload rather than papered over, because
    the difference is real: a penalty answers from its own columns.
    """
    del clean_interventions
    world = await build_pipeline_world(status="rejected")
    await _history(world)

    body = await _record(world.admin.actor, world.student.enrollment_id)
    discipline = cast("dict[str, object]", body["discipline"])
    strikes = cast("list[dict[str, object]]", discipline["strikes"])
    assert len(strikes) == 1
    assert strikes[0]["is_active"] is False
    revocation = cast("dict[str, object]", strikes[0]["revocation"])
    assert revocation["source"] == "audit_log"
    assert revocation["reason"] == "Corrected against the signed sheet"
    assert revocation["actor"] == "Administrator"
    assert cast("dict[str, object]", discipline["revoker_source"]) == {
        "strikes": "audit_log",
        "penalties": "penalties.revoked_by",
    }


async def test_INT1_the_snapshot_diff_says_what_the_application_was_judged_on(
    clean_interventions: None,
) -> None:
    del clean_interventions
    world = await build_pipeline_world(status="rejected")
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text("UPDATE profiles SET cpi = 9.10 WHERE enrollment_id = :id"),
                {"id": world.student.enrollment_id},
            )
    finally:
        await engine.dispose()

    body = await _record(world.admin.actor, world.student.enrollment_id)
    diff = {
        str(row["key"]): row
        for row in cast(
            "list[dict[str, object]]", _applications(body)[0]["snapshot_diff"]
        )
    }
    assert diff["cpi"]["state"] == "changed"
    assert diff["cpi"]["snapshot"] == "8.40"
    assert diff["cpi"]["live"] == "9.10"
    assert diff["graduating_year"]["state"] == "unchanged"
    # A field the snapshot never held is "absent", not "empty": the application
    # was not judged on it at all.
    assert diff["personal_email"]["state"] == "absent"


async def test_INT1_the_enrollment_picker_spans_the_user_s_whole_history(
    clean_interventions: None,
) -> None:
    del clean_interventions
    world = await build_pipeline_world(status="rejected")
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text("UPDATE enrollments SET is_current = false WHERE id = :id"),
                {"id": world.student.enrollment_id},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO enrollments (id, user_id, is_current, roll_number) "
                    "VALUES (gen_random_uuid(), :user_id, true, :roll)"
                ),
                {"user_id": world.student.user_id, "roll": f"22{uuid4().hex[:6]}"},
            )
    finally:
        await engine.dispose()

    body = await _record(world.admin.actor, world.student.enrollment_id)
    enrollments = cast("list[dict[str, object]]", body["enrollments"])
    assert len(enrollments) == 2
    assert [item["selected"] for item in enrollments].count(True) == 1
    assert any(item["is_current"] for item in enrollments)


async def test_INT1_what_the_record_offers_is_what_the_interventions_allow(
    clean_interventions: None,
) -> None:
    """Section 4.22 across four states, because the failure is a missing control.

    Each state is driven for real and compared with the real command's verdict:
    reinstatable, blocked by a duplicate, blocked by a non-active membership,
    and outside the coordinator's cycles.
    """
    del clean_interventions
    executor, _engine = build_test_executor()

    reinstatable = await build_pipeline_world(status="rejected")
    duplicate = await build_pipeline_world(status="withdrawn")
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            await seed_application_row(
                connection,
                job_id=duplicate.job_id,
                enrollment_id=duplicate.student.enrollment_id,
                status="in_progress",
                current_round_id=duplicate.rounds[0],
            )
    finally:
        await engine.dispose()
    removed = await build_pipeline_world(status="rejected", membership_status="removed")
    live = await build_pipeline_world(status="in_progress")

    expectations = {
        reinstatable: None,
        duplicate: DUPLICATE_APPLICATION,
        removed: MEMBERSHIP_NOT_ACTIVE,
        live: INVALID_TRANSITION,
    }
    for world, expected in expectations.items():
        body = await _record(world.admin.actor, world.student.enrollment_id)
        offered = cast(
            "dict[str, object]",
            cast(
                "dict[str, object]",
                _application(body, world.application_id)["actions"],
            )["reinstate"],
        )
        payload = ReinstateApplicationInput(
            cycle_id=world.cycle_id,
            application_id=world.application_id,
            target_round_id=world.rounds[0],
            reason="Equivalence pin",
        )
        try:
            preview = await executor.run(
                "reinstate_application", payload, world.admin.actor, dry_run=True
            )
            allowed, code = isinstance(preview, Preview), None
        except DomainRejection as rejection:
            allowed = False
            code = rejection.rejection.reasons[0].code

        assert offered["allowed"] is allowed, (
            f"the record offers {offered['allowed']} while the command answers {allowed}"
        )
        assert offered["reason"] == code == expected


async def test_INT1_a_coordinator_sees_their_own_students_and_no_others(
    clean_interventions: None,
) -> None:
    """The drill-down spans cycles, so access is gated on sharing one.

    Once inside, the controls stay cycle-scoped: an application in a cycle this
    coordinator does not run is shown, with its buttons disabled and a reason
    that says why.
    """
    del clean_interventions
    mine = await build_pipeline_world(status="rejected")
    theirs = await build_pipeline_world(status="rejected")

    body = await _record(mine.coordinator.actor, mine.student.enrollment_id)
    assert body["enrollment"] is not None

    with pytest.raises(AuthorizationDenied):
        await _record(mine.coordinator.actor, theirs.student.enrollment_id)

    # An administrator sees every record.
    assert (
        await _record(mine.admin.actor, theirs.student.enrollment_id)
    )["enrollment"] is not None

    # And a coordinator's controls stop at their own cycles.
    outside = await _record(theirs.coordinator.actor, theirs.student.enrollment_id)
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "DELETE FROM cycle_coordinators WHERE user_id = :user_id"
                ),
                {"user_id": theirs.coordinator.user_id},
            )
    finally:
        await engine.dispose()
    unscoped = ActorContext(
        principal_id=str(theirs.coordinator.user_id),
        user_id=theirs.coordinator.user_id,
        role="student",
        session_id=theirs.coordinator.session_id,
        coordinated_cycle_ids=(uuid4(),),
    )
    actions = cast(
        "dict[str, object]", _applications(outside)[0]["actions"]
    )
    assert cast("dict[str, object]", actions["reinstate"])["allowed"] is True

    with pytest.raises(AuthorizationDenied):
        await _record(unscoped, theirs.student.enrollment_id)


async def test_INT1_force_transition_control_matches_the_command_across_cycles(
    clean_interventions: None,
) -> None:
    del clean_interventions
    world = await build_pipeline_world(status="rejected")
    other = await build_pipeline_world(status="rejected")
    executor, _engine = build_test_executor()

    body = await _record(other.coordinator.actor, other.student.enrollment_id)
    offered = cast(
        "dict[str, object]",
        cast("dict[str, object]", _applications(body)[0]["actions"])["force_transition"],
    )
    assert offered["allowed"] is True
    preview = await executor.run(
        "force_transition",
        ForceTransitionInput(
            cycle_id=other.cycle_id,
            application_id=other.application_id,
            to_status=ApplicationStatus.WITHDRAWN,
            reason="Equivalence pin",
        ),
        other.coordinator.actor,
        dry_run=True,
    )
    assert isinstance(preview, Preview)

    # The same application, read by a coordinator of a different cycle, is
    # offered nothing -- and the command agrees by denying them outright.
    del world


async def test_INT1_the_profile_edit_control_matches_admin_update_profile(
    clean_interventions: None,
) -> None:
    """the design review section 4.22 for the INT-1 correction dialog.

    "Correct locked profile fields" is an administrator's power in INT-1's
    table, and `admin_update_profile` is registered `actor="admin"`. A
    coordinator reads the whole record -- that is what the drill-down is for --
    but the correction control is not theirs, and the screen has to say so
    rather than the client inferring it from a role it happens to know.
    """
    del clean_interventions
    world = await build_pipeline_world()
    executor, engine = build_test_executor()
    spec = executor.registry.commands["admin_update_profile"]
    input_value = spec.input_model.model_validate(
        {"enrollment_id": str(world.student.enrollment_id), "fields": {"cpi": "9.10"}}
    )

    async def allowed(actor: ActorContext) -> bool:
        try:
            await executor.run("admin_update_profile", input_value, actor, dry_run=True)
        except (AuthorizationDenied, DomainRejection):
            return False
        return True

    try:
        for actor, expected in (
            (world.admin.actor, True),
            (world.coordinator.actor, False),
        ):
            body = await _record(actor, world.student.enrollment_id)
            offered = cast(
                "dict[str, object]",
                cast("dict[str, object]", body["actions"])["edit_profile"],
            )
            assert offered["allowed"] is expected
            assert await allowed(actor) is expected
            if not expected:
                assert offered["human"], "a hidden control must say whose it is"
    finally:
        await engine.dispose()


async def test_INT2_override_controls_match_create_override_permissions_and_domains(
    clean_interventions: None,
) -> None:
    del clean_interventions
    world = await build_pipeline_world()
    executor, engine = build_test_executor()
    enrollment_input = CreateOverrideInput(
        rule_domain=RuleDomain.OUTCOME_GATE,
        enrollment_id=world.student.enrollment_id,
        reason="Permission equivalence pin",
    )
    application_input = CreateOverrideInput(
        rule_domain=RuleDomain.OUTCOME_GATE,
        cycle_id=world.cycle_id,
        application_id=world.application_id,
        reason="Permission equivalence pin",
    )
    job_enrollment_input = CreateOverrideInput(
        rule_domain=RuleDomain.ELIGIBILITY,
        cycle_id=world.cycle_id,
        job_id=world.job_id,
        enrollment_id=world.student.enrollment_id,
        reason="Pre-application permission equivalence pin",
    )

    async def command_allows(input_value: CreateOverrideInput, actor: ActorContext) -> bool:
        try:
            await executor.run("create_override", input_value, actor, dry_run=True)
        except (AuthorizationDenied, DomainRejection):
            return False
        return True

    try:
        for actor, enrollment_allowed in (
            (world.admin.actor, True),
            (world.coordinator.actor, False),
        ):
            body = await _record(actor, world.student.enrollment_id)
            actions = cast("dict[str, object]", body["actions"])
            enrollment_permission = cast(
                "dict[str, object]", actions["grant_enrollment_override"]
            )
            assert enrollment_permission["allowed"] is enrollment_allowed
            assert await command_allows(enrollment_input, actor) is enrollment_allowed

            targets = cast("dict[str, object]", body["override_targets"])
            jobs = cast("list[dict[str, object]]", targets["jobs"])
            assert [row["id"] for row in jobs] == [str(world.job_id)]
            assert targets["job_domains"] == [
                domain.value
                for domain in domains_for_scope("job", "enrollment")
            ]
            assert await command_allows(job_enrollment_input, actor) is True

            application = _application(body, world.application_id)
            application_actions = cast(
                "dict[str, object]", application["actions"]
            )
            application_permission = cast(
                "dict[str, object]", application_actions["grant_override"]
            )
            assert application_permission["allowed"] is True
            assert await command_allows(application_input, actor) is True
            assert application["override_domains"] == [
                RuleDomain.EDIT_WINDOW.value,
                RuleDomain.WITHDRAW_WINDOW.value,
                RuleDomain.OUTCOME_GATE.value,
                RuleDomain.OFFER_CAP.value,
                RuleDomain.OFFER_DEADLINE.value,
            ]
        assert body["override_domains"] == [domain.value for domain in RuleDomain]
    finally:
        await engine.dispose()


async def test_INT2_record_and_application_classify_relevant_overrides() -> None:
    world = await build_pipeline_world()
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            cycle = await grant(
                connection,
                domain=RuleDomain.OFFER_CAP,
                granted_by=world.admin.user_id,
                cycle_id=world.cycle_id,
            )
            job = await grant(
                connection,
                domain=RuleDomain.OFFER_CAP,
                granted_by=world.admin.user_id,
                job_id=world.job_id,
            )
            enrollment = await grant(
                connection,
                domain=RuleDomain.OFFER_CAP,
                granted_by=world.admin.user_id,
                enrollment_id=world.student.enrollment_id,
            )
            application = await grant(
                connection,
                domain=RuleDomain.OFFER_CAP,
                granted_by=world.admin.user_id,
                application_id=world.application_id,
                allow=False,
            )
            expired = await grant(
                connection,
                domain=RuleDomain.OFFER_DEADLINE,
                granted_by=world.admin.user_id,
                job_id=world.job_id,
                enrollment_id=world.student.enrollment_id,
                expires_at=datetime.now(UTC) - timedelta(days=1),
            )
    finally:
        await engine.dispose()

    body = await _record(world.admin.actor, world.student.enrollment_id)
    record_states = {
        row["id"]: row["state"]
        for row in cast("list[dict[str, object]]", body["overrides"])
    }
    assert record_states[str(enrollment)] == "active"
    assert record_states[str(expired)] == "expired"

    card = _application(body, world.application_id)
    application_states = {
        row["id"]: row["state"]
        for row in cast("list[dict[str, object]]", card["overrides"])
    }
    assert application_states[str(application)] == "active"
    for shadowed in (cycle, job, enrollment):
        assert application_states[str(shadowed)] == "shadowed"


async def test_INT1_the_record_offers_every_admin_managed_field_with_its_choices(
    clean_interventions: None,
) -> None:
    """The dialog can only edit what the payload describes.

    `bulk_upsert_profiles` deliberately skips an empty cell, so the single-edit
    path is the only way to clear an admin-managed field (PRO-1, PRO-2). It
    therefore has to reach every one of them, with the taxonomy choices a
    program or branch needs -- a form offering a retired program is a form
    whose save the server refuses.
    """
    del clean_interventions
    world = await build_pipeline_world()

    body = await _record(world.admin.actor, world.student.enrollment_id)

    profile = cast("dict[str, object]", body["profile"])
    fields = cast("list[dict[str, object]]", profile["fields"])
    editable = {str(row["key"]) for row in fields if row["admin_editable"]}
    assert editable == set(ADMIN_FIELDS)
    live = cast("dict[str, object]", profile["live"])
    assert editable <= set(live), "every editable field needs its current value"
    taxonomies = cast("dict[str, list[object]]", profile["taxonomies"])
    assert taxonomies["programs"] and taxonomies["branches"]
    assert profile["program_branches"]
