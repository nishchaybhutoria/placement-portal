"""One notice for a placement that moved, instead of two that contradict it.

Revision ID: 0021_placement_replaced_notice
Revises: 0020_idempotency_key_length

``replace_placement`` ends one accepted placement offer and takes up another in
a single transaction (Behavior OFR-3/OFR-5). Composing it out of the existing
notices would send the student "your offer has been terminated" and "you have
accepted an offer" moments apart, with nothing saying they are the same event
and nothing saying which job they now hold. This template says both halves at
once, which is the only form of the message that is true on its own.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0021_placement_replaced_notice"
down_revision: str | None = "0020_idempotency_key_length"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULTS: tuple[tuple[str, str, str], ...] = (
    (
        "placement_replaced",
        "Your placement has been updated: {to_job}",
        "Dear {student},\n\nThe placement team has updated your placement "
        "record.\n"
        "Previous placement: {from_job} at {from_company}\n"
        "Current placement: {to_job} at {to_company}\n"
        "Reason: {reason}\n\n"
        "You now hold this one placement. Please check the CDS Portal and "
        "contact the office if anything looks wrong.\n\n"
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
