from __future__ import annotations

from pathlib import Path

import pytest

from drawbridge.convert import METHOD_NATIVE, METHOD_OCR, ConversionOptions, convert_pdf
from drawbridge.errors import ConversionOperationalError, InherentlyUnprocessableError
from drawbridge.identify import identify
from drawbridge.mirror import EMPTY_PAGE_MARKER, page_sections, parse_mirror_header, render_mirror, sha256_file
from drawbridge.ocr import OcrResult
from drawbridge.orientation import RecoveredPage
from drawbridge.pdf_tools import EncryptedPdfError, MalformedPdfError


class RecordingOcr:
    def __init__(self, text="recognised", fail=None):
        self.calls = []
        self.text = text
        self.fail = fail

    def extract(self, pdf_path, selected, original_pages):
        self.calls.append((Path(pdf_path), tuple(selected), tuple(original_pages)))
        if self.fail:
            raise self.fail
        pages = list(original_pages)
        recovered = []
        for number in selected:
            pages[number - 1] = f"{self.text} {number}" if self.text else ""
            recovered.append(RecoveredPage(number, pages[number - 1], 180, 42.0))
        return OcrResult(tuple(pages), tuple(recovered))


def test_native_document_needs_no_ocr(fixtures):
    ocr = RecordingOcr()
    result = convert_pdf(fixtures / "rfc8785.pdf", ocr=ocr)
    assert result.method == METHOD_NATIVE and result.selected_pages == () and ocr.calls == []
    header, body = parse_mirror_header(render_mirror(result.mirror))
    assert header["processing"][0]["method"] == METHOD_NATIVE
    assert header["content_hash"] == sha256_file(fixtures / "rfc8785.pdf")
    assert header["page_count"] == 20 and header["ocr_pages"] == []
    sections = page_sections(body)
    assert len(sections) == 20 and "JSON Canonicalization Scheme" in sections[0]
    assert body.startswith("# Rfc8785\n")


def test_native_document_converts_without_any_ocr_backend(fixtures):
    assert convert_pdf(fixtures / "rfc8785.pdf", ocr=None).method == METHOD_NATIVE


def test_mixed_document_routes_only_scan_pages(mixed_pdf):
    ocr = RecordingOcr()
    result = convert_pdf(mixed_pdf, ocr=ocr, options=ConversionOptions(title="Mixed", mirror_of=7))
    assert result.method == METHOD_OCR and result.selected_pages == (2, 3)
    (call,) = ocr.calls
    assert call[1] == (2, 3) and call[2][0].startswith("Native text remains exact")
    sections = page_sections(result.mirror.body)
    assert sections == ["Native text remains exact", "recognised 2", "recognised 3"]
    assert result.mirror.header["mirror_of"] == 7
    assert result.mirror.header["ocr_pages"] == [
        {"page": 2, "rotation": 180, "score": 42.0},
        {"page": 3, "rotation": 180, "score": 42.0},
    ]


def test_scan_without_ocr_backend_fails_closed(mixed_pdf):
    with pytest.raises(ConversionOperationalError, match="OCR is unavailable"):
        convert_pdf(mixed_pdf, ocr=None)


def test_blank_page_is_marked_not_dropped(fixtures):
    result = convert_pdf(fixtures / "trivial.pdf", ocr=RecordingOcr(text=""))
    assert page_sections(result.mirror.body) == [EMPTY_PAGE_MARKER]
    assert result.method == METHOD_OCR


def test_incomplete_ocr_page_sequence_is_refused(mixed_pdf):
    class Short:
        def extract(self, pdf_path, selected, original_pages):
            return OcrResult(("only one",), ())

    with pytest.raises(ConversionOperationalError, match="incomplete"):
        convert_pdf(mixed_pdf, ocr=Short())


def test_inherent_ocr_failure_becomes_operational(mixed_pdf):
    class Inherent(InherentlyUnprocessableError):
        blocked_reason = "degenerate-input"

    with pytest.raises(ConversionOperationalError, match="unusable derivative"):
        convert_pdf(mixed_pdf, ocr=RecordingOcr(fail=Inherent("bad")))


def test_blocked_and_failed_identify_raise_typed_errors(encrypted_pdf, fixtures):
    with pytest.raises(EncryptedPdfError):
        convert_pdf(encrypted_pdf, ocr=RecordingOcr())
    with pytest.raises(MalformedPdfError):
        convert_pdf(fixtures / "invalid.pdf", ocr=RecordingOcr())


def test_precomputed_identify_is_reused(mixed_pdf):
    ident = identify(mixed_pdf)
    result = convert_pdf(mixed_pdf, ocr=RecordingOcr(), identify_result=ident)
    assert result.identify is ident


def test_options_flow_into_header(fixtures):
    options = ConversionOptions(
        title="Custom", acquired_at="2026-01-02T03:04:05Z", acquisition_method="batch",
        acquired_from="intake/box-3", agent="tester", verify=("event-date-unknown",),
    )
    header = convert_pdf(fixtures / "rfc8785.pdf", ocr=None, options=options).mirror.header
    assert header["acquired_at"] == "2026-01-02T03:04:05Z"
    assert header["acquisition_method"] == "batch" and header["acquired_from"] == "intake/box-3"
    assert header["processing"][0]["agent"] == "tester" and header["verify"] == ["event-date-unknown"]
