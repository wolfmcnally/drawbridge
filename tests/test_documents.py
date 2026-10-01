from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import office_fixtures as office  # noqa: E402

from drawbridge import (  # noqa: E402
    ConversionOptions,
    convert_file,
    extract_text,
    parse_mirror_header,
    render_mirror,
    sections,
    sniff_media_type,
    supported,
)
from drawbridge.errors import DrawbridgeError, blocked_reason  # noqa: E402
from drawbridge.office import (  # noqa: E402
    DOC_MEDIA_TYPE,
    DOCX_MEDIA_TYPE,
    XLS_MEDIA_TYPE,
    XLSX_MEDIA_TYPE,
    EncryptedXlsError,
    MalformedDocxError,
)

EXPECTED_SPREADSHEET_BODY = (
    "## Sheet: Ledger  (7 rows × 4 cols, 2 empty rows elided)\n"
    "\n"
    "Merged cells (anchor retains value): A7:C7\n"
    "\n"
    "```csv\n"
    "row,Item,Amount,Posted,Flag\n"
    '2,"Opening, balance",1500,2026-01-02T00:00:00,TRUE\n'
    '4,"Line\nnote",12.5,2026-02-03T06:00:00,FALSE\n'
    "5,Total,1512.5,,#DIV/0!\n"
    "7,Summary note,,,\n"
    "```\n"
    "\n"
    "## Sheet: Empty  (0 rows × 0 cols)\n"
    "\n"
    "```csv\n"
    "row\n"
    "```"
)
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def build_docx(target: Path, paragraphs: list[str]) -> Path:
    body = "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'/>")
        archive.writestr("word/document.xml", f"<w:document xmlns:w='{_W}'><w:body>{body}</w:body></w:document>")
    return target


def round_trip(result, path: Path):
    """Every mirror must survive its own parser, hash the input, and leave the input untouched."""
    header, body = parse_mirror_header(render_mirror(result.mirror))
    assert header["content_hash"] == "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    assert header["format"] == "drawbridge.mirror.v1"
    assert header["media_type"] == result.media_type
    return header, body


@pytest.mark.parametrize(
    ("builder", "name", "media_type"),
    [
        (office.build_xlsx_fixture, "ledger", XLSX_MEDIA_TYPE),
        (office.build_xls_fixture, "ledger-old", XLS_MEDIA_TYPE),
        (office.build_word97_fixture, "memo", DOC_MEDIA_TYPE),
    ],
)
def test_office_types_are_recognised_by_content_not_name(tmp_path, builder, name, media_type):
    path = builder(tmp_path / name)  # no extension at all
    assert sniff_media_type(path)[0] == media_type
    assert supported(media_type)


def test_docx_is_recognised_and_converted(tmp_path):
    path = build_docx(tmp_path / "letter", ["First paragraph.", "Second paragraph."])
    before = path.read_bytes()
    result = convert_file(path, options=ConversionOptions(title="A Letter"))
    header, body = round_trip(result, path)
    assert (result.media_type, header["unit"], result.method) == (DOCX_MEDIA_TYPE, "document", "docx-xml-extract")
    assert body == "# A Letter\n\nFirst paragraph.\n\nSecond paragraph.\n"
    assert path.read_bytes() == before


@pytest.mark.parametrize("builder", [office.build_xlsx_fixture, office.build_xls_fixture])
def test_both_spreadsheet_formats_render_the_same_golden_body(tmp_path, builder):
    path = builder(tmp_path / "ledger")
    result = convert_file(path, options=ConversionOptions(title="Ledger"))
    header, body = round_trip(result, path)
    assert header["unit"] == "sheet"
    assert body == f"# Ledger\n\n{EXPECTED_SPREADSHEET_BODY}\n"
    assert [heading.split("  ")[0] for heading, _ in sections(body)] == ["Sheet: Ledger", "Sheet: Empty"]
    assert extract_text(path) == EXPECTED_SPREADSHEET_BODY


def test_word97_main_story_only(tmp_path):
    path = office.build_word97_fixture(tmp_path / "memo")
    result = convert_file(path, options=ConversionOptions(title="Memo"))
    _, body = round_trip(result, path)
    assert body == f"# Memo\n\n{office.WORD97_EXPECTED_MAIN_TEXT.rstrip()}\n"
    assert "Footnote text" not in body


def test_encrypted_workbook_is_blocked_not_failed(tmp_path):
    path = office.build_encrypted_xls_fixture(tmp_path / "locked")
    with pytest.raises(EncryptedXlsError) as raised:
        convert_file(path)
    assert blocked_reason(raised.value) == "password-protected"


@pytest.mark.parametrize(
    ("builder", "media_type"),
    [
        (office.build_malformed_xlsx_fixture, XLSX_MEDIA_TYPE),
        (office.build_malformed_xls_fixture, XLS_MEDIA_TYPE),
        (office.build_truncated_word97_fixture, DOC_MEDIA_TYPE),
    ],
)
def test_malformed_office_files_fail_typed_and_retryable(tmp_path, builder, media_type):
    path = builder(tmp_path / "broken")
    with pytest.raises(DrawbridgeError) as raised:
        convert_file(path, media_type=media_type)
    assert blocked_reason(raised.value) is None


def test_malformed_docx_fails_typed(tmp_path):
    path = tmp_path / "broken"
    path.write_bytes(b"PK\x03\x04 not a package")
    with pytest.raises(MalformedDocxError):
        convert_file(path, media_type=DOCX_MEDIA_TYPE)


