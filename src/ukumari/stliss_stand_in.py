"""A temporary stand-in for ``stliss``: an ``.sls`` reader and a values-CSV writer.

``stliss`` does not exist yet. This module implements, from ``01-stliss.md``, just enough of
its reader for ukumari's writer to be read back and checked, as the plan requires, and its
values-CSV writer. **Delete it once ``stliss`` exists**, and read back through
``stliss.read_sls`` and write with ``stliss.write_values`` instead. Its types are minimal
on purpose, so nothing grows to depend on them.
"""

import csv
import io
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass

from ukumari.result import Err, Ok, Result

HEADER = "sheet\trow\tcol\tcell\tformat"
_INTEGER = re.compile(r"[1-9][0-9]*")
_NUMBER = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?")
_ESCAPE = re.compile(r"_x[0-9A-Fa-f]{4}_")
_FORBIDDEN_IN_SHEET = set(":\\/?*[]")
_SMALLEST_NORMAL = 2.2250738585072014e-308
_LARGEST = 9.99999999999999e307


def _units(text: str) -> int:
    """Length in UTF-16 code units, as the spreadsheet app counts it."""
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def _bad_characters(text: str) -> bool:
    return any(ord(c) < 0x20 or c == "\x7f" or c in ("￾", "￿") for c in text)


@dataclass(frozen=True, slots=True)
class SlsError:
    line: int
    message: str

    def __str__(self) -> str:
        return f"line {self.line}: {self.message}"


@dataclass(frozen=True, slots=True)
class SlsCell:
    line: int
    sheet: str
    row: int
    col: int
    cell: str
    format: dict[str, str]


def read_sls(text: str) -> Result[tuple[SlsCell, ...], tuple[SlsError, ...]]:
    """Every cell of an ``.sls`` file, or every problem with it, each with its line."""
    errors: list[SlsError] = []

    def fail(line: int, message: str) -> None:
        errors.append(SlsError(line, message))

    if text.startswith("﻿"):
        fail(1, "the file starts with a byte-order mark")
    if "\r" in text:
        fail(text[: text.index("\r")].count("\n") + 1, "a CR is not allowed")
    if not text.endswith("\n"):
        fail(text.count("\n") + 1, "the last line does not end with LF")
    lines = text.split("\n")[:-1] if text.endswith("\n") else text.split("\n")
    if not lines or lines[0] != HEADER:
        fail(1, "the first line must be the header sheet, row, col, cell, format")
    if len(lines) < 2:
        fail(1, "there are no cells")

    cells: list[SlsCell] = []
    seen: dict[tuple[str, int, int], int] = {}
    spelled: dict[str, str] = {}
    widths: dict[tuple[str, int], bool] = {}
    for number, line in enumerate(lines[1:], start=2):
        if not line:
            fail(number, "an empty line")
            continue
        fields = line.split("\t")
        if len(fields) != 5:
            fail(number, f"needs 5 tab-separated fields, not {len(fields)}")
            continue
        sheet, row_text, col_text, cell, format_text = fields
        ok = True
        if not 1 <= _units(sheet) <= 31:
            fail(number, f"sheet name {sheet!r} must be 1 to 31 characters")
            ok = False
        if _FORBIDDEN_IN_SHEET & set(sheet) or _bad_characters(sheet):
            fail(number, f"sheet name {sheet!r} has a character a sheet name cannot")
            ok = False
        if sheet.startswith("'") or sheet.endswith("'"):
            fail(number, f"sheet name {sheet!r} starts or ends with an apostrophe")
        if sheet.casefold() == "history" or _ESCAPE.search(sheet):
            fail(number, f"sheet name {sheet!r} is not allowed")
        key = sheet.casefold()
        if key in spelled and spelled[key] != sheet:
            fail(number, f"sheet {sheet!r} is also spelled {spelled[key]!r}")
        spelled.setdefault(key, sheet)
        row = int(row_text) if _INTEGER.fullmatch(row_text) else 0
        col = int(col_text) if _INTEGER.fullmatch(col_text) else 0
        if not 1 <= row <= 1_048_576:
            fail(
                number,
                f"row must be a whole number from 1 to 1048576, not {row_text!r}",
            )
            ok = False
        if not 1 <= col <= 16_384:
            fail(
                number, f"col must be a whole number from 1 to 16384, not {col_text!r}"
            )
            ok = False
        kind, rest = cell[:1], cell[1:]
        match kind:
            case "=":
                if not rest:
                    fail(number, "a formula needs something after the =")
            case "#":
                if not _NUMBER.fullmatch(rest):
                    fail(number, f"not a number: {rest!r}")
                else:
                    value = float(rest)
                    if not math.isfinite(value) or abs(value) > _LARGEST:
                        fail(number, f"the number {rest} is too large")
                    elif value != 0 and abs(value) < _SMALLEST_NORMAL:
                        fail(number, f"the number {rest} is subnormal")
            case "$":
                if not 1 <= _units(rest) <= 32_767 or _bad_characters(rest):
                    fail(number, f"text {rest!r} is empty, too long or has a control")
            case "?":
                if rest not in ("TRUE", "FALSE"):
                    fail(number, f"a logical is TRUE or FALSE, not {rest!r}")
            case _:
                fail(number, f"a cell starts with =, #, $ or ?, not {cell[:1]!r}")
        pairs: dict[str, str] = {}
        if format_text:
            for pair in format_text.split("|"):
                name, equals, value = pair.partition("=")
                if not equals or not value:
                    fail(number, f"a format pair is key=value, not {pair!r}")
                elif name in pairs:
                    fail(number, f"format key {name!r} appears twice")
                elif name not in ("numberformat", "indent", "columnwidth"):
                    fail(number, f"unknown format key {name!r}")
                else:
                    pairs[name] = value
        indent = pairs.get("indent")
        if indent is not None and not (
            (indent == "0" or _INTEGER.fullmatch(indent)) and int(indent) <= 250
        ):
            fail(number, f"indent must be a whole number from 0 to 250, not {indent!r}")
        width = pairs.get("columnwidth")
        if width not in (None, "default") and not (
            _NUMBER.fullmatch(width) and 0 <= float(width) <= 255
        ):
            fail(number, f"columnwidth must be default or 0 to 255, not {width!r}")
        if ok:
            where = (key, row, col)
            if where in seen:
                fail(number, f"the cell is already written on line {seen[where]}")
            seen.setdefault(where, number)
            column = (key, col)
            if column not in widths:
                widths[column] = True
                if width is None:
                    fail(number, "the first line for a column must carry columnwidth")
            elif width is not None:
                fail(number, "only the first line for a column may carry columnwidth")
            cells.append(SlsCell(number, sheet, row, col, cell, pairs))
    if errors:
        return Err(tuple(errors))
    return Ok(tuple(cells))


def write_values(rows: Iterable[tuple[str, int, int, int, str]]) -> str:
    """A values CSV: ``sheet,row,col,type,value``, LF line endings, RFC 4180 quoting."""
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["sheet", "row", "col", "type", "value"])
    for row in rows:
        writer.writerow(row)
    return out.getvalue()
