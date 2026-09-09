"""Record that a round was finalized, and by whom.

RND-3 makes finalization explicit and previewed, but nothing recorded that it
had happened: "finalized" could only be derived from "no pending rows remain",
which is equally true of a round nobody has reached.  A board could therefore
never truthfully show a round as closed, and a coordinator could not tell
whether a colleague had already finalized it -- which matters, because
finalization awards strikes (the design review section 4.25).

Revision ID: 0006_round_finalized
Revises: 0005_venue_assigned_event
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_round_finalized"
down_revision: str | None = "0005_venue_assigned_event"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "job_rounds", sa.Column("finalized_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "job_rounds",
        sa.Column("finalized_by", postgresql.UUID(as_uuid=True)),
    )
    op.create_foreign_key(
        "fk_job_rounds_finalized_by_users",
        "job_rounds",
        "users",
        ["finalized_by"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_job_rounds_finalized_by_users", "job_rounds", type_="foreignkey")
    op.drop_column("job_rounds", "finalized_by")
    op.drop_column("job_rounds", "finalized_at")
