"""Move the dual-major flag from the program to the student.

the design review section 4.18 put ``is_dual_major`` on the ``programs`` taxonomy row,
reasoning that it is a property of the program rather than of the student.
Section 4.32 reverses that: a dual major is a student completing two majors at
once, one primary and one secondary -- which is why PRO-1 already gives the
profile ``primary_branch_id`` and ``secondary_branch_id``, and why it requires
the second "if dual major".  Two students on the same BTech differ on exactly
this, so the program cannot be what decides it.

The backfill runs while both columns exist, and is deliberately generous: a
profile that already names a secondary branch *is* a dual major whatever the
old taxonomy said, and a student on a program the office had flagged keeps the
flag.  Nobody is demoted by the move.

Revision ID: 0010_profile_dual_major
Revises: 0009_reinstated_notification
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_profile_dual_major"
down_revision: str | None = "0009_reinstated_notification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column(
            "is_dual_major",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute(
        """
        UPDATE profiles p
        SET is_dual_major = true
        WHERE p.secondary_branch_id IS NOT NULL
           OR EXISTS (
               SELECT 1 FROM programs pr
               WHERE pr.id = p.program_id AND pr.is_dual_major
           )
        """
    )
    op.drop_column("programs", "is_dual_major")


def downgrade() -> None:
    op.add_column(
        "programs",
        sa.Column(
            "is_dual_major",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # The reverse cannot be faithful -- a per-student fact does not fit back
    # into a per-program column -- so it restores the reading 4.18 would have
    # given: a program is dual-major if any of its students was.
    op.execute(
        """
        UPDATE programs pr
        SET is_dual_major = true
        WHERE EXISTS (
            SELECT 1 FROM profiles p
            WHERE p.program_id = pr.id AND p.is_dual_major
        )
        """
    )
    op.drop_column("profiles", "is_dual_major")
