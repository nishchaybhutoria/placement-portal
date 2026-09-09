"""Cycle archival and its read-only aftermath (Behavior CYC-1, CYC-4)."""

from __future__ import annotations

import os
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.authz import ARCHIVED_CYCLE_COMMAND_ALLOWLIST
from app.core.db import create_engine
from app.core.errors import CYCLE_ARCHIVED, DomainRejection
from app.core.plan import Preview, Result
from tests.cycles.conftest import (
    Person,
    application_status,
    build_test_executor,
    seed_admin,
    seed_application,
    seed_complete_profile,
    seed_cycle,
    seed_job,
    seed_membership,
    seed_person,
    seed_taxonomy,
)

pytestmark = pytest.mark.usefixtures("clean_cycles")


async def _cycle_with_applications(
    statuses: tuple[str, ...],
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
                resume_id=resume_id,
            )
            applications: dict[str, UUID] = {}
            round_id: UUID | None = None
            for status in statuses:
                application_id, created = await seed_application(
                    connection,
                    cycle_id=cycle_id,
                    enrollment_id=student.enrollment_id,
                    status=status,
                    title=f"Job {status}",
                    with_round=status == "in_progress",
                )
                applications[status] = application_id
                round_id = created or round_id
    finally:
        await engine.dispose()
    return admin, student, cycle_id, membership_id, applications, round_id


@pytest.mark.asyncio
async def test_CYC1_archive_preview_matches_execution_and_force_withdraws() -> None:
    admin, _student, cycle_id, _membership, applications, round_id = (
        await _cycle_with_applications(
            ("in_progress", "pending_offer", "withdrawn", "rejected")
        )
    )

    executor, engine = build_test_executor()
    payload = executor.registry.commands["archive_cycle"].input_model.model_validate(
        {"cycle_id": str(cycle_id)}
    )
    try:
        preview = await executor.run("archive_cycle", payload, admin.actor, dry_run=True)
        result = await executor.run("archive_cycle", payload, admin.actor)
    finally:
        await engine.dispose()

    assert isinstance(preview, Preview) and isinstance(result, Result)
    assert preview.events == result.events
    assert preview.summary["auto_withdrawn"] == result.summary["auto_withdrawn"]
    assert len(cast(list[object], result.summary["auto_withdrawn"])) == 2

    check = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with check.connect() as connection:
            archived_at = await connection.scalar(
                sa.text("SELECT archived_at FROM cycles WHERE id = :id"),
                {"id": cycle_id},
            )
            for status in ("in_progress", "pending_offer"):
                assert (
                    await application_status(connection, applications[status])
                ) == "auto_withdrawn"
            assert (
                await application_status(connection, applications["withdrawn"])
            ) == "withdrawn"
            events = (
                await connection.execute(
                    sa.text("SELECT payload FROM application_events ORDER BY id")
                )
            ).mappings().all()
            preserved = await connection.scalar(
                sa.text("SELECT current_round_id FROM applications WHERE id = :id"),
                {"id": applications["in_progress"]},
            )
    finally:
        await check.dispose()

    assert archived_at is not None
    assert {cast(dict[str, object], row["payload"])["trigger"] for row in events} == {
        "archival"
    }
    assert preserved == round_id


@pytest.mark.asyncio
async def test_CYC1_archive_covers_every_member_not_just_one() -> None:
    admin, _student, cycle_id, _membership, _applications, _round = (
        await _cycle_with_applications(("in_progress",))
    )
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            other = await seed_person(connection, email="other@example.edu")
            await seed_membership(
                connection, cycle_id=cycle_id, enrollment_id=other.enrollment_id
            )
            other_application, _ = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=other.enrollment_id,
                status="in_progress",
                title="Other job",
            )
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    try:
        result = await executor.run(
            "archive_cycle",
            executor.registry.commands["archive_cycle"].input_model.model_validate(
                {"cycle_id": str(cycle_id)}
            ),
            admin.actor,
        )
    finally:
        await engine.dispose()

    assert isinstance(result, Result)
    assert len(cast(list[object], result.summary["auto_withdrawn"])) == 2

    check = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with check.connect() as connection:
            assert (
                await application_status(connection, other_application)
            ) == "auto_withdrawn"
    finally:
        await check.dispose()


