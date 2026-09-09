"""M1 schema and grant gates for Behavior section 16 and LLD sections 6/8."""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import cast

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError

import app.models  # noqa: F401 - populate Base.metadata for parity assertions
from app.core.db import Base, create_engine

EXPECTED_ENUMS: dict[str, tuple[str, ...]] = {
    "role_t": ("student", "admin"),
    "gender_t": ("male", "female", "other"),
    "cycle_kind_t": ("placement", "internship", "open"),
    "membership_status_t": ("pending", "active", "rejected", "withdrawn", "removed"),
    "outcome_t": ("internship", "placement"),
    "application_status_t": (
        "in_progress",
        "pending_offer",
        "offered",
        "accepted",
        "declined",
        "rejected",
        "withdrawn",
        "auto_withdrawn",
        "offer_terminated",
    ),
    "round_result_t": ("pending", "advanced", "eliminated", "waitlisted"),
    "attendance_t": ("pending", "present", "absent", "excused"),
    "offer_response_t": ("accepted", "declined"),
    "termination_kind_t": ("company_revoked", "student_renege", "admin_correction"),
    "external_source_t": ("ppo", "off_campus", "other"),
    "external_status_t": ("offered", "accepted", "declined"),
    "question_type_t": (
        "text",
        "longtext",
        "single",
        "multi",
        "boolean",
        "number",
        "date",
        "email",
        "url",
    ),
    "strike_source_t": ("auto_absence", "manual"),
    "rule_domain_t": (
        "eligibility",
        "application_deadline",
        "edit_window",
        "withdraw_window",
        "outcome_gate",
        "offer_cap",
        "offer_deadline",
        "cycle_registration_window",
        "cycle_join_rule",
    ),
    "offer_expiry_t": ("auto_decline", "auto_accept"),
    "outcome_tag_t": ("higher_studies", "entrepreneurship", "not_seeking"),
    "event_type_t": (
        "created",
        "advanced",
        "eliminated",
        "waitlisted",
        "attendance_marked",
        "venue_assigned",
        "round_finalized",
        "offer_extended",
        "accepted",
        "declined",
        "auto_declined",
        "withdrawn",
        "auto_withdrawn",
        "offer_terminated",
        "reinstated",
        "edited",
        "forced_transition",
        "overridden",
        "external_recorded",
        "external_updated",
    ),
    "finding_status_t": ("open", "resolved", "dismissed"),
    "notif_status_t": ("queued", "sent", "failed", "dead"),
}

