"""Give shipped job-change notices an identifiable company and useful detail.

Only global templates still equal to their shipped defaults are updated.  Cycle
customizations and operator edits are intentionally left for review.

Revision ID: 0022_notification_identity
Revises: 0021_placement_replaced_notice
"""

# Template copy is reviewed literally against shipped rows.
# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0022_notification_identity"
down_revision: str | None = "0021_placement_replaced_notice"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REWRITES = (
    (
        "process_changed",
        "Recruitment process updated: {job}",
        "Dear {student},\n\nThe recruitment process for {job} has changed. Please review the latest details in the CDS Portal.\n\nRegards,\nCareer Development Services",
        "Recruitment process updated: {job} at {company}",
        "Dear {student},\n\nThe recruitment process for {job} at {company} has changed: {change_summary}. Please review the latest details in the CDS Portal.\n\nRegards,\nCareer Development Services",
    ),
    (
        "deadline_changed",
        "Deadline updated: {job}",
        "Dear {student},\n\nA deadline for {job} has been updated.\nApplication deadline: {application_deadline}\nOffer response deadline: {offer_acceptance_deadline}\n\nPlease review the latest details in the CDS Portal.\n\nRegards,\nCareer Development Services",
        "Deadline updated: {job} at {company}",
        "Dear {student},\n\nA deadline for {job} at {company} has been updated.\nApplication deadline: {application_deadline}\nOffer response deadline: {offer_acceptance_deadline}\n\nPlease review the latest details in the CDS Portal.\n\nRegards,\nCareer Development Services",
    ),
    (
        "job_cancelled",
        "Job cancelled: {job}",
        "Dear {student},\n\nThe {job} opportunity has been cancelled.\nReason: {reason}\n\nRegards,\nCareer Development Services",
        "Job cancelled: {job} at {company}",
        "Dear {student},\n\nThe {job} opportunity at {company} has been cancelled.\nReason: {reason}\n\nRegards,\nCareer Development Services",
    ),
    (
        "external_updated",
        "External offer updated",
        "Dear {student},\n\nYour external offer record for {company} has been updated.\n\nRegards,\nCareer Development Services",
        "External offer updated: {company}",
        "Dear {student},\n\nYour external offer record for {company} has been updated. Current status: {status}.\n\nRegards,\nCareer Development Services",
    ),
)

_DEFAULTS: tuple[tuple[str, str, str], ...] = (
    (
        "eligibility_removed",
        "Application update: {job} at {company}",
        "Dear {student},\n\nYour application for {job} at {company} has been "
        "removed from the active process because your current profile no longer "
        "meets the role eligibility criteria. Your submission remains in your "
        "portal history. Please contact Career Development Services if you think "
        "this is incorrect.\n\nRegards,\nCareer Development Services",
    ),
)

_UPDATE = sa.text(
    "UPDATE notification_templates SET subject = :new_subject, body = :new_body "
    "WHERE cycle_id IS NULL AND event_key = :event_key "
    "AND subject = :old_subject AND body = :old_body"
)


def _apply(reverse: bool) -> None:
    connection = op.get_bind()
    for key, old_subject, old_body, new_subject, new_body in _REWRITES:
        if reverse:
            old_subject, new_subject = new_subject, old_subject
            old_body, new_body = new_body, old_body
        connection.execute(
            _UPDATE,
            {
                "event_key": key,
                "old_subject": old_subject,
                "old_body": old_body,
                "new_subject": new_subject,
                "new_body": new_body,
            },
        )


def upgrade() -> None:
    _apply(False)
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
                "event_key": key, "cycle_id": None,
                "subject": subject, "body": body, "enabled": True,
            }
            for key, subject, body in _DEFAULTS
        ],
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM notification_templates WHERE event_key = 'eligibility_removed' "
        "AND cycle_id IS NULL"
    )
    _apply(True)
