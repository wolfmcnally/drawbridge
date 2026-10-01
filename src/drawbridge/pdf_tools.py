"""Document-level Vellric jobs and ordinary artifact readers.

Drawbridge imports no PDF engine. The real lock exports remain for existing
clients' own native calls; subprocess jobs do not use or depend on that lock.
"""

from __future__ import annotations

import functools
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .errors import (
    ConversionOperationalError,
    DrawbridgeError,
    InherentlyUnprocessableError,
)
from .images import image_jpeg as image_jpeg


@dataclass(frozen=True)
class PdfInspection:
    openable: bool
    is_encrypted: bool | None
    needs_password: bool | None
    page_count: int | None
    has_text_layer: bool | None
    page_texts: tuple[str, ...] | None
    source_sha256: str | None = field(default=None, repr=False, compare=False)
    raster_coverage: tuple[float, ...] | None = field(default=None, repr=False, compare=False)
    geometry: tuple[dict, ...] | None = field(default=None, repr=False, compare=False)
    processor: dict = field(default_factory=dict, repr=False, compare=False)

    def as_dict(self, *, include_page_texts: bool = False) -> dict:
        data = {
            k: getattr(self, k)
            for k in [
                "openable",
                "is_encrypted",
                "needs_password",
                "page_count",
                "has_text_layer",
            ]
        }
        if include_page_texts:
            data["page_texts"] = list(self.page_texts) if self.page_texts is not None else None
        return data


UNKNOWN_INSPECTION = PdfInspection(False, None, None, None, None, None)


class MalformedPdfError(DrawbridgeError):
    def __init__(self, message: str, inspection: PdfInspection | None = None):
        self.inspection = inspection or UNKNOWN_INSPECTION
        super().__init__(message)


class EncryptedPdfError(MalformedPdfError, InherentlyUnprocessableError):
    blocked_reason = "password-protected"


class DegeneratePdfError(MalformedPdfError, InherentlyUnprocessableError):
    blocked_reason = "degenerate-input"


class PdfOpenOperationalError(DrawbridgeError):
    def __init__(self, message: str):
        self.inspection = UNKNOWN_INSPECTION
        super().__init__(message)


class PdfReadOperationalError(DrawbridgeError):
    def __init__(self, message: str, inspection: PdfInspection):
        self.inspection = inspection
        super().__init__(message)


PDF_LOCK = threading.RLock()


def pdf_locked(function):
    """Retained real reentrant custody lock for consumers' own native objects.

    It imports no PDF engine and is not used to serialize Vellric processes.
    Removing it awaits those clients' source migrations; it is never a no-op.
    """
    import traceback

    @functools.wraps(function)
    def locked(*args, **kwargs):
        with PDF_LOCK:
            try:
                return function(*args, **kwargs)
            except BaseException as exc:
                seen = set()
                while exc is not None and id(exc) not in seen:
                    seen.add(id(exc))
                    traceback.clear_frames(exc.__traceback__)
                    exc = exc.__cause__ or exc.__context__
                raise

    return locked


def inspection_from_bundle(bundle) -> PdfInspection:
    m = bundle.manifest
    i = m["inspection"]
    pages = m["pages"]
    return PdfInspection(
        i["openable"],
        i["is_encrypted"],
        i["needs_password"],
        i["page_count"],
        i["has_text_layer"],
        tuple(bundle.text(p, "native") for p in pages),
        m["source"]["sha256"],
        tuple(p["raster_coverage"] for p in pages),
        tuple(p["geometry"] for p in pages),
        {
            "tool": m["tool"],
            "behavior": m["behavior"],
            "processing_fingerprint": m["provenance"]["processing_fingerprint"],
        },
    )


def page_texts(pdf_path: Path) -> PdfInspection:
    from ._vellric import document_job

    with document_job(Path(pdf_path), "inspect") as bundle:
        return inspection_from_bundle(bundle)


def has_text_layer(pdf_path: Path) -> bool:
    return bool(page_texts(pdf_path).has_text_layer)


