"""Record compensation as rupees, and leave lakhs to the people reading it.

Revision ID: 0019_ctc_in_rupees
Revises: 0018_rule_semantics

``ctc_lpa`` asked whoever filled the form to do the arithmetic, and stored the
result at two decimal places of a *lakh* -- so ₹18,53,500 became 18.54 LPA and
the figure the office typed was not the figure the portal kept. The column now
holds the annual figure in rupees, exactly as entered, named for the period it
covers like ``stipend_month`` beside it. Lakhs remain how it is displayed.

Existing values are multiplied by 100000, which is exact: every stored value
was already a two-decimal lakh figure.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019_ctc_in_rupees"
down_revision: str | None = "0018_rule_semantics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Every table that records a cost to company, and whether it may be unknown.
TABLES: tuple[tuple[str, bool], ...] = (
    ("jobs", True),
    ("job_program_ctc", False),
    ("external_offers", True),
)
RUPEES_PER_LAKH = 100000


def upgrade() -> None:
    for table, nullable in TABLES:
        op.alter_column(
            table,
            "ctc_lpa",
            new_column_name="ctc_annual",
            type_=sa.Numeric(12, 2),
            existing_type=sa.Numeric(10, 2),
            existing_nullable=nullable,
        )
        op.execute(
            sa.text(
                f"UPDATE {table} SET ctc_annual = ctc_annual * {RUPEES_PER_LAKH}"
            )
        )


def downgrade() -> None:
    # A value entered to the rupee cannot survive the round trip: two decimals
    # of a lakh is ₹1,000 granularity, which is the precision this revision
    # exists to stop losing. Rounding here is deliberate and one-directional.
    for table, nullable in TABLES:
        op.execute(
            sa.text(
                f"UPDATE {table} SET ctc_annual = "
                f"round(ctc_annual / {RUPEES_PER_LAKH}, 2)"
            )
        )
        op.alter_column(
            table,
            "ctc_annual",
            new_column_name="ctc_lpa",
            type_=sa.Numeric(10, 2),
            existing_type=sa.Numeric(12, 2),
            existing_nullable=nullable,
        )
