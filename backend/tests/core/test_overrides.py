"""M2 scoped override lookup for LLD sections 5 and INT-2."""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import create_engine
from app.core.plan import ScopeIds
from app.domain.shared import RuleDomain
from app.modules.overrides.service import applicable, classified_many

ADMIN_ID = UUID("00000000-0000-0000-0000-000000000001")
ENROLLMENT_ID = UUID("00000000-0000-0000-0000-000000000002")
CYCLE_ID = UUID("00000000-0000-0000-0000-000000000003")
COMPANY_ID = UUID("00000000-0000-0000-0000-000000000004")
JOB_ID = UUID("00000000-0000-0000-0000-000000000005")
APPLICATION_ID = UUID("00000000-0000-0000-0000-000000000006")
OLDER_APPLICATION_OVERRIDE = UUID("00000000-0000-0000-0000-000000000010")
NEWER_APPLICATION_OVERRIDE = UUID("00000000-0000-0000-0000-000000000011")
CAP_OVERRIDE = UUID("00000000-0000-0000-0000-000000000012")
ALLOW_DEADLINE_OVERRIDE = UUID("00000000-0000-0000-0000-000000000013")
DENY_DEADLINE_OVERRIDE = UUID("00000000-0000-0000-0000-000000000014")
CYCLE_ENROLLMENT_OVERRIDE = UUID("00000000-0000-0000-0000-000000000015")
JOB_ENROLLMENT_OVERRIDE = UUID("00000000-0000-0000-0000-000000000016")
EXPIRED_APPLICATION_OVERRIDE = UUID("00000000-0000-0000-0000-000000000017")


async def _seed_override_graph() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "TRUNCATE overrides, applications, jobs, companies, cycles, "
                    "enrollments, users CASCADE"
                )
            )
            graph_values = {
                "admin_id": ADMIN_ID,
                "enrollment_id": ENROLLMENT_ID,
                "cycle_id": CYCLE_ID,
                "company_id": COMPANY_ID,
                "job_id": JOB_ID,
                "application_id": APPLICATION_ID,
            }
            graph_statements = (
                "INSERT INTO users (id, email, full_name, role, is_active) "
                "VALUES (:admin_id, 'admin@example.edu', 'Admin', 'admin', true)",
                "INSERT INTO enrollments (id, user_id, is_current) "
                "VALUES (:enrollment_id, :admin_id, true)",
                "INSERT INTO cycles (id, name, kind, is_active) "
                "VALUES (:cycle_id, 'M2 override cycle', 'placement', true)",
                "INSERT INTO companies (id, name, is_active) "
                "VALUES (:company_id, 'M2 override company', true)",
                "INSERT INTO jobs "
                "(id, cycle_id, company_id, outcome, title, description, is_published) "
                "VALUES (:job_id, :cycle_id, :company_id, 'placement', 'Role', 'Role', true)",
                "INSERT INTO applications "
                "(id, job_id, enrollment_id, status, resume_url, profile_snapshot, applied_at) "
                "VALUES (:application_id, :job_id, :enrollment_id, 'in_progress', "
                "'https://drive.google.com/file/d/test', '{}'::jsonb, now())",
            )
            for statement in graph_statements:
                await connection.execute(sa.text(statement), graph_values)

            override_values = {
                "admin_id": ADMIN_ID,
                "cycle_id": CYCLE_ID,
                "job_id": JOB_ID,
                "enrollment_id": ENROLLMENT_ID,
                "application_id": APPLICATION_ID,
                "cycle_enrollment_id": CYCLE_ENROLLMENT_OVERRIDE,
                "job_enrollment_id": JOB_ENROLLMENT_OVERRIDE,
                "expired_id": EXPIRED_APPLICATION_OVERRIDE,
                "older_id": OLDER_APPLICATION_OVERRIDE,
                "newer_id": NEWER_APPLICATION_OVERRIDE,
                "cap_id": CAP_OVERRIDE,
                "allow_deadline_id": ALLOW_DEADLINE_OVERRIDE,
                "deny_deadline_id": DENY_DEADLINE_OVERRIDE,
            }
            override_statements = (
                "INSERT INTO overrides "
                "(id, rule_domain, cycle_id, reason, granted_by, is_active, "
                "created_at, updated_at) "
                "VALUES (gen_random_uuid(), 'eligibility', :cycle_id, 'cycle', :admin_id, "
                "true, now() - interval '4 hours', now() - interval '4 hours')",
                "INSERT INTO overrides "
                "(id, rule_domain, job_id, reason, granted_by, is_active, created_at, updated_at) "
                "VALUES (gen_random_uuid(), 'eligibility', :job_id, 'job', :admin_id, "
                "true, now() - interval '3 hours', now() - interval '3 hours')",
                "INSERT INTO overrides "
                "(id, rule_domain, cycle_id, enrollment_id, reason, granted_by, "
                "is_active, created_at, updated_at) VALUES "
                "(:cycle_enrollment_id, 'eligibility', :cycle_id, :enrollment_id, "
                "'cycle enrollment', :admin_id, true, now() - interval '150 minutes', "
                "now() - interval '150 minutes')",
                "INSERT INTO overrides "
                "(id, rule_domain, job_id, enrollment_id, reason, granted_by, "
                "is_active, created_at, updated_at) VALUES "
                "(:job_enrollment_id, 'eligibility', :job_id, :enrollment_id, "
                "'job enrollment', :admin_id, true, now() - interval '130 minutes', "
                "now() - interval '130 minutes')",
                "INSERT INTO overrides "
                "(id, rule_domain, application_id, reason, granted_by, "
                "is_active, created_at, updated_at) VALUES "
                "(:older_id, 'eligibility', :application_id, 'older app', :admin_id, true, "
                "now() - interval '2 hours', now() - interval '2 hours'), "
                "(:newer_id, 'eligibility', :application_id, 'newer app', :admin_id, true, "
                "now() - interval '1 hour', now() - interval '1 hour'), "
                "(:expired_id, 'eligibility', :application_id, 'expired app', "
                ":admin_id, true, now(), now())",
                "UPDATE overrides SET expires_at = now() - interval '1 minute' "
                "WHERE reason = 'expired app'",
                "INSERT INTO overrides "
                "(id, rule_domain, cycle_id, reason, granted_by, is_active, "
                "created_at, updated_at) "
                "VALUES (:cap_id, 'offer_cap', :cycle_id, 'cap', :admin_id, true, now(), now())",
                "INSERT INTO overrides "
                "(id, rule_domain, application_id, reason, granted_by, allow, "
                "is_active, created_at, updated_at) VALUES "
                "(:allow_deadline_id, 'offer_deadline', :application_id, "
                "'newer allow', :admin_id, true, true, now(), now()), "
                "(:deny_deadline_id, 'offer_deadline', :application_id, "
                "'older deny', :admin_id, false, true, now() - interval '1 day', "
                "now() - interval '1 day')",
                "INSERT INTO overrides "
                "(id, rule_domain, application_id, reason, granted_by, is_active) "
                "VALUES (gen_random_uuid(), 'eligibility', :application_id, 'inactive', "
                ":admin_id, false)",
            )
            for statement in override_statements:
                await connection.execute(sa.text(statement), override_values)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_applicable_filters_and_uses_specificity_then_newest() -> None:
    await _seed_override_graph()
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker[AsyncSession](
        engine, expire_on_commit=False, autobegin=False
    )
    try:
        async with factory() as session:
            async with session.begin():
                result = await applicable(
                    session,
                    (
                        RuleDomain.ELIGIBILITY,
                        RuleDomain.OFFER_CAP,
                        RuleDomain.OFFER_DEADLINE,
                    ),
                    ScopeIds(
                        cycle_id=CYCLE_ID,
                        job_id=JOB_ID,
                        enrollment_id=ENROLLMENT_ID,
                        application_id=APPLICATION_ID,
                    ),
                )
    finally:
        await engine.dispose()

    assert [item.id for item in result] == [
        NEWER_APPLICATION_OVERRIDE,
        CAP_OVERRIDE,
        DENY_DEADLINE_OVERRIDE,
    ]
    assert [item.specificity for item in result] == [
        "application",
        "cycle",
        "application",
    ]
    assert [item.allow for item in result] == [True, True, False]


