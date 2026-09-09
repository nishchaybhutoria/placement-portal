"""The development seed must build a world the whole front end can be used on.

`python -m app.seed` is what a developer runs before opening the app, so its
output is a product surface: a screen that renders correctly against an empty
table and wrongly against a populated one is not something anybody will notice
locally.  These tests pin the shape of the world rather than its exact contents,
so the seed can gain rows without churning them, but cannot quietly lose the
states the F1.5 screens exist to show -- a queue with people waiting in it, a
draft job the students must not see, and a rule that some members fail.
"""

from __future__ import annotations

import os
from typing import Any, cast

import pytest
import pytest_asyncio
import sqlalchemy as sa

from app.core.db import create_engine
from app.modules.analytics import metrics
from app.modules.analytics.metrics import MetricFilters
from app.modules.analytics.reports import batch_report
from app.modules.jobs.queries import staff_job_builder, student_cycle_jobs
from app.seed import STUDENTS, run_seed
from app.settings import Settings

pytestmark = pytest.mark.usefixtures("clean_seed")


def seed_settings() -> Settings:
    return Settings(
        session_secret="seed-world-test-session-secret-32-chars",
        allowed_domain="example.edu",
        dev_login=False,
    )


@pytest_asyncio.fixture
async def clean_seed() -> None:
    """The seed has to be judged against an empty database, as a developer runs it."""
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "TRUNCATE audit_log, idempotency_keys, notification_log, "
                    "consistency_findings, overrides, "
                    "application_events, application_answers, "
                    "application_round_states, applications, offers, external_offers, "
                    "export_presets, job_question_options, job_questions, "
                    "job_program_ctc, job_rounds, jobs, "
                    "cycle_memberships, cycle_coordinators, cycle_policies, cycles, "
                    "resumes, profiles, sessions, enrollments, users, companies, "
                    "company_contacts, staged_profile_rows, settings, "
                    "programs, branches, minors, sectors, round_types, "
                    "program_branches, procrastinate_jobs CASCADE"
                )
            )
    finally:
        await engine.dispose()


async def _seed() -> None:
    await run_seed(
        database_url=os.environ["TEST_DATABASE_URL"],
        settings=seed_settings(),
        admin_email="admin@example.edu",
    )


async def _one(sql: str, params: dict[str, object] | None = None) -> Any:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            return await connection.scalar(sa.text(sql), params or {})
    finally:
        await engine.dispose()


async def _all(sql: str, params: dict[str, object] | None = None) -> list[Any]:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            rows = (await connection.execute(sa.text(sql), params or {})).mappings().all()
            return [dict(row) for row in rows]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_the_seed_leaves_people_waiting_in_the_approvals_queue() -> None:
    """An approvals screen with an empty queue shows nothing worth reviewing."""
    await _seed()

    statuses = await _all(
        "SELECT c.name, m.status, count(*) AS n FROM cycle_memberships m "
        "JOIN cycles c ON c.id = m.cycle_id GROUP BY 1, 2"
    )
    placement = {
        str(row["status"]): int(row["n"])
        for row in statuses
        if str(row["name"]) == "Placement 2026"
    }

    assert placement.get("pending", 0) >= 1
    assert placement.get("active", 0) >= 1
    # Everybody joined; the split is approval, not partial membership.
    assert sum(placement.values()) == len(STUDENTS)


@pytest.mark.asyncio
async def test_the_seed_carries_a_draft_job_the_students_cannot_see() -> None:
    """Published and unpublished both have to exist, or neither state is visible."""
    await _seed()

    jobs = await _all(
        "SELECT j.title, j.is_published FROM jobs j JOIN cycles c ON c.id = j.cycle_id "
        "WHERE c.name = 'Placement 2026'"
    )
    published = {str(row["title"]) for row in jobs if row["is_published"]}
    drafts = {str(row["title"]) for row in jobs if not row["is_published"]}

    assert published
    assert drafts

    cycle_id = await _one("SELECT id FROM cycles WHERE name = 'Placement 2026'")
    enrollment_id = await _one(
        "SELECT e.id FROM enrollments e JOIN users u ON u.id = e.user_id WHERE u.email = :email",
        {"email": STUDENTS[0].email},
    )
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        listing = await student_cycle_jobs(engine, cycle_id=cycle_id, enrollment_id=enrollment_id)
    finally:
        await engine.dispose()

    assert listing is not None
    visible = {str(job["title"]) for job in listing["jobs"]}  # type: ignore[index,union-attr]
    assert visible == published
    assert not visible & drafts


