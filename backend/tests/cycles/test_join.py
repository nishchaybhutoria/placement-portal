"""Joining a cycle: window, completeness, join rule, consent (Behavior CYC-3)."""

from __future__ import annotations

import os
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import (
    CONSENT_REQUIRED,
    CYCLE_ARCHIVED,
    CYCLE_INACTIVE,
    INVALID_TRANSITION,
    JOIN_RULE_FAILED,
    MEMBERSHIP_EXISTS,
    PROFILE_INCOMPLETE,
    REGISTRATION_CLOSED,
    RESUME_NOT_FOUND,
    AuthorizationDenied,
    DomainRejection,
)
from app.core.plan import Preview, Result
from app.domain.shared import RuleDomain
from tests.cycles.conftest import (
    Person,
    build_test_executor,
    seed_admin,
    seed_complete_profile,
    seed_cycle,
    seed_membership,
    seed_person,
    seed_taxonomy,
)
from tests.overrides.conftest import grant

pytestmark = pytest.mark.usefixtures("clean_cycles")


async def _student_in(
    *,
    kind: str = "placement",
    is_active: bool = True,
    registration_open: bool = True,
    archived: bool = False,
    join_rule: str | None = None,
    declared: bool = True,
    with_resume: bool = True,
    cpi: str = "8.40",
) -> tuple[Person, UUID, UUID | None]:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
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
                declared=declared,
                with_resume=with_resume,
                cpi=cpi,
            )
            cycle_id = await seed_cycle(
                connection,
                kind=kind,
                is_active=is_active,
                registration_open=registration_open,
                archived=archived,
                join_rule=join_rule,
            )
    finally:
        await engine.dispose()
    return student, cycle_id, resume_id


async def _join(
    student: Person,
    cycle_id: UUID,
    resume_id: UUID | None,
    *,
    consent: bool = True,
    dry_run: bool = False,
) -> Preview | Result:
    executor, engine = build_test_executor()
    model = executor.registry.commands["join_cycle"].input_model
    try:
        return await executor.run(
            "join_cycle",
            model.model_validate(
                {
                    "cycle_id": str(cycle_id),
                    "enrollment_id": str(student.enrollment_id),
                    "default_resume_id": str(resume_id or uuid4()),
                    "consent": consent,
                }
            ),
            student.actor,
            dry_run=dry_run,
        )
    finally:
        await engine.dispose()


async def _grant_join_override(
    student: Person, cycle_id: UUID, domain: RuleDomain
) -> UUID:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin_id = cast(
                UUID,
                await connection.scalar(
                    sa.text("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
                ),
            )
            return await grant(
                connection,
                domain=domain,
                granted_by=admin_id,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
            )
    finally:
        await engine.dispose()


async def _join_codes(*args: object, **kwargs: object) -> list[str]:
    with pytest.raises(DomainRejection) as error:
        await _join(*args, **kwargs)  # type: ignore[arg-type]
    return [reason.code for reason in error.value.rejection.reasons]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "status"),
    [("placement", "pending"), ("internship", "pending"), ("open", "active")],
)
async def test_CYC3_join_lands_per_the_kind_s_approval_default(
    kind: str, status: str
) -> None:
    student, cycle_id, resume_id = await _student_in(kind=kind)

    result = await _join(student, cycle_id, resume_id)

    assert isinstance(result, Result)
    assert result.summary["status"] == status

    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    sa.text("SELECT * FROM cycle_memberships WHERE cycle_id = :id"),
                    {"id": cycle_id},
                )
            ).mappings().one()
            queued = (
                await connection.scalars(sa.text("SELECT task_name FROM procrastinate_jobs"))
            ).all()
    finally:
        await engine.dispose()

    assert row["status"] == status
    assert row["consented_at"] is not None
    assert row["default_resume_id"] == resume_id
    assert row["auto_created"] is False
    # Only a pending join tells the student to wait; an auto-active join has no key.
    assert len(list(queued)) == (1 if status == "pending" else 0)


@pytest.mark.asyncio
async def test_CYC3_join_preview_matches_execution() -> None:
    student, cycle_id, resume_id = await _student_in()

    preview = await _join(student, cycle_id, resume_id, dry_run=True)
    executed = await _join(student, cycle_id, resume_id)

    assert isinstance(preview, Preview) and isinstance(executed, Result)
    assert preview.events == executed.events
    assert preview.summary["status"] == executed.summary["status"]


@pytest.mark.asyncio
async def test_CYC3_an_incomplete_profile_is_blocked_with_the_whole_checklist() -> None:
    student, cycle_id, resume_id = await _student_in()
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "UPDATE profiles SET cpi = NULL, gender = NULL "
                    "WHERE enrollment_id = :id"
                ),
                {"id": student.enrollment_id},
            )
    finally:
        await engine.dispose()

    with pytest.raises(DomainRejection) as error:
        await _join(student, cycle_id, resume_id)

    reasons = error.value.rejection.reasons
    assert {reason.code for reason in reasons} == {PROFILE_INCOMPLETE}
    # Every failure at once, so the student fixes their profile in one pass.
    assert {reason.path for reason in reasons} == {"cpi", "gender"}


