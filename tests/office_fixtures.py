"""Synthetic Office fixtures assembled at test runtime.

Every byte here is generated from literals in this module: OOXML packages are
built with :mod:`zipfile`, OLE2 compound files and BIFF8 workbooks are
assembled with :mod:`struct`, and Word97 FIB/CLX structures are laid out by
hand. No fixture is derived from a real document, and no expected value comes
from a production parser or renderer.

The builders deliberately contain no paragraph-property encoder: the Word97
decoder reads no PAPX, Prl, or FIB pair 13, so a fixture that encoded them
would test machinery the converter must not have.
"""

from __future__ import annotations

import datetime
import struct
import zipfile
from pathlib import Path
from typing import Mapping, Sequence

# --------------------------------------------------------------------------
# OLE2 compound file
# --------------------------------------------------------------------------

_CFB_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_SECTOR_SIZE = 512
_DIRECTORY_ENTRY_SIZE = 128
_FREESECT = 0xFFFFFFFF
_ENDOFCHAIN = 0xFFFFFFFE
_FATSECT = 0xFFFFFFFD
_NOSTREAM = 0xFFFFFFFF
_MINI_STREAM_CUTOFF = 4096


def _sector_count(size: int) -> int:
    return (size + _SECTOR_SIZE - 1) // _SECTOR_SIZE


def _directory_sort_key(name: str) -> tuple[int, str]:
    # The compound-file directory orders siblings by UTF-16 name length first,
    # then by upper-cased name.
    return (len(name), name.upper())


def _directory_entry(
    name: str,
    *,
    entry_type: int,
    left: int,
    right: int,
    child: int,
    start_sector: int,
    size: int,
) -> bytes:
    encoded = name.encode("utf-16-le") + b"\x00\x00"
    if len(encoded) > 64:
        raise ValueError(f"directory entry name is too long: {name}")
    entry = bytearray(_DIRECTORY_ENTRY_SIZE)
    entry[0 : len(encoded)] = encoded
    struct.pack_into("<H", entry, 0x40, len(encoded))
    entry[0x42] = entry_type
    entry[0x43] = 1  # black
    struct.pack_into("<III", entry, 0x44, left, right, child)
    struct.pack_into("<I", entry, 0x74, start_sector)
    struct.pack_into("<Q", entry, 0x78, size)
    return bytes(entry)