@pytest.mark.asyncio
async def test_the_seed_rule_splits_the_membership_and_names_every_value() -> None:
    """A preview where everybody passes demonstrates nothing about the rule.

    This is also the regression guard for taxonomy labels: the reason a member
    fails names their own branch, and the seed is the only fixture where that
    branch is one the rule never mentions.
    """
    await _seed()

    cycle_id = await _one("SELECT id FROM cycles WHERE name = 'Placement 2026'")
    job_id = await _one(
        "SELECT id FROM jobs WHERE title = 'Backend Engineer' AND cycle_id = :cycle_id",
        {"cycle_id": cycle_id},
    )
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        builder = await staff_job_builder(engine, cycle_id=cycle_id, job_id=job_id)
    finally:
        await engine.dispose()

    assert builder is not None
    impact: Any = builder["eligibility"]["impact"]  # type: ignore[index]
    assert 0 < impact["eligible_count"] < impact["member_count"]

    humans = [str(reason["human"]) for member in impact["members"] for reason in member["reasons"]]
    assert humans
    # Every taxonomy value renders by name on both sides of the sentence
    # (the design review 4.19); a bare id here means a label lookup was missed.
    assert not [line for line in humans if "-" in line and len(line.split("-")) > 4]
    assert any("Mechanical Engineering" in line for line in humans)


@pytest.mark.asyncio
async def test_the_seed_builds_a_job_with_every_builder_tab_populated() -> None:
    await _seed()

    cycle_id = await _one("SELECT id FROM cycles WHERE name = 'Placement 2026'")
    job_id = await _one(
        "SELECT id FROM jobs WHERE title = 'Backend Engineer' AND cycle_id = :cycle_id",
        {"cycle_id": cycle_id},
    )
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        builder = await staff_job_builder(engine, cycle_id=cycle_id, job_id=job_id)
    finally:
        await engine.dispose()

    assert builder is not None
    job: Any = builder["job"]
    # One per builder tab: basics, rounds, questions, eligibility. A tab with
    # nothing in it cannot be judged by looking at it.
    assert job["title"]
    assert len(job["rounds"]) >= 2
    assert len(job["questions"]) >= 2
    assert len(job["program_ctc"]) >= 2
    assert builder["eligibility"]["rule"] is not None  # type: ignore[index]
    # More than one question type, so the form renders more than one control.
    assert len({str(q["qtype"]) for q in job["questions"]}) >= 3


