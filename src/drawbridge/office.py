"""Deterministic text extraction for office documents: Word (OOXML and the 97 binary format) and
Excel (OOXML and binary). No model, no network, no rewriting of the input."""

from __future__ import annotations

import csv
import io
import math
import posixpath
import re
import struct
import zipfile
import zlib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence
from xml.etree import ElementTree

import olefile
import openpyxl
import xlrd
from openpyxl.utils.exceptions import InvalidFileException

from .errors import ConversionOperationalError, InherentlyUnprocessableError


class MalformedDocxError(ConversionOperationalError):
    """The OOXML package is not a readable Word document."""


DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
_WML_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_text(path: Path) -> str:
    """Extract paragraph text from an OOXML word-processing document using
    only the standard library (ZIP container + word/document.xml). Tables are
    covered because their cells contain ordinary paragraph elements."""
    try:
        with zipfile.ZipFile(path) as archive:
            document = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise MalformedDocxError(f"malformed DOCX package: {exc}") from exc
    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError as exc:
        raise MalformedDocxError(f"malformed DOCX document.xml: {exc}") from exc
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{_WML_NS}p"):
        runs: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{_WML_NS}t":
                runs.append(node.text or "")
            elif node.tag == f"{_WML_NS}tab":
                runs.append("\t")
            elif node.tag in (f"{_WML_NS}br", f"{_WML_NS}cr"):
                runs.append("\n")
        text = "".join(runs).strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
XLS_MEDIA_TYPE = "application/vnd.ms-excel"
DOC_MEDIA_TYPE = "application/msword"
#: The three legacy and spreadsheet Office classes.
OFFICE_MEDIA_TYPES = frozenset({XLSX_MEDIA_TYPE, XLS_MEDIA_TYPE, DOC_MEDIA_TYPE})
#: Every Office class with a deterministic text extractor, DOCX included.
OFFICE_TEXT_MEDIA_TYPES = frozenset({DOCX_MEDIA_TYPE, *OFFICE_MEDIA_TYPES})


class OfficeConversionError(ConversionOperationalError):
    """One Office artifact cannot be read by an otherwise healthy pipeline."""


class MalformedXlsxError(OfficeConversionError):
    """An OOXML spreadsheet package or a required part is structurally invalid."""


class EncryptedXlsError(OfficeConversionError, InherentlyUnprocessableError):
    """A legacy workbook declares encryption and cannot be read without a key."""

    blocked_reason = "password-protected"


class MalformedXlsError(OfficeConversionError):
    """A legacy BIFF workbook or its compound container is structurally invalid."""


class UnsupportedWordVersionError(OfficeConversionError):
    """A binary Word document declares a version outside the Word97 profile."""


class MalformedWord97Error(OfficeConversionError):
    """A Word97 document's OLE2, FIB, or piece-table structure is invalid."""


# ---------------------------------------------------------------------------
# Shared spreadsheet representation
# ---------------------------------------------------------------------------

_SML_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_OFFICE_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PACKAGE_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_CELL_REFERENCE = re.compile(r"\$?([A-Za-z]{1,3})\$?([0-9]{1,7})")
_XLSX_PARSE_FAILURES = (
    zipfile.BadZipFile,
    zipfile.LargeZipFile,
    # A package member whose deflate stream is damaged raises zlib.error out of
    # zipfile; that is one unreadable artifact, not a defect in the pipeline.
    zlib.error,
    InvalidFileException,
    ElementTree.ParseError,
    KeyError,
    ValueError,
    struct.error,
)


@dataclass(frozen=True)
class _SpreadsheetSheet:
    """One worksheet reduced to the exact shape the mirror body renders."""

    name: str
    row_extent: int
    column_extent: int
    rows: tuple[tuple[int, tuple[str, ...]], ...]
    elided_rows: int
    merged_ranges: tuple[str, ...]


def _column_letter(index: int) -> str:
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def _column_index(letters: str) -> int:
    value = 0
    for character in letters.upper():
        value = value * 26 + (ord(character) - ord("A") + 1)
    return value


