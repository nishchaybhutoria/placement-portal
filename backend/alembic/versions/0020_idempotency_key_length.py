"""Keep a replay key inside what its own unique index can hold.

Revision ID: 0020_idempotency_key_length
Revises: 0019_ctc_in_rupees

``idempotency_keys.key`` is ``text`` with a UNIQUE constraint, so every key is
a btree entry and PostgreSQL refuses one over 2704 bytes. Nothing stopped a
caller from choosing a longer key: the approvals queue built its batch key out
of every ticked membership id, which overflowed at seventy-two selections and
surfaced as an unreasoned 500 advising a replay that could never be stored.

``app/core/keys.py`` now bounds both ``batch_key`` and ``idempotency_key`` at
``MAX_IDEMPOTENCY_KEY_LENGTH``, and this constraint is the database backstop
for that decision, so the two limits cannot drift apart and no future writer
can reintroduce an unstorable key by going round the input models.

**The constraint is added NOT VALID, and that is the whole point of it.** Every
approval batch of six or more selections produced a key longer than this bound
-- forty-six bytes plus thirty-seven each -- and those rows committed. A
rehearsal against the production database found twenty-seven of forty-nine
already over it, the longest 5655 characters.

Which is also the answer to why select-all failed while much longer pasted
batches did not. An index entry may be compressed, just not stored out of line,
so what the btree measures is the *compressed* size. Ticked rows are membership
UUIDs, which pglz cannot compress at all: seventy-one fit at 2673 bytes and
seventy-two are refused at 2710. Pasted rows are roll numbers and institute
emails sharing a domain and a batch prefix, which compress by about two thirds
-- the 5655-character key is stored in 2125 bytes and fits comfortably. The
same screen therefore succeeded or failed on the shape of the identifiers, not
their number, which is exactly what made it look intermittent.

A validating ``ADD CONSTRAINT`` scans those rows and aborts the upgrade, which
is a migration that only ever succeeds on an empty database.

``NOT VALID`` checks every insert and update from here on and leaves the
historical rows alone, which is exactly the guarantee wanted: those keys are
inert replay records of batches that already ran, and nothing will ever write
one again. Do not "tidy up" later with ``VALIDATE CONSTRAINT`` -- it would fail
for the same reason, and the rows it objects to are evidence, not a defect.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020_idempotency_key_length"
down_revision: str | None = "0019_ctc_in_rupees"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_idempotency_keys_key_length"
# `app/core/keys.py` bounds a caller's key at 200; `run_bulk` then appends
# `:<chunk_number>` before storing it, and this is that bound plus headroom.
MAX_LENGTH = 256


def upgrade() -> None:
    op.execute(
        sa.text(
            f"ALTER TABLE idempotency_keys ADD CONSTRAINT {CONSTRAINT} "
            f"CHECK (char_length(key) <= {MAX_LENGTH}) NOT VALID"
        )
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, "idempotency_keys", type_="check")