@pytest.mark.asyncio
async def test_INT2_combination_specificity_matches_every_named_target() -> None:
    await _seed_override_graph()
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker[AsyncSession](
        engine, expire_on_commit=False, autobegin=False
    )
    try:
        async with factory() as session:
            async with session.begin():
                job_enrollment = await applicable(
                    session,
                    (RuleDomain.ELIGIBILITY,),
                    ScopeIds(
                        cycle_id=CYCLE_ID,
                        job_id=JOB_ID,
                        enrollment_id=ENROLLMENT_ID,
                    ),
                )
                cycle_enrollment = await applicable(
                    session,
                    (RuleDomain.ELIGIBILITY,),
                    ScopeIds(cycle_id=CYCLE_ID, enrollment_id=ENROLLMENT_ID),
                )
                wrong_student = await applicable(
                    session,
                    (RuleDomain.ELIGIBILITY,),
                    ScopeIds(cycle_id=CYCLE_ID, job_id=JOB_ID, enrollment_id=uuid4()),
                )
    finally:
        await engine.dispose()

    assert [(item.id, item.specificity) for item in job_enrollment] == [
        (JOB_ENROLLMENT_OVERRIDE, "job+enrollment")
    ]
    assert [(item.id, item.specificity) for item in cycle_enrollment] == [
        (CYCLE_ENROLLMENT_OVERRIDE, "cycle+enrollment")
    ]
    assert len(wrong_student) == 1
    assert wrong_student[0].specificity == "job"


@pytest.mark.asyncio
async def test_INT2_subject_classification_uses_the_resolver_for_shadowing() -> None:
    await _seed_override_graph()
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker[AsyncSession](
        engine, expire_on_commit=False, autobegin=False
    )
    try:
        async with factory() as session:
            async with session.begin():
                rows = await classified_many(
                    session,
                    (RuleDomain.ELIGIBILITY,),
                    (
                        ScopeIds(
                            cycle_id=CYCLE_ID,
                            job_id=JOB_ID,
                            enrollment_id=ENROLLMENT_ID,
                            application_id=APPLICATION_ID,
                        ),
                    ),
                )
    finally:
        await engine.dispose()

    states = {row.id: row.state for row in rows}
    assert states[NEWER_APPLICATION_OVERRIDE] == "active"
    assert states[EXPIRED_APPLICATION_OVERRIDE] == "expired"
    for shadowed in (
        OLDER_APPLICATION_OVERRIDE,
        JOB_ENROLLMENT_OVERRIDE,
        CYCLE_ENROLLMENT_OVERRIDE,
    ):
        assert states[shadowed] == "shadowed"