def _parse_merged_range(reference: str | None) -> tuple[int, int, int, int] | None:
    if not reference:
        return None
    corners = reference.split(":")
    if len(corners) not in (1, 2):
        return None
    parsed: list[tuple[int, int]] = []
    for corner in corners:
        match = _CELL_REFERENCE.fullmatch(corner.strip())
        if match is None:
            return None
        parsed.append((int(match.group(2)), _column_index(match.group(1))))
    first, last = parsed[0], parsed[-1]
    return (
        min(first[0], last[0]),
        min(first[1], last[1]),
        max(first[0], last[0]),
        max(first[1], last[1]),
    )


def _render_merged_range(bounds: tuple[int, int, int, int]) -> str:
    first_row, first_column, last_row, last_column = bounds
    return (
        f"{_column_letter(first_column)}{first_row}:"
        f"{_column_letter(last_column)}{last_row}"
    )


def _format_spreadsheet_value(value: Any) -> str:
    """Normalize one computed cell value into its mirror field, exactly once."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, str):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        return str(int(value)) if value.is_integer() else str(value)
    return str(value)


def _build_spreadsheet_sheet(
    name: str,
    cells: Mapping[int, Mapping[int, str]],
    merged: Sequence[tuple[int, int, int, int]],
) -> _SpreadsheetSheet:
    """Derive the emitted extents, anchored rows, and elision count for a sheet.

    *cells* holds only non-empty formatted fields, keyed by original 1-based
    worksheet row and column, so both extents are content-derived and identical
    for the same content in either spreadsheet format.
    """
    row_extent = max(cells, default=0)
    column_extent = max((column for row in cells.values() for column in row), default=0)
    for bounds in merged:
        row_extent = max(row_extent, bounds[2])
        column_extent = max(column_extent, bounds[3])
    ranges = tuple(_render_merged_range(bounds) for bounds in sorted(merged))
    if row_extent == 0 or column_extent == 0:
        return _SpreadsheetSheet(name, 0, 0, (), 0, ranges)
    rows: list[tuple[int, tuple[str, ...]]] = []
    elided = 0
    for number in range(1, row_extent + 1):
        row = cells.get(number, {})
        fields = tuple(row.get(column, "") for column in range(1, column_extent + 1))
        if number != 1 and not any(fields):
            elided += 1
            continue
        rows.append((number, fields))
    return _SpreadsheetSheet(
        name, row_extent, column_extent, tuple(rows), elided, ranges
    )


def _render_spreadsheet_body(sheets: Sequence[_SpreadsheetSheet]) -> str:
    """Render the one fenced-CSV body both spreadsheet converters emit."""
    blocks: list[str] = []
    for sheet in sheets:
        heading = (
            f"## Sheet: {sheet.name}  "
            f"({sheet.row_extent} rows × {sheet.column_extent} cols"
        )
        if sheet.elided_rows:
            heading += f", {sheet.elided_rows} empty rows elided"
        heading += ")"
        lines = [heading, ""]
        if sheet.merged_ranges:
            lines.append(
                "Merged cells (anchor retains value): "
                + ", ".join(sheet.merged_ranges)
            )
            lines.append("")
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        if sheet.rows:
            for number, fields in sheet.rows:
                label = "row" if number == 1 else str(number)
                writer.writerow([label, *fields])
        else:
            writer.writerow(["row"])
        lines.extend(("```csv", buffer.getvalue().rstrip("\n"), "```"))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# OOXML spreadsheets
# ---------------------------------------------------------------------------


def _package_member(target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join("xl", target))


def _xlsx_sheet_merges(archive: zipfile.ZipFile, member: str) -> tuple[tuple[int, int, int, int], ...]:
    bounds: list[tuple[int, int, int, int]] = []
    with archive.open(member) as stream:
        parser = ElementTree.iterparse(stream, ("start", "end"))
        _event, root = next(parser)
        for event, element in parser:
            if event != "end":
                continue
            if element.tag == f"{_SML_NS}mergeCell":
                parsed = _parse_merged_range(element.get("ref"))
                if parsed is not None:
                    bounds.append(parsed)
            elif element.tag == f"{_SML_NS}row":
                # Worksheet parts run to megabytes; drop finished rows so the
                # merge scan stays bounded rather than materializing the sheet.
                root.clear()
    return tuple(bounds)


def _xlsx_merged_ranges(path: Path) -> dict[str, tuple[tuple[int, int, int, int], ...]]:
    """Read every worksheet's merged ranges, which read-only mode does not expose."""
    ranges: dict[str, tuple[tuple[int, int, int, int], ...]] = {}
    with path.open("rb") as handle:
        with zipfile.ZipFile(handle) as archive:
            names = frozenset(archive.namelist())
            workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
            relationships = ElementTree.fromstring(
                archive.read("xl/_rels/workbook.xml.rels")
            )
            targets = {
                node.get("Id"): node.get("Target")
                for node in relationships.iter(f"{_PACKAGE_REL_NS}Relationship")
            }
            for node in workbook.iter(f"{_SML_NS}sheet"):
                target = targets.get(node.get(f"{_OFFICE_REL_NS}id") or "")
                if target is None:
                    continue
                member = _package_member(target)
                if member not in names:
                    continue
                ranges[node.get("name") or ""] = _xlsx_sheet_merges(archive, member)
    return ranges


