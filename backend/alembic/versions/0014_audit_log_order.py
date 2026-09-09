"""Record audit-log append order, backfilling existing history.

Revision ID: 0014_audit_log_order
Revises: 0013_notification_copy

The same defect §4.41 fixed for ``application_events``: two audit rows written
in one transaction share ``now()``, and the reader broke the tie on a random
UUID, so a trail could display out of the order it happened in.

Where this deliberately parts from ``0012``: that migration *refused* a
populated table rather than invent ordering for history it could not know. That
was right for a disposable mock database and is impossible here, because a
production audit trail is exactly the thing nobody may reset. So existing rows
are backfilled by ``(created_at, id)`` and the ruling records what that is
worth: for rows that already share a timestamp the tie is still broken by UUID,
which is the very thing being fixed, so pre-migration order is **best effort**.
From this migration forward the sequence is authoritative.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014_audit_log_order"
down_revision: str | None = "0013_notification_copy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Held through backfill and constraint creation together, so no writer can
    # insert an unsequenced row between numbering the old ones and requiring it.
    op.execute("LOCK TABLE audit_log IN ACCESS EXCLUSIVE MODE")
    op.add_column("audit_log", sa.Column("audit_seq", sa.BigInteger(), nullable=True))
    op.execute(
        """
        WITH ordered AS (
            SELECT id, row_number() OVER (ORDER BY created_at, id) AS position
            FROM audit_log
        )
        UPDATE audit_log
        SET audit_seq = ordered.position
        FROM ordered
        WHERE audit_log.id = ordered.id
        """
    )
    op.alter_column("audit_log", "audit_seq", nullable=False)
    op.create_unique_constraint("uq_audit_log_audit_seq", "audit_log", ["audit_seq"])
    # Attached after the backfill so the identity continues from the highest
    # backfilled value rather than colliding with it.
    op.execute("ALTER TABLE audit_log ALTER COLUMN audit_seq ADD GENERATED ALWAYS AS IDENTITY")
    op.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('audit_log', 'audit_seq'),
            COALESCE((SELECT max(audit_seq) FROM audit_log), 0) + 1,
            false
        )
        """
    )


def downgrade() -> None:
    op.execute("LOCK TABLE audit_log IN ACCESS EXCLUSIVE MODE")
    op.execute("ALTER TABLE audit_log ALTER COLUMN audit_seq DROP IDENTITY IF EXISTS")
    op.drop_constraint("uq_audit_log_audit_seq", "audit_log", type_="unique")
    op.drop_column("audit_log", "audit_seq")
