"""Record application event append order (the design review section 4.41).

Revision ID: 0012_application_event_order
Revises: 0011_dual_degree_profiles

Existing mock data is disposable, but deleting it is an operator action, not
migration behavior. Never assign physical-scan order to historical events.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_application_event_order"
down_revision: str | None = "0011_dual_degree_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Hold the same lock through the check and ALTER, so an old writer cannot
    # insert unsequenced history between the two statements.
    op.execute("LOCK TABLE application_events IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM application_events) THEN
                RAISE EXCEPTION '0012_application_event_order requires empty application_events; '
                    'explicitly reset the disposable database, migrate, then reseed. '
                    'No historical event ordering will be invented.';
            END IF;
        END $$
    """)
    op.add_column(
        "application_events",
        sa.Column(
            "event_seq",
            sa.BigInteger(),
            sa.Identity(always=True, cache=1, cycle=False),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_application_events_event_seq", "application_events", ["event_seq"]
    )


def downgrade() -> None:
    # The only ordering evidence must not be erased from populated history.
    op.execute("LOCK TABLE application_events IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM application_events) THEN
                RAISE EXCEPTION 'Cannot discard application event ordering from populated history; '
                    'explicitly reset the disposable database before downgrading.';
            END IF;
        END $$
    """)
    op.drop_constraint("uq_application_events_event_seq", "application_events", type_="unique")
    op.drop_column("application_events", "event_seq")