DOMAIN_COLUMNS: dict[str, set[str]] = {
    "users": {"email", "full_name", "role", "is_active"},
    "sessions": {"token_hash", "user_id", "expires_at", "revoked_at"},
    "enrollments": {"user_id", "is_current", "roll_number"},
    "profiles": {
        "enrollment_id",
        "program_id",
        "primary_branch_id",
        "is_dual_major",
        "is_dual_degree",
        "secondary_program_id",
        "secondary_branch_id",
        "graduating_year",
        "cpi",
        "active_backlogs",
        "total_backlogs",
        "gender",
        "personal_email",
        "contact_number",
        "nationality",
        "tenth_percent",
        "tenth_year",
        "twelfth_percent",
        "twelfth_year",
        "minor1_id",
        "minor2_id",
        "github_url",
        "linkedin_url",
        "portfolio_url",
        "declared_at",
    },
    "resumes": {"enrollment_id", "label", "drive_url", "is_default"},
    "staged_profile_rows": {"institute_email", "payload", "uploaded_by", "applied_at", "error"},
    "programs": {"name", "is_active"},
    "branches": {"name", "is_active"},
    "program_branches": {"program_id", "branch_id"},
    "minors": {"name", "is_active"},
    "sectors": {"name", "is_active"},
    "round_types": {"name", "is_active"},
    "settings": {"key", "value", "updated_by"},
    "cycles": {
        "name",
        "kind",
        "description",
        "starts_on",
        "ends_on",
        "registration_opens_at",
        "registration_closes_at",
        "is_active",
        "archived_at",
    },
    "cycle_policies": {
        "cycle_id",
        "membership_requires_approval",
        "join_rule",
        "max_accepted_offers",
        "penalty_blocks_applications",
        "allow_withdrawal_after_deadline",
        "allow_edit_after_deadline",
        "strike_on_absence",
        "offer_expiry_behavior",
        "deadline_reminder_hours",
        "round_reminder_hours",
    },
    "cycle_coordinators": {"cycle_id", "user_id"},
    "cycle_memberships": {
        "cycle_id",
        "enrollment_id",
        "status",
        "default_resume_id",
        "consented_at",
        "decided_by",
        "decided_at",
        "rejection_reason",
        "outcome_tag",
        "auto_created",
    },
    "companies": {"name", "description", "website_url", "sector_id", "is_active"},
    "company_contacts": {
        "company_id",
        "name",
        "email",
        "phone",
        "designation",
        "is_primary",
    },
    "jobs": {
        "cycle_id",
        "company_id",
        "outcome",
        "title",
        "description",
        "location",
        "sector_id",
        "ctc_lpa",
        "ctc_breakdown",
        "stipend_month",
        "application_deadline",
        "offer_acceptance_deadline",
        "is_published",
        "published_at",
        "cancelled_at",
        "eligibility_rule",
        "eligibility_summary",
    },
    "job_program_ctc": {"job_id", "program_id", "ctc_lpa"},
    "job_rounds": {
        "job_id",
        "round_type_id",
        "name",
        "ord",
        "venue",
        "scheduled_at",
        "duration_min",
        "instructions",
        "finalized_at",
        "finalized_by",
    },
    "job_questions": {"job_id", "ord", "text", "qtype", "required"},
    "job_question_options": {"question_id", "ord", "text"},
    "applications": {
        "job_id",
        "enrollment_id",
        "status",
        "current_round_id",
        "resume_url",
        "profile_snapshot",
        "applied_at",
    },
    "application_answers": {"application_id", "question_id", "value"},
    "application_round_states": {
        "application_id",
        "round_id",
        "result",
        "attendance",
        "venue_override",
        "scheduled_at_override",
        "notified_at",
    },
    "application_events": {
        "event_seq",
        "application_id",
        "event_type",
        "from_status",
        "to_status",
        "from_round_id",
        "to_round_id",
        "actor_user_id",
        "reason",
        "payload",
        "batch_id",
    },
    "offers": {
        "application_id",
        "extended_at",
        "deadline_at",
        "response",
        "responded_at",
        "terminated_at",
        "terminated_by",
        "termination_kind",
        "termination_reason",
    },
    "external_offers": {
        "enrollment_id",
        "company_id",
        "outcome",
        "source",
        "ctc_lpa",
        "stipend_month",
        "status",
        "offered_on",
        "responded_on",
        "source_application_id",
        "attached_cycle_id",
        "notes",
        "created_by",
    },
    "strikes": {
        "enrollment_id",
        "reason",
        "source",
        "awarded_by",
        "is_active",
        "consumed_by_penalty_id",
    },
    "penalties": {
        "enrollment_id",
        "reasons",
        "from_strikes",
        "is_active",
        "created_by",
        "revoked_at",
        "revoked_by",
    },
    "overrides": {
        "rule_domain",
        "allow",
        "cycle_id",
        "job_id",
        "enrollment_id",
        "application_id",
        "reason",
        "granted_by",
        "expires_at",
        "is_active",
    },
    "notification_templates": {"event_key", "cycle_id", "subject", "body", "enabled"},
    "notification_log": {
        "recipient",
        "event_key",
        "subject",
        "status",
        "attempts",
        "last_error",
        "sent_at",
        "context",
    },
    "reminder_sends": {"kind", "dedup_key"},
    # `audit_seq` is the append-order identity (the design review 4.48), the audit
    # counterpart of application_events.event_seq.
    "audit_log": {
        "actor_user_id",
        "action",
        "subject_type",
        "subject_id",
        "details",
        "audit_seq",
    },
    "idempotency_keys": {"key", "command", "result"},
    "consistency_findings": {
        "invariant",
        "subject",
        "detail",
        "status",
        "suggested_fix",
        "resolved_at",
    },
    "export_presets": {"job_id", "columns"},
    "export_jobs": {"kind", "params", "status", "requested_by", "result_meta", "error"},
}

