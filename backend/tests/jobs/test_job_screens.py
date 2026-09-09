"""The four job screens (LLD section 11.3, Behavior JOB-2, JOB-4, ELG-3).

The student pair answers one question -- can I apply, and if not why -- so most
of these tests are about the verdict: that it is complete, that it names things
by their names, and that the screen never leaks a job the student is not
supposed to know exists.  The staff pair is here too because both sides read
the same job rows through the same template.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.domain.rule_text import NO_RULE_SUMMARY
from app.domain.shared import RuleDomain, domains_for_scope
from app.modules.jobs.queries import (
    staff_cycle_jobs,
    staff_job_builder,
    student_cycle_jobs,
    student_job_detail,
)
from tests.cycles.conftest import Person
from tests.jobs.conftest import (
    seed_admin,
    seed_application,
    seed_complete_profile,
    seed_cycle,
    seed_job,
    seed_membership,
    seed_person,
    seed_taxonomy,
)
from tests.overrides.conftest import grant


def _read_engine():  # noqa: ANN202 - test helper
    return create_engine(os.environ["TEST_DATABASE_URL"])


def _write_engine():  # noqa: ANN202 - test helper
    return create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])


async def _set_rule(job_id: UUID, rule: dict[str, object], summary: str) -> None:
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "UPDATE jobs SET eligibility_rule = CAST(:rule AS jsonb), "
                    "eligibility_summary = :summary WHERE id = :id"
                ),
                {"rule": json.dumps(rule), "summary": summary, "id": job_id},
            )
    finally:
        await engine.dispose()


async def _member_and_job(
    *,
    cpi: str = "8.40",
    membership_status: str = "active",
    published: bool = True,
) -> tuple[Person, UUID, UUID, UUID, UUID]:
    """One active member of a placement cycle, and one job in it."""
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            await seed_admin(connection)
            program_id, branch_id = await seed_taxonomy(connection)
            student = await seed_person(connection, email="asha@example.edu")
            resume_id = await seed_complete_profile(
                connection, student, program_id=program_id, branch_id=branch_id, cpi=cpi
            )
            cycle_id = await seed_cycle(connection)
            await seed_membership(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status=membership_status,
                resume_id=resume_id,
            )
            job_id = await seed_job(
                connection, cycle_id=cycle_id, is_published=published
            )
    finally:
        await engine.dispose()
    return student, cycle_id, job_id, program_id, branch_id


@pytest.mark.asyncio
async def test_JOB4_an_eligible_card_carries_the_verdict_and_no_reasons() -> None:
    student, cycle_id, job_id, _program, _branch = await _member_and_job()

    engine = _read_engine()
    try:
        screen = await student_cycle_jobs(
            engine, cycle_id=cycle_id, enrollment_id=student.enrollment_id
        )
    finally:
        await engine.dispose()

    assert screen is not None
    cards = cast(list[dict[str, object]], screen["jobs"])
    assert [card["id"] for card in cards] == [str(job_id)]
    assert cards[0]["eligible"] is True
    assert cards[0]["reasons"] == []
    assert cards[0]["application"] is None
    assert screen["eligible_count"] == 1
    assert screen["membership_status"] == "active"


@pytest.mark.asyncio
async def test_JOB4_an_unpublished_job_is_absent_from_the_student_screens() -> None:
    student, cycle_id, job_id, _program, _branch = await _member_and_job(
        published=False
    )

    engine = _read_engine()
    try:
        listing = await student_cycle_jobs(
            engine, cycle_id=cycle_id, enrollment_id=student.enrollment_id
        )
        detail = await student_job_detail(
            engine, job_id=job_id, enrollment_id=student.enrollment_id
        )
    finally:
        await engine.dispose()

    assert listing is not None
    # Absent, not present-and-ineligible: an unpublished job is a draft, and a
    # draft is not something the student is allowed to know exists (JOB-4).
    assert listing["jobs"] == []
    assert listing["eligible_count"] == 0
    # The detail screen returns None so the route can 404 rather than reveal
    # the job by the shape of its refusal.
    assert detail is None


@pytest.mark.asyncio
async def test_ELG3_a_card_reports_every_reason_gates_and_rule_together() -> None:
    student, cycle_id, job_id, program_id, _branch = await _member_and_job(
        cpi="6.50", membership_status="pending"
    )
    await _set_rule(
        job_id,
        {"all": [
            {"field": "program_id", "op": "eq", "value": str(program_id)},
            {"field": "cpi", "op": "gte", "value": 8.0},
        ]},
        "Eligible when program BTech and CPI at least 8.0.",
    )

    engine = _read_engine()
    try:
        detail = await student_job_detail(
            engine, job_id=job_id, enrollment_id=student.enrollment_id
        )
    finally:
        await engine.dispose()

    assert detail is not None
    eligibility = cast(dict[str, object], detail["eligibility"])
    reasons = cast(list[dict[str, object]], eligibility["reasons"])
    codes = [reason["code"] for reason in reasons]

    assert eligibility["eligible"] is False
    # Both halves run even when the gate already failed: a student told only
    # "membership not active" would fix that, come back, and only then discover
    # the CPI floor they could have seen the first time (ELG-3).
    assert "membership_not_active" in codes
    assert "not_eligible" in codes
    cpi_reason = next(
        reason for reason in reasons if reason["code"] == "not_eligible"
    )
    # The shortfall names the student's own value, so the reason is actionable
    # rather than a restatement of the rule.
    assert cpi_reason["human"] == "Requires CPI at least 8.0; yours is 6.5."
    # The satisfied half of the rule contributes no reason.
    assert len(reasons) == 2
    assert eligibility["summary"] == "Eligible when program BTech and CPI at least 8.0."


@pytest.mark.asyncio
async def test_JOB4_a_job_with_no_rule_says_so_rather_than_showing_a_blank() -> None:
    student, _cycle_id, job_id, _program, _branch = await _member_and_job()

    engine = _read_engine()
    try:
        detail = await student_job_detail(
            engine, job_id=job_id, enrollment_id=student.enrollment_id
        )
    finally:
        await engine.dispose()

    assert detail is not None
    eligibility = cast(dict[str, object], detail["eligibility"])
    assert eligibility["summary"] == NO_RULE_SUMMARY
    assert eligibility["eligible"] is True


@pytest.mark.asyncio
async def test_JOB2_the_detail_shows_this_student_s_program_ctc_not_the_headline() -> None:
    student, _cycle_id, job_id, program_id, _branch = await _member_and_job()
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text("UPDATE jobs SET ctc_lpa = 18.00 WHERE id = :id"),
                {"id": job_id},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO job_program_ctc (id, job_id, program_id, ctc_lpa) "
                    "VALUES (:id, :job_id, :program_id, 24.50)"
                ),
                {"id": uuid4(), "job_id": job_id, "program_id": program_id},
            )
    finally:
        await engine.dispose()

    engine = _read_engine()
    try:
        detail = await student_job_detail(
            engine, job_id=job_id, enrollment_id=student.enrollment_id
        )
    finally:
        await engine.dispose()

    assert detail is not None
    compensation = cast(dict[str, object], detail["compensation"])
    # JOB-2.1: the student sees their own number, not both, and the screen says
    # which one it is so the UI need not guess.
    assert Decimal(str(compensation["ctc_lpa"])) == Decimal("24.50")
    assert compensation["source"] == "program"


@pytest.mark.asyncio
async def test_JOB4_the_detail_hides_the_builder_only_fields_from_the_student() -> None:
    student, cycle_id, job_id, _program, _branch = await _member_and_job()
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            round_type_id = uuid4()
            await connection.execute(
                sa.text(
                    "INSERT INTO round_types (id, name, is_active) "
                    "VALUES (:id, 'Interview', true)"
                ),
                {"id": round_type_id},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO job_rounds (id, job_id, round_type_id, ord, name) "
                    "VALUES (:id, :job_id, :round_type_id, 1, 'Screening')"
                ),
                {"id": uuid4(), "job_id": job_id, "round_type_id": round_type_id},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO job_questions (id, job_id, ord, text, qtype, "
                    "required) VALUES (:id, :job_id, 1, 'Why this role?', "
                    "CAST('longtext' AS question_type_t), true)"
                ),
                {"id": uuid4(), "job_id": job_id},
            )
    finally:
        await engine.dispose()

    engine = _read_engine()
    try:
        detail = await student_job_detail(
            engine, job_id=job_id, enrollment_id=student.enrollment_id
        )
    finally:
        await engine.dispose()

    assert detail is not None
    rounds = cast(list[dict[str, object]], detail["rounds"])
    questions = cast(
        list[dict[str, object]],
        cast(dict[str, object], detail["apply_form"])["questions"],
    )
    assert [round_["name"] for round_ in rounds] == ["Screening"]
    # "deletable", "removable", and "retypable" are builder-lock state: they
    # answer a staff question and would be noise, or a hint, to a student.
    assert "deletable" not in rounds[0]
    assert {"removable", "retypable", "answer_count"} & set(questions[0]) == set()
    assert questions[0]["text"] == "Why this role?"


@pytest.mark.asyncio
async def test_JOB4_an_existing_application_is_reported_on_both_screens() -> None:
    student, cycle_id, job_id, _program, _branch = await _member_and_job()
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            application_id, _round = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                job_id=job_id,
            )
    finally:
        await engine.dispose()

    engine = _read_engine()
    try:
        listing = await student_cycle_jobs(
            engine, cycle_id=cycle_id, enrollment_id=student.enrollment_id
        )
        detail = await student_job_detail(
            engine, job_id=job_id, enrollment_id=student.enrollment_id
        )
    finally:
        await engine.dispose()

    assert listing is not None
    assert detail is not None
    card = cast(list[dict[str, object]], listing["jobs"])[0]
    expected = {"application_id": str(application_id), "status": "in_progress"}
    assert card["application"] == expected
    assert detail["application"] == expected
    # An application in flight is itself a reason the student cannot apply
    # again, so the card must not go on saying "eligible".
    assert card["eligible"] is False
    assert "duplicate_application" in [
        reason["code"] for reason in cast(list[dict[str, object]], card["reasons"])
    ]


@pytest.mark.asyncio
async def test_JOB2_the_staff_listing_counts_what_it_will_not_show_the_student() -> None:
    student, cycle_id, job_id, _program, _branch = await _member_and_job()
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            draft_id = await seed_job(
                connection, cycle_id=cycle_id, title="Draft Role", is_published=False
            )
            await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                job_id=job_id,
            )
    finally:
        await engine.dispose()

    engine = _read_engine()
    try:
        staff = await staff_cycle_jobs(engine, cycle_id)
        student_view = await student_cycle_jobs(
            engine, cycle_id=cycle_id, enrollment_id=student.enrollment_id
        )
    finally:
        await engine.dispose()

    assert staff is not None
    assert student_view is not None
    jobs = cast(list[dict[str, object]], staff["jobs"])
    # Staff see the draft; the student does not. The two screens read the same
    # rows and differ only in the published filter.
    assert {str(job["id"]) for job in jobs} == {str(job_id), str(draft_id)}
    assert {str(job["id"]) for job in cast(list[dict[str, object]], student_view["jobs"])} == {
        str(job_id)
    }
    published = next(job for job in jobs if str(job["id"]) == str(job_id))
    assert published["application_count"] == 1


@pytest.mark.asyncio
async def test_JOB2_the_builder_previews_the_rule_against_the_live_membership() -> None:
    student, cycle_id, job_id, program_id, _branch = await _member_and_job(cpi="6.50")
    await _set_rule(
        job_id,
        {"field": "cpi", "op": "gte", "value": 8.0},
        "Eligible when CPI at least 8.0.",
    )

    engine = _read_engine()
    try:
        builder = await staff_job_builder(engine, cycle_id=cycle_id, job_id=job_id)
        missing = await staff_job_builder(engine, cycle_id=cycle_id, job_id=uuid4())
    finally:
        await engine.dispose()

    assert builder is not None
    eligibility = cast(dict[str, object], builder["eligibility"])
    impact = cast(dict[str, object], eligibility["impact"])
    members = cast(list[dict[str, object]], impact["members"])
    assert impact["member_count"] == 1
    assert impact["eligible_count"] == 0
    # The preview names who fails and why, so staff can see the cost of a floor
    # before saving it rather than after.
    assert members[0]["enrollment_id"] == str(student.enrollment_id)
    assert [reason["code"] for reason in cast(list[dict[str, object]], members[0]["reasons"])] == [
        "not_eligible"
    ]
    # JOB-6: a placement cycle's builder gets the rounds tab.
    assert cast(dict[str, object], builder["cycle"])["supports_rounds"] is True
    assert builder["override_domains"] == [
        domain.value for domain in domains_for_scope("job")
    ]
    assert builder["overrides"] == []
    assert missing is None


@pytest.mark.asyncio
async def test_INT2_job_builder_classifies_active_expired_and_shadowed_overrides() -> None:
    _student, cycle_id, job_id, _program, _branch = await _member_and_job()
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            admin_id = cast(
                UUID,
                await connection.scalar(
                    sa.text("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
                ),
            )
            cycle_override = await grant(
                connection,
                domain=RuleDomain.OFFER_CAP,
                granted_by=admin_id,
                cycle_id=cycle_id,
            )
            job_override = await grant(
                connection,
                domain=RuleDomain.OFFER_CAP,
                granted_by=admin_id,
                job_id=job_id,
                allow=False,
            )
            expired = await grant(
                connection,
                domain=RuleDomain.OFFER_DEADLINE,
                granted_by=admin_id,
                job_id=job_id,
                expires_at=datetime.now(UTC) - timedelta(days=1),
            )
    finally:
        await engine.dispose()

    engine = _read_engine()
    try:
        builder = await staff_job_builder(
            engine, cycle_id=cycle_id, job_id=job_id
        )
    finally:
        await engine.dispose()
    assert builder is not None
    states = {
        row["id"]: row["state"]
        for row in cast("list[dict[str, object]]", builder["overrides"])
    }
    assert states == {
        str(job_override): "active",
        str(cycle_override): "shadowed",
        str(expired): "expired",
    }


@pytest.mark.asyncio
async def test_ELG3_a_shortfall_names_the_student_s_own_branch_not_its_uuid() -> None:
    """The student's value renders by name, like the rule's does.

    The rule's taxonomy ids resolve because the caller collects them from the
    rule; the student's own branch is not in the rule, so it was rendering as a
    raw UUID -- "yours is bfdd47ee-..." -- in the one sentence that exists to
    tell them what to do about it (the design review 4.19).
    """
    student, cycle_id, job_id, _program, branch_id = await _member_and_job()
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            other_branch = uuid4()
            await connection.execute(
                sa.text(
                    "INSERT INTO branches (id, name, is_active) "
                    "VALUES (:id, 'Mechanical Engineering', true)"
                ),
                {"id": other_branch},
            )
    finally:
        await engine.dispose()
    # A rule naming only the branch the student is *not* in: their own branch
    # appears nowhere in the rule, which is what used to leave it unresolved.
    await _set_rule(
        job_id,
        {"field": "primary_branch_id", "op": "eq", "value": str(other_branch)},
        "Eligible when primary branch Mechanical Engineering.",
    )

    engine = _read_engine()
    try:
        detail = await student_job_detail(
            engine, job_id=job_id, enrollment_id=student.enrollment_id
        )
        listing = await student_cycle_jobs(
            engine, cycle_id=cycle_id, enrollment_id=student.enrollment_id
        )
        builder = await staff_job_builder(engine, cycle_id=cycle_id, job_id=job_id)
    finally:
        await engine.dispose()

    assert detail is not None
    assert listing is not None
    assert builder is not None
    expected = (
        "Requires primary branch Mechanical Engineering; yours is CSE."
    )
    reasons = cast(
        list[dict[str, object]],
        cast(dict[str, object], detail["eligibility"])["reasons"],
    )
    assert [reason["human"] for reason in reasons] == [expected]
    # All three readers of a rule resolve the same way; the listing and the
    # builder's impact preview each collect labels separately.
    card = cast(list[dict[str, object]], listing["jobs"])[0]
    assert [
        reason["human"] for reason in cast(list[dict[str, object]], card["reasons"])
    ] == [expected]
    members = cast(
        list[dict[str, object]],
        cast(dict[str, object], cast(dict[str, object], builder["eligibility"])["impact"])[
            "members"
        ],
    )
    assert [
        reason["human"]
        for reason in cast(list[dict[str, object]], members[0]["reasons"])
    ] == [expected]