def ocr_page_numbers(
    pdf_path: Path,
    *,
    raster_threshold: float = 0.5,
    inspection: PdfInspection | None = None,
) -> list[int]:
    from ._vellric import sha256_file

    if not 0 < raster_threshold <= 1:
        raise ValueError("raster_threshold must be in (0, 1]")
    current = (
        inspection
        if inspection is not None and inspection.raster_coverage is not None
        else page_texts(Path(pdf_path))
    )
    if (
        inspection is not None
        and inspection.page_texts is not None
        and len(inspection.page_texts) != current.page_count
    ):
        raise ValueError("inspection page count does not match the document")
    if current.source_sha256 != sha256_file(Path(pdf_path)):
        raise ConversionOperationalError("PDF changed after complete inspection")
    return [
        n
        for n, (text, coverage) in enumerate(
            zip(current.page_texts, current.raster_coverage, strict=True), 1
        )
        if not text.strip() or coverage >= raster_threshold
    ]


def page_image_coverage(pdf_path: Path) -> list[float]:
    return list(page_texts(Path(pdf_path)).raster_coverage)


def page_size(pdf_path: Path, page_number: int) -> tuple[float, float]:
    i = page_texts(Path(pdf_path))
    if not 1 <= page_number <= i.page_count:
        raise ValueError("page number out of range")
    rect = i.geometry[page_number - 1]["displayed_rect"]
    return rect[2] - rect[0], rect[3] - rect[1]


def render_page_png(
    pdf_path: Path,
    page_number: int,
    target: Path,
    *,
    dpi: float = 300,
    rotation: int = 0,
    clip: tuple[float, float, float, float] | None = None,
) -> Path:
    """Read a complete render job; clip uses displayed-page top-left points."""
    import shutil

    from ._vellric import document_job

    if type(page_number) is not int or page_number < 1:
        raise ValueError("page number out of range")
    import math

    if rotation not in {0, 90, 180, 270} or not math.isfinite(dpi) or dpi <= 0:
        raise ValueError("invalid render rotation/resolution")
    formats = {
        ".pnm": "pnm",
        ".ppm": "pnm",
        ".png": "png",
        ".jpg": "jpeg",
        ".jpeg": "jpeg",
    }
    if target.suffix.lower() not in formats:
        raise ValueError("unsupported render image suffix")
    format = formats[target.suffix.lower()]
    opts = [
        "--pages",
        str(page_number),
        "--dpi",
        str(dpi),
        "--rotation",
        str(rotation),
        "--format",
        format,
    ]
    if clip is not None:
        opts += ["--clip", ",".join(map(str, clip))]
    inspection = page_texts(Path(pdf_path))
    if page_number > inspection.page_count:
        raise ValueError("page number out of range")
    with document_job(Path(pdf_path), "render", *opts) as bundle:
        renders = bundle.manifest["pages"][page_number - 1].get("renders", [])
        if len(renders) != 1:
            raise ConversionOperationalError("Vellric render job returned no single-page image")
        if renders[0]["path"] not in {f["path"] for f in bundle.manifest["files"]}:
            raise ConversionOperationalError("Unlisted render artifact")
        shutil.copyfile(bundle.root / renders[0]["path"], target)
    return target


def join_pages(pages: Sequence[str]) -> str:
    return "\f".join(pages)


@dataclass(frozen=True)
class Run:
    text: str
    size: float
    bold: bool = False
    italic: bool = False
    mono: bool = False
    link: str | None = None


@dataclass(frozen=True)
class Line:
    runs: tuple[Run, ...]
    bbox: tuple[float, float, float, float]

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


@dataclass(frozen=True)
class Table:
    bbox: tuple[float, float, float, float]
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class PageLayout:
    blocks: tuple[tuple[Line, ...], ...]
    tables: tuple[Table, ...] = ()


def page_layouts(
    pdf_path: Path, page_numbers: Sequence[int], *, expected_sha256: str | None = None
) -> dict[int, PageLayout]:
    """Read interoperable layout artifacts from one complete inspect job."""
    from ._vellric import _json, document_job

    result = {}
    with document_job(
        Path(pdf_path), "inspect", "--layout", expected_sha256=expected_sha256
    ) as bundle:
        for number in page_numbers:
            if not 1 <= number <= bundle.manifest["page_count"]:
                raise ValueError("page number out of range")
            page = bundle.manifest["pages"][number - 1]
            try:
                layout = _json((bundle.root / page["files"]["layout"]).read_bytes().decode("utf-8"))
                if layout.get("schema") != "vellric.layout/1.0":
                    raise ValueError("unsupported layout artifact")
                interpreted = layout["interpreted"]
                result[number] = PageLayout(
                    tuple(
                        tuple(
                            Line(
                                tuple(Run(**r) for r in line["runs"]),
                                tuple(line["bbox"]),
                            )
                            for line in block
                        )
                        for block in interpreted["blocks"]
                    ),
                    tuple(
                        Table(tuple(t["bbox"]), tuple(tuple(row) for row in t["rows"]))
                        for t in layout["tables"]
                    ),
                )
            except (
                KeyError,
                TypeError,
                ValueError,
                AttributeError,
                OSError,
                UnicodeError,
            ) as exc:
                raise ConversionOperationalError("Invalid Vellric layout artifact") from exc
    return result