def _xlsx_sheets(path: Path) -> tuple[_SpreadsheetSheet, ...]:
    merged = _xlsx_merged_ranges(path)
    sheets: list[_SpreadsheetSheet] = []
    with path.open("rb") as handle:
        # openpyxl routes on path.suffix, and CAS objects carry no extension:
        # the confirmed media type already selected this converter, so the
        # authoritative bytes are handed over as an open binary handle that
        # stays open for the whole lazy read_only traversal.
        workbook = openpyxl.load_workbook(handle, read_only=True, data_only=True)
        try:
            for worksheet in workbook.worksheets:
                cells: dict[int, dict[int, str]] = {}
                for row in worksheet.iter_rows():
                    for cell in row:
                        number = getattr(cell, "row", None)
                        column = getattr(cell, "column", None)
                        if number is None or column is None:
                            continue
                        field = _format_spreadsheet_value(cell.value)
                        if field:
                            cells.setdefault(number, {})[column] = field
                sheets.append(
                    _build_spreadsheet_sheet(
                        worksheet.title, cells, merged.get(worksheet.title, ())
                    )
                )
        finally:
            workbook.close()
    return tuple(sheets)


def xlsx_text(path: Path) -> str:
    """Render an OOXML workbook as the shared provenance-free spreadsheet body."""
    try:
        sheets = _xlsx_sheets(path)
    except _XLSX_PARSE_FAILURES as exc:
        raise MalformedXlsxError(f"malformed XLSX package: {exc}") from exc
    return _render_spreadsheet_body(sheets)


# ---------------------------------------------------------------------------
# Legacy BIFF workbooks
# ---------------------------------------------------------------------------

_XLS_PARSE_FAILURES = (
    xlrd.compdoc.CompDocError,
    struct.error,
    IndexError,
    UnicodeDecodeError,
)


def _xls_datetime(serial: float, datemode: int) -> Any:
    try:
        parts = xlrd.xldate_as_tuple(serial, datemode)
    except xlrd.XLDateError as exc:
        raise MalformedXlsError(f"legacy workbook has an unreadable date: {exc}") from exc
    year, month, day, hour, minute, second = parts
    if (year, month, day) == (0, 0, 0):
        return time(hour, minute, second)
    return datetime(year, month, day, hour, minute, second)


def _xls_cell_value(sheet: Any, row: int, column: int, datemode: int) -> Any:
    kind = sheet.cell_type(row, column)
    value = sheet.cell_value(row, column)
    if kind in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return None
    if kind == xlrd.XL_CELL_BOOLEAN:
        return bool(value)
    if kind == xlrd.XL_CELL_ERROR:
        return xlrd.error_text_from_code.get(value, f"#ERR:{value}")
    if kind == xlrd.XL_CELL_DATE:
        return _xls_datetime(value, datemode)
    return value


