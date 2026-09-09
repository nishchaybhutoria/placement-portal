"""Add notification templates omitted from the LLD section 13 catalog.

Revision ID: 0008_notification_catalog
Revises: 0007_notification_templates
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_notification_catalog"
down_revision: str | None = "0007_notification_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# the design review section 4 records why these mandated JOB-3/OFR-3 events amend the
# catalog in LLD section 13 rather than being silently dropped at delivery.
_DEFAULTS: tuple[tuple[str, str, str], ...] = (
    (
        "deadline_changed",
        "Deadline updated: {job}",
        "Dear {student},\n\nA deadline for {job} has been updated.\n"
        "Application deadline: {application_deadline}\n"
        "Offer response deadline: {offer_acceptance_deadline}\n\n"
        "Please review the latest details in the CDS Portal.\n\n"
        "Regards,\nCareer Development Services",
    ),
    (
        "declined_confirm",
        "Offer declined: {job} at {company}",
        "Dear {student},\n\nYour decision to decline the {job} offer from {company} "
        "has been recorded.\n\nRegards,\nCareer Development Services",
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
