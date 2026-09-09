"""Represent BTech dual degrees without conflating them with dual majors.

Revision ID: 0011_dual_degree_profiles
Revises: 0010_profile_dual_major
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_dual_degree_profiles"
down_revision: str | None = "0010_profile_dual_major"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column("is_dual_degree", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("profiles", sa.Column("secondary_program_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_profiles_secondary_program_id_programs",
        "profiles",
        "programs",
        ["secondary_program_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_profiles_one_dual_kind",
        "profiles",
        "NOT (is_dual_major AND is_dual_degree)",
    )
    op.create_check_constraint(
        "ck_profiles_dual_degree_program",
        "profiles",
        "is_dual_degree = (secondary_program_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_profiles_secondary_branch_kind",
        "profiles",
        "secondary_branch_id IS NULL OR is_dual_major OR is_dual_degree",
    )


def downgrade() -> None:
    op.drop_constraint("ck_profiles_secondary_branch_kind", "profiles", type_="check")
    op.drop_constraint("ck_profiles_dual_degree_program", "profiles", type_="check")
    op.drop_constraint("ck_profiles_one_dual_kind", "profiles", type_="check")
    op.drop_constraint("fk_profiles_secondary_program_id_programs", "profiles", type_="foreignkey")
    op.drop_column("profiles", "secondary_program_id")
    op.drop_column("profiles", "is_dual_degree")
