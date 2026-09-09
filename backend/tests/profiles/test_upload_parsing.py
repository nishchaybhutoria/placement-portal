"""CSV and XLSX parsing for the bulk-upsert upload (PRO-2), pure and DB-free."""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from app.core.errors import DUPLICATE_ROW, FIELD_NOT_EDITABLE, INVALID_FIELD_VALUE
from app.modules.profiles.parsing import (
    HEADER_ALIASES,
    UploadParseError,
    normalize_header,
    parse_upload,
)

CSV = (
    b"Institute Email,Roll Number,CPI,Graduating Year\n"
    b"one@example.edu,21110001,8.5,2026\n"
    b"two@example.edu,21110002,9.1,2027\n"
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
    ("header", "expected"),
    [
        ("Institute Email", "institute_email"),
        ("  roll-number ", "roll_number"),
        ("Graduating  Year", "graduating_year"),
        ("CPI", "cpi"),
    ],
)
def test_PRO2_headers_normalize_to_field_keys(header: str, expected: str) -> None:
    assert normalize_header(header) == expected


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Program", "program_id"),
        ("Primary Branch", "primary_branch_id"),
        ("Secondary branch (dual majors)", None),
        ("Active backlog count", "active_backlogs"),
        ("Gender", "gender"),
        ("Full name", "full_name"),
    ],
)
def test_PRO2_human_column_titles_alias_onto_field_keys(
    header: str, expected: str | None
) -> None:
    assert HEADER_ALIASES.get(normalize_header(header)) == expected


def test_PRO2_csv_rows_carry_only_provided_columns() -> None:
    parsed = parse_upload(CSV, "load.csv")
    assert parsed.errors == ()
    assert [row.institute_email for row in parsed.rows] == [
        "one@example.edu",
        "two@example.edu",
    ]
    assert [row.row_number for row in parsed.rows] == [2, 3]
    assert parsed.rows[0].fields == {
        "roll_number": "21110001",
        "cpi": "8.5",
        "graduating_year": "2026",
    }


def test_PRO2_institution_pre_registration_sheet_derives_dual_degree_shape_and_year() -> None:
    payload = (
        b"Roll No,Name of the Student,Email ID,Contact Number,Gender,Prog.,"
        b"Dept./Disp.,Secondary Disp.,Date of Birth\n"
        b"23110001,Asha Rao,asha@example.edu,9876543210,Female,"
        b"BTech - M.Tech Dual degree,CE,CSE,2001-01-01\n"
        b"23110002,Dev Shah,dev@example.edu,9876543211,Male,"
        b"Dual Major BTech,CL,EE,2001-01-02\n"
    )
    parsed = parse_upload(payload, "Pre-registered FT 2027.xlsx - Sheet1.csv")

    assert parsed.errors == ()
    assert parsed.rows[0].fields == {
        "roll_number": "23110001",
        "full_name": "Asha Rao",
        "contact_number": "9876543210",
        "gender": "Female",
        "program_id": "BTech",
        "primary_branch_id": "Civil Engineering",
        "is_dual_major": False,
        "is_dual_degree": True,
        "secondary_program_id": "MTech",
        "secondary_branch_id": "Computer Science and Engineering",
        "graduating_year": "2027",
    }
    assert parsed.rows[1].fields["is_dual_major"] is True
    assert parsed.rows[1].fields["is_dual_degree"] is False
    assert parsed.rows[1].fields["primary_branch_id"] == "Chemical Engineering"
    assert "secondary_program_id" not in parsed.rows[1].fields


def test_PRO2_xlsx_rows_parse_with_native_cell_types() -> None:
    payload = _workbook(
        [
            ["institute_email", "cpi", "graduating_year", "gender"],
            ["one@example.edu", 8.5, 2026, "female"],
            ["two@example.edu", None, 2027, None],
        ]
    )
    parsed = parse_upload(payload, "load.xlsx")
    assert parsed.errors == ()
    assert parsed.rows[0].fields == {"cpi": "8.5", "graduating_year": "2026", "gender": "female"}
    assert parsed.rows[1].fields == {"graduating_year": "2027"}


def test_PRO2_student_managed_columns_are_reported_as_file_errors() -> None:
    payload = b"institute_email,github_url,cpi\none@example.edu,https://x.dev,8.0\n"
    parsed = parse_upload(payload, "load.csv")
    assert [error.code for error in parsed.errors] == [FIELD_NOT_EDITABLE]
    assert parsed.rows[0].fields == {"cpi": "8.0"}


def test_PRO2_duplicate_addresses_are_excluded_and_reported() -> None:
    payload = (
        b"institute_email,cpi\n"
        b"one@example.edu,8.0\n"
        b"ONE@example.edu,9.0\n"
        b"two@example.edu,7.0\n"
    )
    parsed = parse_upload(payload, "load.csv")
    assert [row.institute_email for row in parsed.rows] == ["two@example.edu"]
    assert [(error.row_number, error.code) for error in parsed.errors] == [
        (2, DUPLICATE_ROW),
        (3, DUPLICATE_ROW),
    ]


def test_PRO2_rows_without_an_address_are_row_errors() -> None:
    parsed = parse_upload(b"institute_email,cpi\n,8.0\none@example.edu,7.0\n", "load.csv")
    assert [(error.row_number, error.code) for error in parsed.errors] == [
        (2, INVALID_FIELD_VALUE)
    ]
    assert [row.institute_email for row in parsed.rows] == ["one@example.edu"]


@pytest.mark.parametrize(
    ("payload", "filename"),
    [
        (b"cpi\n8.0\n", "load.csv"),
        (b"", "load.csv"),
        (b"institute_email\n", "load.txt"),
        (b"not-a-workbook", "load.xlsx"),
        ("institute_email\n\xff".encode("latin-1"), "load.csv"),
    ],
)
def test_PRO2_unusable_uploads_fail_closed(payload: bytes, filename: str) -> None:
    with pytest.raises(UploadParseError):
        parse_upload(payload, filename)
