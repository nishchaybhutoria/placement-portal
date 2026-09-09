"""Seed the complete LLD section 13 notification template catalog.

Revision ID: 0007_notification_templates
Revises: 0006_round_finalized
"""

# Template copy is kept as one literal per row so migration review shows the
# exact email in one place rather than a chain of source-code fragments.
# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_notification_templates"
down_revision: str | None = "0006_round_finalized"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Deliberately local to the migration.  The gate test combines these 28 rows
# with catalog amendments from later migrations, then compares that exact set
# with the application catalog and every production emitter.
_DEFAULTS: tuple[tuple[str, str, str], ...] = (
    (
        "application_submitted",
        "Application submitted: {job} at {company}",
        "Dear {student},\n\nYour application for {job} at {company} has been submitted successfully.\n\nRegards,\nCareer Development Services",
    ),
    (
        "advanced",
        "You have advanced to {next_round}",
        "Dear {student},\n\nYou have advanced to {next_round} for {job}.\nVenue: {venue}\nTime: {time}\n\nRegards,\nCareer Development Services",
    ),
    (
        "rejected",
        "Application update: {job}",
        "Dear {student},\n\nYour application for {job} will not progress further.\nRound: {round}\nReason: {reason}\n\nRegards,\nCareer Development Services",
    ),
    (
        "absent_marked",
        "Absence recorded for {round}",
        "Dear {student},\n\nYou were marked absent for {round} in the {job} process.\nCurrent strike total: {strike_total}\n\nRegards,\nCareer Development Services",
    ),
    (
        "offer_extended",
        "Offer extended: {job} at {company}",
        "Dear {student},\n\nCongratulations! {company} has extended you an offer for {job}.\n\nPlease review and respond through the CDS Portal.\nResponse deadline: {deadline}\n\nRegards,\nCareer Development Services",
    ),
    (
        "offer_accepted",
        "Offer accepted: {job} at {company}",
        "Dear {student},\n\nYour acceptance of the {job} offer from {company} has been recorded.\n\nRegards,\nCareer Development Services",
    ),
    (
        "auto_declined",
        "Offer declined after another acceptance",
        "Dear {student},\n\nYour offer for {job} at {company} was declined automatically after you accepted {accepted_job}.\n\nRegards,\nCareer Development Services",
    ),
    (
        "auto_withdrawn",
        "Application withdrawn automatically: {job}",
        "Dear {student},\n\nYour application for {job} was withdrawn automatically.\nTrigger: {trigger}\n\nRegards,\nCareer Development Services",
    ),
    (
        "offer_terminated",
        "Offer terminated: {job} at {company}",
        "Dear {student},\n\nYour offer for {job} at {company} has been terminated.\nKind: {kind}\nReason: {reason}\n\nRegards,\nCareer Development Services",
    ),
    (
        "offer_expired",
        "Offer response deadline passed: {job}",
        "Dear {student},\n\nThe response deadline for your {job} offer at {company} has passed.\nThe configured action was: {behavior}.\n\nRegards,\nCareer Development Services",
    ),
    (
        "external_recorded",
        "External offer recorded",
        "Dear {student},\n\nAn external {outcome} offer from {company} has been recorded.\nSource: {source}\n\nRegards,\nCareer Development Services",
    ),
    (
        "external_updated",
        "External offer updated",
        "Dear {student},\n\nYour external offer record for {company} has been updated.\n\nRegards,\nCareer Development Services",
    ),
    (
        "strike_added",
        "Strike added to your CDS record",
        "Dear {student},\n\nA strike was added to your CDS record.\nReason: {reason}\nCurrent total: {total}\n\nRegards,\nCareer Development Services",
    ),
    (
        "strike_revoked",
        "Strike revoked from your CDS record",
        "Dear {student},\n\nA strike was revoked from your CDS record.\nCurrent total: {total}\n\nRegards,\nCareer Development Services",
    ),
    (
        "penalty_added",
        "Penalty added to your CDS record",
        "Dear {student},\n\nA penalty was added to your CDS record.\nReasons: {reasons}\n\nRegards,\nCareer Development Services",
    ),
    (
        "penalty_revoked",
        "Penalty revoked from your CDS record",
        "Dear {student},\n\nA penalty was revoked from your CDS record.\n\nRegards,\nCareer Development Services",
    ),
    (
        "venue_timing",
        "Schedule published for {round}",
        "Dear {student},\n\nSchedule details for {round} in the {job} process:\nVenue: {venue}\nTime: {time}\nUpdated schedule: {is_update}\n\nRegards,\nCareer Development Services",
    ),
    (
        "process_changed",
        "Recruitment process updated: {job}",
        "Dear {student},\n\nThe recruitment process for {job} has changed. Please review the latest details in the CDS Portal.\n\nRegards,\nCareer Development Services",
    ),
    (
        "job_cancelled",
        "Job cancelled: {job}",
        "Dear {student},\n\nThe {job} opportunity has been cancelled.\nReason: {reason}\n\nRegards,\nCareer Development Services",
    ),
    (
        "membership_pending",
        "Cycle registration pending: {cycle}",
        "Dear {student},\n\nYour registration for {cycle} is awaiting approval.\n\nRegards,\nCareer Development Services",
    ),
    (
        "membership_approved",
        "Cycle registration approved: {cycle}",
        "Dear {student},\n\nYour registration for {cycle} has been approved.\n\nRegards,\nCareer Development Services",
    ),
    (
        "membership_rejected",
        "Cycle registration not approved: {cycle}",
        "Dear {student},\n\nYour registration for {cycle} was not approved.\nReason: {reason}\n\nRegards,\nCareer Development Services",
    ),
    (
        "membership_removed",
        "Removed from cycle: {cycle}",
        "Dear {student},\n\nYour membership in {cycle} has been removed.\nReason: {reason}\n\nRegards,\nCareer Development Services",
    ),
    (
        "membership_restored",
        "Cycle membership restored: {cycle}",
        "Dear {student},\n\nYour membership in {cycle} has been restored.\n\nRegards,\nCareer Development Services",
    ),
    (
        "coordinator_assigned",
        "Coordinator assignment: {cycle}",
        "You have been assigned as a coordinator for {cycle}.\n\nRegards,\nCareer Development Services",
    ),
    (
        "coordinator_removed",
        "Coordinator assignment removed: {cycle}",
        "Your coordinator assignment for {cycle} has been removed.\n\nRegards,\nCareer Development Services",
    ),
    (
        "deadline_reminder",
        "Application deadline reminder: {job}",
        "Dear {student},\n\nThe application deadline for {job} at {company} is about {hours_left} hours away. You are currently eligible and have not applied.\n\nRegards,\nCareer Development Services",
    ),
    (
        "round_reminder",
        "Upcoming round: {round}",
        "Dear {student},\n\nReminder: your {round} for {job} is coming up.\nVenue: {venue}\nTime: {time}\n\nRegards,\nCareer Development Services",
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
