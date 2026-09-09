"""Add the reinstatement notification omitted from the LLD section 13 catalog.

Revision ID: 0009_reinstated_notification
Revises: 0008_notification_catalog
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_reinstated_notification"
down_revision: str | None = "0008_notification_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# the design review section 4.28 records the amendment: Behavior INT-1 gives
# reinstatement a notify choice and the APP-4.14 transition row carries
# ``notify:optional``, so the catalog's omission is the same class of gap the
# 0008 migration closed for ``deadline_changed`` and ``declined_confirm``.
_DEFAULTS: tuple[tuple[str, str, str], ...] = (
    (
        "reinstated",
        "Application reinstated: {job}",
        "Dear {student},\n\nYour application for {job} at {company} has been "
        "reinstated by the placement team.\n"
        "Current round: {round}\n"
        "Reason: {reason}\n\n"
        "Please check the CDS Portal for what happens next.\n\n"
        "Regards,\nCareer Development Services",
    ),
)


def upgrade() -> None:
    table = sa.table(
        "notification_templates",
        sa.column("event_key", sa.Text()),
        sa.column("cycle_id", sa.Uuid()),
        sa.column("subject", sa.Text()),
        sa.column("body", sa.Text()),
        sa.column("enabled", sa.Boolean()),
    )
    op.bulk_insert(
        table,
        [
            {
                "event_key": event_key,
                "cycle_id": None,
                "subject": subject,
                "body": body,
                "enabled": True,
            }
            for event_key, subject, body in _DEFAULTS
        ],
    )


def downgrade() -> None:
    keys = [event_key for event_key, _subject, _body in _DEFAULTS]
    op.execute(
        sa.text(
            "DELETE FROM notification_templates WHERE cycle_id IS NULL AND event_key = ANY(:keys)"
        ).bindparams(sa.bindparam("keys", value=keys))
    )
