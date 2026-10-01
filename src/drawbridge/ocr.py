"""OCR backend: ocrmypdf preflight plus per-page orientation-recovered Tesseract.

The backend receives the pages that need recognition and the native text of
every page, and returns a complete page list: recognised text for selected
pages, the original native text for every other page, exactly one string per
page.

Concurrency is bounded by a shared core-token pool so that many documents in
flight, each running an OCR engine that parallelises internally, cannot
oversubscribe the machine.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence

from .errors import ConversionOperationalError
from .orientation import RecoveredPage


@dataclass(frozen=True)
class OcrResult:
    pages: tuple[str, ...]
    recovered: tuple[RecoveredPage, ...]
    searchable_pdf: Path | None = None
    processor: dict = field(default_factory=dict)


class OcrBackend(Protocol):
    def extract(
        self, pdf_path: Path, selected: Sequence[int], original_pages: Sequence[str]
    ) -> OcrResult: ...


def ocr_jobs_for(document_workers: int, available_cores: int | None) -> int:
    """Per-document OCR jobs that keep aggregate load within the core count."""
    if (
        isinstance(document_workers, bool)
        or not isinstance(document_workers, int)
        or document_workers <= 0
    ):
        raise ValueError("document worker count must be a positive integer")
    cores = available_cores if available_cores is not None else 1
    if isinstance(cores, bool) or not isinstance(cores, int) or cores <= 0:
        cores = 1
    return max(1, cores // min(document_workers, cores))


class OcrCapacity:
    """A shared, atomically reserved CPU-token budget for OCR subprocesses."""

    def __init__(self, cores: int) -> None:
        if isinstance(cores, bool) or not isinstance(cores, int) or cores <= 0:
            raise ValueError("OCR capacity must be a positive integer")
        self.cores = cores
        self._available = cores
        self._condition = threading.Condition()

    @property
    def available(self) -> int:
        with self._condition:
            return self._available

    @contextmanager
    def reserve(self, tokens: int):
        if isinstance(tokens, bool) or not isinstance(tokens, int):
            raise ValueError("OCR reservation must be a positive integer")
        if not 1 <= tokens <= self.cores:
            raise ValueError("OCR reservation exceeds shared capacity")
        with self._condition:
            self._condition.wait_for(lambda: self._available >= tokens)
            self._available -= tokens
        try:
            yield
        finally:
            with self._condition:
                self._available += tokens
                self._condition.notify_all()


class CliOcrBackend:
    """Complete Vellric document conversion with a caller-owned CPU grant.

    Vellric owns PDF preflight, rendering, recognition, and native formatting.
    This adapter reads validated ordinary artifacts and preserves Drawbridge's
    mirror/API and aggregate cross-document capacity boundary.
    """

    def __init__(
        self,
        *,
        document_workers: int = 1,
        available_cores: int | None = None,
        capacity: OcrCapacity | None = None,
        preflight: bool = True,
        searchable_pdf: Path | None = None,
        dpi: int = 300,
        rotate_threshold: float = 2,
        language: str | None = None,
        ocrmypdf_timeout: int = 1800,
        tesseract_timeout: int = 300,
        tessdata_dir: Path | None = None,
        memory_mib: float | None = None,
        document_timeout: float | None = None,
        max_input_bytes: int | None = None,
        max_pages: int | None = None,
    ) -> None:
        cores = (
            available_cores if available_cores is not None else (os.cpu_count() or 1)
        )
        if isinstance(cores, bool) or not isinstance(cores, int) or cores <= 0:
            cores = 1
        self.capacity = capacity or OcrCapacity(cores)
        self.ocr_jobs = min(self.capacity.cores, ocr_jobs_for(document_workers, cores))
        self.preflight = preflight
        self.searchable_pdf = (
            Path(searchable_pdf) if searchable_pdf is not None else None
        )
        self.dpi = dpi
        self.rotate_threshold = rotate_threshold
        self.language = language
        self.ocrmypdf_timeout = ocrmypdf_timeout
        self.tesseract_timeout = tesseract_timeout
        self.tessdata_dir = (
            Path(tessdata_dir).resolve() if tessdata_dir is not None else None
        )
        self.memory_mib = memory_mib
        self.document_timeout = document_timeout
        self.max_input_bytes = max_input_bytes
        self.max_pages = max_pages

    def document(
        self,
        pdf_path: Path,
        *,
        raster_threshold: float = 0.5,
        selected: Sequence[int] | None = None,
        expected_sha256: str | None = None,
        original_pages: Sequence[str] | None = None,
        require_complete_recognition: bool = True,
    ):
        from ._vellric import document_job
        from .pdf_tools import inspection_from_bundle

        options = [
            "--ocr",
            "auto",
            "--structure",
            "native",
            "--jobs",
            str(self.ocr_jobs),
            "--raster-threshold",
            str(raster_threshold),
            "--preflight",
            "on" if self.preflight else "off",
            "--dpi",
            str(self.dpi),
            "--language",
            self.language or "eng",
            "--page-timeout-seconds",
            str(self.tesseract_timeout),
            "--preflight-timeout-seconds",
            str(self.ocrmypdf_timeout),
            "--rotate-threshold",
            str(self.rotate_threshold),
        ]
        if self.tessdata_dir is not None:
            options += ["--tessdata-dir", str(self.tessdata_dir)]
        memory = self.memory_mib
        if memory is None and "DRAWBRIDGE_VELLRIC_MEMORY_MIB" not in os.environ:
            memory = 2048 + 512 * (self.ocr_jobs - 1)
        for flag, value in [
            ("--memory-mib", memory),
            ("--max-input-bytes", self.max_input_bytes),
            ("--max-pages", self.max_pages),
        ]:
            if value is not None:
                options += [flag, str(value)]
        deadline = self.document_timeout
        if deadline is None and "DRAWBRIDGE_VELLRIC_TIMEOUT_SECONDS" not in os.environ:
            page_budget = (
                len(selected)
                if selected is not None
                else len(original_pages)
                if original_pages is not None
                else 1
            )
            deadline = max(
                3600,
                self.ocrmypdf_timeout
                + 4 * self.tesseract_timeout * max(1, page_budget) / self.ocr_jobs,
            )
        if selected is not None:
            options += ["--ocr-pages", ",".join(map(str, sorted(set(selected))))]
        if self.searchable_pdf is not None:
            options += ["--searchable-pdf"]
        with self.capacity.reserve(self.ocr_jobs):
            with document_job(
                Path(pdf_path),
                "convert",
                *options,
                expected_sha256=expected_sha256,
                timeout=deadline,
            ) as bundle:
                m = bundle.manifest
                if require_complete_recognition and m["outstanding_candidates"]:
                    raise ConversionOperationalError(
                        "Vellric left OCR candidates outstanding"
                    )
                inspection = inspection_from_bundle(bundle)
                if original_pages is not None and inspection.page_texts != tuple(
                    original_pages
                ):
                    raise ConversionOperationalError(
                        "PDF/native text changed after inspection"
                    )
                recovered = tuple(
                    RecoveredPage(
                        p["number"],
                        bundle.text(p),
                        p["ocr"]["rotation"],
                        p["ocr"]["score"],
                        p["ocr"]["bands"],
                    )
                    for p in m["pages"]
                    if p["method"] == "ocr"
                )
                if selected is not None and [p.page for p in recovered] != sorted(
                    set(selected)
                ):
                    raise ConversionOperationalError(
                        "Vellric recognition selection mismatch"
                    )
                searchable = None
                if self.searchable_pdf is not None:
                    if "searchable.pdf" not in {f["path"] for f in m["files"]}:
                        raise ConversionOperationalError(
                            "Vellric searchable derivative missing"
                        )
                    self.searchable_pdf.parent.mkdir(parents=True, exist_ok=True)
                    # Retain a complete validated derivative; never expose a partial copy.
                    with tempfile.NamedTemporaryFile(
                        dir=self.searchable_pdf.parent, delete=False
                    ) as temporary:
                        staged = Path(temporary.name)
                        try:
                            with (bundle.root / "searchable.pdf").open("rb") as src:
                                shutil.copyfileobj(src, temporary)
                            temporary.flush()
                            os.fsync(temporary.fileno())
                        except BaseException:
                            staged.unlink(missing_ok=True)
                            raise
                    try:
                        os.replace(staged, self.searchable_pdf)
                    finally:
                        staged.unlink(missing_ok=True)
                    searchable = self.searchable_pdf
                facts = {
                    "tool": m["tool"],
                    "behavior": m["behavior"],
                    "processing_fingerprint": m["provenance"]["processing_fingerprint"],
                }
                return (
                    inspection,
                    OcrResult(bundle.texts, recovered, searchable, facts),
                    facts,
                )

    def extract(
        self, pdf_path: Path, selected: Sequence[int], original_pages: Sequence[str]
    ) -> OcrResult:
        selected = sorted(set(selected))
        if not selected:
            return OcrResult(tuple(original_pages), ())
        if any(
            type(n) is not int or not 1 <= n <= len(original_pages) for n in selected
        ):
            raise ValueError("selected page out of range")
        inspection, result, _ = self.document(
            pdf_path,
            selected=selected,
            original_pages=original_pages,
            require_complete_recognition=False,
        )
        if inspection.page_texts != tuple(original_pages):
            raise ConversionOperationalError("PDF/native text changed after inspection")
        return result