# Kept at this public module path for callers; implementation is non-PDF Pillow.


@dataclass(frozen=True)
class ImageFingerprint:
    width: int
    height: int
    pixels: bytes
    pixel_sha256: str
    difference_hash: int


def _canonical_fingerprint(record: dict) -> dict:
    import re

    if (
        record.get("algorithm") != "mupdf-rgb-dhash-9x8/v1"
        or record.get("channels") != 3
        or type(record.get("difference_hash")) is not int
        or not 0 <= record["difference_hash"] < 2**64
        or any(type(record.get(k)) is not int or record[k] <= 0 for k in ("width", "height"))
        or not isinstance(record.get("pixel_sha256"), str)
        or not re.fullmatch("[0-9a-f]{64}", record["pixel_sha256"])
    ):
        raise ConversionOperationalError("Vellric native fingerprint is invalid")
    return record


def _fingerprint_pixels(path: Path, record: dict) -> bytes:
    import hashlib

    from PIL import Image

    with Image.open(path) as image:
        if image.mode != "RGB" or image.size != (record["width"], record["height"]):
            raise ConversionOperationalError("Image pixels contradict canonical dimensions")
        pixels = image.tobytes()
    shape = f"{record['width']}:{record['height']}:3:".encode()
    if hashlib.sha256(shape + pixels).hexdigest() != record["pixel_sha256"]:
        raise ConversionOperationalError("Image pixels contradict canonical fingerprint")
    return pixels


def page_fingerprints(pdf_path: Path) -> tuple[tuple[str, ...], tuple[int, ...]]:
    """Whole-document native page fingerprints, including forms and annotations."""
    from ._vellric import document_job

    with document_job(Path(pdf_path), "render", "--dpi", "144", "--pixel-fingerprints") as bundle:
        records = []
        for page in bundle.manifest["pages"]:
            renders = page.get("renders", [])
            if len(renders) != 1:
                raise ConversionOperationalError("Missing canonical page raster")
            record = _canonical_fingerprint(renders[0].get("fingerprint", {}))
            _fingerprint_pixels(bundle.root / renders[0]["path"], record)
            records.append(record)
        return (
            tuple(r["pixel_sha256"] for r in records),
            tuple(r["difference_hash"] for r in records),
        )


def canonical_image(
    path: Path, *, width: int | None = None, height: int | None = None
) -> ImageFingerprint:
    """Read a complete normalized image artifact; the native engine remains external."""
    from ._vellric import document_job

    options = (
        [] if width is None and height is None else ["--width", str(width), "--height", str(height)]
    )
    with document_job(Path(path), "image", *options) as bundle:
        page = bundle.manifest["pages"][0]
        record = _canonical_fingerprint(page.get("fingerprint", {}))
        pixels = _fingerprint_pixels(bundle.root / page["files"]["image"], record)
        return ImageFingerprint(
            record["width"],
            record["height"],
            pixels,
            record["pixel_sha256"],
            record["difference_hash"],
        )


def materialize_pdf_range(parent: Path, destination: Path, start: int, end: int) -> Path:
    """Validated deterministic PDF derivative for a complete inclusive page range."""
    import shutil

    from ._vellric import document_job

    if any(type(v) is not int for v in (start, end)) or not 1 <= start <= end:
        raise ValueError("page range lies outside the document")
    with document_job(
        Path(parent),
        "render",
        "--pages",
        f"{start}-{end}",
        "--dpi",
        "72",
        "--subset-pdf",
    ) as bundle:
        subset = bundle.manifest.get("pdf_subset")
        if (
            not isinstance(subset, dict)
            or subset.get("path") != "subset.pdf"
            or (
                subset.get("pages") != list(range(start, end + 1))
                or "subset.pdf" not in {r["path"] for r in bundle.manifest["files"]}
            )
        ):
            raise ConversionOperationalError("PDF subset contradicts requested range")
        destination = Path(destination)
        if destination.is_symlink():
            raise ValueError("PDF subset destination must not be a symlink")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bundle.root / "subset.pdf", destination)
    return destination
