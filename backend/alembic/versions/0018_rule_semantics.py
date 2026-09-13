"""Version eligibility-rule evaluation without rewriting existing rules.

Revision ID: 0018_rule_semantics
Revises: 0017_program_structure

Rules already stored in production retain the evaluator contract under which
an owner reviewed them.  Newly authored or explicitly re-saved rules use the
current fail-closed contract.  The same rule tree can therefore be previewed
under the new contract without a migration silently changing its verdicts.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018_rule_semantics"
down_revision: str | None = "0017_program_structure"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_version(table: str, column: str, constraint: str) -> None:
    op.add_column(
        table,
        sa.Column(column, sa.SmallInteger(), nullable=False, server_default="1"),
    )
    op.create_check_constraint(constraint, table, f"{column} IN (1, 2)")
    # Existing rows were materialized as v1 by ADD COLUMN. New rows default to
    # v2; commands also write v2 explicitly whenever a rule is changed.
    op.alter_column(table, column, server_default="2")


def upgrade() -> None:
    _add_version("jobs", "eligibility_rule_version", "ck_jobs_rule_version")
    _add_version(
        "cycle_policies", "join_rule_version", "ck_cycle_policies_join_rule_version"
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_cycle_policies_join_rule_version", "cycle_policies", type_="check"
    )
    op.drop_column("cycle_policies", "join_rule_version")
    op.drop_constraint("ck_jobs_rule_version", "jobs", type_="check")
    op.drop_column("jobs", "eligibility_rule_version")
