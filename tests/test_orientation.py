from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from drawbridge import orientation
from drawbridge.errors import OcrOperationalError

HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"


def _row(conf, text, line=1):
    return f"5\t1\t1\t1\t{line}\t1\t0\t0\t10\t10\t{conf}\t{text}\n"


def test_score_prefers_readable_text_over_confident_noise():
    _, good = orientation.tsv_text_and_score(
        HEADER + _row(95, "Readable") + _row(90, "evidence")
    )
    _, bad = orientation.tsv_text_and_score(
        HEADER + _row(12, "Unreadable") + _row(20, "garbage")
    )
    _, short = orientation.tsv_text_and_score(HEADER + _row(99, "a"))
    assert good > short > bad == 0


def test_lines_are_regrouped_by_block_paragraph_line():
    text, _ = orientation.tsv_text_and_score(
        HEADER
        + _row(90, "first", line=1)
        + _row(90, "line", line=1)
        + _row(90, "second", line=2)
    )
    assert text == "first line\nsecond"


def test_malformed_tsv_raises():
    with pytest.raises(ValueError, match="malformed"):
        orientation.tsv_text_and_score("broken output")
    with pytest.raises(ValueError, match="malformed"):
        orientation.tsv_text_and_score(HEADER + _row("x", "word"))


def test_recover_page_tries_all_four_rotations_and_keeps_best(
    monkeypatch, tmp_path, raster_png
):
    source = tmp_path / "scan.png"
    source.write_bytes(raster_png)
    before = source.read_bytes()
    rotations = []

    def fake_run(command, **kwargs):
        image = Path(command[1])
        assert image.is_file()
        assert command[-3:] == ["--psm", "3", "tsv"]
        angle = int(image.stem.split("-")[-1])
        rotations.append(angle)
        confidence = 95 if angle == 270 else 10
        return subprocess.CompletedProcess(
            command, 0, HEADER + _row(confidence, f"Recovered{angle}"), ""
        )

    monkeypatch.setattr(orientation.shutil, "which", lambda name: "/synthetic/" + name)
    monkeypatch.setattr(orientation.subprocess, "run", fake_run)
    page = orientation.recover_page(source, 1, dpi=72)
    assert rotations == [0, 90, 180, 270]
    assert (page.text, page.rotation, page.page) == ("Recovered270", 270, 1)
    assert page.score > 0
    assert source.read_bytes() == before


def test_recover_page_yields_empty_text_when_nothing_scores(
    monkeypatch, tmp_path, raster_png
):
    source = tmp_path / "scan.png"
    source.write_bytes(raster_png)
    monkeypatch.setattr(orientation.shutil, "which", lambda name: "/synthetic/" + name)
    monkeypatch.setattr(
        orientation.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, HEADER + _row(5, "noise"), ""
        ),
    )
    page = orientation.recover_page(source, 1, dpi=72)
    assert page.text == "" and page.score == 0


def test_recover_page_requires_tesseract(monkeypatch, tmp_path, raster_png):
    source = tmp_path / "scan.png"
    source.write_bytes(raster_png)
    monkeypatch.setattr(orientation.shutil, "which", lambda name: None)
    with pytest.raises(OcrOperationalError, match="tesseract"):
        orientation.recover_page(source, 1)


def test_recover_page_reports_tool_failure(monkeypatch, tmp_path, raster_png):
    source = tmp_path / "scan.png"
    source.write_bytes(raster_png)
    monkeypatch.setattr(orientation.shutil, "which", lambda name: "/synthetic/" + name)

    def failing(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, stderr="boom")

    monkeypatch.setattr(orientation.subprocess, "run", failing)
    with pytest.raises(OcrOperationalError, match="boom"):
        orientation.recover_page(source, 1, dpi=72)


def _long_page(path, *, width=200.0, height=9000.0, line_every=30.0):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (int(width), int(height)), "white")
    draw = ImageDraw.Draw(image)
    lines = []
    y = 20.0
    while y < height - 10:
        draw.text((10, int(y) - 8), f"Line at {int(y)}", fill="black")
        lines.append((y - 7, y + 1))
        y += line_every
    image.save(path, format="PNG", dpi=(72, 72))
    return lines


def _recording_tesseract(monkeypatch, seen):
    from PIL import Image

    def fake_run(command, **kwargs):
        image = Path(command[1])
        pixmap = Image.open(image)
        band, angle = int(image.stem.split("-")[1]), int(image.stem.split("-")[-1])
        seen.append((band, angle, pixmap.width, pixmap.height))
        confidence = 95 if angle == 0 else 10
        return subprocess.CompletedProcess(
            command, 0, HEADER + _row(confidence, f"Band{band}"), ""
        )

    monkeypatch.setattr(orientation.shutil, "which", lambda name: "/synthetic/" + name)
    monkeypatch.setattr(orientation.subprocess, "run", fake_run)


