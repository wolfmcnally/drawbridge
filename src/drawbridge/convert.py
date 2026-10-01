"""One PDF in, one verified Markdown mirror out."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

from .errors import ConversionOperationalError, InherentlyUnprocessableError
from .identify import IdentifyResult, identify
from .mirror import Mirror, build_header, page_body, title_from_name
from .ocr import CliOcrBackend, OcrBackend, OcrResult
from .orientation import RecoveredPage
from .pdf_tools import ocr_page_numbers

METHOD_NATIVE = "pymupdf-text"
METHOD_OCR = "ocr"


@dataclass(frozen=True)
class ConversionOptions:
    title: str | None = None
    mirror_of: str | int | None = None
    acquired_at: str | None = None
    acquisition_method: str = "drawbridge-cli"
    acquired_from: str | None = None
    agent: str = "drawbridge"
    raster_threshold: float = 0.5
    verify: tuple[str, ...] = ()
    extensions: dict[str, Any] | None = None

    def with_verify(self, flags: Iterable[str]) -> "ConversionOptions":
        return replace(self, verify=(*self.verify, *flags))


@dataclass(frozen=True)
class ConversionResult:
    mirror: Mirror
    identify: IdentifyResult
    method: str
    selected_pages: tuple[int, ...]
    recovered: tuple[RecoveredPage, ...] = ()
    searchable_pdf: Path | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def page_count(self) -> int:
        return len(self.identify.inspection.page_texts or ())


def convert_pdf(
    pdf_path: Path | str,
    *,
    ocr: OcrBackend | None,
    options: ConversionOptions | None = None,
    identify_result: IdentifyResult | None = None,
) -> ConversionResult:
    """Convert one PDF. Raises a typed ``DrawbridgeError`` for every document-local failure.

    ``ocr=None`` means "no OCR available": a document with scan-like pages then
    fails closed instead of producing a mirror with silently empty pages.
    """
    pdf_path = Path(pdf_path)
    options = options or ConversionOptions()
    ident = identify_result or identify(pdf_path)
    if not ident.processable:
        ident.raise_for_outcome()
    assert ident.inspection is not None and ident.inspection.page_texts is not None
    pages = list(ident.inspection.page_texts)
    expected = len(pages)
    selected = tuple(
        ocr_page_numbers(
            pdf_path,
            raster_threshold=options.raster_threshold,
            inspection=ident.inspection,
        )
    )
    recovered: tuple[RecoveredPage, ...] = ()
    searchable: Path | None = None
    processor = ident.inspection.processor
    if selected:
        if ocr is None:
            raise ConversionOperationalError(
                "PDF has pages requiring OCR and OCR is unavailable"
            )
        try:
            if isinstance(ocr, CliOcrBackend):
                _, result, _ = ocr.document(
                    pdf_path,
                    selected=selected,
                    raster_threshold=options.raster_threshold,
                    expected_sha256=ident.inspection.source_sha256,
                    original_pages=pages,
                )
            else:
                result: OcrResult = ocr.extract(pdf_path, selected, pages)
        except InherentlyUnprocessableError as exc:
            raise ConversionOperationalError(
                "PDF OCR produced an unusable derivative"
            ) from exc
        if len(result.pages) != expected:
            raise ConversionOperationalError("OCR returned an incomplete page sequence")
        pages = list(result.pages)
        recovered = tuple(result.recovered)
        searchable = result.searchable_pdf
        processor = result.processor or processor
        method = METHOD_OCR
    else:
        method = METHOD_NATIVE
    extra: dict[str, Any] = {
        "page_count": expected,
        "ocr_pages": [page.as_dict() for page in recovered],
    }
    if processor:
        extra["pdf_processor"] = processor
    if method == METHOD_OCR and not recovered:
        extra["ocr_pages"] = [{"page": number} for number in selected]
    header = build_header(
        pdf_path,
        method=method,
        mirror_of=options.mirror_of,
        acquired_at=options.acquired_at,
        acquisition_method=options.acquisition_method,
        acquired_from=options.acquired_from,
        agent=options.agent,
        verify=options.verify,
        extra=extra,
        extensions=options.extensions,
    )
    if (
        ident.inspection.source_sha256
        and header["content_hash"] != "sha256:" + ident.inspection.source_sha256
    ):
        raise ConversionOperationalError("PDF changed after complete conversion")
    title = options.title or title_from_name(pdf_path.name)
    mirror = Mirror(header, page_body(title, pages))
    return ConversionResult(
        mirror, ident, method, selected, recovered, searchable, extra
    )
