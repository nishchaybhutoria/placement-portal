"""Granting and revoking overrides (Behavior INT-2, LLD section 10)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError

from app.core.db import create_engine
from app.core.errors import (
    CYCLE_ARCHIVED,
    ENROLLMENT_NOT_FOUND,
    INVALID_FIELD_VALUE,
    INVALID_REQUEST,
    JOB_NOT_FOUND,
    OVERRIDE_ALREADY_INACTIVE,
    OVERRIDE_NOT_FOUND,
    AuthorizationDenied,
    DomainRejection,
)
from app.core.plan import Preview, Result
from app.domain.shared import RuleDomain
from app.modules.overrides.commands import (
    CreateOverrideInput,
    DeactivateOverrideInput,
)
from tests.cycles.conftest import (
    seed_admin,
    seed_application,
    seed_coordinator_link,
    seed_cycle,
    seed_job,
    seed_person,
)
from tests.overrides.conftest import build_test_executor

pytestmark = pytest.mark.asyncio


def _write_engine():  # noqa: ANN202 - compact test helper
    return create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])


def _read_engine():  # noqa: ANN202 - compact test helper
    return create_engine(os.environ["TEST_DATABASE_URL"])


async def _row(override_id: UUID) -> sa.RowMapping:
    engine = _read_engine()
    try:
        async with engine.connect() as connection:
            return (
                await connection.execute(
                    sa.text(
                        "SELECT rule_domain, allow, cycle_id, job_id, enrollment_id, "
                        "application_id, reason, granted_by, expires_at, is_active "
                        "FROM overrides WHERE id = :id"
                    ),
                    {"id": override_id},
                )
            ).mappings().one()
    finally:
        await engine.dispose()


async def test_INT2_a_single_target_grant_stores_only_its_scope_column(
    clean_overrides: None,
) -> None:
    """Specificity is read off which column is set, so only one may be set."""
    del clean_overrides
    executor, _engine = build_test_executor()
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            cycle_id = await seed_cycle(connection)
            job_id = await seed_job(connection, cycle_id=cycle_id)
    finally:
        await engine.dispose()

    result = await executor.run(
        "create_override",
        CreateOverrideInput(
            rule_domain=RuleDomain.APPLICATION_DEADLINE,
            cycle_id=cycle_id,
            job_id=job_id,
            reason="The company extended their own deadline",
        ),
        admin.actor,
    )
    assert isinstance(result, Result)
    assert result.summary["scope"] == "job"

    row = await _row(UUID(str(result.summary["override_id"])))
    assert row["job_id"] == job_id
    # The cycle rode along on the wire for the route-stage authorization check
    # and deliberately did not reach the row.
    assert row["cycle_id"] is None
    assert row["enrollment_id"] is None and row["application_id"] is None
    assert row["granted_by"] == admin.user_id
    assert bool(row["is_active"])


@pytest.mark.parametrize("combination", ("cycle+enrollment", "job+enrollment"))
async def test_INT2_a_combination_grant_persists_both_target_columns(
    clean_overrides: None, combination: str
) -> None:
    del clean_overrides
    executor, _engine = build_test_executor()
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            cycle_id = await seed_cycle(connection)
            job_id = await seed_job(connection, cycle_id=cycle_id)
            student = await seed_person(connection, email=f"{combination}@example.edu")
    finally:
        await engine.dispose()

    created = await executor.run(
        "create_override",
        CreateOverrideInput(
            rule_domain=(
                RuleDomain.CYCLE_REGISTRATION_WINDOW
                if combination == "cycle+enrollment"
                else RuleDomain.ELIGIBILITY
            ),
            cycle_id=cycle_id,
            job_id=job_id if combination == "job+enrollment" else None,
            enrollment_id=student.enrollment_id,
            reason="A precise pre-application exception",
        ),
        admin.actor,
    )
    assert isinstance(created, Result)
    assert created.summary["scope"] == combination
    row = await _row(UUID(str(created.summary["override_id"])))
    assert row["enrollment_id"] == student.enrollment_id
    assert row["job_id"] == (job_id if combination == "job+enrollment" else None)
    assert row["cycle_id"] == (
        cycle_id if combination == "cycle+enrollment" else None
    )


@pytest.mark.parametrize(
    "targets",
    (
        {},
        {"cycle_id": "cycle", "job_id": "job"},
        {"cycle_id": "cycle", "application_id": "application"},
        {"job_id": "job", "application_id": "application"},
        {"cycle_id": "cycle", "job_id": "job", "enrollment_id": "enrollment"},
    ),
)
async def test_INT2_the_database_rejects_illegal_scope_combinations(
    clean_overrides: None, targets: dict[str, str]
) -> None:
    del clean_overrides
    engine = _write_engine()
    with pytest.raises(DBAPIError) as rejected:
        try:
            async with engine.begin() as connection:
                admin = await seed_admin(connection)
                cycle_id = await seed_cycle(connection)
                job_id = await seed_job(connection, cycle_id=cycle_id)
                student = await seed_person(
                    connection, email=f"constraint-{uuid4()}@example.edu"
                )
                application_id, _ = await seed_application(
                    connection,
                    cycle_id=cycle_id,
                    enrollment_id=student.enrollment_id,
                    job_id=job_id,
                )
                values = {
                    "admin": admin.user_id,
                    "cycle": cycle_id,
                    "job": job_id,
                    "enrollment": student.enrollment_id,
                    "application": application_id,
                }
                await connection.execute(
                    sa.text(
                        "INSERT INTO overrides (rule_domain, cycle_id, job_id, "
                        "enrollment_id, application_id, reason, granted_by) VALUES "
                        "('offer_cap', :cycle_id, :job_id, :enrollment_id, "
                        ":application_id, 'Malformed direct insert', :admin)"
                    ),
                    {
                        "admin": values["admin"],
                        **{
                            field: values[name]
                            for field, name in targets.items()
                        },
                        **{
                            field: None
                            for field in (
                                "cycle_id",
                                "job_id",
                                "enrollment_id",
                                "application_id",
                            )
                            if field not in targets
                        },
                    },
                )
        finally:
            await engine.dispose()
    assert getattr(rejected.value.orig, "sqlstate", None) == "23514"


async def test_INT2_a_job_scoped_grant_must_name_the_job_s_own_cycle(
    clean_overrides: None,
) -> None:
    del clean_overrides
    executor, _engine = build_test_executor()
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            cycle_id = await seed_cycle(connection, name="Placement 2026")
            other_cycle = await seed_cycle(connection, name="Internship 2026")
            job_id = await seed_job(connection, cycle_id=cycle_id)
    finally:
        await engine.dispose()

    with pytest.raises(DomainRejection) as rejected:
        await executor.run(
            "create_override",
            CreateOverrideInput(
                rule_domain=RuleDomain.APPLICATION_DEADLINE,
                cycle_id=other_cycle,
                job_id=job_id,
                reason="Wrong cycle",
            ),
            admin.actor,
        )
    assert [reason.code for reason in rejected.value.rejection.reasons] == [INVALID_REQUEST]


async def test_INT2_only_the_six_scope_combinations_pass_request_validation() -> None:
    """Target combinations are checked before anything is loaded."""
    with pytest.raises(ValidationError):
        CreateOverrideInput(
            rule_domain=RuleDomain.OFFER_CAP, reason="Nothing to point at"
        )
    CreateOverrideInput(
        rule_domain=RuleDomain.OFFER_CAP,
        enrollment_id=uuid4(),
        cycle_id=uuid4(),
        reason="One student in one cycle",
    )
    with pytest.raises(ValidationError):
        CreateOverrideInput(
            rule_domain=RuleDomain.OFFER_CAP,
            job_id=uuid4(),
            reason="A job grant must say which cycle authorizes it",
        )
    with pytest.raises(ValidationError):
        CreateOverrideInput(
            rule_domain=RuleDomain.OFFER_CAP,
            cycle_id=uuid4(),
            application_id=uuid4(),
            enrollment_id=uuid4(),
            reason="An application already determines its student",
        )


async def test_INT2_an_enrollment_scoped_grant_is_administrative_only(
    clean_overrides: None,
) -> None:
    """It follows the student across every cycle, so no coordinator owns it."""
    del clean_overrides
    executor, _engine = build_test_executor()
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            cycle_id = await seed_cycle(connection)
            coordinator = await seed_person(
                connection, email="coordinator@example.edu", role="student"
            )
            await seed_coordinator_link(connection, cycle_id, coordinator.user_id)
            student = await seed_person(connection, email="student@example.edu")
    finally:
        await engine.dispose()

    payload = CreateOverrideInput(
        rule_domain=RuleDomain.OUTCOME_GATE,
        enrollment_id=student.enrollment_id,
        reason="Recorded off-campus outcome is being corrected",
    )
    with pytest.raises(AuthorizationDenied):
        await executor.run(
            "create_override", payload, coordinator.coordinating(cycle_id).actor
        )

    result = await executor.run("create_override", payload, admin.actor)
    assert isinstance(result, Result)
    assert result.summary["scope"] == "enrollment"


async def test_INT2_a_coordinator_grants_inside_their_cycle_and_nowhere_else(
    clean_overrides: None,
) -> None:
    del clean_overrides
    executor, _engine = build_test_executor()
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            cycle_id = await seed_cycle(connection, name="Placement 2026")
            other_cycle = await seed_cycle(connection, name="Internship 2026")
            coordinator = await seed_person(
                connection, email="coordinator@example.edu", role="student"
            )
            await seed_coordinator_link(connection, cycle_id, coordinator.user_id)
    finally:
        await engine.dispose()

    actor = coordinator.coordinating(cycle_id).actor
    result = await executor.run(
        "create_override",
        CreateOverrideInput(
            rule_domain=RuleDomain.APPLICATION_DEADLINE,
            cycle_id=cycle_id,
            reason="Late applications open for one more day",
        ),
        actor,
    )
    assert isinstance(result, Result)

    with pytest.raises(AuthorizationDenied):
        await executor.run(
            "create_override",
            CreateOverrideInput(
                rule_domain=RuleDomain.APPLICATION_DEADLINE,
                cycle_id=other_cycle,
                reason="Not my cycle",
            ),
            actor,
        )


@pytest.mark.parametrize(
    "domain",
    (RuleDomain.ELIGIBILITY, RuleDomain.APPLICATION_DEADLINE),
)
async def test_INT2_an_application_grant_that_can_no_longer_fire_is_refused(
    clean_overrides: None, domain: RuleDomain
) -> None:
    del clean_overrides
    executor, _engine = build_test_executor()
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            cycle_id = await seed_cycle(connection)
            job_id = await seed_job(connection, cycle_id=cycle_id)
            student = await seed_person(connection, email="inert-override@example.edu")
            application_id, _ = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                job_id=job_id,
            )
    finally:
        await engine.dispose()

    with pytest.raises(DomainRejection) as rejected:
        await executor.run(
            "create_override",
            CreateOverrideInput(
                rule_domain=domain,
                cycle_id=cycle_id,
                application_id=application_id,
                reason="This gate has already run",
            ),
            admin.actor,
        )
    assert [reason.code for reason in rejected.value.rejection.reasons] == [
        INVALID_FIELD_VALUE
    ]
    assert rejected.value.rejection.reasons[0].path == "rule_domain"


async def test_INT2_an_expiry_already_in_the_past_is_refused(
    clean_overrides: None,
) -> None:
    """A grant that is inert on arrival reads as a grant and is not one."""
    del clean_overrides
    executor, _engine = build_test_executor()
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            cycle_id = await seed_cycle(connection)
    finally:
        await engine.dispose()

    with pytest.raises(DomainRejection) as rejected:
        await executor.run(
            "create_override",
            CreateOverrideInput(
                rule_domain=RuleDomain.OFFER_DEADLINE,
                cycle_id=cycle_id,
                reason="Backdated",
                expires_at=datetime.now(UTC) - timedelta(hours=1),
            ),
            admin.actor,
        )
    reasons = rejected.value.rejection.reasons
    assert [reason.code for reason in reasons] == [INVALID_FIELD_VALUE]
    assert reasons[0].path == "expires_at"


async def test_INT2_a_grant_on_an_archived_cycle_is_refused(
    clean_overrides: None,
) -> None:
    """CYC-1: an archived cycle is read-only, overrides included."""
    del clean_overrides
    executor, _engine = build_test_executor()
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            cycle_id = await seed_cycle(connection, archived=True)
    finally:
        await engine.dispose()

    with pytest.raises(DomainRejection) as rejected:
        await executor.run(
            "create_override",
            CreateOverrideInput(
                rule_domain=RuleDomain.ELIGIBILITY,
                cycle_id=cycle_id,
                reason="Too late",
            ),
            admin.actor,
        )
    assert [r.code for r in rejected.value.rejection.reasons] == [CYCLE_ARCHIVED]


async def test_INT2_a_grant_on_a_missing_target_is_refused(
    clean_overrides: None,
) -> None:
    del clean_overrides
    executor, _engine = build_test_executor()
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            cycle_id = await seed_cycle(connection)
    finally:
        await engine.dispose()

    with pytest.raises(DomainRejection) as missing_job:
        await executor.run(
            "create_override",
            CreateOverrideInput(
                rule_domain=RuleDomain.ELIGIBILITY,
                cycle_id=cycle_id,
                job_id=uuid4(),
                reason="No such job",
            ),
            admin.actor,
        )
    assert [r.code for r in missing_job.value.rejection.reasons] == [JOB_NOT_FOUND]

    with pytest.raises(DomainRejection) as missing_enrollment:
        await executor.run(
            "create_override",
            CreateOverrideInput(
                rule_domain=RuleDomain.ELIGIBILITY,
                enrollment_id=uuid4(),
                reason="No such student",
            ),
            admin.actor,
        )
    assert [r.code for r in missing_enrollment.value.rejection.reasons] == [
        ENROLLMENT_NOT_FOUND
    ]


async def test_INT2_deactivation_is_one_click_audited_and_not_repeatable(
    clean_overrides: None,
) -> None:
    """INT-2 asks for one-click deactivation, so the reason stays optional."""
    del clean_overrides
    executor, _engine = build_test_executor()
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            cycle_id = await seed_cycle(connection)
    finally:
        await engine.dispose()

    created = await executor.run(
        "create_override",
        CreateOverrideInput(
            rule_domain=RuleDomain.WITHDRAW_WINDOW,
            cycle_id=cycle_id,
            reason="Correcting a bulk import",
        ),
        admin.actor,
    )
    assert isinstance(created, Result)
    override_id = UUID(str(created.summary["override_id"]))

    preview = await executor.run(
        "deactivate_override",
        DeactivateOverrideInput(override_id=override_id),
        admin.actor,
        dry_run=True,
    )
    assert isinstance(preview, Preview)
    assert preview.summary["is_active"] is False

    result = await executor.run(
        "deactivate_override",
        DeactivateOverrideInput(override_id=override_id),
        admin.actor,
    )
    assert isinstance(result, Result)
    assert not bool((await _row(override_id))["is_active"])

    with pytest.raises(DomainRejection) as repeated:
        await executor.run(
            "deactivate_override",
            DeactivateOverrideInput(override_id=override_id),
            admin.actor,
        )
    assert [r.code for r in repeated.value.rejection.reasons] == [
        OVERRIDE_ALREADY_INACTIVE
    ]

    engine = _read_engine()
    try:
        async with engine.connect() as connection:
            actions = (
                await connection.scalars(
                    sa.text(
                        "SELECT action FROM audit_log WHERE subject_id = :id "
                        "ORDER BY created_at"
                    ),
                    {"id": override_id},
                )
            ).all()
    finally:
        await engine.dispose()
    assert list(actions) == ["create_override", "deactivate_override"]


async def test_INT2_deactivating_an_override_that_does_not_exist_is_refused(
    clean_overrides: None,
) -> None:
    del clean_overrides
    executor, _engine = build_test_executor()
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
    finally:
        await engine.dispose()

    with pytest.raises(DomainRejection) as rejected:
        await executor.run(
            "deactivate_override",
            DeactivateOverrideInput(override_id=uuid4()),
            admin.actor,
        )
    assert [r.code for r in rejected.value.rejection.reasons] == [OVERRIDE_NOT_FOUND]


async def test_INT2_the_grant_records_who_granted_it_and_why(
    clean_overrides: None,
) -> None:
    """INT-2's row is the audit: reason, granter, expiry, active flag."""
    del clean_overrides
    executor, _engine = build_test_executor()
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            cycle_id = await seed_cycle(connection)
    finally:
        await engine.dispose()

    expires = datetime.now(UTC) + timedelta(days=2)
    created = await executor.run(
        "create_override",
        CreateOverrideInput(
            rule_domain=RuleDomain.OFFER_CAP,
            cycle_id=cycle_id,
            allow=False,
            reason="Cap frozen while the office reconciles external offers",
            expires_at=expires,
        ),
        admin.actor,
    )
    assert isinstance(created, Result)
    row = await _row(UUID(str(created.summary["override_id"])))
    assert row["reason"] == "Cap frozen while the office reconciles external offers"
    assert bool(row["allow"]) is False
    assert cast(datetime, row["expires_at"]) == expires