@pytest.mark.asyncio
async def test_CYC1_archive_leaves_applications_carrying_offers_untouched() -> None:
    admin, _student, cycle_id, _membership, applications, _round = (
        await _cycle_with_applications(("offered", "accepted"))
    )

    executor, engine = build_test_executor()
    try:
        result = await executor.run(
            "archive_cycle",
            executor.registry.commands["archive_cycle"].input_model.model_validate(
                {"cycle_id": str(cycle_id)}
            ),
            admin.actor,
        )
    finally:
        await engine.dispose()

    assert isinstance(result, Result)
    assert result.summary["auto_withdrawn"] == []
    untouched = cast(list[dict[str, object]], result.summary["untouched"])
    assert {row["status"] for row in untouched} == {"offered", "accepted"}

    check = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with check.connect() as connection:
            assert (
                await application_status(connection, applications["offered"])
            ) == "offered"
    finally:
        await check.dispose()


@pytest.mark.asyncio
async def test_CYC1_an_archived_cycle_cannot_be_archived_again() -> None:
    admin, _student, cycle_id, _membership, _applications, _round = (
        await _cycle_with_applications(())
    )

    executor, engine = build_test_executor()
    payload = executor.registry.commands["archive_cycle"].input_model.model_validate(
        {"cycle_id": str(cycle_id)}
    )
    try:
        await executor.run("archive_cycle", payload, admin.actor)
        with pytest.raises(DomainRejection) as error:
            await executor.run("archive_cycle", payload, admin.actor)
    finally:
        await engine.dispose()

    assert [reason.code for reason in error.value.rejection.reasons] == [CYCLE_ARCHIVED]