@pytest.mark.asyncio
async def test_the_seed_carries_a_duplicate_company_worth_merging() -> None:
    """merge_companies is only demonstrable against a real near-duplicate."""
    await _seed()

    companies = await _all("SELECT id, name FROM companies ORDER BY name")
    names = [str(row["name"]) for row in companies]
    assert len(names) >= 3

    pair = [row for row in companies if str(row["name"]).startswith("Northwind")]
    assert len(pair) == 2
    emails = await _all(
        "SELECT company_id, email FROM company_contacts WHERE company_id = ANY(:ids)",
        {"ids": [row["id"] for row in pair]},
    )
    by_company: dict[Any, set[str]] = {}
    for row in emails:
        by_company.setdefault(row["company_id"], set()).add(str(row["email"]))
    left, right = by_company.values()
    # A shared email is what makes the merge preview's contacts_dropped payload
    # non-empty, which is the half of that screen worth looking at.
    assert left & right
    assert left ^ right


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_the_seed_files_applications_through_the_command() -> None:
    """APP-1 rows a board and a student dashboard can be read against.

    Pinned as states rather than as counts: a pipeline job's application holds
    a round position and an open-cycle one cannot, which is the distinction
    JOB-6 draws and the one a board has to render without a pipeline.
    """
    await _seed()

    rows = await _all(
        "SELECT a.status, a.current_round_id, c.kind, j.title, u.email "
        "FROM applications a "
        "JOIN jobs j ON j.id = a.job_id "
        "JOIN cycles c ON c.id = j.cycle_id "
        "JOIN enrollments e ON e.id = a.enrollment_id "
        "JOIN users u ON u.id = e.user_id"
    )

    assert rows, "the seed files no applications"
    # A withdrawal is part of the world on purpose: the dashboard needs the
    # state that reads as "you left this one", and the freed slot is what makes
    # APP-2's re-application path visible locally.
    assert {row["status"] for row in rows} == {
        "in_progress",
        "withdrawn",
        "rejected",
        "offered",
        "accepted",
        "offer_terminated",
        # M14's winter cohort: an offer whose auto-accept revalidation failed at
        # fire time and fell back to declining (OFR-4).
        "declined",
    }
    assert sum(1 for row in rows if row["status"] == "withdrawn") == 1
    # The rejected row is the deliberately absent quant applicant closed by
    # M11 finalization; the flagship board remains live for round operations.
    assert sum(1 for row in rows if row["status"] == "rejected") == 1
    pipeline = [row for row in rows if row["kind"] != "open"]
    open_cycle = [row for row in rows if row["kind"] == "open"]
    assert pipeline and open_cycle, "both kinds must be represented"
    # Status changes caused by offers preserve pipeline position. The intern
    # role has no rounds configured, so its offered/accepted rows correctly
    # carry no position; the position follows the job, not the status.
    with_rounds = [row for row in pipeline if row["title"] != "Software Engineering Intern"]
    assert with_rounds
    assert all(row["current_round_id"] is not None for row in with_rounds)
    assert all(row["current_round_id"] is None for row in open_cycle)

    # Every application carries the event that created it, and the flagship's
    # answers came along with it.
    events = await _one("SELECT count(*) FROM application_events WHERE event_type = 'created'")
    assert events == len(rows)
    answered = await _one(
        "SELECT count(*) FROM application_answers ans "
        "JOIN applications a ON a.id = ans.application_id "
        "JOIN jobs j ON j.id = a.job_id WHERE j.title = 'Backend Engineer'"
    )
    assert answered > 0


@pytest.mark.asyncio
async def test_the_seed_only_admits_students_the_rule_allows() -> None:
    """Nobody the flagship rule excludes has an application to it.

    The seed is the world every screen is judged against, so an application
    that the job's own rule would have refused would make the board show a
    state ``apply`` cannot produce.
    """
    await _seed()

    excluded = await _all(
        "SELECT u.email FROM applications a "
        "JOIN jobs j ON j.id = a.job_id "
        "JOIN enrollments e ON e.id = a.enrollment_id "
        "JOIN users u ON u.id = e.user_id "
        "JOIN profiles p ON p.enrollment_id = e.id "
        "WHERE j.title = 'Backend Engineer' AND p.cpi < 8.0"
    )

    assert excluded == []


@pytest.mark.asyncio
async def test_the_seed_marks_a_sheet_and_publishes_a_slot() -> None:
    """RND-3 and RND-4 states a board can be read against, not just pending rows.

    Pinned as states rather than counts, for the same reason the application
    test is: what matters is that the board has a marked row, an unmarked one
    and a published slot to render, not how many of each there happen to be.
    """
    await _seed()

    rows = await _all(
        "SELECT u.email, j.title, r.ord, s.attendance, s.venue_override, "
        "       s.scheduled_at_override, s.notified_at "
        "FROM application_round_states s "
        "JOIN applications a ON a.id = s.application_id "
        "JOIN jobs j ON j.id = a.job_id "
        "JOIN enrollments e ON e.id = a.enrollment_id "
        "JOIN users u ON u.id = e.user_id "
        "JOIN job_rounds r ON r.id = s.round_id"
    )

    marked = {str(row["attendance"]) for row in rows}
    assert {"present", "absent", "pending"} <= marked
    published = [row for row in rows if row["venue_override"] is not None]
    assert published, "no slot is published, so the board renders no venue"
    for row in published:
        # Publishing is what notifies (RND-4), so a venue without the stamp
        # would mean a student was given a room nobody told them about.
        assert row["scheduled_at_override"] is not None
        assert row["notified_at"] is not None
    assert any(row["venue_override"] is None for row in rows), (
        "every slot is overridden, so the round-default case is unrendered"
    )

    # The marks are on the timeline, not only in the state row.
    events = await _one(
        "SELECT count(*) FROM application_events "
        "WHERE event_type IN ('attendance_marked', 'venue_assigned')"
    )
    assert events >= len(published) + 2