def test_a_page_too_long_for_one_image_is_read_in_bands_cut_between_lines(
    monkeypatch, tmp_path
):
    source = tmp_path / "long.png"
    _long_page(source)
    before = source.read_bytes()
    seen = []
    _recording_tesseract(monkeypatch, seen)
    page = orientation.recover_page(source, 1)
    bands = sorted({band for band, *_ in seen})
    assert len(bands) == page.bands >= 5
    assert [angle for band, angle, *_ in seen if band == 0] == [0, 90, 180, 270]
    assert all(angle == 0 for band, angle, *_ in seen if band > 0)
    assert all(
        max(width, height) <= orientation.BAND_PIXELS + 2 for *_, width, height in seen
    )
    assert page.text == "\n".join(f"Band{band}" for band in bands)
    assert page.as_dict()["bands"] == page.bands
    assert source.read_bytes() == before


def test_band_cuts_fall_between_lines_of_text(tmp_path):
    from drawbridge import images as pdf_tools

    source = tmp_path / "long.png"
    lines = _long_page(source)
    # 1905 points falls inside the line whose baseline is 1910, so a cut at the limit would split it.
    cuts = pdf_tools.image_band_cuts(source, 1, 1905.0)
    assert len(cuts) >= 4 and cuts[0] < 1903
    edges = (0.0, *cuts, 9000.0)
    assert all(0 < bottom - top <= 1905.0 for top, bottom in zip(edges, edges[1:]))
    assert not [cut for cut in cuts for top, bottom in lines if top < cut < bottom]
    assert pdf_tools.image_band_cuts(source, 1, 9000.0) == ()


def test_a_page_too_wide_for_one_image_is_rendered_at_a_lower_resolution(
    monkeypatch, tmp_path
):
    source = tmp_path / "wide.png"
    _long_page(source, width=9000.0, height=100.0)
    seen = []
    _recording_tesseract(monkeypatch, seen)
    page = orientation.recover_page(source, 1)
    assert page.bands == 1 and "bands" not in page.as_dict()
    assert all(
        max(width, height) <= orientation.MAX_RENDER_SIDE + 2
        for *_, width, height in seen
    )


def test_an_ordinary_page_is_one_rendering_per_rotation_at_the_requested_resolution(
    monkeypatch, tmp_path
):
    source = tmp_path / "letter.png"
    _long_page(source, width=612.0, height=792.0)
    seen = []
    _recording_tesseract(monkeypatch, seen)
    page = orientation.recover_page(source, 1)
    assert [(band, angle) for band, angle, *_ in seen] == [
        (0, 0),
        (0, 90),
        (0, 180),
        (0, 270),
    ]
    assert (seen[0][2], seen[0][3]) == (2550, 3300)
    assert page.bands == 1 and page.text == "Band0"


def test_image_score_excludes_implicitly_rotated_vertical_word_boxes():
    upright = HEADER + _row(95, "Evidence")
    sideways = upright.replace("\t10\t10\t95\t", "\t10\t80\t95\t")
    assert orientation.tsv_text_and_score(upright, horizontal=True)[1] > 0
    assert orientation.tsv_text_and_score(sideways, horizontal=True)[1] == 0
    assert orientation.tsv_text_and_score(sideways)[1] > 0


def test_pdf_recovery_selects_one_page_in_a_complete_job(
    monkeypatch, native_pdf, tmp_path
):
    from contextlib import contextmanager
    from types import SimpleNamespace

    from drawbridge import _vellric

    source = native_pdf(["First native page", "Second native page"])
    calls = []

    @contextmanager
    def job(path, command, *options, **kwargs):
        calls.append(options)
        yield SimpleNamespace(
            manifest={
                "page_count": 2,
                "pages": [{}, {"ocr": {"rotation": 90, "score": 10, "bands": 1}}],
            },
            text=lambda page: "Recovered selected page",
        )

    monkeypatch.setattr(_vellric, "document_job", job)
    result = orientation.recover_page(source, 2)
    assert result.text == "Recovered selected page"
    assert calls[0][calls[0].index("--ocr-pages") + 1] == "2"
    assert calls[0][calls[0].index("--ocr") + 1] == "auto"


def test_permissive_image_rotation_is_clockwise_and_metadata_free_dpi_matches_baseline(
    tmp_path,
):
    import pymupdf
    from drawbridge.images import image_size, render_image
    from PIL import Image

    source = tmp_path / "corners.png"
    image = Image.new("RGB", (2, 3), "white")
    image.putpixel((0, 0), (255, 0, 0))
    image.save(source)
    with pymupdf.open(source) as baseline:
        assert image_size(source) == (baseline[0].rect.width, baseline[0].rect.height)
    target = render_image(source, 1, tmp_path / "clockwise.png", dpi=96, rotation=90)
    with Image.open(target) as rotated:
        assert rotated.size == (3, 2) and rotated.getpixel((2, 0)) == (255, 0, 0)