def _xls_sheets(path: Path) -> tuple[_SpreadsheetSheet, ...]:
    payload = path.read_bytes()
    try:
        # xlrd is fed the authoritative bytes rather than a filename for the
        # same reason openpyxl is fed a handle: the CAS object has no suffix.
        # formatting_info exposes the MERGEDCELLS records the mirror records.
        book = xlrd.open_workbook(
            file_contents=payload, on_demand=True, formatting_info=True
        )
    except xlrd.XLRDError as exc:
        if "encrypt" in str(exc).lower():
            raise EncryptedXlsError(f"encrypted legacy workbook: {exc}") from exc
        raise MalformedXlsError(f"malformed legacy workbook: {exc}") from exc
    except _XLS_PARSE_FAILURES as exc:
        raise MalformedXlsError(f"malformed legacy workbook: {exc}") from exc
    try:
        sheets: list[_SpreadsheetSheet] = []
        for worksheet in book.sheets():
            cells: dict[int, dict[int, str]] = {}
            for row in range(worksheet.nrows):
                for column in range(worksheet.ncols):
                    field = _format_spreadsheet_value(
                        _xls_cell_value(worksheet, row, column, book.datemode)
                    )
                    if field:
                        cells.setdefault(row + 1, {})[column + 1] = field
            merged = [
                (first_row + 1, first_column + 1, last_row, last_column)
                for first_row, last_row, first_column, last_column in (
                    worksheet.merged_cells
                )
            ]
            sheets.append(_build_spreadsheet_sheet(worksheet.name, cells, merged))
    except xlrd.XLRDError as exc:
        raise MalformedXlsError(f"malformed legacy workbook: {exc}") from exc
    except _XLS_PARSE_FAILURES as exc:
        raise MalformedXlsError(f"malformed legacy workbook: {exc}") from exc
    finally:
        book.release_resources()
    return tuple(sheets)


def xls_text(path: Path) -> str:
    """Render a legacy BIFF workbook as the same shared spreadsheet body."""
    return _render_spreadsheet_body(_xls_sheets(path))


# ---------------------------------------------------------------------------
# Word 97 binary documents
# ---------------------------------------------------------------------------

_WORD97_FIB_BASE_SIZE = 32
_WORD97_FIB_SIGNATURE = 0xA5EC
_WORD97_CSW = 0x000E
_WORD97_CSLW = 0x0016
#: The `cbRgFcLcb` MS-DOC mandates for each *effective* nFib. `FibBase.nFib` is
#: only a compatibility base: when `cswNew` is nonzero the effective version is
#: `FibRgCswNew.nFibNew`, which is how a later Word writes `0x00C1` in the base
#: while declaring its own longer arrays. Reading the version therefore means
#: walking the whole declared `fibRgFcLcb` to reach `FibRgCswNew`.
#:
#: These counts are enforced as a **floor**, never as equality. A specification
#: MUST that binds a *writer* is not a validity predicate a *reader* may
#: assert. What this reader consumes is pair 33 and `ccpText`; every mandated
#: count clears pair 33 many times over, `FibRgFcLcb` is forward-extensible,
#: and the walker separately requires the declared array to lie inside the
#: stream. Floor + in-stream bound is exactly the protection the decode needs:
#: it refuses truncation and over-read. Demanding equality would additionally
#: reject documents that are perfectly readable — real writers do pair a later
#: `cbRgFcLcb` with an earlier `nFibNew` — buying well-formedness this decoder
#: never consumes. `cswNew` likewise locates the version; it is not asserted.
_WORD_FIB_MANDATED_CB_RG_FC_LCB: Mapping[int, int] = {
    0x00C1: 0x005D,
    0x00D9: 0x006C,
    0x0101: 0x0088,
    0x010C: 0x00A4,
    0x0112: 0x00B7,
}
_WORD97_FLAGS_OFFSET = 0x0A
_WORD97_TABLE_STREAM_FLAG = 0x0200
_WORD97_CCP_TEXT_INDEX = 3
_WORD97_CLX_PAIR_INDEX = 33
_WORD97_FC_LCB_PAIR_SIZE = 8
_WORD97_COMPRESSED_FLAG = 0x40000000
_WORD97_FC_MASK = 0x3FFFFFFF
_WORD97_PCD_SIZE = 8
_WORD97_CP_SIZE = 4


