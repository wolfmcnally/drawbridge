from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from drawbridge.citations import CITATIONS, anchor, assemble, split
from drawbridge.errors import ConversionOperationalError, MirrorFormatError
from drawbridge.mirror import Mirror, build_header, page_sections, parse_mirror_header, render_mirror


def cited(tmp_path, pages):
    original = tmp_path / "source.pdf"
    original.write_bytes(b"%PDF synthetic original identity")
    header = build_header(original, method="test", extra={"page_count": len(pages)})
    body, mapping = assemble("# Example", pages, header["content_hash"][7:])
    header.update(page_citations=dict(CITATIONS), pdf_page_map=mapping)
    return Mirror(header, body)


def test_exact_identity_and_large_ordinals():
    assert anchor("a" * 64, 1) == "vellric-pdf-" + "a" * 64 + "-page-000001"
    assert anchor("a" * 64, 1000000).endswith("-page-1000000")
    for number in [True, 0, -1, 1.0]:
        with pytest.raises(ValueError, match="ordinal"):
            anchor("a" * 64, number)
    with pytest.raises(ValueError, match="digest"):
        anchor("A" * 64, 1)


def test_untrusted_pages_round_trip_by_metadata(tmp_path):
    fake = '<a id="vellric-pdf-' + "a" * 64 + '-page-000002"></a>'
    pages = ["```\n## Page 2\n" + fake + "\n<script>raw HTML", "😀\r\nNUL\x00 retained\rline", ""]
    mirror = cited(tmp_path, pages)
    header, body = parse_mirror_header(render_mirror(mirror))
    expected = [pages[0], "😀\nNUL retained\nline", "[No text recovered from this page; check the original.]"]
    assert page_sections(body, header=header) == expected
    assert split(header, body)[2] == tuple(anchor(header["content_hash"][7:], n) for n in range(1, 4))
    # Raw combined Markdown deliberately retains hostile content, not a sanitizer promise.
    assert "<script>" in body and "```" in body and fake in body
    assert render_mirror(Mirror(header, body)) == render_mirror(mirror)


def test_body_only_helper_retains_ordinary_compatibility(tmp_path):
    mirror = cited(tmp_path, ["first", "second"])
    assert page_sections(mirror.body) == ["first", "second"]


@pytest.mark.parametrize("fault", ["digest", "number", "boolean", "duplicate", "missing", "schema", "span", "gap", "extra", "unit"])
def test_mapping_tampering_refused(tmp_path, fault):
    mirror = cited(tmp_path, ["one", "two"])
    header = copy.deepcopy(mirror.header)
    records = header["pdf_page_map"]["pages"]
    if fault == "digest": header["content_hash"] = "sha256:" + "f" * 64
    elif fault == "number": records[0]["number"] = 2
    elif fault == "boolean": records[0]["start"] = True
    elif fault == "duplicate": records[1]["anchor"] = records[0]["anchor"]
    elif fault == "missing": records.pop()
    elif fault == "schema": header["page_citations"]["extra"] = "not allowed"
    elif fault == "span": records[0]["end"] = 10**9
    elif fault == "gap": records[0]["end"] -= 1
    elif fault == "extra": records[0]["text"] = "untrusted"
    elif fault == "unit": header["unit"] = "document"
    with pytest.raises(MirrorFormatError, match="PDF page citations"):
        render_mirror(Mirror(header, mirror.body))


def test_grooming_uses_actual_pages_and_preserves_mapping(tmp_path):
    from drawbridge.structure import semantic_mirror

    mirror = cited(tmp_path, ["## Page 99\n\nraw", "```\nunclosed"])
    seen = []
    def annotate(lines):
        seen.append(lines)
        return {"blocks": [{"lines": [1, len(lines)], "kind": "keep"}]}
    groomed = semantic_mirror(render_mirror(mirror), annotate=annotate, method="test", endpoint=None)
    header, body = parse_mirror_header(render_mirror(groomed))
    assert len(seen) == 2
    assert all(not any('vellric-pdf-' in line for line in lines) for lines in seen)
    assert page_sections(body, header=header) == ["## Page 99\n\nraw", "```\nunclosed"]
    assert split(header, body)[2] == split(mirror.header, mirror.body)[2]


