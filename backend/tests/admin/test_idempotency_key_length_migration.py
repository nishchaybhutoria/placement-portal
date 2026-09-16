"""Revision 0020 against a database that has actually been used.

Every approval batch of six or more selections wrote a key longer than this
bound -- forty-six bytes plus thirty-seven each -- and every one of them
committed: a btree measures the *compressed* entry, and a key built from pasted
roll numbers and institute emails compresses by about two thirds even when it
runs to five and a half thousand characters. A rehearsal against the production
database found twenty-seven such rows out of forty-nine.

So the rows the constraint objects to are in every database that has ever run
an approval queue, and a validating ``ADD CONSTRAINT`` would abort the upgrade
on all of them while passing cleanly on the empty one a test usually builds.

CONTRIBUTING asks for both an empty upgrade and the populated-state behaviour;
this is the populated half, and it is the half that matters here.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from tests.admin.conftest import write_engine

pytestmark = pytest.mark.asyncio

CONSTRAINT = "ck_idempotency_keys_key_length"
#: What the old approvals screen sent for a batch of ten ticked memberships.
LEGACY_KEY = f"approvals-{'a' * 36}-" + ",".join("b" * 36 for _ in range(10))


async def test_S20_a_key_from_before_the_bound_survives_and_still_replays() -> None:
    """The constraint is NOT VALID: history is left alone, not rewritten."""
    assert len(LEGACY_KEY) > 256, "the fixture must reproduce the oversized shape"
    engine = write_engine()
    try:
        # Planted the way history planted it: while no such constraint existed.
        # Inserting it afterwards would be refused, which is the other half of
        # what this revision promises and the test below.
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(f"ALTER TABLE idempotency_keys DROP CONSTRAINT {CONSTRAINT}")
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO idempotency_keys (key, command, result) "
                    "VALUES (:key, 'approve_memberships', CAST('{}' AS jsonb))"
                ),
                {"key": LEGACY_KEY},
            )
            await connection.execute(
                sa.text(
                    f"ALTER TABLE idempotency_keys ADD CONSTRAINT {CONSTRAINT} "
                    "CHECK (char_length(key) <= 256) NOT VALID"
                )
            )
        async with engine.connect() as connection:
            stored = await connection.scalar(
                sa.text("SELECT key FROM idempotency_keys WHERE key = :key"),
                {"key": LEGACY_KEY},
            )
            # Declared, and deliberately unvalidated: `convalidated` false is
            # the record of the decision, not an oversight to be tidied away.
            validated = await connection.scalar(
                sa.text(
                    "SELECT convalidated FROM pg_constraint "
                    "WHERE conrelid = 'idempotency_keys'::regclass AND conname = :name"
                ),
                {"name": CONSTRAINT},
            )
        async with engine.begin() as connection:
            await connection.execute(
                sa.text("DELETE FROM idempotency_keys WHERE key = :key"), {"key": LEGACY_KEY}
            )
    finally:
        await engine.dispose()

    assert stored == LEGACY_KEY
    assert validated is False


async def test_S20_a_new_key_over_the_bound_is_refused_by_the_database() -> None:
    """NOT VALID skips the back-scan; it does not stop checking new rows."""
    engine = write_engine()
    try:
        with pytest.raises(DBAPIError) as error:
            async with engine.begin() as connection:
                await connection.execute(
                    sa.text(
                        "INSERT INTO idempotency_keys (key, command, result) "
                        "VALUES (:key, 'approve_memberships', CAST('{}' AS jsonb))"
                    ),
                    {"key": "k" * 257},
                )
    finally:
        await engine.dispose()

    assert CONSTRAINT in str(error.value)