IMMUTABLE_TABLES = {
    "program_branches",
    "cycle_coordinators",
    "application_events",
    "reminder_sends",
    "audit_log",
    "idempotency_keys",
}

EXPECTED_PARTIAL_UNIQUES = {
    "uq_enrollments_current_roll_number": "enrollments",
    "uq_enrollments_current_user_id": "enrollments",
    "uq_resumes_default_enrollment_id": "resumes",
    "uq_company_contacts_primary_company_id": "company_contacts",
    "uq_applications_active_job_enrollment": "applications",
}

EXPECTED_UNIQUE_PAIRS = {
    "uq_program_branches_program_id_branch_id": ("program_branches", ("program_id", "branch_id")),
    "uq_cycle_coordinators_cycle_id_user_id": ("cycle_coordinators", ("cycle_id", "user_id")),
    "uq_cycle_memberships_cycle_id_enrollment_id": (
        "cycle_memberships",
        ("cycle_id", "enrollment_id"),
    ),
    "uq_company_contacts_company_id_email": ("company_contacts", ("company_id", "email")),
    "uq_job_program_ctc_job_id_program_id": ("job_program_ctc", ("job_id", "program_id")),
    "uq_job_rounds_job_id_ord": ("job_rounds", ("job_id", "ord")),
    "uq_application_answers_application_id_question_id": (
        "application_answers",
        ("application_id", "question_id"),
    ),
    "uq_application_round_states_application_id_round_id": (
        "application_round_states",
        ("application_id", "round_id"),
    ),
    "uq_notification_templates_event_key_cycle_id": (
        "notification_templates",
        ("event_key", "cycle_id"),
    ),
}

EXPECTED_FOREIGN_KEYS: dict[tuple[str, str], tuple[str, str]] = {
    ("sessions", "user_id"): ("users", "RESTRICT"),
    ("enrollments", "user_id"): ("users", "RESTRICT"),
    ("program_branches", "program_id"): ("programs", "RESTRICT"),
    ("program_branches", "branch_id"): ("branches", "RESTRICT"),
    ("settings", "updated_by"): ("users", "RESTRICT"),
    ("profiles", "enrollment_id"): ("enrollments", "RESTRICT"),
    ("profiles", "program_id"): ("programs", "RESTRICT"),
    ("profiles", "secondary_program_id"): ("programs", "RESTRICT"),
    ("profiles", "primary_branch_id"): ("branches", "RESTRICT"),
    ("profiles", "secondary_branch_id"): ("branches", "RESTRICT"),
    ("profiles", "minor1_id"): ("minors", "RESTRICT"),
    ("profiles", "minor2_id"): ("minors", "RESTRICT"),
    ("resumes", "enrollment_id"): ("enrollments", "RESTRICT"),
    ("staged_profile_rows", "uploaded_by"): ("users", "RESTRICT"),
    ("cycle_policies", "cycle_id"): ("cycles", "RESTRICT"),
    ("cycle_coordinators", "cycle_id"): ("cycles", "RESTRICT"),
    ("cycle_coordinators", "user_id"): ("users", "RESTRICT"),
    ("cycle_memberships", "cycle_id"): ("cycles", "RESTRICT"),
    ("cycle_memberships", "enrollment_id"): ("enrollments", "RESTRICT"),
    ("cycle_memberships", "default_resume_id"): ("resumes", "SET NULL"),
    ("cycle_memberships", "decided_by"): ("users", "RESTRICT"),
    ("companies", "sector_id"): ("sectors", "RESTRICT"),
    ("company_contacts", "company_id"): ("companies", "RESTRICT"),
    ("jobs", "cycle_id"): ("cycles", "RESTRICT"),
    ("jobs", "company_id"): ("companies", "RESTRICT"),
    ("jobs", "sector_id"): ("sectors", "RESTRICT"),
    ("job_program_ctc", "job_id"): ("jobs", "RESTRICT"),
    ("job_program_ctc", "program_id"): ("programs", "RESTRICT"),
    ("job_rounds", "job_id"): ("jobs", "RESTRICT"),
    ("job_rounds", "round_type_id"): ("round_types", "RESTRICT"),
    ("job_rounds", "finalized_by"): ("users", "RESTRICT"),
    ("job_questions", "job_id"): ("jobs", "RESTRICT"),
    ("job_question_options", "question_id"): ("job_questions", "RESTRICT"),
    ("applications", "job_id"): ("jobs", "RESTRICT"),
    ("applications", "enrollment_id"): ("enrollments", "RESTRICT"),
    ("applications", "current_round_id"): ("job_rounds", "RESTRICT"),
    ("application_answers", "application_id"): ("applications", "RESTRICT"),
    ("application_answers", "question_id"): ("job_questions", "RESTRICT"),
    ("application_round_states", "application_id"): ("applications", "RESTRICT"),
    ("application_round_states", "round_id"): ("job_rounds", "RESTRICT"),
    ("application_events", "application_id"): ("applications", "RESTRICT"),
    ("application_events", "from_round_id"): ("job_rounds", "RESTRICT"),
    ("application_events", "to_round_id"): ("job_rounds", "RESTRICT"),
    ("application_events", "actor_user_id"): ("users", "RESTRICT"),
    ("offers", "application_id"): ("applications", "RESTRICT"),
    ("offers", "terminated_by"): ("users", "RESTRICT"),
    ("external_offers", "enrollment_id"): ("enrollments", "RESTRICT"),
    ("external_offers", "company_id"): ("companies", "RESTRICT"),
    ("external_offers", "source_application_id"): ("applications", "RESTRICT"),
    ("external_offers", "attached_cycle_id"): ("cycles", "RESTRICT"),
    ("external_offers", "created_by"): ("users", "RESTRICT"),
    ("strikes", "enrollment_id"): ("enrollments", "RESTRICT"),
    ("strikes", "awarded_by"): ("users", "RESTRICT"),
    ("strikes", "consumed_by_penalty_id"): ("penalties", "RESTRICT"),
    ("penalties", "enrollment_id"): ("enrollments", "RESTRICT"),
    ("penalties", "created_by"): ("users", "RESTRICT"),
    ("penalties", "revoked_by"): ("users", "RESTRICT"),
    ("overrides", "cycle_id"): ("cycles", "RESTRICT"),
    ("overrides", "job_id"): ("jobs", "RESTRICT"),
    ("overrides", "enrollment_id"): ("enrollments", "RESTRICT"),
    ("overrides", "application_id"): ("applications", "RESTRICT"),
    ("overrides", "granted_by"): ("users", "RESTRICT"),
    ("notification_templates", "cycle_id"): ("cycles", "RESTRICT"),
    ("audit_log", "actor_user_id"): ("users", "RESTRICT"),
    ("export_presets", "job_id"): ("jobs", "RESTRICT"),
    ("export_jobs", "requested_by"): ("users", "RESTRICT"),
}