def test_custom_ocr_preserves_original_identity_and_rejects_substitution(tmp_path, monkeypatch):
    from drawbridge.convert import convert_pdf
    from drawbridge.ocr import OcrResult
    from drawbridge.pdf_tools import PdfInspection
    from drawbridge.mirror import sha256_file

    original = tmp_path / "original.pdf"
    original.write_bytes(b"%PDF original")
    digest = sha256_file(original)[7:]
    anchors = (anchor(digest, 1), anchor(digest, 2))
    inspection = PdfInspection(True, False, False, 2, True, ("native", ""), digest, (0., 1.), page_anchors=anchors)
    ident = SimpleNamespace(processable=True, inspection=inspection)
    monkeypatch.setattr("drawbridge.convert.ocr_page_numbers", lambda *a, **k: [2])
    derivative = tmp_path / "searchable.pdf"
    derivative.write_bytes(b"different PDF bytes")
    class Custom:
        def extract(self, *args): return OcrResult(("native", "OCR"), (), derivative)
    result = convert_pdf(original, ocr=Custom(), identify_result=ident)
    assert split(result.mirror.header, result.mirror.body)[2] == anchors
    assert result.mirror.header["content_hash"] == "sha256:" + digest
    assert result.searchable_pdf == derivative
    class Wrong:
        def extract(self, *args): return OcrResult(("native", "OCR"), (), derivative, {}, (anchor("b" * 64, 1), anchor("b" * 64, 2)))
    with pytest.raises(ConversionOperationalError, match="changed original"):
        convert_pdf(original, ocr=Wrong(), identify_result=ident)


def test_cli_verify_refuses_tampered_citation_mapping(native_pdf, tmp_path, capsys):
    import yaml
    from drawbridge import cli

    source = native_pdf(["Citation original evidence."])
    target = tmp_path / "mirror.md"
    assert cli.main(["convert", str(source), "--no-profile", "--no-ocr", "-o", str(target)]) == 0
    header, body = parse_mirror_header(target)
    assert cli.main(["verify", str(target), "--pdf", str(source)]) == 0
    header["pdf_page_map"]["pages"][0]["anchor"] = anchor("b" * 64, 1)
    target.write_text("---\n" + yaml.safe_dump(header) + "---\n\n" + body)
    assert cli.main(["verify", str(target), "--pdf", str(source)]) == cli.EXIT_VERIFY
    assert "PDF page citations" in capsys.readouterr().err


@pytest.mark.parametrize("edge", ["payload", "preamble"])
def test_accepted_citation_mirror_cannot_shift_during_serialization(tmp_path, edge):
    mirror = cited(tmp_path, ["text"])
    record = mirror.header["pdf_page_map"]["pages"][0]
    if edge == "payload":
        mirror.body += "  "
        record["end"] += 2
    else:
        mirror.body = "\n" + mirror.body
        record["start"] += 1
        record["end"] += 1
    with pytest.raises(MirrorFormatError, match="noncanonical"):
        render_mirror(mirror)


def test_structure_routing_uses_physical_map_not_source_headings(tmp_path, monkeypatch):
    from drawbridge.profile import parse_profile, build_plan
    from drawbridge.structure import run_structure
    from drawbridge.mirror import sections

    mirror = cited(tmp_path, ["## Page 99\nraw", "second"])
    mirror.header["ocr_pages"] = []
    seen = []
    def layouts(source, numbers, **kwargs):
        seen.extend(numbers)
        return {}
    monkeypatch.setattr("drawbridge.pdf_tools.page_layouts", layouts)
    profile = parse_profile({"stages": {"structure": {}}})
    assert run_structure(render_mirror(mirror), profile=profile,
                         plan=build_plan(profile, "application/pdf"), source=tmp_path / "source.pdf") is None
    assert seen == [1, 2]
    assert sections(mirror.body, header=mirror.header) == [("Page 1", "## Page 99\nraw"), ("Page 2", "second")]
