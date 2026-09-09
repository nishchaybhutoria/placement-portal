"""The venue/timing upload format (RND-4, the design review section 4.5), pure and DB-free."""

from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest
from openpyxl import Workbook

from app.core.errors import DUPLICATE_ROW, INVALID_FIELD_VALUE
from app.core.plan import Reason
from app.core.uploads import UploadParseError
from app.modules.applications.slots import parse_slot_time, parse_slot_upload

CSV = (
    b"identifier,venue,time\n"
    b"21110001,AB 5 / 201,2026-03-14 09:30\n"
    b"two@example.edu,AB 5 / 204,14-03-2026 11:00\n"
)


def _workbook(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-03-14 09:30", datetime(2026, 3, 14, 4, 0, tzinfo=UTC)),
        ("14-03-2026 09:30", datetime(2026, 3, 14, 4, 0, tzinfo=UTC)),
        ("  2026-03-14   09:30 ", datetime(2026, 3, 14, 4, 0, tzinfo=UTC)),
        ("2026-01-02 00:00", datetime(2026, 1, 1, 18, 30, tzinfo=UTC)),
    ],
)
def test_RND4_an_accepted_time_is_read_as_IST_and_stored_UTC(
    text: str, expected: datetime
) -> None:
    assert parse_slot_time(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "2026-03-14 09:30:00",
        "14/03/2026 09:30",
        "March 14 2026 09:30",
        "2026-03-14",
        "09:30",
        "26-03-14 09:30",
        "",
    ],
)
def test_RND4_anything_else_is_a_row_error_rather_than_a_guess(text: str) -> None:
    """A guessed slot sends a student to an interview on the wrong day."""
    parsed = parse_slot_time(text)
    assert isinstance(parsed, Reason)
    assert parsed.code == INVALID_FIELD_VALUE
    assert parsed.path == "time"


def test_RND4_the_two_formats_do_not_collide() -> None:
    """01-02-2026 is the first of February, never the second of January."""
    assert parse_slot_time("01-02-2026 09:00") == datetime(
        2026, 2, 1, 3, 30, tzinfo=UTC
    )
    assert parse_slot_time("2026-01-02 09:00") == datetime(
        2026, 1, 2, 3, 30, tzinfo=UTC
    )


def test_RND4_a_csv_carries_identifier_venue_and_time() -> None:
    parsed = parse_slot_upload(CSV, "slots.csv")
    assert parsed.errors == ()
    assert [(row.identifier, row.venue, row.time) for row in parsed.rows] == [
        ("21110001", "AB 5 / 201", "2026-03-14 09:30"),
        ("two@example.edu", "AB 5 / 204", "14-03-2026 11:00"),
    ]


def test_RND4_a_spreadsheet_datetime_keeps_its_time_of_day() -> None:
    """The profile loader renders a datetime as a bare date; 09:30 must survive."""
    payload = _workbook(
        [
            ["identifier", "venue", "time"],
            ["21110001", "AB 5 / 201", datetime(2026, 3, 14, 9, 30)],
        ]
    )
    parsed = parse_slot_upload(payload, "slots.xlsx")
    assert parsed.errors == ()
    assert parsed.rows[0].time == "2026-03-14 09:30"
    assert parse_slot_time(parsed.rows[0].time) == datetime(
        2026, 3, 14, 4, 0, tzinfo=UTC
    )


def test_RND4_a_row_may_name_only_a_venue_or_only_a_time() -> None:
    parsed = parse_slot_upload(
        b"identifier,venue,time\n21110001,AB 5 / 201,\n21110002,,2026-03-14 09:30\n",
        "slots.csv",
    )
    assert parsed.errors == ()
    assert [(row.venue, row.time) for row in parsed.rows] == [
        ("AB 5 / 201", ""),
        ("", "2026-03-14 09:30"),
    ]


def test_RND4_a_row_naming_neither_asks_for_nothing() -> None:
    parsed = parse_slot_upload(b"identifier,venue,time\n21110001,,\n", "slots.csv")
    assert parsed.rows == ()
    assert [(error.row_number, error.code) for error in parsed.errors] == [
        (2, INVALID_FIELD_VALUE)
    ]


def test_RND4_a_bad_time_is_reported_by_row_and_the_rest_still_parse() -> None:
    parsed = parse_slot_upload(
        b"identifier,venue,time\n"
        b"21110001,AB 5 / 201,14/03/2026 09:30\n"
        b"21110002,AB 5 / 204,2026-03-14 09:30\n",
        "slots.csv",
    )
    assert [row.identifier for row in parsed.rows] == ["21110002"]
    assert [(error.row_number, error.path) for error in parsed.errors] == [(2, "time")]


def test_RND4_one_student_named_twice_takes_neither_slot() -> None:
    parsed = parse_slot_upload(
        b"identifier,venue,time\n"
        b"21110001,AB 5 / 201,2026-03-14 09:30\n"
        b"21110001,AB 5 / 204,2026-03-14 11:00\n",
        "slots.csv",
    )
    assert [row.venue for row in parsed.rows] == ["AB 5 / 201"]
    assert [(error.row_number, error.code) for error in parsed.errors] == [
        (3, DUPLICATE_ROW)
    ]


def test_RND4_a_missing_identifier_is_a_row_error() -> None:
    parsed = parse_slot_upload(
        b"identifier,venue,time\n,AB 5 / 201,2026-03-14 09:30\n", "slots.csv"
    )
    assert parsed.rows == ()
    assert [(error.row_number, error.path) for error in parsed.errors] == [
        (2, "identifier")
    ]


@pytest.mark.parametrize(
    ("payload", "filename"),
    [
        (b"venue,time\nAB 5 / 201,2026-03-14 09:30\n", "slots.csv"),
        (b"identifier\n21110001\n", "slots.csv"),
        (b"identifier,venue,time\n", "slots.txt"),
        (b"", "slots.csv"),
    ],
)
def test_RND4_a_file_that_can_do_nothing_is_refused_whole(
    payload: bytes, filename: str
) -> None:
    with pytest.raises(UploadParseError):
        parse_slot_upload(payload, filename)


def test_RND4_headers_are_read_case_and_spacing_insensitively() -> None:
    parsed = parse_slot_upload(
        b"Roll Number,Venue,Scheduled At\n21110001,AB 5 / 201,2026-03-14 09:30\n",
        "slots.csv",
    )
    assert parsed.errors == ()
    assert parsed.rows[0].identifier == "21110001"
