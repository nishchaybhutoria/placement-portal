"""Correct three template lines that no supplied value can rescue.

Revision ID: 0013_notification_copy
Revises: 0012_application_event_order

The mock D.33 review read all 206 envelopes of a full-year run. Most of what it
found is fixed at the emitter, by supplying a rendered value instead of a raw
one. Three lines cannot be: the template itself asks the wrong question.

* ``venue_timing`` printed ``Updated schedule: {is_update}``, which reached
  fifteen students as ``Updated schedule: False`` -- a label whose only honest
  answers are a Python literal or noise on a first schedule. The variable now
  carries the whole clause, so the line is a sentence.
* ``auto_withdrawn`` printed ``Trigger: {trigger}``. "Trigger" is our word for
  it, not the student's.
* ``offer_expired`` printed ``The configured action was: {behavior}.``, which
  reads as a confession of implementation. It is a labelled fact.

Only rows still holding the shipped default are rewritten: a cycle override or
an operator's edit through ``admin/templates`` is their decision, not ours.
"""

# Template copy is kept as one literal per row so migration review shows the
# exact email in one place rather than a chain of source-code fragments.
# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_notification_copy"
down_revision: str | None = "0012_application_event_order"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (event_key, the body as 0007/0008 shipped it, the body it becomes)
_REWRITES: tuple[tuple[str, str, str], ...] = (
    (
        "venue_timing",
        "Dear {student},\n\nSchedule details for {round} in the {job} process:\nVenue: {venue}\nTime: {time}\nUpdated schedule: {is_update}\n\nRegards,\nCareer Development Services",
        "Dear {student},\n\n{is_update}\n\nSchedule details for {round} in the {job} process:\nVenue: {venue}\nTime: {time}\n\nRegards,\nCareer Development Services",
    ),
    (
        "auto_withdrawn",
        "Dear {student},\n\nYour application for {job} was withdrawn automatically.\nTrigger: {trigger}\n\nRegards,\nCareer Development Services",
        "Dear {student},\n\nYour application for {job} was withdrawn automatically because {trigger}.\n\nRegards,\nCareer Development Services",
    ),
    (
        "offer_expired",
        "Dear {student},\n\nThe response deadline for your {job} offer at {company} has passed.\nThe configured action was: {behavior}.\n\nRegards,\nCareer Development Services",
        "Dear {student},\n\nThe response deadline for your {job} offer at {company} has passed.\nWhat happened to the offer: {behavior}\n\nRegards,\nCareer Development Services",
    ),
)

_UPDATE = sa.text(
    "UPDATE notification_templates SET body = :new_body "
    "WHERE event_key = :event_key AND body = :old_body"
)


def upgrade() -> None:
    bind = op.get_bind()
    for event_key, old_body, new_body in _REWRITES:
        bind.execute(
            _UPDATE,
            {"event_key": event_key, "old_body": old_body, "new_body": new_body},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for event_key, old_body, new_body in _REWRITES:
        bind.execute(
            _UPDATE,
            {"event_key": event_key, "old_body": new_body, "new_body": old_body},
        )
