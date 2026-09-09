"""Mark which programs are dual majors.

Behavior PRO-1 requires a secondary branch "if dual major" and ELG-2 implies
eligibility rules can target dual majors, but nothing in the schema recorded
the fact, so neither was expressible (the design review section 4.18).  It lives on the
program rather than the profile because it is a property of the program a
student is enrolled in, not of the student.

Revision ID: 0004_program_dual_major
Revises: 0003_procrastinate_grants
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_program_dual_major"
down_revision: str | None = "0003_procrastinate_grants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "programs",
        sa.Column(
            "is_dual_major",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("programs", "is_dual_major")