@pytest.mark.asyncio
async def test_the_seed_closes_a_round_and_builds_discipline_through_commands() -> None:
    """Every M11 write path leaves a state its two screens can display."""
    await _seed()

    closed = await _all(
        "SELECT r.finalized_at, r.finalized_by FROM job_rounds r "
        "JOIN jobs j ON j.id = r.job_id "
        "WHERE j.title = 'Quantitative Researcher' AND r.ord = 1"
    )
    assert closed[0]["finalized_at"] is not None
    assert closed[0]["finalized_by"] is not None

    records = await _all(
        "SELECT 'strike' AS kind, is_active FROM strikes "
        "UNION ALL SELECT 'penalty' AS kind, is_active FROM penalties"
    )
    assert any(row["kind"] == "strike" and row["is_active"] for row in records)
    assert any(row["kind"] == "strike" and not row["is_active"] for row in records)
    assert any(row["kind"] == "penalty" and row["is_active"] for row in records)
    assert any(row["kind"] == "penalty" and not row["is_active"] for row in records)

    actions = {
        str(row["action"])
        for row in await _all(
            "SELECT DISTINCT action FROM audit_log WHERE action IN "
            "('finalize_round', 'award_strike', 'revoke_strike', "
            "'award_penalty', 'revoke_penalty')"
        )
    }
    assert actions == {
        "finalize_round",
        "award_strike",
        "revoke_strike",
        "award_penalty",
        "revoke_penalty",
    }