@pytest.mark.asyncio
async def test_CYC3_an_undeclared_profile_cannot_join() -> None:
    student, cycle_id, resume_id = await _student_in(declared=False)

    codes = await _join_codes(student, cycle_id, resume_id)

    assert codes == [PROFILE_INCOMPLETE]


@pytest.mark.asyncio
async def test_CYC3_joining_requires_at_least_one_resume() -> None:
    student, cycle_id, _ = await _student_in(with_resume=False)

    with pytest.raises(DomainRejection) as error:
        await _join(student, cycle_id, None)

    paths = {reason.path for reason in error.value.rejection.reasons}
    assert paths == {"default_resume_id", "resumes"}


@pytest.mark.asyncio
async def test_CYC3_the_default_resume_must_belong_to_the_joining_student() -> None:
    student, cycle_id, _ = await _student_in()
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            other = await seed_person(connection, email="other@example.edu")
            stranger_resume = uuid4()
            await connection.execute(
                sa.text(
                    "INSERT INTO resumes (id, enrollment_id, label, drive_url, is_default) "
                    "VALUES (:id, :enrollment_id, 'Theirs', :url, true)"
                ),
                {
                    "id": stranger_resume,
                    "enrollment_id": other.enrollment_id,
                    "url": "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view",
                },
            )
    finally:
        await engine.dispose()

    codes = await _join_codes(student, cycle_id, stranger_resume)

    assert codes == [RESUME_NOT_FOUND]


@pytest.mark.asyncio
async def test_CYC3_consent_is_required() -> None:
    student, cycle_id, resume_id = await _student_in()

    codes = await _join_codes(student, cycle_id, resume_id, consent=False)

    assert codes == [CONSENT_REQUIRED]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "code"),
    [
        ("inactive", CYCLE_INACTIVE),
        ("closed", REGISTRATION_CLOSED),
        ("archived", CYCLE_ARCHIVED),
    ],
)
async def test_CYC1_joining_is_gated_by_the_flag_window_and_archival(
    scenario: str, code: str
) -> None:
    student, cycle_id, resume_id = await _student_in(
        is_active=scenario != "inactive",
        registration_open=scenario != "closed",
        archived=scenario == "archived",
    )

    codes = await _join_codes(student, cycle_id, resume_id)

    assert codes == [code]


@pytest.mark.asyncio
async def test_CYC3_join_rule_failures_are_reported_with_reasons() -> None:
    rule = '{"all": [{"field": "cpi", "op": "gte", "value": 9.0}]}'
    student, cycle_id, resume_id = await _student_in(join_rule=rule, cpi="7.20")

    with pytest.raises(DomainRejection) as error:
        await _join(student, cycle_id, resume_id)

    reasons = error.value.rejection.reasons
    assert {reason.code for reason in reasons} == {JOIN_RULE_FAILED}
    assert reasons[0].path is not None
    assert "CPI" in reasons[0].human or "cpi" in reasons[0].human


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("domain", "registration_open", "join_rule", "expected_code"),
    (
        (
            RuleDomain.CYCLE_REGISTRATION_WINDOW,
            False,
            None,
            REGISTRATION_CLOSED,
        ),
        (
            RuleDomain.CYCLE_JOIN_RULE,
            True,
            '{"all": [{"field": "cpi", "op": "gte", "value": 9.0}]}',
            JOIN_RULE_FAILED,
        ),
    ),
)
async def test_INT2_a_student_cycle_override_bypasses_only_its_join_gate(
    domain: RuleDomain,
    registration_open: bool,
    join_rule: str | None,
    expected_code: str,
) -> None:
    student, cycle_id, resume_id = await _student_in(
        registration_open=registration_open,
        join_rule=join_rule,
        cpi="7.20",
    )
    assert await _join_codes(student, cycle_id, resume_id) == [expected_code]
    override_id = await _grant_join_override(student, cycle_id, domain)

    result = await _join(student, cycle_id, resume_id)

    assert isinstance(result, Result)
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            details = await connection.scalar(
                sa.text(
                    "SELECT details FROM audit_log WHERE action = 'join_cycle' "
                    "AND subject_id = :membership_id"
                ),
                {"membership_id": UUID(str(result.summary["membership_id"]))},
            )
    finally:
        await engine.dispose()
    assert cast(dict[str, object], details)["applied_override_ids"] == [
        str(override_id)
    ]