def build_ole_compound_file(streams: Mapping[str, bytes]) -> bytes:
    """Assemble a valid OLE2 compound file holding root-level *streams*.

    Every stream is stored in the regular FAT chain, so the fixture needs no
    mini-FAT and no mini stream. Callers therefore pad each stream to at least
    the 4096-byte mini-stream cutoff; the builder refuses anything smaller
    rather than silently producing a file whose layout it does not implement.
    """
    if not streams:
        raise ValueError("a compound file needs at least one stream")
    for name, payload in streams.items():
        if len(payload) < _MINI_STREAM_CUTOFF:
            raise ValueError(
                f"stream {name} must reach the {_MINI_STREAM_CUTOFF}-byte cutoff"
            )

    names = list(streams)
    directory_order = sorted(names, key=_directory_sort_key)
    entry_index = {name: position + 1 for position, name in enumerate(directory_order)}

    entry_count = len(names) + 1
    directory_sectors = _sector_count(entry_count * _DIRECTORY_ENTRY_SIZE)
    stream_sectors = {name: _sector_count(len(streams[name])) for name in names}
    data_sectors = directory_sectors + sum(stream_sectors.values())

    fat_sectors = 1
    while fat_sectors * (_SECTOR_SIZE // 4) < data_sectors + fat_sectors:
        fat_sectors += 1

    fat = [_FREESECT] * (fat_sectors * (_SECTOR_SIZE // 4))
    for index in range(fat_sectors):
        fat[index] = _FATSECT

    def chain(first: int, count: int) -> None:
        for offset in range(count):
            sector = first + offset
            fat[sector] = _ENDOFCHAIN if offset == count - 1 else sector + 1

    directory_first = fat_sectors
    chain(directory_first, directory_sectors)

    stream_first: dict[str, int] = {}
    cursor = directory_first + directory_sectors
    for name in names:
        stream_first[name] = cursor
        chain(cursor, stream_sectors[name])
        cursor += stream_sectors[name]

    entries = [
        _directory_entry(
            "Root Entry",
            entry_type=5,
            left=_NOSTREAM,
            right=_NOSTREAM,
            child=entry_index[directory_order[0]],
            start_sector=_ENDOFCHAIN,
            size=0,
        )
    ]
    ordered_entries: list[bytes] = [b""] * len(names)
    for position, name in enumerate(directory_order):
        following = directory_order[position + 1] if position + 1 < len(directory_order) else None
        ordered_entries[position] = _directory_entry(
            name,
            entry_type=2,
            left=_NOSTREAM,
            right=_NOSTREAM if following is None else entry_index[following],
            child=_NOSTREAM,
            start_sector=stream_first[name],
            size=len(streams[name]),
        )
    entries.extend(ordered_entries)

    directory = b"".join(entries)
    directory += b"\x00" * (directory_sectors * _SECTOR_SIZE - len(directory))

    header = bytearray(_SECTOR_SIZE)
    header[0:8] = _CFB_SIGNATURE
    struct.pack_into("<HH", header, 0x18, 0x003E, 0x0003)
    struct.pack_into("<H", header, 0x1C, 0xFFFE)
    struct.pack_into("<HH", header, 0x1E, 9, 6)
    struct.pack_into("<I", header, 0x2C, fat_sectors)
    struct.pack_into("<I", header, 0x30, directory_first)
    struct.pack_into("<I", header, 0x38, _MINI_STREAM_CUTOFF)
    struct.pack_into("<I", header, 0x3C, _ENDOFCHAIN)
    struct.pack_into("<I", header, 0x40, 0)
    struct.pack_into("<I", header, 0x44, _ENDOFCHAIN)
    struct.pack_into("<I", header, 0x48, 0)
    for index in range(109):
        value = index if index < fat_sectors else _FREESECT
        struct.pack_into("<I", header, 0x4C + index * 4, value)

    body = bytearray()
    for value in fat:
        body += struct.pack("<I", value)
    body += directory
    for name in names:
        payload = streams[name]
        body += payload
        body += b"\x00" * (stream_sectors[name] * _SECTOR_SIZE - len(payload))
    return bytes(header) + bytes(body)


def _pad_stream(payload: bytes) -> bytes:
    if len(payload) >= _MINI_STREAM_CUTOFF:
        return payload
    return payload + b"\x00" * (_MINI_STREAM_CUTOFF - len(payload))


# --------------------------------------------------------------------------
# Shared spreadsheet content
# --------------------------------------------------------------------------

_EXCEL_EPOCH = datetime.date(1899, 12, 30)
LEDGER_SHEET_NAME = "Ledger"
EMPTY_SHEET_NAME = "Empty"
LEDGER_MERGED_RANGE = "A7:C7"
POSTED_DATE = datetime.date(2026, 1, 2)
POSTED_DATETIME = datetime.datetime(2026, 2, 3, 6, 0, 0)
SHARED_STRINGS = (
    "Item",
    "Amount",
    "Posted",
    "Flag",
    "Opening, balance",
    "Line\nnote",
    "Total",
    "Summary note",
)


def _date_serial(value: datetime.date) -> int:
    return (value - _EXCEL_EPOCH).days


def _datetime_serial(value: datetime.datetime) -> float:
    day = _date_serial(value.date())
    seconds = value.hour * 3600 + value.minute * 60 + value.second
    return day + seconds / 86400.0


def _column_letter(index: int) -> str:
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


# --------------------------------------------------------------------------
# OOXML spreadsheet packages
# --------------------------------------------------------------------------

_SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_OOXML_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"

XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def _content_types(*, shared_strings: bool, sheet_count: int = 2) -> str:
    overrides = [
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
    ]
    overrides.extend(
        f'<Override PartName="/xl/worksheets/sheet{number}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.'
        'spreadsheetml.worksheet+xml"/>'
        for number in range(1, sheet_count + 1)
    )
    if shared_strings:
        overrides.append(
            '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Types xmlns="{_OOXML_TYPES}">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-'
        'package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        + "".join(overrides)
        + "</Types>"
    )


def _package_rels() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_PACKAGE_REL_NS}">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )


def _workbook_xml(names: Sequence[str] = (LEDGER_SHEET_NAME, EMPTY_SHEET_NAME)) -> str:
    sheets = "".join(
        f'<sheet name="{name}" sheetId="{number}" r:id="rId{number}"/>'
        for number, name in enumerate(names, 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{_SHEET_NS}" xmlns:r="{_REL_NS}">'
        f"<sheets>{sheets}</sheets></workbook>"
    )


def _workbook_rels(*, shared_strings: bool, sheet_count: int = 2) -> str:
    relationships = [
        f'<Relationship Id="rId{number}" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{number}.xml"/>'
        for number in range(1, sheet_count + 1)
    ]
    relationships.append(
        f'<Relationship Id="rId{sheet_count + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/styles" Target="styles.xml"/>'
    )
    if shared_strings:
        relationships.append(
            f'<Relationship Id="rId{sheet_count + 2}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/sharedStrings" Target="sharedStrings.xml"/>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_PACKAGE_REL_NS}">'
        + "".join(relationships)
        + "</Relationships>"
    )


def _styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<styleSheet xmlns="{_SHEET_NS}">'
        '<numFmts count="2">'
        '<numFmt numFmtId="164" formatCode="yyyy\\-mm\\-dd"/>'
        '<numFmt numFmtId="165" formatCode="yyyy\\-mm\\-dd\\ hh:mm:ss"/>'
        "</numFmts>"
        '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
        "<borders count=\"1\"><border/></borders>"
        '<cellStyleXfs count="1">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
        "</cellStyleXfs>"
        '<cellXfs count="4">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0"'
        ' applyNumberFormat="1"/>'
        '<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0"'
        ' applyNumberFormat="1"/>'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        "</cellXfs>"
        '<cellStyles count="1">'
        '<cellStyle name="Normal" xfId="0" builtinId="0"/>'
        "</cellStyles>"
        "</styleSheet>"
    )


def _shared_strings_xml() -> str:
    items = "".join(
        f"<si><t>{value.replace(chr(10), '&#10;')}</t></si>" for value in SHARED_STRINGS
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<sst xmlns="{_SHEET_NS}" count="{len(SHARED_STRINGS)}"'
        f' uniqueCount="{len(SHARED_STRINGS)}">{items}</sst>'
    )


def _string_cell(reference: str, value: str, *, shared: bool) -> str:
    if shared:
        return f'<c r="{reference}" t="s"><v>{SHARED_STRINGS.index(value)}</v></c>'
    escaped = value.replace(chr(10), "&#10;")
    return f'<c r="{reference}" t="inlineStr"><is><t>{escaped}</t></is></c>'


def _ledger_sheet_xml(*, shared: bool) -> str:
    date_serial = _date_serial(POSTED_DATE)
    datetime_serial = _datetime_serial(POSTED_DATETIME)
    rows = [
        (
            1,
            "".join(
                _string_cell(f"{_column_letter(index)}1", value, shared=shared)
                for index, value in enumerate(("Item", "Amount", "Posted", "Flag"), 1)
            ),
        ),
        (
            2,
            _string_cell("A2", "Opening, balance", shared=shared)
            + '<c r="B2"><v>1500</v></c>'
            + f'<c r="C2" s="1"><v>{date_serial}</v></c>'
            + '<c r="D2" t="b"><v>1</v></c>',
        ),
        (
            4,
            _string_cell("A4", "Line\nnote", shared=shared)
            + '<c r="B4"><v>12.5</v></c>'
            + f'<c r="C4" s="2"><v>{datetime_serial!r}</v></c>'
            + '<c r="D4" t="b"><v>0</v></c>',
        ),
        (
            5,
            _string_cell("A5", "Total", shared=shared)
            + "<c r=\"B5\"><f>SUM(B2:B4)</f><v>1512.5</v></c>"
            + '<c r="D5" t="e"><v>#DIV/0!</v></c>',
        ),
        (6, '<c r="E6" s="3"/>'),
        (7, _string_cell("A7", "Summary note", shared=shared)),
    ]
    body = "".join(f'<row r="{number}">{cells}</row>' for number, cells in rows)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{_SHEET_NS}" xmlns:r="{_REL_NS}">'
        '<dimension ref="A1:E7"/>'
        f"<sheetData>{body}</sheetData>"
        f'<mergeCells count="1"><mergeCell ref="{LEDGER_MERGED_RANGE}"/></mergeCells>'
        "</worksheet>"
    )


def _empty_sheet_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{_SHEET_NS}" xmlns:r="{_REL_NS}">'
        '<dimension ref="A1"/><sheetData/></worksheet>'
    )