def _expected_columns() -> dict[str, set[str]]:
    expected: dict[str, set[str]] = {}
    for table_name, domain_columns in DOMAIN_COLUMNS.items():
        base_columns = {"created_at"}
        if table_name != "settings":
            base_columns.add("id")
        if table_name not in IMMUTABLE_TABLES:
            base_columns.add("updated_at")
        expected[table_name] = domain_columns | base_columns
    return expected


async def _catalog_rows(statement: str) -> list[RowMapping]:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            result = await connection.execute(sa.text(statement))
            return list(result.mappings())
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_schema_conformance() -> None:
    expected_columns = _expected_columns()
    table_rows = await _catalog_rows(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
    )
    all_tables = {str(row["table_name"]) for row in table_rows}
    domain_tables = {
        table
        for table in all_tables
        if table != "alembic_version" and not table.startswith("procrastinate_")
    }
    assert domain_tables == set(DOMAIN_COLUMNS)
    assert "procrastinate_jobs" in all_tables

    column_rows = await _catalog_rows(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'public'"
    )
    actual_columns: dict[str, set[str]] = {table: set() for table in DOMAIN_COLUMNS}
    for row in column_rows:
        table_name = str(row["table_name"])
        if table_name in actual_columns:
            actual_columns[table_name].add(str(row["column_name"]))
    assert actual_columns == expected_columns

    assert set(Base.metadata.tables) == set(DOMAIN_COLUMNS)
    for table_name, table in Base.metadata.tables.items():
        assert set(table.columns.keys()) == expected_columns[table_name]

    enum_rows = await _catalog_rows(
        "SELECT type.typname AS enum_name, enum.enumlabel AS enum_value "
        "FROM pg_type AS type "
        "JOIN pg_enum AS enum ON enum.enumtypid = type.oid "
        "JOIN pg_namespace AS namespace ON namespace.oid = type.typnamespace "
        "WHERE namespace.nspname = 'public' "
        "ORDER BY type.typname, enum.enumsortorder"
    )
    actual_enums: dict[str, list[str]] = {}
    for row in enum_rows:
        actual_enums.setdefault(str(row["enum_name"]), []).append(str(row["enum_value"]))
    assert {name: tuple(actual_enums[name]) for name in EXPECTED_ENUMS} == EXPECTED_ENUMS

    primary_key_rows = await _catalog_rows(
        "SELECT table_name, column_name FROM information_schema.table_constraints AS tc "
        "JOIN information_schema.key_column_usage AS kcu "
        "USING (constraint_catalog, constraint_schema, constraint_name, table_name) "
        "WHERE tc.constraint_schema = 'public' "
        "AND tc.constraint_type = 'PRIMARY KEY'"
    )
    primary_keys = {
        str(row["table_name"]): str(row["column_name"])
        for row in primary_key_rows
        if str(row["table_name"]) in DOMAIN_COLUMNS
    }
    assert primary_keys == {
        table_name: "key" if table_name == "settings" else "id"
        for table_name in DOMAIN_COLUMNS
    }

    partial_index_rows = await _catalog_rows(
        "SELECT index_class.relname AS index_name, table_class.relname AS table_name, "
        "index.indisunique, pg_get_expr(index.indpred, index.indrelid) AS predicate "
        "FROM pg_index AS index "
        "JOIN pg_class AS index_class ON index_class.oid = index.indexrelid "
        "JOIN pg_class AS table_class ON table_class.oid = index.indrelid "
        "JOIN pg_namespace AS namespace ON namespace.oid = table_class.relnamespace "
        "WHERE namespace.nspname = 'public' AND index.indisunique AND index.indpred IS NOT NULL"
    )
    partial_indexes = {
        str(row["index_name"]): str(row["table_name"])
        for row in partial_index_rows
        if str(row["table_name"]) in DOMAIN_COLUMNS
    }
    assert partial_indexes == EXPECTED_PARTIAL_UNIQUES

    unique_rows = await _catalog_rows(
        "SELECT con.conname AS constraint_name, table_class.relname AS table_name, "
        "array_agg(attribute.attname ORDER BY constraint_key.ordinality) AS columns, "
        "con.condeferrable, con.condeferred, unique_index.indnullsnotdistinct "
        "FROM pg_constraint AS con "
        "JOIN pg_class AS table_class ON table_class.oid = con.conrelid "
        "JOIN pg_index AS unique_index ON unique_index.indexrelid = con.conindid "
        "JOIN LATERAL unnest(con.conkey) WITH ORDINALITY "
        "AS constraint_key(attnum, ordinality) "
        "ON TRUE JOIN pg_attribute AS attribute "
        "ON attribute.attrelid = con.conrelid AND attribute.attnum = constraint_key.attnum "
        "WHERE con.contype = 'u' GROUP BY con.oid, table_class.relname, "
        "unique_index.indnullsnotdistinct"
    )
    unique_pairs: dict[str, tuple[str, tuple[str, ...]]] = {}
    for row in unique_rows:
        table_name = str(row["table_name"])
        columns = tuple(str(column) for column in cast(Sequence[object], row["columns"]))
        if table_name in DOMAIN_COLUMNS and len(columns) == 2:
            unique_pairs[str(row["constraint_name"])] = (table_name, columns)
    assert unique_pairs == EXPECTED_UNIQUE_PAIRS
    unique_by_name = {str(row["constraint_name"]): row for row in unique_rows}
    round_unique = unique_by_name["uq_job_rounds_job_id_ord"]
    assert round_unique["condeferrable"] is True
    assert round_unique["condeferred"] is True
    template_unique = unique_by_name["uq_notification_templates_event_key_cycle_id"]
    assert template_unique["indnullsnotdistinct"] is True

    check_rows = await _catalog_rows(
        "SELECT con.conname AS constraint_name, "
        "pg_get_constraintdef(con.oid) AS definition "
        "FROM pg_constraint AS con "
        "JOIN pg_class AS table_class ON table_class.oid = con.conrelid "
        "WHERE con.contype = 'c' AND table_class.relname = ANY "
        "(ARRAY['cycles', 'jobs', 'overrides'])"
    )
    checks = {str(row["constraint_name"]): str(row["definition"]) for row in check_rows}
    assert set(checks) == {
        "ck_cycles_start_before_end",
        "ck_jobs_offer_deadline_after_application_deadline",
        "ck_overrides_scope_combination",
    }
    assert "starts_on <= ends_on" in checks["ck_cycles_start_before_end"]
    assert "offer_acceptance_deadline > application_deadline" in checks[
        "ck_jobs_offer_deadline_after_application_deadline"
    ]
    scope_check = checks["ck_overrides_scope_combination"]
    assert "cycle_id IS NOT NULL" in scope_check
    assert "job_id IS NOT NULL" in scope_check
    assert "enrollment_id IS NOT NULL" in scope_check
    assert "application_id IS NOT NULL" in scope_check

    foreign_key_rows = await _catalog_rows(
        "SELECT source.relname AS table_name, source_attribute.attname AS column_name, "
        "target.relname AS target_table, "
        "CASE con.confdeltype WHEN 'r' THEN 'RESTRICT' WHEN 'n' THEN 'SET NULL' "
        "ELSE con.confdeltype::text END AS delete_rule "
        "FROM pg_constraint AS con "
        "JOIN pg_class AS source ON source.oid = con.conrelid "
        "JOIN pg_class AS target ON target.oid = con.confrelid "
        "JOIN LATERAL unnest(con.conkey) WITH ORDINALITY "
        "AS constraint_key(attnum, ordinality) "
        "ON TRUE JOIN pg_attribute AS source_attribute "
        "ON source_attribute.attrelid = source.oid "
        "AND source_attribute.attnum = constraint_key.attnum "
        "WHERE con.contype = 'f'"
    )
    foreign_keys = {
        (str(row["table_name"]), str(row["column_name"])): (
            str(row["target_table"]),
            str(row["delete_rule"]),
        )
        for row in foreign_key_rows
        if str(row["table_name"]) in DOMAIN_COLUMNS
    }
    assert foreign_keys == EXPECTED_FOREIGN_KEYS