@pytest.mark.asyncio
async def test_INT2_registration_override_does_not_bypass_cycle_inactive() -> None:
    student, cycle_id, resume_id = await _student_in(is_active=False)
    await _grant_join_override(
        student, cycle_id, RuleDomain.CYCLE_REGISTRATION_WINDOW
    )

    assert await _join_codes(student, cycle_id, resume_id) == [CYCLE_INACTIVE]


@pytest.mark.asyncio
async def test_CYC3_a_satisfied_join_rule_admits_the_student() -> None:
    rule = '{"all": [{"field": "cpi", "op": "gte", "value": 8.0}]}'
    student, cycle_id, resume_id = await _student_in(join_rule=rule, cpi="8.40")

    result = await _join(student, cycle_id, resume_id)

    assert isinstance(result, Result)
    assert result.summary["status"] == "pending"


@pytest.mark.asyncio
async def test_CYC3_one_membership_per_enrollment_and_cycle() -> None:
    student, cycle_id, resume_id = await _student_in()
    await _join(student, cycle_id, resume_id)

    codes = await _join_codes(student, cycle_id, resume_id)

    assert codes == [MEMBERSHIP_EXISTS]


@pytest.mark.asyncio
async def test_CYC3_simultaneous_memberships_across_cycles_are_allowed() -> None:
    student, first, resume_id = await _student_in()
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            second = await seed_cycle(
                connection, name="Placement 2027", kind="placement"
            )
    finally:
        await engine.dispose()

    await _join(student, first, resume_id)
    result = await _join(student, second, resume_id)

    assert isinstance(result, Result)
    assert result.summary["status"] == "pending"


@pytest.mark.asyncio
async def test_CYC3_a_student_cannot_join_on_another_enrollment() -> None:
    student, cycle_id, resume_id = await _student_in()
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            other = await seed_person(connection, email="other@example.edu")
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    model = executor.registry.commands["join_cycle"].input_model
    try:
        with pytest.raises(AuthorizationDenied):
            await executor.run(
                "join_cycle",
                model.model_validate(
                    {
                        "cycle_id": str(cycle_id),
                        "enrollment_id": str(other.enrollment_id),
                        "default_resume_id": str(resume_id),
                        "consent": True,
                    }
                ),
                student.actor,
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_CYC3_rejected_membership_can_be_re_requested_back_to_pending() -> None:
    student, cycle_id, resume_id = await _student_in()
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            membership_id = await seed_membership(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status="rejected",
                resume_id=resume_id,
                rejection_reason="Incomplete documents",
            )
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    model = executor.registry.commands["rerequest_membership"].input_model
    try:
        result = await executor.run(
            "rerequest_membership",
            model.model_validate(
                {
                    "cycle_id": str(cycle_id),
                    "enrollment_id": str(student.enrollment_id),
                    "default_resume_id": str(resume_id),
                    "consent": True,
                }
            ),
            student.actor,
        )
    finally:
        await engine.dispose()

    assert isinstance(result, Result)
    assert result.summary["status"] == "pending"

    check = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with check.connect() as connection:
            row = (
                await connection.execute(
                    sa.text("SELECT * FROM cycle_memberships WHERE id = :id"),
                    {"id": membership_id},
                )
            ).mappings().one()
    finally:
        await check.dispose()

    # The prior decision is cleared, not kept alongside the new request.
    assert row["status"] == "pending"
    assert row["rejection_reason"] is None
    assert row["decided_by"] is None
    assert row["decided_at"] is None


@pytest.mark.asyncio
async def test_CYC3_re_request_re_runs_the_window_check() -> None:
    student, cycle_id, resume_id = await _student_in(registration_open=False)
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await seed_membership(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status="rejected",
                resume_id=resume_id,
            )
    finally:
        await engine.dispose()

    executor, engine = build_test_executor()
    model = executor.registry.commands["rerequest_membership"].input_model
    try:
        with pytest.raises(DomainRejection) as error:
            await executor.run(
                "rerequest_membership",
                model.model_validate(
                    {
                        "cycle_id": str(cycle_id),
                        "enrollment_id": str(student.enrollment_id),
                        "default_resume_id": str(resume_id),
                        "consent": True,
                    }
                ),
                student.actor,
            )
    finally:
        await engine.dispose()

    assert [reason.code for reason in error.value.rejection.reasons] == [
        REGISTRATION_CLOSED
    ]


@pytest.mark.asyncio
async def test_CYC3_membership_actions_by_students_are_audited() -> None:
    """the design review section 4.3: the student is the actor on their own writes."""
    student, cycle_id, resume_id = await _student_in()

    await _join(student, cycle_id, resume_id)

    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    sa.text(
                        "SELECT actor_user_id, action, subject_type FROM audit_log "
                        "WHERE action = 'join_cycle'"
                    )
                )
            ).mappings().one()
    finally:
        await engine.dispose()

    assert row["actor_user_id"] == student.user_id
    assert row["subject_type"] == "cycle_membership"