def _write_package(target: Path, members: Sequence[tuple[str, str]]) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members:
            archive.writestr(name, payload)
    return target


def build_xlsx_fixture(target: Path) -> Path:
    """Write a two-sheet OOXML workbook exercising every value convention."""
    return _write_package(
        target,
        (
            ("[Content_Types].xml", _content_types(shared_strings=True)),
            ("_rels/.rels", _package_rels()),
            ("xl/workbook.xml", _workbook_xml()),
            ("xl/_rels/workbook.xml.rels", _workbook_rels(shared_strings=True)),
            ("xl/styles.xml", _styles_xml()),
            ("xl/sharedStrings.xml", _shared_strings_xml()),
            ("xl/worksheets/sheet1.xml", _ledger_sheet_xml(shared=True)),
            ("xl/worksheets/sheet2.xml", _empty_sheet_xml()),
        ),
    )


def build_xlsx_without_shared_strings(target: Path) -> Path:
    """Write the same workbook using inline strings and no shared-string part."""
    return _write_package(
        target,
        (
            ("[Content_Types].xml", _content_types(shared_strings=False)),
            ("_rels/.rels", _package_rels()),
            ("xl/workbook.xml", _workbook_xml()),
            ("xl/_rels/workbook.xml.rels", _workbook_rels(shared_strings=False)),
            ("xl/styles.xml", _styles_xml()),
            ("xl/worksheets/sheet1.xml", _ledger_sheet_xml(shared=False)),
            ("xl/worksheets/sheet2.xml", _empty_sheet_xml()),
        ),
    )