@pytest.mark.asyncio
async def test_the_seed_covers_M12_portal_external_and_restoration_scenarios() -> None:
    """The four M12 screens must open on consequential, reachable states."""
    await _seed()

    portal = await _all(
        "SELECT u.email, a.status, count(o.id) AS offer_rows, "
        "bool_or(o.response = 'accepted') AS has_accepted, "
        "bool_or(o.response = 'declined') AS has_declined, "
        "bool_or(o.terminated_at IS NOT NULL) AS has_terminated "
        "FROM applications a JOIN offers o ON o.application_id = a.id "
        "JOIN enrollments e ON e.id = a.enrollment_id "
        "JOIN users u ON u.id = e.user_id "
        "GROUP BY u.email, a.id, a.status"
    )
    statuses = {str(row["status"]) for row in portal}
    assert {"offered", "accepted", "offer_terminated"} <= statuses
    bikram = next(row for row in portal if row["email"] == "bikram.singh@example.edu")
    assert bikram["offer_rows"] == 2
    assert bikram["has_declined"] is True
    asha = next(row for row in portal if row["email"] == "asha.mehta@example.edu")
    assert asha["has_terminated"] is True
    # Farhan holds more than one offer row since M14 gave him the winter
    # cohort's expired one, so the M12 claim is "he has an accepted offer",
    # not "his first row is the accepted one".
    farhan = [row for row in portal if row["email"] == "farhan.khan@example.edu"]
    assert any(row["has_accepted"] for row in farhan)

    external = await _all(
        "SELECT u.email, eo.outcome, eo.status, eo.attached_cycle_id, eo.notes "
        "FROM external_offers eo "
        "JOIN enrollments e ON e.id = eo.enrollment_id "
        "JOIN users u ON u.id = e.user_id ORDER BY u.email, eo.notes"
    )
    assert {str(row["status"]) for row in external} == {
        "offered",
        "accepted",
        "declined",
    }
    dev = next(row for row in external if row["email"] == "dev.patel@example.edu")
    assert dev["outcome"] == "placement"
    assert dev["status"] == "accepted"
    assert dev["attached_cycle_id"] is None
    chitra = next(row for row in external if row["email"] == "chitra.rao@example.edu")
    assert chitra["outcome"] == "internship"
    assert chitra["status"] == "accepted"
    assert chitra["attached_cycle_id"] is not None
    auto_membership = await _one(
        "SELECT count(*) FROM cycle_memberships m "
        "JOIN enrollments e ON e.id = m.enrollment_id "
        "JOIN users u ON u.id = e.user_id "
        "WHERE u.email = 'chitra.rao@example.edu' AND m.auto_created "
        "AND m.status = 'active'"
    )
    assert auto_membership == 1

    # Asha's temporary accepted PPO caused and then compensated a cascade.
    history = await _all(
        "SELECT ev.event_type, ev.from_status, ev.to_status, ev.payload "
        "FROM application_events ev JOIN applications a ON a.id = ev.application_id "
        "JOIN jobs j ON j.id = a.job_id "
        "JOIN enrollments e ON e.id = a.enrollment_id "
        "JOIN users u ON u.id = e.user_id "
        "WHERE u.email = 'asha.mehta@example.edu' AND j.title = 'Backend Engineer' "
        "ORDER BY ev.created_at, ev.id"
    )
    assert any(row["event_type"] == "auto_withdrawn" for row in history)
    assert any(row["event_type"] == "reinstated" for row in history)
    assert any(row["event_type"] == "offer_terminated" for row in history)


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_the_seed_makes_every_analytics_dashboard_show_something_real() -> None:
    """M15: a seeded dashboard whose figures are all zero proves nothing.

    Three things have to be non-zero, because a broken query looks exactly like
    a correct one when they are not: the *external* half of ANA-1's placed
    split in the placement cycle, *both* halves somewhere a user actually
    looks, and an outcome tag separating the two ANA-3 denominators. Without
    them, a dashboard that silently drops attached externals -- or one that
    ignores tags -- renders identically to a working one.

    The placement cycle's own on-campus half is deliberately zero: M12 seeds
    Asha's acceptance terminated for the restoration demo and leaves Bikram's
    offer open for the student dashboard, so the portal half of that split is
    genuinely empty and is asserted portal-wide instead.
    """
    await run_seed(settings=seed_settings())
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            placement_id = await connection.scalar(
                sa.text("SELECT id FROM cycles WHERE kind = 'placement' LIMIT 1")
            )
            assert placement_id is not None
            cycle_funnel = await metrics.funnel(
                connection, MetricFilters(cycle_ids=(placement_id,))
            )
            everywhere = await metrics.placed(connection, MetricFilters())
            report = await batch_report(
                connection,
                MetricFilters(cycle_ids=(placement_id,)),
                program_labels={},
            )
    finally:
        await engine.dispose()

    placed = cast("dict[str, Any]", cycle_funnel.as_dict()["placed"])
    assert placed["total"] > 0, "nobody is placed in the seeded placement cycle"
    assert placed["split"]["external"] > 0, (
        "the placement cycle has no externally-driven placement, so its split "
        "renders as all-portal and cannot distinguish a working attachment "
        "scope from a broken one"
    )
    assert placed["external_sources"]["ppo"] > 0, "the PPO bucket is empty"
    assert placed["split"]["portal"] + placed["split"]["external"] == placed["total"]

    # Both halves have to appear somewhere, or the split's on-campus side is
    # never exercised by any seeded page.
    across = everywhere.split
    assert across["portal"] > 0, "no on-campus acceptance anywhere in the seed"
    assert across["ppo"] + across["off_campus"] + across["other"] > 0

    total = cast("dict[str, Any]", report["total"])
    assert int(total["higher_studies"]) > 0, "no tagged member for the ANA-3 column"
    assert int(total["registered_seeking"]) < int(total["registered"]), (
        "the seeking-only denominator is identical to the flat one, so the two "
        "rates the report exists to distinguish cannot be told apart"
    )