@dataclass(frozen=True)
class _Word97FibArrayWalk:
    """Where each counted FIB array starts, derived from its declared counts."""

    csw: int
    cslw: int
    cb_rg_fc_lcb: int
    csw_new: int
    n_fib_new: int | None
    fib_rg_w_offset: int
    fib_rg_lw_offset: int
    fib_rg_fc_lcb_offset: int
    fib_rg_csw_new_offset: int


@dataclass(frozen=True)
class _Word97Fib:
    ccp_text: int
    fc_clx: int
    lcb_clx: int
    table_stream: str


@dataclass(frozen=True)
class _WordPiece:
    cp_start: int
    cp_end: int
    byte_offset: int
    compressed: bool


def _word97_uint16(buffer: bytes, offset: int) -> int:
    if offset < 0 or offset + 2 > len(buffer):
        raise MalformedWord97Error("Word97 FIB ends inside a counted array")
    return struct.unpack_from("<H", buffer, offset)[0]


def _word97_uint32(buffer: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(buffer):
        raise MalformedWord97Error("Word97 FIB ends inside a counted value")
    return struct.unpack_from("<I", buffer, offset)[0]


def _walk_word97_fib_arrays(document: bytes) -> _Word97FibArrayWalk:
    """Walk every counted FIB array, through `fibRgFcLcb` to `FibRgCswNew`.

    MS-DOC's "How to read the FIB" requires walking the counted arrays rather
    than trusting a remembered position, so no `rgFcLcb` pair offset is written
    down anywhere in this module. The walk does not stop at `fibRgFcLcb`:
    `FibRgCswNew.nFibNew` — reachable only by stepping over the whole declared
    array — carries the effective version whose pair count `cbRgFcLcb` must
    clear. Stepping over that array is also what proves it lies in the stream.
    """
    csw = _word97_uint16(document, _WORD97_FIB_BASE_SIZE)
    fib_rg_w_offset = _WORD97_FIB_BASE_SIZE + 2
    cslw_offset = fib_rg_w_offset + csw * 2
    cslw = _word97_uint16(document, cslw_offset)
    fib_rg_lw_offset = cslw_offset + 2
    cb_rg_fc_lcb_offset = fib_rg_lw_offset + cslw * 4
    cb_rg_fc_lcb = _word97_uint16(document, cb_rg_fc_lcb_offset)
    fib_rg_fc_lcb_offset = cb_rg_fc_lcb_offset + 2
    csw_new_offset = fib_rg_fc_lcb_offset + cb_rg_fc_lcb * _WORD97_FC_LCB_PAIR_SIZE
    if csw_new_offset > len(document):
        raise MalformedWord97Error("Word97 FIB array table is truncated")
    csw_new = _word97_uint16(document, csw_new_offset)
    fib_rg_csw_new_offset = csw_new_offset + 2
    if fib_rg_csw_new_offset + csw_new * 2 > len(document):
        raise MalformedWord97Error("Word97 FibRgCswNew is truncated")
    n_fib_new = _word97_uint16(document, fib_rg_csw_new_offset) if csw_new else None
    return _Word97FibArrayWalk(
        csw,
        cslw,
        cb_rg_fc_lcb,
        csw_new,
        n_fib_new,
        fib_rg_w_offset,
        fib_rg_lw_offset,
        fib_rg_fc_lcb_offset,
        fib_rg_csw_new_offset,
    )


def _effective_word_n_fib(base_n_fib: int, walk: _Word97FibArrayWalk) -> int:
    """Return the version the document really is, per "Determining the nFib".

    `FibBase.nFib` is a compatibility base value. When `FibRgCswNew` is present
    the effective version is `nFibNew`, so a document written by a later Word
    reports `0x00C1` in the base and its true version here.
    """
    if walk.n_fib_new is None:
        return base_n_fib
    return walk.n_fib_new


def _read_word97_fib(document: bytes) -> _Word97Fib:
    """Validate the FIB and read only `ccpText` and the `Clx` location."""
    if _word97_uint16(document, 0) != _WORD97_FIB_SIGNATURE:
        raise MalformedWord97Error("legacy Word document has no FIB signature")
    base_n_fib = _word97_uint16(document, 2)
    walk = _walk_word97_fib_arrays(document)
    if (walk.csw, walk.cslw) != (_WORD97_CSW, _WORD97_CSLW):
        raise MalformedWord97Error(
            "Word97 FIB declares array counts the format forbids"
        )
    n_fib = _effective_word_n_fib(base_n_fib, walk)
    mandated = _WORD_FIB_MANDATED_CB_RG_FC_LCB.get(n_fib)
    if mandated is None:
        raise UnsupportedWordVersionError(
            f"unsupported binary Word version: nFib=0x{n_fib:04X}"
        )
    if walk.cb_rg_fc_lcb < mandated:
        raise MalformedWord97Error(
            f"Word97 FIB declares cbRgFcLcb=0x{walk.cb_rg_fc_lcb:04X}, fewer "
            f"rgFcLcb pairs than nFib=0x{n_fib:04X} requires"
        )
    ccp_text = _word97_uint32(
        document, walk.fib_rg_lw_offset + _WORD97_CCP_TEXT_INDEX * 4
    )
    pair = walk.fib_rg_fc_lcb_offset + _WORD97_CLX_PAIR_INDEX * _WORD97_FC_LCB_PAIR_SIZE
    flags = _word97_uint16(document, _WORD97_FLAGS_OFFSET)
    return _Word97Fib(
        ccp_text,
        _word97_uint32(document, pair),
        _word97_uint32(document, pair + 4),
        "1Table" if flags & _WORD97_TABLE_STREAM_FLAG else "0Table",
    )


def _read_word97_clx(table: bytes, fib: _Word97Fib) -> tuple[_WordPiece, ...]:
    """Return the main piece table, discarding property groups unread."""
    if fib.lcb_clx <= 0 or fib.fc_clx + fib.lcb_clx > len(table):
        raise MalformedWord97Error("Word97 Clx lies outside its table stream")
    clx = table[fib.fc_clx : fib.fc_clx + fib.lcb_clx]
    cursor = 0
    while cursor < len(clx) and clx[cursor] == 0x01:
        # A Prc. Its payload is skipped by its own declared length: this
        # converter interprets no Prl and reads no paragraph property.
        if cursor + 3 > len(clx):
            raise MalformedWord97Error("Word97 property-group record is truncated")
        size = struct.unpack_from("<h", clx, cursor + 1)[0]
        if size < 0:
            raise MalformedWord97Error("Word97 property-group size is negative")
        cursor += 3 + size
    if cursor + 5 > len(clx) or clx[cursor] != 0x02:
        raise MalformedWord97Error("Word97 Clx has no terminal piece table")
    lcb = struct.unpack_from("<I", clx, cursor + 1)[0]
    body = clx[cursor + 5 : cursor + 5 + lcb]
    stride = _WORD97_CP_SIZE + _WORD97_PCD_SIZE
    if len(body) != lcb or lcb < _WORD97_CP_SIZE or (lcb - _WORD97_CP_SIZE) % stride:
        raise MalformedWord97Error("Word97 piece table has an invalid shape")
    count = (lcb - _WORD97_CP_SIZE) // stride
    positions = [
        struct.unpack_from("<I", body, index * _WORD97_CP_SIZE)[0]
        for index in range(count + 1)
    ]
    base = (count + 1) * _WORD97_CP_SIZE
    pieces: list[_WordPiece] = []
    for index in range(count):
        stored = struct.unpack_from("<I", body, base + index * _WORD97_PCD_SIZE + 2)[0]
        compressed = bool(stored & _WORD97_COMPRESSED_FLAG)
        offset = stored & _WORD97_FC_MASK
        start, end = positions[index], positions[index + 1]
        if end < start:
            raise MalformedWord97Error("Word97 piece positions are not ordered")
        pieces.append(
            _WordPiece(start, end, offset // 2 if compressed else offset, compressed)
        )
    return tuple(pieces)


def _decode_word97_main_text(
    document: bytes, pieces: Sequence[_WordPiece], ccp_text: int
) -> str:
    """Decode only `[0, ccpText)`; footnote and header stories stay excluded."""
    parts: list[str] = []
    for piece in pieces:
        start = piece.cp_start
        end = min(piece.cp_end, ccp_text)
        if end <= start:
            continue
        length = end - start
        width = 1 if piece.compressed else 2
        begin = piece.byte_offset + (start - piece.cp_start) * width
        chunk = document[begin : begin + length * width]
        if len(chunk) != length * width:
            raise MalformedWord97Error("Word97 text piece exceeds its document stream")
        encoding = "cp1252" if piece.compressed else "utf-16-le"
        parts.append(chunk.decode(encoding, errors="replace"))
    return "".join(parts)


def _normalize_word97_text(text: str) -> str:
    """Drop field instructions, then map control marks literally.

    Every `0x0007` becomes a tab and every remaining carriage return becomes a
    newline. Word97 writes the same `0x0007` for a cell mark and a row mark and
    distinguishes them only through `sprmPFTtp`, a paragraph property this
    converter deliberately does not read, so table structure is not
    reconstructed and successive rows are not separated in the mirror. No
    byte-pattern heuristic substitutes for the missing property.
    """
    result: list[str] = []
    instructions: list[bool] = []
    suppressed = 0
    for character in text:
        if character == "\x13":
            instructions.append(True)
            suppressed += 1
        elif character == "\x14":
            if not instructions or not instructions[-1]:
                raise MalformedWord97Error(
                    "Word97 field separator has no open instruction"
                )
            instructions[-1] = False
            suppressed -= 1
        elif character == "\x15":
            if not instructions:
                raise MalformedWord97Error("Word97 field end has no open field")
            if instructions.pop():
                suppressed -= 1
        elif suppressed:
            continue
        elif character == "\x07":
            result.append("\t")
        elif character == "\r":
            result.append("\n")
        else:
            result.append(character)
    if instructions:
        raise MalformedWord97Error("Word97 field is not terminated")
    return "".join(result)


def word97_text(path: Path) -> str:
    """Extract the Word97 main story through its FIB and piece table."""
    try:
        with olefile.OleFileIO(str(path)) as container:
            if not container.exists("WordDocument"):
                raise MalformedWord97Error(
                    "legacy Word document has no WordDocument stream"
                )
            with container.openstream("WordDocument") as stream:
                document = stream.read()
            fib = _read_word97_fib(document)
            if not container.exists(fib.table_stream):
                raise MalformedWord97Error(
                    f"legacy Word document has no {fib.table_stream} stream"
                )
            with container.openstream(fib.table_stream) as stream:
                table = stream.read()
    except (OSError, struct.error) as exc:
        raise MalformedWord97Error(f"malformed legacy Word document: {exc}") from exc
    pieces = _read_word97_clx(table, fib)
    return _normalize_word97_text(
        _decode_word97_main_text(document, pieces, fib.ccp_text)
    )


def office_text(path: Path, media_type: str) -> str:
    """Extract deterministic text for any Office class the engine converts."""
    if media_type == DOCX_MEDIA_TYPE:
        return docx_text(path)
    if media_type == XLSX_MEDIA_TYPE:
        return xlsx_text(path)
    if media_type == XLS_MEDIA_TYPE:
        return xls_text(path)
    if media_type == DOC_MEDIA_TYPE:
        return word97_text(path)
    raise ValueError(f"no deterministic Office text extractor for {media_type}")
