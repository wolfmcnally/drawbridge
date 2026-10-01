from __future__ import annotations

import pytest
from drawbridge import pdf_tools
from drawbridge.pdf_tools import (
    DegeneratePdfError,
    EncryptedPdfError,
    MalformedPdfError,
    ocr_page_numbers,
    page_texts,
)


def test_native_fixture_traverses_completely(fixtures):
    inspection = page_texts(fixtures / "rfc8785.pdf")
    assert inspection.openable and not inspection.needs_password
    assert inspection.page_count == 20
    assert inspection.page_texts is not None and len(inspection.page_texts) == 20
    assert inspection.has_text_layer
    assert "JSON Canonicalization Scheme" in inspection.page_texts[0]


def test_invalid_fixture_is_malformed(fixtures):
    with pytest.raises(MalformedPdfError) as info:
        page_texts(fixtures / "invalid.pdf")
    assert info.value.inspection.openable is False


def test_encrypted_pdf_is_blocked_with_partial_inspection(encrypted_pdf):
    with pytest.raises(EncryptedPdfError) as info:
        page_texts(encrypted_pdf)
    inspection = info.value.inspection
    assert inspection.openable and inspection.is_encrypted and inspection.needs_password
    assert inspection.page_count == 1
    assert inspection.page_texts is None
    assert info.value.blocked_reason == "password-protected"


def test_permissions_only_pdf_reads_normally(permissions_only_pdf):
    inspection = page_texts(permissions_only_pdf)
    assert inspection.needs_password is False
    assert inspection.has_text_layer
    assert "readable despite owner password" in inspection.page_texts[0]


def test_zero_page_pdf_is_degenerate(zero_page_pdf):
    with pytest.raises(DegeneratePdfError) as info:
        page_texts(zero_page_pdf)
    assert info.value.inspection.page_count == 0
    assert info.value.blocked_reason == "degenerate-input"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("rfc8785.pdf", []),
        ("trivial.pdf", [1]),
        ("graph_ocred.pdf", [1]),
        ("ccitt.pdf", [1]),
        ("cardinal.pdf", [1, 2, 3, 4]),
    ],
)
def test_ocr_page_selection_on_fixtures(fixtures, name, expected):
    assert ocr_page_numbers(fixtures / name) == expected


def test_ocr_page_selection_is_per_page(mixed_pdf):
    assert ocr_page_numbers(mixed_pdf) == [2, 3]


def test_small_logo_does_not_force_ocr(logo_pdf):
    assert ocr_page_numbers(logo_pdf) == []


def test_ocr_page_selection_reuses_inspection(mixed_pdf):
    inspection = page_texts(mixed_pdf)
    assert ocr_page_numbers(mixed_pdf, inspection=inspection) == [2, 3]


def test_ocr_page_selection_rejects_bad_threshold(mixed_pdf):
    with pytest.raises(ValueError):
        ocr_page_numbers(mixed_pdf, raster_threshold=0)


def test_ocr_page_selection_refuses_encrypted(encrypted_pdf):
    with pytest.raises(EncryptedPdfError):
        ocr_page_numbers(encrypted_pdf)


def test_render_page_png_reads_without_writing(tmp_path, fixtures):
    source = fixtures / "ccitt.pdf"
    before = source.read_bytes()
    target = pdf_tools.render_page_png(
        source, 1, tmp_path / "p.png", dpi=72, rotation=90
    )
    assert target.is_file() and target.stat().st_size > 0
    assert source.read_bytes() == before
    with pytest.raises(ValueError):
        pdf_tools.render_page_png(source, 2, tmp_path / "q.png")


def test_page_image_coverage(fixtures, logo_pdf):
    assert pdf_tools.page_image_coverage(fixtures / "ccitt.pdf") == [pytest.approx(1.0)]
    (coverage,) = pdf_tools.page_image_coverage(logo_pdf)
    assert 0 < coverage < 0.5


def test_every_pymupdf_call_is_serialised_across_threads(
    fixtures, tmp_path, monkeypatch
):
    """The real exported lock still protects clients' own native work.

    Drawbridge PDF jobs now use separate processes, so they never expose native
    objects in this process. Do not substitute a no-op lock for unmigrated clients.
    """
    import threading
    import time

    import drawbridge

    assert drawbridge.PDF_LOCK is pdf_tools.PDF_LOCK
    state = {"inside": 0, "peak": 0}

    @pdf_tools.pdf_locked
    def client_native_call():
        state["inside"] += 1
        state["peak"] = max(state["inside"], state["peak"])
        time.sleep(0.01)
        state["inside"] -= 1

    threads = [threading.Thread(target=client_native_call) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert not any(t.is_alive() for t in threads) and state["peak"] == 1
    with pdf_tools.PDF_LOCK:
        client_native_call()
    assert state["inside"] == 0


def test_a_failed_pymupdf_call_frees_its_native_objects_under_the_lock(
    fixtures, tmp_path, monkeypatch
):
    """A locked function that raises clears its finished frames before releasing the lock: the exception, kept
    and later discarded on any thread, no longer holds a document or pixmap alive, and the clearing is seen to
    happen while the lock is still held. Covers a failure of our own after the objects exist and a failure
    inside PyMuPDF itself (a rendered page saved to a directory)."""
    import traceback

    import drawbridge
    from drawbridge import pdf_tools

    assert drawbridge.pdf_locked is pdf_tools.pdf_locked
    import pymupdf as real

    real_clear, cleared_holding = traceback.clear_frames, []

    def clearing(tb):  # the lock's ownership at each clearing
        cleared_holding.append(pdf_tools.PDF_LOCK._is_owned())
        return real_clear(tb)

    monkeypatch.setattr(traceback, "clear_frames", clearing)

    @pdf_tools.pdf_locked
    def failing(path):
        document = real.open(path)
        pixmap = document[0].get_pixmap(dpi=24)
        assert pixmap is not None
        raise ValueError("after the native objects exist")

    for call in (lambda: failing(fixtures / "rfc8785.pdf"),):
        cleared_holding.clear()
        kept = None
        try:
            call()
        except Exception as exc:  # noqa: BLE001 - MuPDF's own failure type is not ours to name
            kept = exc
        assert kept is not None and cleared_holding and all(cleared_holding), (
            cleared_holding
        )
        frame_locals = []
        tb = kept.__traceback__
        while tb is not None:
            for value in tb.tb_frame.f_locals.values():
                frame_locals.extend(
                    value if isinstance(value, (tuple, list)) else (value,)
                )
            tb = tb.tb_next
        assert not any(
            type(value).__module__.startswith(("pymupdf", "fitz"))
            for value in frame_locals
        )