async def _assert_permission_denied(statement: str) -> None:
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        with pytest.raises(DBAPIError) as error:
            async with engine.connect() as connection:
                await connection.execute(sa.text(statement))
        assert getattr(error.value.orig, "sqlstate", None) == "42501"
    finally:
        await engine.dispose()


async def _table_privileges(table_name: str) -> set[str]:
    rows = await _catalog_rows(
        "SELECT privilege_type FROM information_schema.role_table_grants "
        f"WHERE grantee = 'cds_app' AND table_schema = 'public' "
        f"AND table_name = '{table_name}'"
    )
    return {str(row["privilege_type"]) for row in rows}


@pytest.mark.asyncio
async def test_append_only_events() -> None:
    assert await _table_privileges("application_events") == {"INSERT", "SELECT"}
    await _assert_permission_denied(
        "UPDATE application_events SET reason = reason WHERE false"
    )
    await _assert_permission_denied("DELETE FROM application_events WHERE false")


@pytest.mark.asyncio
async def test_append_only_audit() -> None:
    assert await _table_privileges("audit_log") == {"INSERT", "SELECT"}
    await _assert_permission_denied("UPDATE audit_log SET action = action WHERE false")
    await _assert_permission_denied("DELETE FROM audit_log WHERE false")


@pytest.mark.asyncio
async def test_application_role_has_crud_on_authoritative_tables() -> None:
    expected_crud = {"DELETE", "INSERT", "SELECT", "UPDATE"}
    for table_name in set(DOMAIN_COLUMNS) - {"application_events", "audit_log"}:
        assert await _table_privileges(table_name) == expected_crud

    table_rows = await _catalog_rows(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name LIKE 'procrastinate_%'"
    )
    queue_tables = {str(row["table_name"]) for row in table_rows}
    assert queue_tables
    for table_name in queue_tables:
        assert await _table_privileges(table_name) == expected_crud