@pytest.mark.asyncio
async def test_the_seed_is_idempotent() -> None:
    await _seed()
    first = {
        table: await _one(f"SELECT count(*) FROM {table}")  # noqa: S608
        for table in (
            "audit_log",
            "users",
            "cycles",
            "companies",
            "company_contacts",
            "jobs",
            "job_rounds",
            "job_questions",
            "resumes",
            "cycle_memberships",
            "profiles",
            "cycle_coordinators",
            "applications",
            "application_answers",
            "application_round_states",
            "application_events",
            "strikes",
            "penalties",
            "offers",
            "external_offers",
            "overrides",
            "consistency_findings",
        )
    }

    await _seed()
    second = {
        table: await _one(f"SELECT count(*) FROM {table}")  # noqa: S608
        for table in first
    }

    assert second == first


@pytest.mark.asyncio
async def test_the_seed_builds_the_M14_override_finding_and_snapshot_drift() -> None:
    """admin/overrides, admin/findings and the drill-down need real rows.

    The finding is earned by a real expiry rather than planted, then closed by
    the seed's administrator so the seeded world has history but no launch debt.
    """
    await _seed()

    overrides = await _all(
        "SELECT o.rule_domain, o.is_active, o.expires_at, c.name AS cycle "
        "FROM overrides o JOIN cycles c ON c.id = o.cycle_id ORDER BY o.rule_domain"
    )
    assert [row["rule_domain"] for row in overrides] == [
        "application_deadline",
        "offer_cap",
    ]
    live = next(row for row in overrides if row["rule_domain"] == "application_deadline")
    assert live["is_active"] is True and live["expires_at"] is not None
    revoked = next(row for row in overrides if row["rule_domain"] == "offer_cap")
    assert revoked["is_active"] is False

    findings = await _all(
        "SELECT invariant, status, suggested_fix, detail FROM consistency_findings"
    )
    assert len(findings) == 1
    assert findings[0]["invariant"] == "offer_expiry_auto_accept_gate_failed"
    assert findings[0]["status"] == "resolved"
    # the design review section 4.29: the worker's own finding carries a fix from the
    # same catalog the nightly checker writes from.
    assert findings[0]["suggested_fix"] == "re_extend_offer"
    assert "membership_not_active" in str(findings[0]["detail"])

    # The offer that produced it was auto-declined rather than auto-accepted.
    declined = await _one(
        "SELECT count(*) FROM offers o JOIN applications a ON a.id = o.application_id "
        "JOIN jobs j ON j.id = a.job_id JOIN cycles c ON c.id = j.cycle_id "
        "WHERE c.name = 'Winter Internship 2026' AND o.response = 'declined'"
    )
    assert declined == 1

    snapshot_cpi = await _one(
        "SELECT a.profile_snapshot ->> 'cpi' FROM applications a "
        "JOIN enrollments e ON e.id = a.enrollment_id "
        "JOIN users u ON u.id = e.user_id "
        "WHERE u.email = 'asha.mehta@example.edu' ORDER BY a.applied_at LIMIT 1"
    )
    live_cpi = await _one(
        "SELECT p.cpi::text FROM profiles p JOIN enrollments e ON e.id = p.enrollment_id "
        "JOIN users u ON u.id = e.user_id WHERE u.email = 'asha.mehta@example.edu'"
    )
    assert live_cpi == "9.12"
    assert snapshot_cpi != live_cpi


@pytest.mark.asyncio
async def test_the_seeded_world_passes_its_own_consistency_check() -> None:
    """The strongest statement the seed can make about itself.

    Every invariant in LLD section 12 asserted against a world built entirely by
    commands: if the seed can produce drift, so can the application.
    """
    await _seed()

    from app.bootstrap import build_executor, build_registry
    from app.core.plan import ActorContext
    from app.modules.admin.commands import RunConsistencyCheckerInput

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        executor = build_executor(build_registry(settings=seed_settings()), engine)
        result = await executor.run(
            "run_consistency_checker",
            RunConsistencyCheckerInput(),
            ActorContext(principal_id="system", is_system=True),
        )
    finally:
        await engine.dispose()

    assert result.summary["violations"] == 0, result.summary["by_invariant"]
    assert result.summary["findings_opened"] == 0
