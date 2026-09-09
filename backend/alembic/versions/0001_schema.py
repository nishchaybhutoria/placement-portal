"""Create the complete LLD section 8 schema.

Revision ID: 0001_schema
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUM_VALUES: dict[str, tuple[str, ...]] = {
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
        "edit_withdraw_window",
        "outcome_gate",
        "offer_cap",
        "offer_deadline",
    ),
    "offer_expiry_t": ("auto_decline", "auto_accept"),
    "outcome_tag_t": ("higher_studies", "entrepreneurship", "not_seeking"),
    "event_type_t": (
        "created",
        "advanced",
        "eliminated",
        "waitlisted",
        "attendance_marked",
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


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*ENUM_VALUES[name], name=name, create_type=False)


def _id_column() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def _created_at_column() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def _updated_at_column() -> sa.Column:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def _base_columns(*, mutable: bool = True) -> tuple[sa.Column, ...]:
    columns = [_id_column(), _created_at_column()]
    if mutable:
        columns.append(_updated_at_column())
    return tuple(columns)


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    for name, values in ENUM_VALUES.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=False)

    op.create_table(
        "users",
        *_base_columns(),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column(
            "role",
            _enum("role_t"),
            nullable=False,
            server_default=sa.text("'student'::role_t"),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "sessions",
        *_base_columns(),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", name="fk_sessions_user_id_users", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
    )
    op.create_table(
        "enrollments",
        *_base_columns(),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id", name="fk_enrollments_user_id_users", ondelete="RESTRICT"
            ),
            nullable=False,
        ),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("roll_number", postgresql.CITEXT()),
    )
    op.create_index(
        "uq_enrollments_current_roll_number",
        "enrollments",
        ["roll_number"],
        unique=True,
        postgresql_where=sa.text("is_current AND roll_number IS NOT NULL"),
    )
    op.create_index(
        "uq_enrollments_current_user_id",
        "enrollments",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )

    for table_name in ("programs", "branches", "minors", "sectors", "round_types"):
        op.create_table(
            table_name,
            *_base_columns(),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.UniqueConstraint("name", name=f"uq_{table_name}_name"),
        )
    op.create_table(
        "program_branches",
        *_base_columns(mutable=False),
        sa.Column(
            "program_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "programs.id",
                name="fk_program_branches_program_id_programs",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column(
            "branch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "branches.id",
                name="fk_program_branches_branch_id_branches",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "program_id", "branch_id", name="uq_program_branches_program_id_branch_id"
        ),
    )
    op.create_table(
        "settings",
        # SPEC-GAP: LLD section 8's universal UUID-PK rule conflicts with the explicit
        # `settings(key text pk, ...)` declaration. The explicit key primary key wins.
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id", name="fk_settings_updated_by_users", ondelete="RESTRICT"
            ),
        ),
        _created_at_column(),
        _updated_at_column(),
    )

    op.create_table(
        "profiles",
        *_base_columns(),
        sa.Column(
            "enrollment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "enrollments.id", name="fk_profiles_enrollment_id_enrollments", ondelete="RESTRICT"
            ),
            nullable=False,
        ),
        sa.Column(
            "program_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "programs.id", name="fk_profiles_program_id_programs", ondelete="RESTRICT"
            ),
        ),
        sa.Column(
            "primary_branch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "branches.id",
                name="fk_profiles_primary_branch_id_branches",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column(
            "secondary_branch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "branches.id",
                name="fk_profiles_secondary_branch_id_branches",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column("graduating_year", sa.Integer()),
        sa.Column("cpi", sa.Numeric(4, 2)),
        sa.Column("active_backlogs", sa.Integer()),
        sa.Column("total_backlogs", sa.Integer()),
        sa.Column("gender", _enum("gender_t")),
        sa.Column("personal_email", postgresql.CITEXT()),
        sa.Column("contact_number", sa.Text()),
        sa.Column("nationality", sa.Text(), server_default=sa.text("'IN'")),
        sa.Column("tenth_percent", sa.Numeric(5, 2)),
        sa.Column("tenth_year", sa.Integer()),
        sa.Column("twelfth_percent", sa.Numeric(5, 2)),
        sa.Column("twelfth_year", sa.Integer()),
        sa.Column(
            "minor1_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("minors.id", name="fk_profiles_minor1_id_minors", ondelete="RESTRICT"),
        ),
        sa.Column(
            "minor2_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("minors.id", name="fk_profiles_minor2_id_minors", ondelete="RESTRICT"),
        ),
        sa.Column("github_url", sa.Text()),
        sa.Column("linkedin_url", sa.Text()),
        sa.Column("portfolio_url", sa.Text()),
        sa.Column("declared_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("enrollment_id", name="uq_profiles_enrollment_id"),
    )
    op.create_table(
        "resumes",
        *_base_columns(),
        sa.Column(
            "enrollment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "enrollments.id", name="fk_resumes_enrollment_id_enrollments", ondelete="RESTRICT"
            ),
            nullable=False,
        ),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("drive_url", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
    )
    op.create_index(
        "uq_resumes_default_enrollment_id",
        "resumes",
        ["enrollment_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_table(
        "staged_profile_rows",
        *_base_columns(),
        sa.Column("institute_email", postgresql.CITEXT(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "uploaded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id", name="fk_staged_profile_rows_uploaded_by_users", ondelete="RESTRICT"
            ),
            nullable=False,
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
    )

    op.create_table(
        "cycles",
        *_base_columns(),
        sa.Column("name", postgresql.CITEXT(), nullable=False),
        sa.Column("kind", _enum("cycle_kind_t"), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("starts_on", sa.Date()),
        sa.Column("ends_on", sa.Date()),
        sa.Column("registration_opens_at", sa.DateTime(timezone=True)),
        sa.Column("registration_closes_at", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("name", name="uq_cycles_name"),
        sa.CheckConstraint(
            "starts_on IS NULL OR ends_on IS NULL OR starts_on <= ends_on",
            name="ck_cycles_start_before_end",
        ),
    )
    op.create_table(
        "cycle_policies",
        *_base_columns(),
        sa.Column(
            "cycle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "cycles.id", name="fk_cycle_policies_cycle_id_cycles", ondelete="RESTRICT"
            ),
            nullable=False,
        ),
        sa.Column("membership_requires_approval", sa.Boolean(), nullable=False),
        sa.Column("join_rule", postgresql.JSONB()),
        sa.Column("max_accepted_offers", sa.Integer()),
        sa.Column("penalty_blocks_applications", sa.Boolean(), nullable=False),
        sa.Column("allow_withdrawal_after_deadline", sa.Boolean(), nullable=False),
        sa.Column("allow_edit_after_deadline", sa.Boolean(), nullable=False),
        sa.Column("strike_on_absence", sa.Boolean(), nullable=False),
        sa.Column(
            "offer_expiry_behavior",
            _enum("offer_expiry_t"),
            nullable=False,
            server_default=sa.text("'auto_decline'::offer_expiry_t"),
        ),
        sa.Column(
            "deadline_reminder_hours", sa.Integer(), nullable=False, server_default=sa.text("6")
        ),
        sa.Column(
            "round_reminder_hours", sa.Integer(), nullable=False, server_default=sa.text("24")
        ),
        sa.UniqueConstraint("cycle_id", name="uq_cycle_policies_cycle_id"),
    )
    op.create_table(
        "cycle_coordinators",
        *_base_columns(mutable=False),
        sa.Column(
            "cycle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "cycles.id", name="fk_cycle_coordinators_cycle_id_cycles", ondelete="RESTRICT"
            ),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id", name="fk_cycle_coordinators_user_id_users", ondelete="RESTRICT"
            ),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "cycle_id", "user_id", name="uq_cycle_coordinators_cycle_id_user_id"
        ),
    )
    op.create_table(
        "cycle_memberships",
        *_base_columns(),
        sa.Column(
            "cycle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "cycles.id", name="fk_cycle_memberships_cycle_id_cycles", ondelete="RESTRICT"
            ),
            nullable=False,
        ),
        sa.Column(
            "enrollment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "enrollments.id",
                name="fk_cycle_memberships_enrollment_id_enrollments",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("status", _enum("membership_status_t"), nullable=False),
        sa.Column(
            "default_resume_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "resumes.id",
                name="fk_cycle_memberships_default_resume_id_resumes",
                ondelete="SET NULL",
            ),
        ),
        sa.Column("consented_at", sa.DateTime(timezone=True)),
        sa.Column(
            "decided_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id", name="fk_cycle_memberships_decided_by_users", ondelete="RESTRICT"
            ),
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column("outcome_tag", _enum("outcome_tag_t")),
        sa.Column("auto_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint(
            "cycle_id", "enrollment_id", name="uq_cycle_memberships_cycle_id_enrollment_id"
        ),
    )

    op.create_table(
        "companies",
        *_base_columns(),
        sa.Column("name", postgresql.CITEXT(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("website_url", sa.Text()),
        sa.Column(
            "sector_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "sectors.id", name="fk_companies_sector_id_sectors", ondelete="RESTRICT"
            ),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("name", name="uq_companies_name"),
    )
    op.create_table(
        "company_contacts",
        *_base_columns(),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "companies.id",
                name="fk_company_contacts_company_id_companies",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("phone", sa.Text()),
        sa.Column("designation", sa.Text()),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.UniqueConstraint(
            "company_id", "email", name="uq_company_contacts_company_id_email"
        ),
    )
    op.create_index(
        "uq_company_contacts_primary_company_id",
        "company_contacts",
        ["company_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )

    op.create_table(
        "jobs",
        *_base_columns(),
        sa.Column(
            "cycle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cycles.id", name="fk_jobs_cycle_id_cycles", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "companies.id", name="fk_jobs_company_id_companies", ondelete="RESTRICT"
            ),
            nullable=False,
        ),
        sa.Column("outcome", _enum("outcome_t"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("location", sa.Text()),
        sa.Column(
            "sector_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sectors.id", name="fk_jobs_sector_id_sectors", ondelete="RESTRICT"),
        ),
        sa.Column("ctc_lpa", sa.Numeric(10, 2)),
        sa.Column("ctc_breakdown", sa.Text()),
        sa.Column("stipend_month", sa.Numeric(10, 2)),
        sa.Column("application_deadline", sa.DateTime(timezone=True)),
        sa.Column("offer_acceptance_deadline", sa.DateTime(timezone=True)),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("eligibility_rule", postgresql.JSONB()),
        sa.Column("eligibility_summary", sa.Text()),
        sa.CheckConstraint(
            "offer_acceptance_deadline IS NULL OR application_deadline IS NULL "
            "OR offer_acceptance_deadline > application_deadline",
            name="ck_jobs_offer_deadline_after_application_deadline",
        ),
    )
    op.create_table(
        "job_program_ctc",
        *_base_columns(),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "jobs.id", name="fk_job_program_ctc_job_id_jobs", ondelete="RESTRICT"
            ),
            nullable=False,
        ),
        sa.Column(
            "program_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "programs.id",
                name="fk_job_program_ctc_program_id_programs",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("ctc_lpa", sa.Numeric(10, 2), nullable=False),
        sa.UniqueConstraint(
            "job_id", "program_id", name="uq_job_program_ctc_job_id_program_id"
        ),
    )
    op.create_table(
        "job_rounds",
        *_base_columns(),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", name="fk_job_rounds_job_id_jobs", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "round_type_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "round_types.id",
                name="fk_job_rounds_round_type_id_round_types",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("ord", sa.Integer(), nullable=False),
        sa.Column("venue", sa.Text()),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("duration_min", sa.Integer()),
        sa.Column("instructions", sa.Text()),
        sa.UniqueConstraint(
            "job_id",
            "ord",
            name="uq_job_rounds_job_id_ord",
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    op.create_table(
        "job_questions",
        *_base_columns(),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "jobs.id", name="fk_job_questions_job_id_jobs", ondelete="RESTRICT"
            ),
            nullable=False,
        ),
        sa.Column("ord", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("qtype", _enum("question_type_t"), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "job_question_options",
        *_base_columns(),
        sa.Column(
            "question_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "job_questions.id",
                name="fk_job_question_options_question_id_job_questions",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("ord", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
    )

    op.create_table(
        "applications",
        *_base_columns(),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "jobs.id", name="fk_applications_job_id_jobs", ondelete="RESTRICT"
            ),
            nullable=False,
        ),
        sa.Column(
            "enrollment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "enrollments.id",
                name="fk_applications_enrollment_id_enrollments",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("status", _enum("application_status_t"), nullable=False),
        sa.Column(
            "current_round_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "job_rounds.id",
                name="fk_applications_current_round_id_job_rounds",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column("resume_url", sa.Text(), nullable=False),
        sa.Column("profile_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_applications_active_job_enrollment",
        "applications",
        ["job_id", "enrollment_id"],
        unique=True,
        postgresql_where=sa.text(
            "status NOT IN ('withdrawn'::application_status_t, "
            "'auto_withdrawn'::application_status_t)"
        ),
    )
    op.create_index(
        "ix_applications_enrollment_id_status",
        "applications",
        ["enrollment_id", "status"],
    )
    op.create_index(
        "ix_applications_job_id_status", "applications", ["job_id", "status"]
    )
    op.create_table(
        "application_answers",
        *_base_columns(),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "applications.id",
                name="fk_application_answers_application_id_applications",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column(
            "question_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "job_questions.id",
                name="fk_application_answers_question_id_job_questions",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint(
            "application_id",
            "question_id",
            name="uq_application_answers_application_id_question_id",
        ),
    )
    op.create_table(
        "application_round_states",
        *_base_columns(),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "applications.id",
                name="fk_application_round_states_application_id_applications",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column(
            "round_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "job_rounds.id",
                name="fk_application_round_states_round_id_job_rounds",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column(
            "result",
            _enum("round_result_t"),
            nullable=False,
            server_default=sa.text("'pending'::round_result_t"),
        ),
        sa.Column(
            "attendance",
            _enum("attendance_t"),
            nullable=False,
            server_default=sa.text("'pending'::attendance_t"),
        ),
        sa.Column("venue_override", sa.Text()),
        sa.Column("scheduled_at_override", sa.DateTime(timezone=True)),
        sa.Column("notified_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "application_id",
            "round_id",
            name="uq_application_round_states_application_id_round_id",
        ),
    )
    op.create_table(
        "application_events",
        *_base_columns(mutable=False),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "applications.id",
                name="fk_application_events_application_id_applications",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("event_type", _enum("event_type_t"), nullable=False),
        sa.Column("from_status", _enum("application_status_t")),
        sa.Column("to_status", _enum("application_status_t")),
        sa.Column(
            "from_round_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "job_rounds.id",
                name="fk_application_events_from_round_id_job_rounds",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column(
            "to_round_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "job_rounds.id",
                name="fk_application_events_to_round_id_job_rounds",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id",
                name="fk_application_events_actor_user_id_users",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column("reason", sa.Text()),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True)),
    )

    op.create_table(
        "offers",
        *_base_columns(),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "applications.id", name="fk_offers_application_id_applications", ondelete="RESTRICT"
            ),
            nullable=False,
        ),
        sa.Column("extended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True)),
        sa.Column("response", _enum("offer_response_t")),
        sa.Column("responded_at", sa.DateTime(timezone=True)),
        sa.Column("terminated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "terminated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id", name="fk_offers_terminated_by_users", ondelete="RESTRICT"
            ),
        ),
        sa.Column("termination_kind", _enum("termination_kind_t")),
        sa.Column("termination_reason", sa.Text()),
    )
    op.execute(
        "CREATE INDEX ix_offers_application_id_extended_at_desc "
        "ON offers (application_id, extended_at DESC)"
    )
    op.create_table(
        "external_offers",
        *_base_columns(),
        sa.Column(
            "enrollment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "enrollments.id",
                name="fk_external_offers_enrollment_id_enrollments",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "companies.id",
                name="fk_external_offers_company_id_companies",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("outcome", _enum("outcome_t"), nullable=False),
        sa.Column("source", _enum("external_source_t"), nullable=False),
        sa.Column("ctc_lpa", sa.Numeric(10, 2)),
        sa.Column("stipend_month", sa.Numeric(10, 2)),
        sa.Column("status", _enum("external_status_t"), nullable=False),
        sa.Column("offered_on", sa.Date()),
        sa.Column("responded_on", sa.Date()),
        sa.Column(
            "source_application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "applications.id",
                name="fk_external_offers_source_application_id_applications",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column(
            "attached_cycle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "cycles.id",
                name="fk_external_offers_attached_cycle_id_cycles",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id", name="fk_external_offers_created_by_users", ondelete="RESTRICT"
            ),
            nullable=False,
        ),
    )

    # the design review amendment 10: create both tables before adding the cyclic strike FK.
    op.create_table(
        "strikes",
        *_base_columns(),
        sa.Column(
            "enrollment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "enrollments.id", name="fk_strikes_enrollment_id_enrollments", ondelete="RESTRICT"
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source", _enum("strike_source_t"), nullable=False),
        sa.Column(
            "awarded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id", name="fk_strikes_awarded_by_users", ondelete="RESTRICT"
            ),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("consumed_by_penalty_id", postgresql.UUID(as_uuid=True)),
    )
    op.create_table(
        "penalties",
        *_base_columns(),
        sa.Column(
            "enrollment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "enrollments.id",
                name="fk_penalties_enrollment_id_enrollments",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("reasons", sa.Text(), nullable=False),
        sa.Column("from_strikes", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id", name="fk_penalties_created_by_users", ondelete="RESTRICT"
            ),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "revoked_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id", name="fk_penalties_revoked_by_users", ondelete="RESTRICT"
            ),
        ),
    )
    op.create_foreign_key(
        "fk_strikes_consumed_by_penalty_id_penalties",
        "strikes",
        "penalties",
        ["consumed_by_penalty_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "overrides",
        *_base_columns(),
        sa.Column("rule_domain", _enum("rule_domain_t"), nullable=False),
        sa.Column("allow", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "cycle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "cycles.id", name="fk_overrides_cycle_id_cycles", ondelete="RESTRICT"
            ),
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", name="fk_overrides_job_id_jobs", ondelete="RESTRICT"),
        ),
        sa.Column(
            "enrollment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "enrollments.id",
                name="fk_overrides_enrollment_id_enrollments",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "applications.id",
                name="fk_overrides_application_id_applications",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "granted_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id", name="fk_overrides_granted_by_users", ondelete="RESTRICT"
            ),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "notification_templates",
        *_base_columns(),
        sa.Column("event_key", sa.Text(), nullable=False),
        sa.Column(
            "cycle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "cycles.id",
                name="fk_notification_templates_cycle_id_cycles",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint(
            "event_key",
            "cycle_id",
            name="uq_notification_templates_event_key_cycle_id",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_table(
        "notification_log",
        *_base_columns(),
        sa.Column("recipient", postgresql.CITEXT(), nullable=False),
        sa.Column("event_key", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("status", _enum("notif_status_t"), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("context", postgresql.JSONB(), nullable=False),
    )
    op.create_table(
        "reminder_sends",
        *_base_columns(mutable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("dedup_key", sa.Text(), nullable=False),
        sa.UniqueConstraint("dedup_key", name="uq_reminder_sends_dedup_key"),
    )
    op.create_table(
        "audit_log",
        *_base_columns(mutable=False),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id", name="fk_audit_log_actor_user_id_users", ondelete="RESTRICT"
            ),
        ),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.Text()),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True)),
        sa.Column("details", postgresql.JSONB(), nullable=False),
    )
    op.create_table(
        "idempotency_keys",
        *_base_columns(mutable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("key", name="uq_idempotency_keys_key"),
    )
    op.create_table(
        "consistency_findings",
        *_base_columns(),
        sa.Column("invariant", sa.Text(), nullable=False),
        sa.Column("subject", postgresql.JSONB(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column(
            "status",
            _enum("finding_status_t"),
            nullable=False,
            server_default=sa.text("'open'::finding_status_t"),
        ),
        sa.Column("suggested_fix", sa.Text()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "export_presets",
        *_base_columns(),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "jobs.id", name="fk_export_presets_job_id_jobs", ondelete="RESTRICT"
            ),
            nullable=False,
        ),
        sa.Column("columns", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("job_id", name="uq_export_presets_job_id"),
    )
    op.create_table(
        "export_jobs",
        *_base_columns(),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "requested_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id", name="fk_export_jobs_requested_by_users", ondelete="RESTRICT"
            ),
            nullable=False,
        ),
        sa.Column("result_meta", postgresql.JSONB()),
        sa.Column("error", sa.Text()),
    )


def downgrade() -> None:
    op.drop_table("export_jobs")
    op.drop_table("export_presets")
    op.drop_table("consistency_findings")
    op.drop_table("idempotency_keys")
    op.drop_table("audit_log")
    op.drop_table("reminder_sends")
    op.drop_table("notification_log")
    op.drop_table("notification_templates")
    op.drop_table("overrides")
    op.drop_constraint(
        "fk_strikes_consumed_by_penalty_id_penalties", "strikes", type_="foreignkey"
    )
    op.drop_table("penalties")
    op.drop_table("strikes")
    op.drop_table("external_offers")
    op.drop_table("offers")
    op.drop_table("application_events")
    op.drop_table("application_round_states")
    op.drop_table("application_answers")
    op.drop_table("applications")
    op.drop_table("job_question_options")
    op.drop_table("job_questions")
    op.drop_table("job_rounds")
    op.drop_table("job_program_ctc")
    op.drop_table("jobs")
    op.drop_table("company_contacts")
    op.drop_table("companies")
    op.drop_table("cycle_memberships")
    op.drop_table("cycle_coordinators")
    op.drop_table("cycle_policies")
    op.drop_table("cycles")
    op.drop_table("staged_profile_rows")
    op.drop_table("resumes")
    op.drop_table("profiles")
    op.drop_table("settings")
    op.drop_table("program_branches")
    op.drop_table("round_types")
    op.drop_table("sectors")
    op.drop_table("minors")
    op.drop_table("branches")
    op.drop_table("programs")
    op.drop_table("enrollments")
    op.drop_table("sessions")
    op.drop_table("users")

    bind = op.get_bind()
    for name, values in reversed(ENUM_VALUES.items()):
        postgresql.ENUM(*values, name=name).drop(bind, checkfirst=False)
