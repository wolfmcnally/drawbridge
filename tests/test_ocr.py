from __future__ import annotations

import threading

import pytest
from drawbridge.errors import (
    ConversionOperationalError,
    OcrOperationalError,
    OcrPreflightError,
)
from drawbridge.ocr import CliOcrBackend, OcrCapacity, ocr_jobs_for


@pytest.mark.parametrize(
    ("workers", "cores", "expected"),
    [(1, 8, 8), (2, 8, 4), (3, 8, 2), (8, 8, 1), (16, 8, 1), (1, None, 1), (4, 0, 1)],
)
def test_ocr_jobs_for(workers, cores, expected):
    assert ocr_jobs_for(workers, cores) == expected


@pytest.mark.parametrize("bad", [0, -1, True, "2"])
def test_ocr_jobs_for_rejects_bad_workers(bad):
    with pytest.raises(ValueError):
        ocr_jobs_for(bad, 4)


def test_capacity_reserves_and_releases():
    capacity = OcrCapacity(3)
    with capacity.reserve(2):
        assert capacity.available == 1
        with pytest.raises(ValueError):
            with capacity.reserve(4):
                pass
    assert capacity.available == 3
    with pytest.raises(ValueError):
        OcrCapacity(0)


def test_capacity_blocks_until_tokens_return():
    capacity = OcrCapacity(1)
    order = []
    started = threading.Event()

    def worker():
        started.set()
        with capacity.reserve(1):
            order.append("second")

    with capacity.reserve(1):
        thread = threading.Thread(target=worker)
        thread.start()
        started.wait(1)
        order.append("first")
    thread.join(5)
    assert order == ["first", "second"]


from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from drawbridge import _vellric


def fake_jobs(
    monkeypatch,
    tmp_path,
    *,
    original=None,
    selected=(2, 3),
    outstanding=(),
    fail=None,
    calls=None,
    capacity=None,
):
    original = tuple(
        original or ["Native text remains exact\n", "", "stale wrong OCR\n"]
    )
    calls = calls if calls is not None else []

    @contextmanager
    def job(source, command, *options, **kwargs):
        calls.append((command, list(options), kwargs))
        if capacity is not None:
            assert capacity.available == 0
        if fail:
            raise fail
        folder = tmp_path / "bundle"
        folder.mkdir(exist_ok=True)
        recovered = set(selected)
        pages = []
        texts = []
        for number, text in enumerate(original, 1):
            final = f"recovered scan {number}" if number in recovered else text
            texts.append(final)
            p = {
                "number": number,
                "geometry": {},
                "raster_coverage": 1.0 if number in recovered else 0.0,
                "method": "ocr" if number in recovered else "pymupdf-text",
            }
            if number in recovered:
                p["ocr"] = {"rotation": 90, "score": 10.0, "bands": 1}
            pages.append(p)
        (folder / "searchable.pdf").write_bytes(b"validated derivative bytes")
        manifest = {
            "source": {"sha256": "a" * 64},
            "inspection": {
                "openable": True,
                "is_encrypted": False,
                "needs_password": False,
                "page_count": len(original),
                "has_text_layer": True,
            },
            "pages": pages,
            "page_count": len(original),
            "outstanding_candidates": list(outstanding),
            "tool": {"name": "vellric", "version": "0.0.0"},
            "behavior": _vellric.BEHAVIOR,
            "provenance": {"processing_fingerprint": "b" * 64},
            "files": [{"path": "searchable.pdf"}],
        }
        from drawbridge.progress import advance

        advance("recognition", 0, len(recovered))
        for done in range(1, len(recovered) + 1):
            advance("recognition", done, len(recovered))
        yield SimpleNamespace(
            root=folder,
            manifest=manifest,
            text=lambda p, kind="text": (
                original[p["number"] - 1]
                if kind == "native"
                else texts[p["number"] - 1]
            ),
            texts=tuple(texts),
        )

    monkeypatch.setattr(_vellric, "document_job", job)
    return original, calls


def test_backend_replaces_selected_pages_and_keeps_native_exact(
    monkeypatch, mixed_pdf, tmp_path
):
    before = mixed_pdf.read_bytes()
    original, calls = fake_jobs(monkeypatch, tmp_path)
    result = CliOcrBackend(available_cores=2).extract(mixed_pdf, [2, 3], original)
    assert result.pages == (
        "Native text remains exact\n",
        "recovered scan 2",
        "recovered scan 3",
    )
    assert [p.page for p in result.recovered] == [2, 3] and [
        p.rotation for p in result.recovered
    ] == [90, 90]
    command, options, _ = calls[0]
    assert command == "convert"
    assert (
        options[options.index("--ocr-pages") + 1] == "2,3"
        and options[options.index("--jobs") + 1] == "2"
    )
    assert (
        options[options.index("--preflight") + 1] == "on"
        and result.processor["tool"]["name"] == "vellric"
    )
    assert mixed_pdf.read_bytes() == before


def test_backend_with_nothing_selected_returns_originals(mixed_pdf):
    result = CliOcrBackend(available_cores=1).extract(mixed_pdf, [], ["a", "b", "c"])
    assert result.pages == ("a", "b", "c") and result.recovered == ()


def test_backend_rejects_out_of_range_selection(mixed_pdf):
    with pytest.raises(ValueError):
        CliOcrBackend(available_cores=1, preflight=False).extract(
            mixed_pdf, [4], ["a", "b", "c"]
        )


def test_backend_requires_ocrmypdf_for_preflight(monkeypatch, mixed_pdf, tmp_path):
    original, _ = fake_jobs(
        monkeypatch, tmp_path, fail=OcrOperationalError("ocrmypdf unavailable")
    )
    with pytest.raises(OcrOperationalError, match="ocrmypdf"):
        CliOcrBackend(available_cores=1).extract(mixed_pdf, [2, 3], original)


