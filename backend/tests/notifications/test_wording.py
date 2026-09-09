"""Student-facing wording: the rendered format is pinned, not incidental.

The mock D.33 review found a 09:30 IST venue slot reaching the student as
``2027-07-01T04:00:00+00:00``. Twenty-two envelopes a run carry a time, and a
missed round becomes a strike that can convert to a penalty, so the format is
part of the contract rather than a presentation detail.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.modules.notifications.wording import (
    NO_DEADLINE,
    NOT_APPLICABLE,
    UNSCHEDULED,
    expiry_outcome,
    format_deadline,
    format_time,
    humanise,
    or_absent,
    schedule_note,
    withdrawal_trigger,
)


def test_NTF_a_stored_utc_instant_is_read_back_as_the_students_own_clock() -> None:
    """The exact defect: 09:30 IST uploaded, 04:00 UTC stored, 09:30 IST sent."""
    stored = datetime(2027, 7, 1, 4, 0, tzinfo=UTC)

    assert format_time(stored) == "01 Jul 2027, 09:30 IST"


def test_NTF_the_zone_is_named_in_every_rendered_time() -> None:
    assert format_time(datetime(2027, 7, 1, 4, 0, tzinfo=UTC)).endswith(" IST")
    assert format_deadline(datetime(2027, 7, 1, 4, 0, tzinfo=UTC)).endswith(" IST")


def test_NTF_an_instant_in_another_zone_is_converted_not_relabelled() -> None:
    """Anything that is not UTC still has to arrive as the student's clock."""
    elsewhere = datetime(2027, 6, 30, 23, 0, tzinfo=timezone(timedelta(hours=-5)))

    assert format_time(elsewhere) == "01 Jul 2027, 09:30 IST"


def test_NTF_a_naive_instant_is_read_as_utc() -> None:
    """Timestamps are timestamptz UTC; a naive one must not become local time."""
    assert format_time(datetime(2027, 7, 1, 4, 0)) == "01 Jul 2027, 09:30 IST"


@pytest.mark.parametrize(
    ("rendered", "expected"),
    [
        (format_time(None), UNSCHEDULED),
        (format_deadline(None), NO_DEADLINE),
        (or_absent(None), UNSCHEDULED),
        (or_absent(""), UNSCHEDULED),
        (or_absent("LT-1"), "LT-1"),
        (or_absent(None, NOT_APPLICABLE), NOT_APPLICABLE),
    ],
)
def test_NTF_an_absent_value_is_named_rather_than_left_blank(
    rendered: str, expected: str
) -> None:
    """``advanced`` promised a venue and a time with two empty lines."""
    assert rendered == expected


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("off_campus", "Off campus"),
        ("student_renege", "Student renege"),
        ("auto_decline", "Auto decline"),
        ("ppo", "PPO"),
        ("internship", "Internship"),
    ],
)
def test_NTF_a_wire_enum_never_reaches_a_student_as_a_token(
    token: str, expected: str
) -> None:
    assert humanise(token) == expected


def test_NTF_a_boolean_never_reaches_a_student_as_a_python_literal() -> None:
    """Fifteen envelopes said "Updated schedule: False"."""
    assert schedule_note(True) == "This replaces the schedule sent to you earlier."
    assert schedule_note(False) == "This is the first schedule published for this round."
    assert "False" not in schedule_note(False)


def test_NTF_a_withdrawal_trigger_reads_as_a_clause() -> None:
    assert withdrawal_trigger("accepted_another_offer") == "you accepted another offer"
    assert withdrawal_trigger("archival") == "the cycle was closed"
    # An unmapped trigger still degrades to words, never to a raw token.
    assert withdrawal_trigger("some_new_trigger") == "some new trigger"


def test_NTF_an_expiry_outcome_says_what_happened_not_what_was_configured() -> None:
    assert expiry_outcome("auto_decline") == "declined automatically"
    assert expiry_outcome("auto_accept") == "accepted automatically"
