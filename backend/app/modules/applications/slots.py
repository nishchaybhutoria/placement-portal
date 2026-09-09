"""Reading a venue and a time for one applicant (Behavior RND-4).

The format is the design review section 4.5: columns ``identifier`` (a roll number or
an institute email), ``venue``, and ``time``, where a time reads either
``YYYY-MM-DD HH:MM`` or ``DD-MM-YYYY HH:MM``, is interpreted as IST, and is
stored UTC.  Anything else is a per-row error.

Everything here is pure.  The same ``parse_slot_time`` runs in the upload route
and inside ``assign_venue_timing``'s decide, because rows reach the command two
ways -- from a spreadsheet and typed by hand on the board -- and a validation
that lives only in the upload route is one a hand-typed row walks straight past.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone

from app.core.errors import DUPLICATE_ROW, INVALID_FIELD_VALUE
from app.core.plan import Reason
from app.core.uploads import UploadParseError, read_table

#: Asia/Kolkata.  Fixed rather than zoneinfo: India has no DST, and a fixed
#: offset cannot depend on which tzdata the container happens to ship.
IST = timezone(timedelta(hours=5, minutes=30))

#: The two accepted spellings (the design review section 4.5).  Unambiguous as a pair:
#: a DD-MM-YYYY string cannot parse as YYYY-MM-DD, since its day lands in the
#: year's place and its year in the day's.
SLOT_TIME_FORMATS = ("%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M")

MAX_ROWS = 20_000

IDENTIFIER_HEADERS = frozenset({"identifier", "roll_number", "roll", "email"})
VENUE_HEADERS = frozenset({"venue", "location"})
TIME_HEADERS = frozenset({"time", "timing", "scheduled_at", "slot"})


@dataclass(frozen=True, slots=True)
class SlotRow:
    """One parsed row, in the shape ``assign_venue_timing`` consumes."""

    row_number: int
    identifier: str
    venue: str
    time: str


@dataclass(frozen=True, slots=True)
class SlotParseError:
    row_number: int | None
    code: str
    human: str
    path: str | None = None


@dataclass(frozen=True, slots=True)
class SlotParseResult:
    rows: tuple[SlotRow, ...]
    errors: tuple[SlotParseError, ...]
    headers: tuple[str, ...]


def parse_slot_time(text: str) -> datetime | Reason:
    """An IST slot as UTC, or the reason it could not be read.

    Strict on purpose: a time with seconds, a two-digit year, or a month name
    is refused rather than guessed at, because guessing wrong sends a student
    to an interview on the wrong day.
    """
    candidate = " ".join(text.split())
    for slot_format in SLOT_TIME_FORMATS:
        try:
            naive = datetime.strptime(candidate, slot_format)
        except ValueError:
            continue
        return naive.replace(tzinfo=IST).astimezone(UTC)
    return Reason(
        code=INVALID_FIELD_VALUE,
        human=(
            f"'{text}' is not a time: write it as 2026-03-14 09:30 "
            "or 14-03-2026 09:30, in IST"
        ),
        path="time",
    )


def render_slot_cell(value: object) -> str:
    """One spreadsheet cell as text, keeping the time of day.

    The profile loader renders a spreadsheet datetime as a bare date, which is
    right for a date of birth and would silently drop 09:30 from an interview
    slot -- so this renderer, not that one, reads a venue upload.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def normalize_header(header: str) -> str:
    return "_".join(header.strip().casefold().replace("-", " ").replace("_", " ").split())


def parse_slot_upload(payload: bytes, filename: str) -> SlotParseResult:
    """Parse a venue/timing upload into command rows and per-row problems."""
    table = read_table(payload, filename, cell=render_slot_cell)
    if not table:
        raise UploadParseError("The file has no rows")
    if len(table) - 1 > MAX_ROWS:
        raise UploadParseError(f"The file exceeds {MAX_ROWS} rows")

    raw_headers = tuple(render_slot_cell(cell) for cell in table[0])
    headers = tuple(normalize_header(header) for header in raw_headers)
    identifier_column = _column(headers, IDENTIFIER_HEADERS)
    venue_column = _column(headers, VENUE_HEADERS)
    time_column = _column(headers, TIME_HEADERS)
    if identifier_column is None:
        raise UploadParseError("The file needs an identifier column")
    if venue_column is None and time_column is None:
        raise UploadParseError("The file needs a venue column, a time column, or both")

    errors: list[SlotParseError] = []
    rows: list[SlotRow] = []
    seen: dict[str, int] = {}
    for row_number, raw_row in enumerate(table[1:], start=2):
        identifier = _at(raw_row, identifier_column)
        venue = _at(raw_row, venue_column)
        time_text = _at(raw_row, time_column)
        if not identifier:
            errors.append(
                SlotParseError(
                    row_number=row_number,
                    code=INVALID_FIELD_VALUE,
                    human="The identifier is missing",
                    path="identifier",
                )
            )
            continue
        first = seen.setdefault(identifier.casefold(), row_number)
        if first != row_number:
            # Two slots for one student is a mistake with a wrong answer either
            # way, so neither is chosen: the file is reported and resubmitted.
            errors.append(
                SlotParseError(
                    row_number=row_number,
                    code=DUPLICATE_ROW,
                    human=f"'{identifier}' already appears on row {first}",
                    path="identifier",
                )
            )
            continue
        if not venue and not time_text:
            # An empty cell leaves that override alone (the design review section 4.23),
            # so a row with both empty asks for nothing at all.
            errors.append(
                SlotParseError(
                    row_number=row_number,
                    code=INVALID_FIELD_VALUE,
                    human="Give a venue, a time, or both",
                    path="venue",
                )
            )
            continue
        if time_text:
            parsed = parse_slot_time(time_text)
            if isinstance(parsed, Reason):
                errors.append(
                    SlotParseError(
                        row_number=row_number,
                        code=parsed.code,
                        human=parsed.human,
                        path=parsed.path,
                    )
                )
                continue
        rows.append(
            SlotRow(
                row_number=row_number,
                identifier=identifier,
                venue=venue,
                time=time_text,
            )
        )
    return SlotParseResult(rows=tuple(rows), errors=tuple(errors), headers=headers)


def _column(headers: tuple[str, ...], names: frozenset[str]) -> int | None:
    return next(
        (index for index, header in enumerate(headers) if header in names), None
    )


def _at(row: list[str], column: int | None) -> str:
    if column is None or column >= len(row):
        return ""
    return row[column].strip()
