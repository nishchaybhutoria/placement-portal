"""The bound on caller-supplied replay keys (LLD section 5, RND-2).

``run_bulk`` stores ``f"{batch_key}:{chunk_number}"`` in ``idempotency_keys.key``
and a single command stores its ``idempotency_key`` there unchanged.  That
column carries a UNIQUE constraint, so every key becomes a btree entry, and
PostgreSQL refuses an entry larger than 2704 bytes.

A client is therefore able to choose a key the database cannot store.  The
approvals queue did exactly that by building its key out of every selected
identifier.  The limit applies to the *compressed* entry, so the same screen
broke on the shape of what was selected rather than on how much: ticked
membership UUIDs do not compress and failed above seventy-one, while pasted
roll numbers and institute emails compress by about two thirds and ran past
five thousand characters without complaint.  The overflow surfaced as an
unreasoned 500 whose only advice was to replay a key that could never be
stored.  Bounding the key here turns that into an ordinary, field-scoped
validation failure long before any row is touched, and
``ck_idempotency_keys_key_length`` (revision 0020) is the database backstop that
keeps the two limits from drifting apart.

The bound is deliberately far below the btree maximum.  A replay key identifies
an intent; it is not a place to carry the intent's contents, and a caller that
wants selection-specific identity digests the selection (see
``frontend/src/lib/idempotency.ts``).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints

#: Longest replay key the API accepts, for both `batch_key` and `idempotency_key`.
MAX_IDEMPOTENCY_KEY_LENGTH = 200

#: Longest key the column itself may hold.  ``run_bulk`` stores a batch key
#: with ``:<chunk_number>`` appended, so the stored value is a little longer
#: than what the caller sent; the headroom is what that suffix needs, and it
#: stays far below the 2704-byte btree maximum either way.
MAX_STORED_KEY_LENGTH = 256

#: The batch key every bulk command input must use in place of a bare ``str``.
BatchKey = Annotated[
    str,
    StringConstraints(
        min_length=1, max_length=MAX_IDEMPOTENCY_KEY_LENGTH, strip_whitespace=True
    ),
]

#: The single-command replay key accepted by the generated command envelope.
IdempotencyKey = Annotated[
    str,
    StringConstraints(
        min_length=1, max_length=MAX_IDEMPOTENCY_KEY_LENGTH, strip_whitespace=True
    ),
]