def build_single_value_xlsx(target: Path, value: str) -> Path:
    """Write a one-sheet, one-cell workbook carrying exactly *value*."""
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{_SHEET_NS}" xmlns:r="{_REL_NS}">'
        '<dimension ref="A1"/><sheetData>'
        f'<row r="1"><c r="A1" t="inlineStr"><is><t>{value}</t></is></c></row>'
        "</sheetData></worksheet>"
    )
    return _write_package(
        target,
        (
            ("[Content_Types].xml", _content_types(shared_strings=False, sheet_count=1)),
            ("_rels/.rels", _package_rels()),
            ("xl/workbook.xml", _workbook_xml((LEDGER_SHEET_NAME,))),
            (
                "xl/_rels/workbook.xml.rels",
                _workbook_rels(shared_strings=False, sheet_count=1),
            ),
            ("xl/styles.xml", _styles_xml()),
            ("xl/worksheets/sheet1.xml", sheet),
        ),
    )


def build_zip_without_ooxml_parts(target: Path) -> Path:
    """Write a well-formed ZIP that is not an OOXML package."""
    return _write_package(target, (("notes.txt", "plain archive member"),))


def build_ooxml_package_missing_workbook(target: Path) -> Path:
    """Write an OOXML-declaring package whose required workbook part is absent."""
    return _write_package(
        target,
        (
            ("[Content_Types].xml", _content_types(shared_strings=False)),
            ("_rels/.rels", _package_rels()),
        ),
    )


def build_xlsx_with_corrupt_workbook_part(target: Path) -> Path:
    """Write a package that still classifies as XLSX but whose workbook part
    fails its own CRC, so a corruption precheck must reject it."""
    _write_package(
        target,
        (
            ("[Content_Types].xml", _content_types(shared_strings=False, sheet_count=1)),
            ("_rels/.rels", _package_rels()),
            ("xl/workbook.xml", _workbook_xml((LEDGER_SHEET_NAME,))),
            (
                "xl/_rels/workbook.xml.rels",
                _workbook_rels(shared_strings=False, sheet_count=1),
            ),
            ("xl/styles.xml", _styles_xml()),
            ("xl/worksheets/sheet1.xml", _empty_sheet_xml()),
        ),
    )
    with zipfile.ZipFile(target) as archive:
        info = archive.getinfo("xl/workbook.xml")
        header_offset = info.header_offset
    payload = bytearray(target.read_bytes())
    name_length, extra_length = struct.unpack_from("<HH", payload, header_offset + 26)
    data_offset = header_offset + 30 + name_length + extra_length
    payload[data_offset] ^= 0xFF
    target.write_bytes(bytes(payload))
    return target