@pytest.mark.asyncio
async def test_CYC3_an_open_cycle_join_records_no_approval_decision() -> None:
    student, cycle_id, resume_id = await _student_in(kind="open")

    result = await _join(student, cycle_id, resume_id)

    assert isinstance(result, Result)
    summary = cast(dict[str, object], result.summary)
    assert summary["status"] == "active"


async def _rerequest(
    student: Person, cycle_id: UUID, resume_id: UUID | None, *, consent: bool = True
) -> Preview | Result:
    executor, engine = build_test_executor()
    model = executor.registry.commands["rerequest_membership"].input_model
    try:
        return await executor.run(
            "rerequest_membership",
            model.model_validate(
                {
                    "cycle_id": str(cycle_id),
                    "enrollment_id": str(student.enrollment_id),
                    "default_resume_id": str(resume_id),
                    "consent": consent,
                }
            ),
            student.actor,
        )
    finally:
        await engine.dispose()


async def _withdrawn_member(
    *, kind: str = "placement", declared: bool = True, cpi: str = "8.40"
) -> tuple[Person, UUID, UUID | None, UUID]:
    student, cycle_id, resume_id = await _student_in(
        kind=kind, declared=declared, cpi=cpi
    )
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            membership_id = await seed_membership(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status="withdrawn",
                resume_id=resume_id,
            )
    finally:
        await engine.dispose()
    return student, cycle_id, resume_id, membership_id


@pytest.mark.asyncio
async def test_CYC3_rerequest_after_withdrawal_lands_pending_when_approval_is_on() -> None:
    """the design review section 4.34: leaving is not a one-way door."""
    student, cycle_id, resume_id, membership_id = await _withdrawn_member()

    result = await _rerequest(student, cycle_id, resume_id)

    assert isinstance(result, Result)
    assert result.summary["status"] == "pending"
    assert result.summary["membership_id"] == str(membership_id)

    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    sa.text("SELECT * FROM cycle_memberships WHERE id = :id"),
                    {"id": membership_id},
                )
            ).mappings().one()
            # One membership per (enrollment, cycle) still holds: the row the
            # student left is the row they came back to.
            count = await connection.scalar(
                sa.text(
                    "SELECT count(*) FROM cycle_memberships "
                    "WHERE cycle_id = :cycle_id AND enrollment_id = :enrollment_id"
                ),
                {"cycle_id": cycle_id, "enrollment_id": student.enrollment_id},
            )
    finally:
        await engine.dispose()

    assert row["status"] == "pending"
    assert row["default_resume_id"] == resume_id
    assert count == 1


@pytest.mark.asyncio
async def test_CYC3_rerequest_after_withdrawal_lands_active_when_approval_is_off() -> None:
    """An open cycle has no approval queue, so re-entry must not wait on one."""
    student, cycle_id, resume_id, membership_id = await _withdrawn_member(kind="open")

    result = await _rerequest(student, cycle_id, resume_id)

    assert isinstance(result, Result)
    assert result.summary["status"] == "active"

    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            status = await connection.scalar(
                sa.text("SELECT status FROM cycle_memberships WHERE id = :id"),
                {"id": membership_id},
            )
    finally:
        await engine.dispose()

    assert status == "active"


@pytest.mark.asyncio
async def test_CYC3_rerequest_re_runs_the_profile_checklist() -> None:
    """Re-entry runs the whole gauntlet, not just the window it used to check."""
    student, cycle_id, resume_id, _membership_id = await _withdrawn_member(
        declared=False
    )

    with pytest.raises(DomainRejection) as error:
        await _rerequest(student, cycle_id, resume_id)

    assert PROFILE_INCOMPLETE in {
        reason.code for reason in error.value.rejection.reasons
    }


@pytest.mark.asyncio
async def test_CYC3_rerequest_asks_for_consent_again() -> None:
    """The consent is this join's, not the one the student later walked away from."""
    student, cycle_id, resume_id, _membership_id = await _withdrawn_member()

    with pytest.raises(DomainRejection) as error:
        await _rerequest(student, cycle_id, resume_id, consent=False)

    assert [reason.code for reason in error.value.rejection.reasons] == [
        CONSENT_REQUIRED
    ]


@pytest.mark.asyncio
async def test_CYC3_rerequest_is_refused_from_a_status_it_does_not_name() -> None:
    """`removed` stays staff's call to undo; `active` has nothing to re-request."""
    student, cycle_id, resume_id = await _student_in()
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await seed_membership(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status="removed",
                resume_id=resume_id,
            )
    finally:
        await engine.dispose()

    with pytest.raises(DomainRejection) as error:
        await _rerequest(student, cycle_id, resume_id)

    assert [reason.code for reason in error.value.rejection.reasons] == [
        INVALID_TRANSITION
    ]