def test_backend_skip_preflight_only_needs_tesseract(monkeypatch, mixed_pdf, tmp_path):
    original, calls = fake_jobs(monkeypatch, tmp_path)
    result = CliOcrBackend(available_cores=1, preflight=False).extract(
        mixed_pdf, [2, 3], original
    )
    options = calls[0][1]
    assert (
        options[options.index("--preflight") + 1] == "off"
        and result.searchable_pdf is None
    )


def test_backend_detects_page_count_drift(monkeypatch, mixed_pdf, tmp_path):
    fake_jobs(monkeypatch, tmp_path, original=["only one page"], selected=(1,))
    with pytest.raises(ConversionOperationalError, match="changed after inspection"):
        CliOcrBackend(available_cores=1).extract(mixed_pdf, [2], ["a", "b", "c"])


def test_backend_surfaces_preflight_refusal(monkeypatch, mixed_pdf, tmp_path):
    original, _ = fake_jobs(
        monkeypatch,
        tmp_path,
        fail=OcrPreflightError("InputFileError: bad", returncode=2),
    )
    with pytest.raises(OcrPreflightError) as info:
        CliOcrBackend(available_cores=1).extract(mixed_pdf, [2, 3], original)
    assert info.value.returncode == 2 and "InputFileError" in str(info.value)


def test_backend_keeps_searchable_derivative(monkeypatch, mixed_pdf, tmp_path):
    original, calls = fake_jobs(monkeypatch, tmp_path)
    keep = tmp_path / "out/searchable.pdf"
    result = CliOcrBackend(available_cores=1, searchable_pdf=keep).extract(
        mixed_pdf, [2, 3], original
    )
    assert (
        result.searchable_pdf == keep
        and keep.read_bytes() == b"validated derivative bytes"
    )
    assert "--searchable-pdf" in calls[0][1]
    assert not [p for p in keep.parent.iterdir() if p != keep]


def test_language_is_threaded_to_both_tools(monkeypatch, mixed_pdf, tmp_path):
    original, calls = fake_jobs(monkeypatch, tmp_path)
    CliOcrBackend(
        available_cores=1,
        language="eng+deu",
        dpi=200,
        rotate_threshold=3,
        ocrmypdf_timeout=60,
        tesseract_timeout=30,
    ).extract(mixed_pdf, [2, 3], original)
    options = calls[0][1]
    for key, value in [
        ("--language", "eng+deu"),
        ("--dpi", "200"),
        ("--rotate-threshold", "3"),
        ("--preflight-timeout-seconds", "60"),
        ("--page-timeout-seconds", "30"),
    ]:
        assert options[options.index(key) + 1] == value


def test_a_documents_pages_are_recognised_side_by_side(
    monkeypatch, mixed_pdf, tmp_path
):
    # Actual engine-side parallelism is qualified by Vellric's scheduling tests;
    # this boundary must reserve and forward its complete aggregate CPU grant.
    backend = CliOcrBackend(preflight=False, available_cores=3)
    original, calls = fake_jobs(monkeypatch, tmp_path, capacity=backend.capacity)
    backend.extract(mixed_pdf, [2, 3], original)
    assert calls[0][1][calls[0][1].index("--jobs") + 1] == "3"
    assert backend.capacity.available == 3


def test_recognition_reports_each_page_in_order_as_it_finishes(
    monkeypatch, mixed_pdf, tmp_path
):
    import threading

    from drawbridge import report_progress

    original, _ = fake_jobs(monkeypatch, tmp_path)
    heard = []
    caller = threading.get_ident()
    with report_progress(
        lambda s, d, t: heard.append((s, d, t, threading.get_ident() == caller))
    ):
        result = CliOcrBackend(available_cores=2, preflight=False).extract(
            mixed_pdf, [2, 3], original
        )
    assert result.pages[1:] == ("recovered scan 2", "recovered scan 3")
    assert heard == [
        ("recognition", 0, 2, True),
        ("recognition", 1, 2, True),
        ("recognition", 2, 2, True),
    ]


def test_protocol_extract_accepts_partial_recognition_without_claiming_complete(monkeypatch, mixed_pdf, tmp_path):
    original, _ = fake_jobs(monkeypatch, tmp_path, selected=(2,), outstanding=(3,))
    backend = CliOcrBackend(available_cores=1, preflight=False)
    result = backend.extract(mixed_pdf, [2], original)
    assert result.pages == (original[0], "recovered scan 2", original[2])
    with pytest.raises(ConversionOperationalError, match="outstanding"):
        backend.document(mixed_pdf, selected=[2], original_pages=original)


def test_complete_job_resource_limits_follow_grant_and_allow_explicit_overrides(monkeypatch, mixed_pdf, tmp_path):
    monkeypatch.delenv("DRAWBRIDGE_VELLRIC_MEMORY_MIB", raising=False)
    original, calls = fake_jobs(monkeypatch, tmp_path)
    CliOcrBackend(available_cores=16, document_timeout=7200, max_input_bytes=1024**3, max_pages=20000, tessdata_dir=tmp_path).extract(mixed_pdf, [2, 3], original)
    _, options, kwargs = calls[0]
    assert options[options.index("--jobs") + 1] == "16"
    assert options[options.index("--memory-mib") + 1] == str(2048 + 512 * 15)
    assert options[options.index("--max-input-bytes") + 1] == str(1024**3)
    assert options[options.index("--max-pages") + 1] == "20000"
    assert options[options.index("--tessdata-dir") + 1] == str(tmp_path.resolve())
    assert kwargs["timeout"] == 7200