def build_malformed_xlsx_fixture(target: Path) -> Path:
    """Write bytes that claim to be a spreadsheet but are not a readable ZIP."""
    target.parent.mkdir(parents=True, exist_ok=True)
    package = bytearray(build_xlsx_fixture(target).read_bytes())
    target.write_bytes(bytes(package[: len(package) // 2]))
    return target


# --------------------------------------------------------------------------
# Legacy BIFF8 workbooks
# --------------------------------------------------------------------------

XLS_MEDIA_TYPE = "application/vnd.ms-excel"

_BIFF_BOF = 0x0809
_BIFF_EOF = 0x000A
_BIFF_CODEPAGE = 0x0042
_BIFF_DATEMODE = 0x0022
_BIFF_FILEPASS = 0x002F
_BIFF_FONT = 0x0031
_BIFF_FORMAT = 0x041E
_BIFF_XF = 0x00E0
_BIFF_BOUNDSHEET = 0x0085
_BIFF_SST = 0x00FC
_BIFF_DIMENSIONS = 0x0200
_BIFF_BLANK = 0x0201
_BIFF_NUMBER = 0x0203
_BIFF_BOOLERR = 0x0205
_BIFF_FORMULA = 0x0006
_BIFF_LABELSST = 0x00FD
_BIFF_MERGEDCELLS = 0x00E5

_XF_GENERAL = 1
_XF_DATE = 2
_XF_DATETIME = 3
_XF_BLANK = 4
_DATE_FORMAT_INDEX = 164
_DATETIME_FORMAT_INDEX = 165


def _record(code: int, payload: bytes) -> bytes:
    return struct.pack("<HH", code, len(payload)) + payload


def _biff_bof(substream: int) -> bytes:
    return _record(
        _BIFF_BOF,
        struct.pack("<HHHHII", 0x0600, substream, 0x0DBB, 0x07CC, 0x00000041, 0x00000006),
    )


def _short_unicode(value: str) -> bytes:
    encoded = value.encode("utf-16-le")
    return struct.pack("<BB", len(value), 0x01) + encoded


def _long_unicode(value: str) -> bytes:
    encoded = value.encode("utf-16-le")
    return struct.pack("<HB", len(value), 0x01) + encoded


def _biff_font() -> bytes:
    payload = struct.pack(
        "<HHHHHBBBB", 220, 0x0000, 0x7FFF, 400, 0, 0, 0, 0, 0
    ) + _short_unicode("Calibri")
    return _record(_BIFF_FONT, payload)


def _biff_format(index: int, code: str) -> bytes:
    return _record(_BIFF_FORMAT, struct.pack("<H", index) + _long_unicode(code))


def _biff_xf(*, format_index: int, style: bool) -> bytes:
    type_parent = (0x0004 | (0x0FFF << 4)) if style else 0x0000
    return _record(
        _BIFF_XF,
        struct.pack(
            "<HHHBBBBIiH",
            0,  # font index
            format_index,
            type_parent,
            0x20,  # general horizontal alignment, bottom vertical
            0,  # rotation
            0,
            0,
            0x00000000,
            0x00000000,
            0x20C0,  # default foreground/background colour indexes
        ),
    )


def _biff_sst(values: Sequence[str]) -> bytes:
    payload = struct.pack("<ii", len(values), len(values))
    for value in values:
        payload += struct.pack("<HB", len(value), 0x01) + value.encode("utf-16-le")
    return _record(_BIFF_SST, payload)


def _biff_boundsheet(name: str, position: int) -> bytes:
    return _record(
        _BIFF_BOUNDSHEET,
        struct.pack("<IBB", position, 0x00, 0x00) + _short_unicode(name),
    )


def _biff_dimensions(rows: int, columns: int) -> bytes:
    return _record(
        _BIFF_DIMENSIONS, struct.pack("<IIHHH", 0, rows, 0, columns, 0)
    )


def _biff_labelsst(row: int, column: int, index: int) -> bytes:
    return _record(
        _BIFF_LABELSST, struct.pack("<HHHI", row, column, _XF_GENERAL, index)
    )


def _biff_number(row: int, column: int, value: float, xf: int) -> bytes:
    return _record(_BIFF_NUMBER, struct.pack("<HHHd", row, column, xf, value))


def _biff_boolean(row: int, column: int, value: bool) -> bytes:
    return _record(
        _BIFF_BOOLERR,
        struct.pack("<HHHBB", row, column, _XF_GENERAL, 1 if value else 0, 0),
    )


def _biff_error(row: int, column: int, code: int) -> bytes:
    return _record(
        _BIFF_BOOLERR, struct.pack("<HHHBB", row, column, _XF_GENERAL, code, 1)
    )


def _biff_blank(row: int, column: int) -> bytes:
    return _record(_BIFF_BLANK, struct.pack("<HHH", row, column, _XF_BLANK))


def _biff_cached_formula(row: int, column: int, value: float) -> bytes:
    tokens = struct.pack("<Bd", 0x1F, value)  # tNum
    payload = (
        struct.pack("<HHH", row, column, _XF_GENERAL)
        + struct.pack("<d", value)
        + struct.pack("<HIH", 0x0000, 0x00000000, len(tokens))
        + tokens
    )
    return _record(_BIFF_FORMULA, payload)


def _biff_merged_cells(ranges: Sequence[tuple[int, int, int, int]]) -> bytes:
    payload = struct.pack("<H", len(ranges))
    for first_row, last_row, first_column, last_column in ranges:
        payload += struct.pack("<HHHH", first_row, last_row, first_column, last_column)
    return _record(_BIFF_MERGEDCELLS, payload)


def _ledger_substream() -> bytes:
    date_serial = float(_date_serial(POSTED_DATE))
    datetime_serial = _datetime_serial(POSTED_DATETIME)
    index = {value: position for position, value in enumerate(SHARED_STRINGS)}
    return b"".join(
        (
            _biff_bof(0x0010),
            _biff_dimensions(7, 5),
            _biff_labelsst(0, 0, index["Item"]),
            _biff_labelsst(0, 1, index["Amount"]),
            _biff_labelsst(0, 2, index["Posted"]),
            _biff_labelsst(0, 3, index["Flag"]),
            _biff_labelsst(1, 0, index["Opening, balance"]),
            _biff_number(1, 1, 1500.0, _XF_GENERAL),
            _biff_number(1, 2, date_serial, _XF_DATE),
            _biff_boolean(1, 3, True),
            _biff_labelsst(3, 0, index["Line\nnote"]),
            _biff_number(3, 1, 12.5, _XF_GENERAL),
            _biff_number(3, 2, datetime_serial, _XF_DATETIME),
            _biff_boolean(3, 3, False),
            _biff_labelsst(4, 0, index["Total"]),
            _biff_cached_formula(4, 1, 1512.5),
            _biff_error(4, 3, 0x07),
            _biff_blank(5, 4),
            _biff_labelsst(6, 0, index["Summary note"]),
            _biff_merged_cells(((6, 6, 0, 2),)),
            _record(_BIFF_EOF, b""),
        )
    )


def _empty_substream() -> bytes:
    return b"".join(
        (_biff_bof(0x0010), _biff_dimensions(0, 0), _record(_BIFF_EOF, b""))
    )


def _biff_workbook(substreams: Sequence[tuple[str, bytes]]) -> bytes:
    prefix = b"".join(
        (
            _biff_bof(0x0005),
            _record(_BIFF_CODEPAGE, struct.pack("<H", 1200)),
            _record(_BIFF_DATEMODE, struct.pack("<H", 0)),
            _biff_font(),
            _biff_format(_DATE_FORMAT_INDEX, "yyyy\\-mm\\-dd"),
            _biff_format(_DATETIME_FORMAT_INDEX, "yyyy\\-mm\\-dd\\ hh:mm:ss"),
            _biff_xf(format_index=0, style=True),
            _biff_xf(format_index=0, style=False),
            _biff_xf(format_index=_DATE_FORMAT_INDEX, style=False),
            _biff_xf(format_index=_DATETIME_FORMAT_INDEX, style=False),
            _biff_xf(format_index=0, style=False),
        )
    )
    suffix = _biff_sst(SHARED_STRINGS) + _record(_BIFF_EOF, b"")
    boundsheet_size = sum(
        len(_biff_boundsheet(name, 0)) for name, _payload in substreams
    )
    globals_size = len(prefix) + boundsheet_size + len(suffix)
    positions: list[int] = []
    cursor = globals_size
    for _name, payload in substreams:
        positions.append(cursor)
        cursor += len(payload)
    boundsheets = b"".join(
        _biff_boundsheet(name, position)
        for (name, _payload), position in zip(substreams, positions)
    )
    return prefix + boundsheets + suffix + b"".join(
        payload for _name, payload in substreams
    )


def build_xls_fixture(target: Path) -> Path:
    """Write a legacy BIFF8 workbook mirroring the OOXML fixture's content."""
    workbook = _biff_workbook(
        (
            (LEDGER_SHEET_NAME, _ledger_substream()),
            (EMPTY_SHEET_NAME, _empty_substream()),
        )
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(
        build_ole_compound_file({"Workbook": _pad_stream(workbook)})
    )
    return target


def build_encrypted_xls_fixture(target: Path) -> Path:
    """Write a BIFF8 workbook whose globals declare standard encryption."""
    workbook = b"".join(
        (
            _biff_bof(0x0005),
            _record(_BIFF_FILEPASS, struct.pack("<HH", 0x0001, 0x0001) + b"\x00" * 48),
            _record(_BIFF_EOF, b""),
        )
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(
        build_ole_compound_file({"Workbook": _pad_stream(workbook)})
    )
    return target


def build_malformed_xls_fixture(target: Path) -> Path:
    """Write an OLE2 file whose Workbook stream holds no readable BIFF record."""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(
        build_ole_compound_file({"Workbook": _pad_stream(b"not a BIFF stream")})
    )
    return target


# --------------------------------------------------------------------------
# Word 97 binary documents
# --------------------------------------------------------------------------

DOC_MEDIA_TYPE = "application/msword"

WORD97_N_FIB = 0x00C1
WORD97_CSW = 0x000E
WORD97_CSLW = 0x0016
WORD97_CB_RG_FC_LCB = 0x005D
#: The ``(cbRgFcLcb, cswNew)`` MS-DOC mandates for each effective nFib. A later
#: Word writes ``0x00C1`` into ``FibBase.nFib`` and its real version into
#: ``FibRgCswNew.nFibNew``, so these are the counts a *conforming* writer emits
#: for the version ``nFibNew`` declares. Non-conforming writers exist; see
#: ``WORD_OBSERVED_INCONSISTENT_VARIANT``.
WORD_FIB_VARIANTS: dict[int, tuple[int, int]] = {
    0x00C1: (0x005D, 0x0000),
    0x00D9: (0x006C, 0x0002),
    0x0101: (0x0088, 0x0002),
    0x010C: (0x00A4, 0x0002),
    0x0112: (0x00B7, 0x0005),
}
#: ``(nFibNew, cbRgFcLcb, cswNew)`` of a real, readable document shape that no
#: conforming writer produces: a Word 2002 version declaring the Word 2007
#: array size and a ``FibRgCswNew`` of seven values, a shape MS-DOC gives for
#: no version at all. The array still clears pair 33 and the piece table
#: decodes, so the reader accepts it.
WORD_OBSERVED_INCONSISTENT_VARIANT = (0x010C, 0x00B7, 0x0007)
_FIB_BASE_SIZE = 32
_CCP_TEXT_INDEX = 3
_CLX_PAIR_INDEX = 33
_PARAGRAPH_PROPERTY_PAIR_INDEX = 13
_WHICH_TABLE_STREAM_FLAG = 0x0200

WORD97_COMPRESSED_PIECE = "Memo to counsel\rCell A\x07Cell B\x07"
WORD97_UNICODE_PIECE = (
    "Amount \x13 REF outer \x13 INNER \x14 inner-result \x15 \x14 42 \x15 due\r"
)
WORD97_FOOTNOTE_PIECE = "Footnote text that is not main-story content\r"
#: Both 0x0007 marks become tabs and no row newline is invented; the field
#: instruction (including its nested field) is dropped and the result kept.
WORD97_EXPECTED_MAIN_TEXT = (
    "Memo to counsel\nCell A\tCell B\tAmount  42  due\n"
)

#: Every piece body sits above the longest header a mandated ``cbRgFcLcb``
#: produces (0x00B7 pairs ends at 1630) so no fixture's text overwrites its
#: own FIB.
_PIECE_ONE_OFFSET = 2048
_PIECE_TWO_OFFSET = 2560
_PIECE_THREE_OFFSET = 3072
_CLX_OFFSET = 256


def build_noncanonical_fib_walk_buffer(
    csw: int,
    cslw: int,
    cb_rg_fc_lcb: int,
    *,
    csw_new: int = 0,
    n_fib_new: int | None = None,
) -> bytes:
    """Build a counted-array buffer that is *not* a valid Word97 document.

    It exists only to exercise the FIB count walker's arithmetic across sizes
    the Word97 profile forbids, so the walker is proved to derive offsets
    rather than to reproduce a remembered constant.
    """
    buffer = bytearray(_FIB_BASE_SIZE)
    struct.pack_into("<H", buffer, 0, 0xA5EC)
    struct.pack_into("<H", buffer, 2, WORD97_N_FIB)
    buffer += struct.pack("<H", csw) + b"\x11" * (csw * 2)
    buffer += struct.pack("<H", cslw) + b"\x22" * (cslw * 4)
    buffer += struct.pack("<H", cb_rg_fc_lcb) + b"\x33" * (cb_rg_fc_lcb * 8)
    buffer += struct.pack("<H", csw_new) + _fib_rg_csw_new(csw_new, n_fib_new)
    return bytes(buffer)


def _fib_rg_csw_new(csw_new: int, n_fib_new: int | None) -> bytes:
    """Encode ``FibRgCswNew``: ``nFibNew`` followed by its version's payload."""
    if csw_new <= 0:
        return b""
    payload = struct.pack("<H", n_fib_new or 0) + b"\x00" * ((csw_new - 1) * 2)
    return payload[: csw_new * 2]


def _word97_clx(pieces: Sequence[tuple[int, int, int, bool]]) -> bytes:
    """Assemble a Clx: one property group to skip, then the piece table."""
    property_group = b"\x01" + struct.pack("<h", 6) + b"\xAA" * 6
    character_positions = [pieces[0][0]] + [piece[1] for piece in pieces]
    plc = b"".join(struct.pack("<I", value) for value in character_positions)
    for _start, _end, offset, compressed in pieces:
        stored = (offset * 2) | 0x40000000 if compressed else offset
        plc += struct.pack("<HIH", 0, stored, 0)
    return property_group + b"\x02" + struct.pack("<I", len(plc)) + plc


def build_word97_fixture(
    target: Path,
    *,
    n_fib: int = WORD97_N_FIB,
    n_fib_new: int | None = None,
    csw: int = WORD97_CSW,
    cslw: int = WORD97_CSLW,
    cb_rg_fc_lcb: int | None = None,
    declared_cb_rg_fc_lcb: int | None = None,
    csw_new: int | None = None,
    poison_paragraph_property_pair: bool = False,
    truncate_clx: bool = False,
    omit_table_stream: bool = False,
    main_text: str = WORD97_COMPRESSED_PIECE,
) -> Path:
    """Write a Word97 compound document with a spec-shaped FIB and piece table.

    ``n_fib`` is ``FibBase.nFib``, the compatibility base. Passing ``n_fib_new``
    additionally writes a ``FibRgCswNew``, which makes that value the effective
    version. ``cb_rg_fc_lcb`` and ``csw_new`` default to the counts MS-DOC
    mandates for the effective version, so the fixture is spec-valid unless a
    caller deliberately changes one of them. ``declared_cb_rg_fc_lcb`` writes a
    count larger than the array that follows it, which is how a document claims
    an array that runs past its own stream.
    """
    effective_n_fib = n_fib if n_fib_new is None else n_fib_new
    # An unrecognised version has no mandated pair; give it the Word97 array
    # and, when it is declared through nFibNew, the smallest FibRgCswNew that
    # actually carries that value.
    mandated_cb, mandated_csw_new = WORD_FIB_VARIANTS.get(
        effective_n_fib, (WORD97_CB_RG_FC_LCB, 0x0002)
    )
    if cb_rg_fc_lcb is None:
        cb_rg_fc_lcb = mandated_cb
    if csw_new is None:
        csw_new = mandated_csw_new if n_fib_new is not None else 0x0000
    compressed = main_text.encode("cp1252")
    unicode_piece = WORD97_UNICODE_PIECE.encode("utf-16-le")
    footnote = WORD97_FOOTNOTE_PIECE.encode("cp1252")

    first = (0, len(main_text), _PIECE_ONE_OFFSET, True)
    second = (
        first[1],
        first[1] + len(WORD97_UNICODE_PIECE),
        _PIECE_TWO_OFFSET,
        False,
    )
    third = (
        second[1],
        second[1] + len(WORD97_FOOTNOTE_PIECE),
        _PIECE_THREE_OFFSET,
        True,
    )
    ccp_text = second[1]

    clx = _word97_clx((first, second, third))
    if truncate_clx:
        clx = clx[: len(clx) // 2]

    fib = bytearray(_FIB_BASE_SIZE)
    struct.pack_into("<H", fib, 0, 0xA5EC)
    struct.pack_into("<H", fib, 2, n_fib)
    struct.pack_into("<H", fib, 0x0A, _WHICH_TABLE_STREAM_FLAG)
    struct.pack_into("<H", fib, 0x0C, 0x00BF)

    fib_rg_w = bytearray(csw * 2)
    fib_rg_lw = bytearray(cslw * 4)
    if cslw > _CCP_TEXT_INDEX:
        struct.pack_into("<I", fib_rg_lw, _CCP_TEXT_INDEX * 4, ccp_text)
    if cslw > _CCP_TEXT_INDEX + 1:
        struct.pack_into(
            "<I", fib_rg_lw, (_CCP_TEXT_INDEX + 1) * 4, len(WORD97_FOOTNOTE_PIECE)
        )
    fib_rg_fc_lcb = bytearray(cb_rg_fc_lcb * 8)
    if cb_rg_fc_lcb > _CLX_PAIR_INDEX:
        struct.pack_into(
            "<II", fib_rg_fc_lcb, _CLX_PAIR_INDEX * 8, _CLX_OFFSET, len(clx)
        )
    if poison_paragraph_property_pair and cb_rg_fc_lcb > _PARAGRAPH_PROPERTY_PAIR_INDEX:
        struct.pack_into(
            "<II",
            fib_rg_fc_lcb,
            _PARAGRAPH_PROPERTY_PAIR_INDEX * 8,
            0xFFFFFFF0,
            0xFFFFFFF0,
        )

    header = (
        bytes(fib)
        + struct.pack("<H", csw)
        + bytes(fib_rg_w)
        + struct.pack("<H", cslw)
        + bytes(fib_rg_lw)
        + struct.pack(
            "<H",
            cb_rg_fc_lcb if declared_cb_rg_fc_lcb is None else declared_cb_rg_fc_lcb,
        )
        + bytes(fib_rg_fc_lcb)
        + struct.pack("<H", csw_new)
        + _fib_rg_csw_new(csw_new, n_fib_new)
    )

    document = bytearray(_pad_stream(header))
    document[_PIECE_ONE_OFFSET : _PIECE_ONE_OFFSET + len(compressed)] = compressed
    document[_PIECE_TWO_OFFSET : _PIECE_TWO_OFFSET + len(unicode_piece)] = unicode_piece
    document[_PIECE_THREE_OFFSET : _PIECE_THREE_OFFSET + len(footnote)] = footnote
    if cslw >= 1:
        struct.pack_into("<I", document, len(fib) + 2 + len(fib_rg_w) + 2, len(document))

    table = bytearray(_pad_stream(b""))
    table[_CLX_OFFSET : _CLX_OFFSET + len(clx)] = clx

    streams = {"WordDocument": bytes(document)}
    if not omit_table_stream:
        streams["1Table"] = bytes(table)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(build_ole_compound_file(streams))
    return target


def build_truncated_word97_fixture(target: Path) -> Path:
    """Write a Word97 document whose counted FIB arrays run past the stream."""
    header = bytearray(_FIB_BASE_SIZE)
    struct.pack_into("<H", header, 0, 0xA5EC)
    struct.pack_into("<H", header, 2, WORD97_N_FIB)
    header += struct.pack("<H", 0x7FFF)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(
        build_ole_compound_file({"WordDocument": _pad_stream(bytes(header))})
    )
    return target


def build_non_ole_doc_fixture(target: Path) -> Path:
    """Write bytes recorded as legacy Word that are not a compound file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"plain text pretending to be a legacy Word document\n")
    return target