def test_email_headers_body_and_attachment_note(tmp_path, monkeypatch):
    path = tmp_path / "note"
    path.write_bytes(
        b"From: A Sender <a@example.org>\r\nTo: b@example.org\r\nSubject: Pipes | and more\r\n"
        b"Date: Thu, 01 Jan 2026 10:00:00 +0000\r\nMIME-Version: 1.0\r\n"
        b"Content-Type: multipart/mixed; boundary=XX\r\n\r\n"
        b"--XX\r\nContent-Type: text/plain\r\n\r\nHello there.\r\n"
        b"--XX\r\nContent-Type: application/pdf\r\nContent-Disposition: attachment; filename=scan.pdf\r\n\r\n%PDF-\r\n--XX--\r\n"
    )
    from drawbridge import refine_media_type
    import subprocess

    # Reproduce Linux libmagic's preference for the embedded attachment signature.
    real_run = subprocess.run
    def linux_file(argv, **kwargs):
        if argv[0] == "file":
            return subprocess.CompletedProcess(argv, 0, "application/pdf\n", "")
        return real_run(argv, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "run", linux_file)
        result = convert_file(path)
    pdf = tmp_path / "header-fields-in-pdf"
    pdf.write_bytes(b"%PDF-1.7\nFrom: source\nTo: destination\nSubject: example\n\n")
    assert refine_media_type(pdf, "application/pdf") == "application/pdf"
    header, body = round_trip(result, path)
    assert (result.media_type, header["unit"], header["attachment_count"]) == ("message/rfc822", "message", 1)
    assert "| Subject | Pipes \\| and more |" in body
    assert "Attachments (not converted here): scan.pdf" in body
    assert dict(sections(body))["Body"].strip() == "Hello there."


def test_html_only_email_keeps_its_words_and_says_how(tmp_path):
    path = tmp_path / "html-note"
    path.write_bytes(b"From: a@example.org\r\nTo: b@example.org\r\nSubject: x\r\nMIME-Version: 1.0\r\nContent-Type: text/html\r\n\r\n<p>Hi</p>\r\n")
    result = convert_file(path, media_type="message/rfc822")
    assert result.mirror.header["verify"] == ["email-body-from-html"]
    assert dict(sections(result.mirror.body))["Body"].strip() == "Hi"


def test_html_body_keeps_words_and_drops_markup_and_scripts():
    from drawbridge.documents import html_text

    markup = "<html><head><style>p{color:red}</style></head><body><p>First &amp; second</p><script>x()</script><div>Third<br>Fourth</div></body></html>"
    assert html_text(markup) == "First & second\n\nThird\nFourth"


def test_old_mac_and_windows_line_endings_become_newlines(tmp_path):
    path = tmp_path / "old-mac"
    path.write_bytes(b"one\rtwo\r\nthree\n")
    assert convert_file(path, media_type="text/plain", options=ConversionOptions(title="T")).mirror.body == "# T\n\none\ntwo\nthree\n"


def test_text_keeps_words_and_flags_lossy_decoding(tmp_path):
    clean = tmp_path / "notes"
    clean.write_text("Plain notes with unicode é.\n", encoding="utf-8")
    result = convert_file(clean, options=ConversionOptions(title="Notes"))
    assert round_trip(result, clean)[1] == "# Notes\n\nPlain notes with unicode é.\n"
    assert result.mirror.header["verify"] == []
    lossy = tmp_path / "latin"
    lossy.write_bytes(b"caf\xe9 society\n")
    flagged = convert_file(lossy, media_type="text/plain")
    assert "text-decode-lossy" in flagged.mirror.header["verify"]


def test_image_without_ocr_is_marked_pending(tmp_path, raster_png):
    path = tmp_path / "photo"
    path.write_bytes(raster_png)
    result = convert_file(path, ocr=None)
    header, body = round_trip(result, path)
    assert result.media_type == "image/png"
    assert header["verify"] == ["ocr-pending"]
    assert "[No text detected.]" in body


def test_unsupported_type_yields_a_stub_that_says_so(tmp_path):
    path = tmp_path / "blob"
    import sqlite3

    connection = sqlite3.connect(path)
    connection.execute("create table t (x)")
    connection.commit()
    connection.close()
    result = convert_file(path)
    header, body = round_trip(result, path)
    assert header["processing"][0]["method"] == "conversion-deferred:unsupported-media-type"
    assert "mirror-pending" in header["verify"]
    assert "original remains authoritative" in body
    assert not supported(result.media_type)


def test_pdf_goes_through_the_same_door(tmp_path, native_pdf):
    path = native_pdf(["Page one text.", "Page two text."])
    result = convert_file(path, options=ConversionOptions(extensions={"client": {"number": 12}}))
    header, _ = round_trip(result, path)
    assert (header["unit"], result.pdf.page_count) == ("page", 2)
    assert header["extensions"] == {"client": {"number": 12}}


def test_binary_mislabelled_as_text_is_not_converted_as_text(tmp_path):
    path = tmp_path / "zeros"
    path.write_bytes(b"\x7fELF" + bytes(64))
    result = convert_file(path, media_type="text/plain")
    assert result.method == "conversion-deferred:binary-content"
    assert "mirror-pending" in result.mirror.header["verify"]
