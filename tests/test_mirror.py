from __future__ import annotations

import pytest

from drawbridge.errors import MirrorFormatError
from drawbridge.mirror import (
    EMPTY_PAGE_MARKER,
    REQUIRED_HEADER_FIELDS,
    Mirror,
    build_header,
    mirror_text,
    page_body,
    page_sections,
    parse_mirror_header,
    render_mirror,
    sections,
    sha256_file,
    title_from_name,
)


def test_header_has_every_required_field(fixtures):
    header = build_header(fixtures / "trivial.pdf", method="pymupdf-text")
    assert REQUIRED_HEADER_FIELDS <= set(header)
    assert header["mirror_of"] == "trivial.pdf"
    assert header["content_hash"] == sha256_file(fixtures / "trivial.pdf")
    assert header["byte_size"] == (fixtures / "trivial.pdf").stat().st_size
    assert header["processing"] == [
        {"seq": 1, "method": "pymupdf-text", "performed_at": header["processing"][0]["performed_at"], "agent": "drawbridge"}
    ]
    assert header["acquired_at"].endswith("Z")


def test_header_extra_cannot_shadow_required(fixtures):
    with pytest.raises(ValueError):
        build_header(fixtures / "trivial.pdf", method="ocr", extra={"content_hash": "x"})


def test_verify_flags_are_sorted_and_unique(fixtures):
    header = build_header(fixtures / "trivial.pdf", method="ocr", verify=["b", "a", "b"])
    assert header["verify"] == ["a", "b"]


def test_page_body_marks_empty_pages():
    body = page_body("Doc", ["  hello \n", "", "\n\n"])
    assert body == f"# Doc\n\n## Page 1\n\nhello\n\n## Page 2\n\n{EMPTY_PAGE_MARKER}\n\n## Page 3\n\n{EMPTY_PAGE_MARKER}"
    assert page_sections(body) == ["hello", EMPTY_PAGE_MARKER, EMPTY_PAGE_MARKER]


def test_page_sections_refuse_disorder():
    with pytest.raises(MirrorFormatError):
        page_sections("# T\n\n## Page 2\n\nx\n")


def test_render_parse_round_trip(fixtures):
    header = build_header(fixtures / "trivial.pdf", method="ocr", extra={"page_count": 1})
    body = "# Trivial\n\n## Page 1\n\nwith \x00 nul and unicode é"
    rendered = render_mirror(Mirror(header, body))
    assert rendered.startswith("---\nmirror_of: trivial.pdf\n")
    assert "\x00" not in rendered and rendered.endswith("\n")
    parsed_header, parsed_body = parse_mirror_header(rendered)
    assert parsed_header == header
    assert parsed_body == body.replace("\x00", "") + "\n"


def test_parse_normalises_line_endings_and_refuses_missing_fields():
    good = "---\n" + "\n".join(f"{field}: x" for field in sorted(REQUIRED_HEADER_FIELDS)) + "\n---\n\nbody\r\nline\r\n"
    header, body = parse_mirror_header(good)
    assert body == "body\nline\n"
    with pytest.raises(MirrorFormatError, match="missing: content_hash"):
        parse_mirror_header(good.replace("content_hash: x\n", ""))
    with pytest.raises(MirrorFormatError, match="front matter"):
        parse_mirror_header("no header here")
    with pytest.raises(MirrorFormatError, match="mapping"):
        parse_mirror_header("---\n- a list\n---\nbody")


def test_parse_accepts_path(tmp_path, fixtures):
    header = build_header(fixtures / "trivial.pdf", method="ocr")
    target = tmp_path / "m.md"
    target.write_text(render_mirror(Mirror(header, "# T\n\n## Page 1\n\nx")), encoding="utf-8")
    parsed, body = parse_mirror_header(target)
    assert parsed["mirror_of"] == "trivial.pdf" and body.endswith("x\n")


def test_mirror_text_is_a_reading_view():
    assert mirror_text(b"\n\r\nfirst\r\nsecond\rthird") == "first\nsecond\nthird"


@pytest.mark.parametrize(
    ("name", "title"),
    [("rfc8785.pdf", "Rfc8785"), ("2014-01-01_site report.PDF", "2014 01 01 Site Report"), ("___.pdf", "Document")],
)
def test_title_from_name(name, title):
    assert title_from_name(name) == title


def test_header_declares_format_and_unit(fixtures):
    header = build_header(fixtures / "trivial.pdf", method="pymupdf-text")
    assert header["format"] == "drawbridge.mirror.v1"
    assert header["unit"] == "page"
    with pytest.raises(ValueError):
        build_header(fixtures / "trivial.pdf", method="pymupdf-text", unit="chapter")


def test_extensions_are_preserved_and_never_top_level(fixtures):
    pdf = fixtures / "trivial.pdf"
    header = build_header(pdf, method="pymupdf-text", extensions={"client": {"document_number": 7}})
    parsed, _ = parse_mirror_header(render_mirror(Mirror(header, page_body("T", ["x"]))))
    assert parsed["extensions"] == {"client": {"document_number": 7}}
    assert "document_number" not in parsed
    with pytest.raises(ValueError):
        build_header(pdf, method="pymupdf-text", extensions={"client": "not a mapping"})


def test_unversioned_mirror_still_parses_and_other_formats_are_refused(fixtures):
    header = build_header(fixtures / "trivial.pdf", method="pymupdf-text")
    old = {k: v for k, v in header.items() if k not in {"format", "unit"}}
    parsed, _ = parse_mirror_header(render_mirror(Mirror(old, page_body("T", ["x"]))))
    assert "format" not in parsed
    header["format"] = "drawbridge.mirror.v9"
    with pytest.raises(MirrorFormatError):
        parse_mirror_header(render_mirror(Mirror(header, page_body("T", ["x"]))))


def test_sections_reads_any_unit():
    body = "# T\n\n## Sheet: Costs\n\na | b\n\n## Sheet: Notes\n\nc\n"
    assert sections(body) == [("Sheet: Costs", "a | b"), ("Sheet: Notes", "c")]
