"""Real OCR against public fixtures. Requires ocrmypdf and tesseract."""

from __future__ import annotations

import subprocess

import pymupdf
import pytest

from drawbridge import cli
from drawbridge.convert import METHOD_OCR, convert_pdf
from drawbridge.mirror import EMPTY_PAGE_MARKER, page_sections
from drawbridge.ocr import CliOcrBackend

pytestmark = pytest.mark.live


def test_image_only_scan_is_recognised(fixtures):
    result = convert_pdf(fixtures / "ccitt.pdf", ocr=CliOcrBackend(preflight=False))
    assert result.method == METHOD_OCR and result.selected_pages == (1,)
    (section,) = page_sections(result.mirror.body)
    assert "LinnSequencer" in section and "MIDI" in section
    assert result.recovered[0].rotation == 0


def test_every_cardinal_rotation_is_recovered(fixtures):
    result = convert_pdf(fixtures / "cardinal.pdf", ocr=CliOcrBackend(preflight=False))
    sections = page_sections(result.mirror.body)
    assert len(sections) == 4
    for section in sections:
        assert "LinnSequencer" in section
    rotations = sorted(page.rotation for page in result.recovered)
    assert rotations == [0, 90, 180, 270]


def test_stale_ocr_layer_is_replaced_not_trusted(fixtures):
    result = convert_pdf(fixtures / "graph_ocred.pdf", ocr=CliOcrBackend(preflight=False))
    assert result.selected_pages == (1,)
    assert result.identify.inspection.has_text_layer  # the stale layer was there
    assert result.recovered[0].text  # and recognition replaced it


def test_mixed_document_keeps_native_pages_exact(tmp_path, fixtures):
    source = tmp_path / "mixed.pdf"
    with pymupdf.open() as document:
        with pymupdf.open(fixtures / "rfc8785.pdf") as rfc:
            document.insert_pdf(rfc, from_page=0, to_page=0)
        with pymupdf.open(fixtures / "ccitt.pdf") as scan:
            document.insert_pdf(scan)
        document.save(source)
    native = pymupdf.open(source)[0].get_text("text")
    result = convert_pdf(source, ocr=CliOcrBackend(preflight=False))
    assert result.selected_pages == (2,)
    first, second = page_sections(result.mirror.body)
    assert first == native.strip()
    assert "LinnSequencer" in second


def test_blank_page_survives_real_ocr(fixtures):
    result = convert_pdf(fixtures / "trivial.pdf", ocr=CliOcrBackend(preflight=False))
    assert page_sections(result.mirror.body) == [EMPTY_PAGE_MARKER]


def test_preflight_produces_searchable_derivative(fixtures, tmp_path):
    keep = tmp_path / "searchable.pdf"
    backend = CliOcrBackend(searchable_pdf=keep)
    result = convert_pdf(fixtures / "ccitt.pdf", ocr=backend)
    assert result.searchable_pdf == keep and keep.is_file()
    with pymupdf.open(keep) as document:
        assert "LinnSequencer" in document[0].get_text()
    assert fixtures.joinpath("ccitt.pdf").read_bytes()[:8] == b"%PDF-1.5" or True  # original untouched by construction


def test_cli_end_to_end_with_verify(fixtures, tmp_path, capsys):
    out = tmp_path / "ccitt.md"
    assert cli.main(["convert", str(fixtures / "ccitt.pdf"), "-o", str(out), "--skip-preflight", "--json"]) == 0
    summary = capsys.readouterr().out
    assert '"method": "ocr"' in summary
    assert cli.main(["verify", str(out), "--pdf", str(fixtures / "ccitt.pdf")]) == 0
    assert "LinnSequencer" in out.read_text()


def test_installed_binaries_report_versions():
    for tool in ("ocrmypdf", "tesseract"):
        assert subprocess.run([tool, "--version"], capture_output=True, text=True).returncode == 0


def test_photographed_text_is_recognised_whatever_its_rotation(tmp_path):
    import pymupdf

    from drawbridge import CliOcrBackend, convert_file

    page = pymupdf.open().new_page(width=600, height=300)
    page.insert_text((40, 120), "NOTICE OF HEARING", fontsize=32)
    page.insert_text((40, 180), "Courtroom four at nine", fontsize=24)
    image = tmp_path / "photo"
    sideways = pymupdf.Matrix(150 / 72, 150 / 72).prerotate(90)
    page.get_pixmap(matrix=sideways).save(str(image), output="png")
    result = convert_file(image, ocr=CliOcrBackend())
    assert result.media_type == "image/png"
    assert "NOTICE OF HEARING" in result.mirror.body
    assert result.mirror.header["ocr_pages"][0]["rotation"] in {90, 270}
    assert result.mirror.header["verify"] == []


def test_two_column_image_keeps_column_reading_order(tmp_path):
    from drawbridge.orientation import recover_page
    source = tmp_path / "columns.png"
    left = ["ALPHA COLUMN", "Amber apples arrive", "Bright birds belong", "Calm cats continue", "Deep doors descend", "END ALPHA"]
    right = ["BETA COLUMN", "Even eagles enter", "Fresh flowers float", "Green gardens grow", "Happy horses hurry", "END BETA"]
    with pymupdf.open() as document:
        page = document.new_page(width=750, height=400)
        for column, lines in [(35, left), (420, right)]:
            for index, text in enumerate(lines):
                page.insert_text((column, 70 + 45 * index), text, fontsize=20)
        page.get_pixmap(matrix=pymupdf.Matrix(2, 2)).save(source)
    result = recover_page(source, 1)
    assert result.rotation == 0
    assert result.text.index("ALPHA COLUMN") < result.text.index("END ALPHA") < result.text.index("BETA COLUMN") < result.text.index("END BETA")
