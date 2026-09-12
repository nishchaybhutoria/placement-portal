"""Collect session-qualified study years without changing existing eligibility.

Revision ID: 0016_academic_standing
Revises: 0015_override_scope_domains

This additive release deliberately leaves every existing profile NULL. It does
not change memberships, applications, job rules, imports, or academic-session
settings. The office configures the session through the audited set_setting
command; students declare their actual standing (1–8), never a derived year.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016_academic_standing"
down_revision: str | None = "0015_override_scope_domains"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("study_year", sa.Integer(), nullable=True))
    op.add_column("profiles", sa.Column("study_year_session", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_profiles_study_year_range", "profiles", "study_year BETWEEN 1 AND 8"
    )
    op.create_check_constraint(
        "ck_profiles_study_year_session_range",
        "profiles",
        "study_year_session BETWEEN 1900 AND 2100",
    )
    op.create_check_constraint(
        "ck_profiles_study_year_pair", "profiles",
        "(study_year IS NULL) = (study_year_session IS NULL)",
    )


def downgrade() -> None:
    # Rolling back application code against additive columns is safe. Dropping
    # collected student facts is not an undo: require an explicit recovery plan.
    collected = op.get_bind().scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM profiles WHERE study_year IS NOT NULL "
        "OR study_year_session IS NOT NULL)"
    ))
    if collected:
        raise RuntimeError(
            "Cannot drop collected academic standing. Keep the additive schema "
            "and roll back application code, or use a reviewed recovery plan."
        )
    op.drop_constraint("ck_profiles_study_year_pair", "profiles", type_="check")
    op.drop_constraint("ck_profiles_study_year_session_range", "profiles", type_="check")
    op.drop_constraint("ck_profiles_study_year_range", "profiles", type_="check")
    op.drop_column("profiles", "study_year_session")
    op.drop_column("profiles", "study_year")