@pytest.mark.asyncio
async def test_CYC1_every_cycle_scoped_mutation_rejects_on_an_archived_cycle() -> None:
    """The registry drives this: every command is guarded or explicitly allowed."""
    admin, student, cycle_id, membership_id, _applications, _round = (
        await _cycle_with_applications(())
    )
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            staff = await seed_person(connection, email="coord@example.edu")
            resume_id = await connection.scalar(
                sa.text("SELECT id FROM resumes WHERE enrollment_id = :id"),
                {"id": student.enrollment_id},
            )
            job_id = await seed_job(connection, cycle_id=cycle_id, title="Archived job")
            company_id = await connection.scalar(
                sa.text("SELECT company_id FROM jobs WHERE id = :id"), {"id": job_id}
            )
            override_id = uuid4()
            await connection.execute(
                sa.text(
                    "INSERT INTO overrides (id, rule_domain, allow, cycle_id, reason, "
                    "granted_by, is_active) VALUES (:id, 'offer_deadline', true, "
                    ":cycle_id, 'Granted before archival', :admin, true)"
                ),
                {"id": override_id, "cycle_id": cycle_id, "admin": admin.user_id},
            )
            await connection.execute(
                sa.text("UPDATE cycles SET archived_at = now() WHERE id = :id"),
                {"id": cycle_id},
            )
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    cases: dict[str, tuple[dict[str, object], Person]] = {
        "update_cycle": ({"cycle_id": str(cycle_id), "description": "x"}, admin),
        "set_cycle_active": ({"cycle_id": str(cycle_id), "is_active": False}, admin),
        "update_cycle_policy": (
            {"cycle_id": str(cycle_id), "strike_on_absence": False},
            admin,
        ),
        "assign_coordinator": (
            {"cycle_id": str(cycle_id), "user_id": str(staff.user_id)},
            admin,
        ),
        "remove_coordinator": (
            {"cycle_id": str(cycle_id), "user_id": str(staff.user_id)},
            admin,
        ),
        "archive_cycle": ({"cycle_id": str(cycle_id)}, admin),
        # M14's interventions are cycle-scoped writes like any other, and CYC-1's
        # read-only is unqualified: an override granted on an archived cycle
        # would reopen a gate nobody can act through anyway.
        "create_override": (
            {
                "cycle_id": str(cycle_id),
                "rule_domain": "application_deadline",
                "reason": "x",
            },
            admin,
        ),
        "deactivate_override": ({"override_id": str(override_id)}, admin),
        "reinstate_application": (
            {
                "cycle_id": str(cycle_id),
                "application_id": str(uuid4()),
                "reason": "x",
            },
            admin,
        ),
        "force_transition": (
            {
                "cycle_id": str(cycle_id),
                "application_id": str(uuid4()),
                "to_status": "withdrawn",
                "reason": "x",
            },
            admin,
        ),
        "join_cycle": (
            {
                "cycle_id": str(cycle_id),
                "enrollment_id": str(student.enrollment_id),
                "default_resume_id": str(resume_id),
                "consent": True,
            },
            student,
        ),
        "reject_membership": (
            {
                "cycle_id": str(cycle_id),
                "membership_id": str(membership_id),
                "reason": "x",
            },
            admin,
        ),
        "rerequest_membership": (
            {
                "cycle_id": str(cycle_id),
                "enrollment_id": str(student.enrollment_id),
                "default_resume_id": str(resume_id),
                "consent": True,
            },
            student,
        ),
        "set_outcome_tag": (
            {
                "cycle_id": str(cycle_id),
                "membership_id": str(membership_id),
                "outcome_tag": "not_seeking",
            },
            admin,
        ),
        "withdraw_membership": (
            {"cycle_id": str(cycle_id), "enrollment_id": str(student.enrollment_id)},
            student,
        ),
        "remove_membership": (
            {
                "cycle_id": str(cycle_id),
                "membership_id": str(membership_id),
                "reason": "x",
            },
            admin,
        ),
        "restore_membership": (
            {"cycle_id": str(cycle_id), "membership_id": str(membership_id)},
            admin,
        ),
        # APP-1 is the student's own write, and CYC-1's read-only is
        # unqualified: an archived cycle refuses it before the gates run.
        "apply": (
            {
                "cycle_id": str(cycle_id),
                "job_id": str(job_id),
                "enrollment_id": str(student.enrollment_id),
            },
            student,
        ),
        "edit_application": (
            {
                "cycle_id": str(cycle_id),
                "enrollment_id": str(student.enrollment_id),
                "application_id": str(uuid4()),
            },
            student,
        ),
        "withdraw_application": (
            {
                "cycle_id": str(cycle_id),
                "enrollment_id": str(student.enrollment_id),
                "application_id": str(uuid4()),
            },
            student,
        ),
        "accept_offer": (
            {
                "cycle_id": str(cycle_id),
                "job_id": str(job_id),
                "enrollment_id": str(student.enrollment_id),
                "application_id": str(uuid4()),
                "offer_id": str(uuid4()),
                "expected_status": "offered",
            },
            student,
        ),
        "decline_offer": (
            {
                "cycle_id": str(cycle_id),
                "job_id": str(job_id),
                "enrollment_id": str(student.enrollment_id),
                "application_id": str(uuid4()),
                "offer_id": str(uuid4()),
                "expected_status": "offered",
            },
            student,
        ),
        "terminate_offer": (
            {
                "cycle_id": str(cycle_id),
                "job_id": str(job_id),
                "application_id": str(uuid4()),
                "offer_id": str(uuid4()),
                "expected_status": "offered",
                "termination_kind": "admin_correction",
                "reason": "Archived fixture",
            },
            admin,
        ),
        "re_extend_offer": (
            {
                "cycle_id": str(cycle_id),
                "job_id": str(job_id),
                "application_id": str(uuid4()),
                "offer_id": str(uuid4()),
                "expected_status": "declined",
                "reason": "Archived fixture",
            },
            admin,
        ),
        "attach_external_offer": (
            {
                "cycle_id": str(cycle_id),
                "external_offer_id": str(uuid4()),
                "reason": "Archived fixture",
            },
            admin,
        ),
        "detach_external_offer": (
            {
                "cycle_id": str(cycle_id),
                "external_offer_id": str(uuid4()),
                "expected_attached_cycle_id": str(cycle_id),
                "reason": "Archived fixture",
            },
            admin,
        ),
        "mark_attendance": (
            {
                "cycle_id": str(cycle_id),
                "job_id": str(job_id),
                "round_id": str(uuid4()),
                "application_id": str(uuid4()),
                "attendance": "present",
                "expected_attendance": "pending",
            },
            admin,
        ),
        "finalize_round": (
            {
                "cycle_id": str(cycle_id),
                "job_id": str(job_id),
                "round_id": str(uuid4()),
            },
            admin,
        ),
        "create_job": (
            {
                "cycle_id": str(cycle_id),
                "company_id": str(company_id),
                "title": "Archived",
                "description": "x",
                "application_deadline": "2030-01-01T00:00:00Z",
            },
            admin,
        ),
        "update_job_basics": (
            {"cycle_id": str(cycle_id), "job_id": str(job_id), "title": "x"},
            admin,
        ),
        "update_job_eligibility": (
            {"cycle_id": str(cycle_id), "job_id": str(job_id)},
            admin,
        ),
        "upsert_job_rounds": (
            {"cycle_id": str(cycle_id), "job_id": str(job_id), "rounds": []},
            admin,
        ),
        "upsert_job_questions": (
            {"cycle_id": str(cycle_id), "job_id": str(job_id), "questions": []},
            admin,
        ),
        "publish_job": ({"cycle_id": str(cycle_id), "job_id": str(job_id)}, admin),
        "unpublish_job": ({"cycle_id": str(cycle_id), "job_id": str(job_id)}, admin),
        "save_export_preset": (
            {
                "cycle_id": str(cycle_id),
                "job_id": str(job_id),
                "columns": ["roll_number"],
            },
            admin,
        ),
    }
    single = {
        name
        for name, spec in executor.registry.commands.items()
        if spec.scope == "cycle" and spec.execution_mode == "single"
    }
    assert ARCHIVED_CYCLE_COMMAND_ALLOWLIST <= single
    assert single - ARCHIVED_CYCLE_COMMAND_ALLOWLIST == set(cases), (
        "a cycle-scoped command is neither in the archival guard nor its "
        "explicit read allow-list"
    )

    try:
        for name, (payload, actor) in cases.items():
            model = executor.registry.commands[name].input_model
            with pytest.raises(DomainRejection) as error:
                await executor.run(name, model.model_validate(payload), actor.actor)
            assert [
                reason.code for reason in error.value.rejection.reasons
            ] == [CYCLE_ARCHIVED], name

        # The bulk command takes the same path: its first chunk rejects, and
        # with no chunk committed run_bulk surfaces the rejection itself.
        with pytest.raises(DomainRejection) as bulk_error:
            await executor.run_bulk(
                "approve_memberships",
                [{"membership_id": str(membership_id)}],
                "archived-batch",
                admin.actor,
                batch_fields={"cycle_id": cycle_id},
            )
        assert [
            reason.code for reason in bulk_error.value.rejection.reasons
        ] == [CYCLE_ARCHIVED]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_CYC1_an_archived_cycle_can_be_exported_but_not_mutated() -> None:
    """Exports read closed seasons; the same season remains frozen for writes."""
    admin, _student, cycle_id, _membership, _applications, _round = (
        await _cycle_with_applications(())
    )
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            await connection.execute(
                sa.text("UPDATE cycles SET archived_at = now() WHERE id = :id"),
                {"id": cycle_id},
            )
    finally:
        await migration.dispose()

    executor, engine = build_test_executor()
    export_model = executor.registry.commands["request_export"].input_model
    mutation_model = executor.registry.commands["set_cycle_active"].input_model
    try:
        exported = await executor.run(
            "request_export",
            export_model.model_validate(
                {"cycle_id": str(cycle_id), "kind": "cycle_memberships"}
            ),
            admin.actor,
        )
        with pytest.raises(DomainRejection) as error:
            await executor.run(
                "set_cycle_active",
                mutation_model.model_validate(
                    {"cycle_id": str(cycle_id), "is_active": False}
                ),
                admin.actor,
            )
    finally:
        await engine.dispose()

    assert exported.summary["status"] == "ready"
    assert exported.summary["row_count"] == 1
    assert [reason.code for reason in error.value.rejection.reasons] == [
        CYCLE_ARCHIVED
    ]


@pytest.mark.asyncio
async def test_CYC1_archiving_an_unknown_cycle_is_rejected() -> None:
    admin, _student, _cycle, _membership, _applications, _round = (
        await _cycle_with_applications(())
    )

    executor, engine = build_test_executor()
    try:
        with pytest.raises(DomainRejection):
            await executor.run(
                "archive_cycle",
                executor.registry.commands["archive_cycle"].input_model.model_validate(
                    {"cycle_id": str(uuid4())}
                ),
                admin.actor,
            )
    finally:
        await engine.dispose()
