"""Reading a CSV or XLSX upload into a table of strings.

Nothing here interprets what the columns *mean*: this is the mechanical half
of an upload -- decode, open the workbook, hand back rows -- shared so that the
PRO-2 profile load and the RND-4 venue load cannot drift on encoding, workbook
handling, or how big a file may be.  What a cell says is the caller's business,
which is why the cell renderer is a parameter: a profile row wants a date out
of a spreadsheet date, and a round's slot wants the time as well.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

#: Renders one spreadsheet cell as the text the parser will read.
CellRenderer = Callable[[object], str]


class UploadParseError(ValueError):
    """The upload could not be read at all."""


def read_table(payload: bytes, filename: str, *, cell: CellRenderer) -> list[list[str]]:
    """Decode an upload into rows of rendered cells, blank rows dropped."""
    if filename.casefold().endswith(".xlsx"):
        table = _read_xlsx(payload, cell)
    elif filename.casefold().endswith(".csv"):
        table = _read_csv(payload, cell)
    else:
        raise UploadParseError("Upload a .csv or .xlsx file")
    return [row for row in table if any(value for value in row)]


def _read_csv(payload: bytes, cell: CellRenderer) -> list[list[str]]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise UploadParseError("The file must be UTF-8 encoded") from error
    reader = csv.reader(io.StringIO(text))
    return [[cell(value) for value in row] for row in reader]


def _read_xlsx(payload: bytes, cell: CellRenderer) -> list[list[str]]:
    try:
        workbook = load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
    except (InvalidFileException, BadZipFile, KeyError, ValueError, TypeError) as error:
        raise UploadParseError("The workbook could not be read") from error
    try:
        worksheet = workbook.worksheets[0]
        return [
            [cell(value) for value in row]
            for row in worksheet.iter_rows(values_only=True)
        ]
    finally:
        workbook.close()
