"""Pure CSV/XLSX parsing for the PRO-2 admin bulk upsert.

Parsing performs no writes and no database access: it turns an uploaded
spreadsheet into the row shape ``bulk_upsert_profiles`` consumes, and reports
per-row problems the command can never see (bad headers, duplicate keys).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.core.errors import DUPLICATE_ROW, FIELD_NOT_EDITABLE, INVALID_FIELD_VALUE
from app.core.uploads import UploadParseError, read_table
from app.modules.profiles.fields import BULK_FIELDS, FIELDS, FIELDS_BY_KEY

EMAIL_HEADERS = frozenset({"institute_email", "email"})

# The Registrar's pre-registration export uses terse, stable column names and
# discipline codes. It is adapted to the canonical bulk contract before the
# normal strict parser runs; unrelated sensitive columns (DOB, category, etc.)
# are deliberately discarded and never reach staging or audit payloads.
_PRE_REG_REQUIRED = frozenset(
    {"roll_no", "name_of_the_student", "email_id", "prog", "dept_disp", "secondary_disp"}
)
_DISCIPLINE_CODES: dict[str, str] = {
    "AI": "Artificial Intelligence",
    "BE": "Biological Engineering",
    "CE": "Civil Engineering",
    "CL": "Chemical Engineering",
    "CSE": "Computer Science and Engineering",
    "EE": "Electrical Engineering",
    "ESS": "Earth Sciences",
    "ICDT": "Integrated Circuit Design and Technology",
    "MSE": "Materials Engineering",
    "ME": "Mechanical Engineering",
    "CH": "Chemistry",
    "CG": "Cognitive Science",
    "MA": "Mathematics",
    "PH": "Physics",
    "HSS": "Humanities and Social Sciences",
}


def _header_aliases() -> dict[str, str]:
    """Accept both the field key and the human column title a spreadsheet carries."""
    aliases: dict[str, str] = {}
    for field in FIELDS:
        aliases[field.key] = field.key
        aliases[normalize_header(field.label)] = field.key
        if field.key.endswith("_id"):
            aliases[field.key.removesuffix("_id")] = field.key
    return aliases


MAX_ROWS = 20_000


@dataclass(frozen=True, slots=True)
class ParsedRow:
    row_number: int
    institute_email: str
    fields: dict[str, object]


@dataclass(frozen=True, slots=True)
class ParseError:
    row_number: int | None
    code: str
    human: str
    path: str | None = None


@dataclass(frozen=True, slots=True)
class ParseResult:
    rows: tuple[ParsedRow, ...]
    errors: tuple[ParseError, ...]
    headers: tuple[str, ...]


__all__ = [
    "MAX_ROWS",
    "ParseError",
    "ParseResult",
    "ParsedRow",
    "UploadParseError",
    "normalize_header",
    "parse_upload",
]


def normalize_header(header: str) -> str:
    return "_".join(header.strip().casefold().replace("-", " ").replace("_", " ").split())


HEADER_ALIASES = _header_aliases()


def _canonical_program(raw: str) -> tuple[str, bool, bool, str | None]:
    normalized = " ".join(re.sub(r"[^a-z0-9]+", " ", raw.casefold()).split())
    compact = normalized.replace(" ", "")
    if "dualmajor" in compact:
        return "BTech", True, False, None
    if "dual" in normalized:
        if "btech" not in compact:
            raise UploadParseError(f"Dual-degree program '{raw}' does not name BTech")
        second = "MTech" if "mtech" in compact else "MSc" if "msc" in compact else None
        if second is None:
            raise UploadParseError(f"Dual-degree program '{raw}' must identify MTech or MSc")
        return "BTech", False, True, second
    programs = {
        "btech": "BTech",
        "mtech": "MTech",
        "msc": "MSc",
        "ma": "MA",
        "phd": "PhD",
    }
    try:
        return programs[compact], False, False, None
    except KeyError as error:
        raise UploadParseError(f"Unknown program '{raw}'") from error


def _discipline(raw: object, *, row_number: int, column: str) -> str | None:
    code = _cell_text(raw).upper()
    if code in {"", "0"}:
        return None
    try:
        return _DISCIPLINE_CODES[code]
    except KeyError as error:
        raise UploadParseError(f"Row {row_number}: unknown {column} code '{code}'") from error


def _source_header(value: object) -> str:
    return "_".join(re.sub(r"[^a-z0-9]+", " ", _cell_text(value).casefold()).split())


def _adapt_pre_registration(
    table: Sequence[Sequence[object]], filename: str
) -> list[list[object]]:
    source_headers = [_source_header(cell) for cell in table[0]]
    indexes = {header: index for index, header in enumerate(source_headers)}
    year_match = re.search(r"\bFT[ _-]*(20\d{2})\b", filename, re.IGNORECASE)
    output_headers: list[object] = [
        "institute_email",
        "roll_number",
        "full_name",
        "contact_number",
        "gender",
        "program_id",
        "primary_branch_id",
        "is_dual_major",
        "is_dual_degree",
        "secondary_program_id",
        "secondary_branch_id",
    ]
    if year_match:
        output_headers.append("graduating_year")
    output: list[list[object]] = [output_headers]
    for row_number, source in enumerate(table[1:], start=2):

        def cell(name: str, current: Sequence[object] = source) -> object:
            index = indexes[name]
            return current[index] if index < len(current) else ""

        program, dual_major, dual_degree, secondary_program = _canonical_program(
            _cell_text(cell("prog"))
        )
        primary = _discipline(cell("dept_disp"), row_number=row_number, column="primary discipline")
        secondary = _discipline(
            cell("secondary_disp"), row_number=row_number, column="secondary discipline"
        )
        if (dual_major or dual_degree) and secondary is None:
            raise UploadParseError(
                f"Row {row_number}: {program} dual record needs a secondary discipline"
            )
        if not (dual_major or dual_degree) and secondary is not None:
            raise UploadParseError(
                f"Row {row_number}: a non-dual program has a secondary discipline"
            )
        values: list[object] = [
            cell("email_id"),
            cell("roll_no"),
            cell("name_of_the_student"),
            cell("contact_number") if "contact_number" in indexes else "",
            cell("gender") if "gender" in indexes else "",
            program,
            primary or "",
            dual_major,
            dual_degree,
            secondary_program or "",
            secondary or "",
        ]
        if year_match:
            values.append(year_match.group(1))
        output.append(values)
    return output


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (int, Decimal)):
        return str(value)
    return str(value).strip()


def parse_upload(payload: bytes, filename: str) -> ParseResult:
    """Parse a CSV or XLSX upload into bulk-upsert rows and per-row problems."""
    table: Sequence[Sequence[object]] = read_table(
        payload, filename, cell=_cell_text
    )
    if not table:
        raise UploadParseError("The file has no rows")
    source_headers = frozenset(_source_header(cell) for cell in table[0])
    if _PRE_REG_REQUIRED <= source_headers:
        table = _adapt_pre_registration(table, filename)
    if len(table) - 1 > MAX_ROWS:
        raise UploadParseError(f"The file exceeds {MAX_ROWS} rows")

    raw_headers = tuple(_cell_text(cell) for cell in table[0])
    headers = tuple(
        HEADER_ALIASES.get(normalize_header(header), normalize_header(header))
        for header in raw_headers
    )
    errors: list[ParseError] = []
    email_columns = [index for index, header in enumerate(headers) if header in EMAIL_HEADERS]
    if not email_columns:
        raise UploadParseError("The file needs an institute_email column")
    email_column = email_columns[0]

    known_columns: dict[int, str] = {}
    for index, header in enumerate(headers):
        if index == email_column or not header:
            continue
        if header in BULK_FIELDS:
            known_columns[index] = header
        else:
            label = FIELDS_BY_KEY[header].label if header in FIELDS_BY_KEY else header
            errors.append(
                ParseError(
                    row_number=None,
                    code=FIELD_NOT_EDITABLE,
                    human=f"Column '{raw_headers[index]}' is not an admin-managed field",
                    path=label,
                )
            )

    rows: list[ParsedRow] = []
    seen: dict[str, int] = {}
    duplicated: set[str] = set()
    staged: list[tuple[int, str, dict[str, object]]] = []
    for offset, raw_row in enumerate(table[1:], start=2):
        email = _cell_text(raw_row[email_column]) if email_column < len(raw_row) else ""
        if not email:
            errors.append(
                ParseError(
                    row_number=offset,
                    code=INVALID_FIELD_VALUE,
                    human="The institute email is missing",
                    path="institute_email",
                )
            )
            continue
        key = email.casefold()
        if key in seen:
            duplicated.add(key)
        else:
            seen[key] = offset
        values: dict[str, object] = {}
        for index, field_key in known_columns.items():
            if index >= len(raw_row):
                continue
            cell = raw_row[index]
            if cell == "":
                continue
            values[field_key] = cell
        staged.append((offset, email, values))

    for row_number, email, values in staged:
        if email.casefold() in duplicated:
            errors.append(
                ParseError(
                    row_number=row_number,
                    code=DUPLICATE_ROW,
                    human=f"'{email}' appears more than once in this file",
                    path="institute_email",
                )
            )
            continue
        rows.append(ParsedRow(row_number=row_number, institute_email=email, fields=values))

    return ParseResult(rows=tuple(rows), errors=tuple(errors), headers=headers)
