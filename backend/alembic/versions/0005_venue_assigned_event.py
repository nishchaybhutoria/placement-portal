"""Give a published venue a place on the application's timeline.

RND-4 notifies every student whose slot is published, but ``event_type_t`` had
no value for it, so assigning a venue to two hundred students left nothing on
any application's timeline -- and "I was never told where to go" would have to
be answered from ``notification_log`` plus a batch audit row rather than from
the timeline the schema exists to answer it with.  ``attendance_marked`` is the
precedent: non-status pipeline facts get events (the design review section 4.23).

The value is added after ``attendance_marked`` so the type's order matches
``EventType``'s.

Revision ID: 0005_venue_assigned_event
Revises: 0004_program_dual_major
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_venue_assigned_event"
down_revision: str | None = "0004_program_dual_major"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VALUES_WITHOUT = (
    "created",
    "advanced",
    "eliminated",
    "waitlisted",
    "attendance_marked",
    "round_finalized",
    "offer_extended",
    "accepted",
    "declined",
    "auto_declined",
    "withdrawn",
    "auto_withdrawn",
    "offer_terminated",
    "reinstated",
    "edited",
    "forced_transition",
    "overridden",
    "external_recorded",
    "external_updated",
)


def upgrade() -> None:
    op.execute(
        "ALTER TYPE event_type_t ADD VALUE 'venue_assigned' AFTER 'attendance_marked'"
    )


def downgrade() -> None:
    # Postgres cannot drop an enum value, so the type is rebuilt without it.
    # This fails, deliberately, if any event was recorded as venue_assigned:
    # an event row is append-only history and a downgrade must not erase it.
    values = ", ".join(f"'{value}'" for value in _VALUES_WITHOUT)
    op.execute(f"CREATE TYPE event_type_t__old AS ENUM ({values})")
    op.execute(
        "ALTER TABLE application_events ALTER COLUMN event_type "
        "TYPE event_type_t__old USING event_type::text::event_type_t__old"
    )
    op.execute("DROP TYPE event_type_t")
    op.execute("ALTER TYPE event_type_t__old RENAME TO event_type_t")
