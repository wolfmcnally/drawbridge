"""Content-based identification: the processability gate.

Identify runs once per document and establishes everything later stages
consume: the media type (from bytes, never from the filename), whether the PDF
opens, whether it needs a password, its page count, and the native text of
every page. Later stages never re-derive any of this from a weaker proxy.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .errors import (
    ConversionOperationalError,
    ConverterUnavailable,
    DrawbridgeError,
    MediaTypeError,
)
from .pdf_tools import (
    DegeneratePdfError,
    EncryptedPdfError,
    MalformedPdfError,
    PdfInspection,
    PdfOpenOperationalError,
    PdfReadOperationalError,
    page_texts,
)

PDF_MEDIA_TYPE = "application/pdf"
Outcome = Literal["processable", "blocked", "failed"]


@dataclass(frozen=True)
class IdentifyResult:
    path: str
    media_type: str | None
    flags: tuple[str, ...]
    outcome: Outcome
    code: str | None
    message: str | None
    blocked_reason: str | None
    inspection: PdfInspection | None

    @property
    def processable(self) -> bool:
        return self.outcome == "processable"

    def as_dict(self, *, include_page_texts: bool = False) -> dict:
        return {
            "path": self.path,
            "media_type": self.media_type,
            "flags": list(self.flags),
            "outcome": self.outcome,
            "code": self.code,
            "message": self.message,
            "blocked_reason": self.blocked_reason,
            "inspection": (
                self.inspection.as_dict(include_page_texts=include_page_texts)
                if self.inspection is not None
                else None
            ),
        }

    def raise_for_outcome(self) -> None:
        """Re-raise the typed error a non-processable result stands for."""
        if self.outcome == "processable":
            return
        inspection = self.inspection
        message = self.message or self.code or "identify failed"
        if self.code == "password-required":
            raise EncryptedPdfError(message, inspection)
        if self.code == "zero-page":
            raise DegeneratePdfError(message, inspection)
        if self.code == "malformed-pdf":
            raise MalformedPdfError(message, inspection)
        if self.code == "pdf-read-operational":
            raise PdfReadOperationalError(
                message, inspection or PdfInspection(True, None, None, None, None, None)
            )
        if self.code == "pdf-open-operational":
            raise PdfOpenOperationalError(message)
        if self.code == "pdf-processing-operational":
            raise ConversionOperationalError(message)
        if self.code in {"not-a-pdf", "media-type-unknown"}:
            raise MediaTypeError(message)
        raise DrawbridgeError(message)


def sniff_media_type(path: Path) -> tuple[str, list[str]]:
    """Classify by content. Uses ``file(1)`` (libmagic) when present, else magic bytes.

    Returns the media type and a list of flags describing degraded detection.
    The filename suffix is never consulted.
    """
    flags: list[str] = []
    if shutil.which("file"):
        try:
            result = subprocess.run(
                ["file", "--mime-type", "--brief", str(path)],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            media = result.stdout.strip().split(";", 1)[0]
            if media and "/" in media and media != "application/octet-stream":
                return refine_media_type(path, media), flags
        except (OSError, subprocess.SubprocessError):
            flags.append("libmagic-unavailable")
    else:
        flags.append("libmagic-unavailable")
    with path.open("rb") as handle:
        head = handle.read(1024)
    # The PDF specification tolerates junk before the header within the first
    # 1024 bytes, which is exactly what libmagic also allows.
    if b"%PDF-" in head:
        return PDF_MEDIA_TYPE, flags
    flags.append("media-type-unknown")
    return "application/octet-stream", flags


def _failed(
    path: Path,
    media: str | None,
    flags: list[str],
    code: str,
    message: str,
    inspection=None,
) -> IdentifyResult:
    return IdentifyResult(
        str(path), media, tuple(flags), "failed", code, message, None, inspection
    )


def identify(path: Path | str) -> IdentifyResult:
    """Establish processability without raising for document conditions.

    Programming errors still raise; document conditions become a result whose
    ``outcome`` is ``blocked`` (inherent) or ``failed`` (operational or malformed).
    """
    path = Path(path)
    if not path.is_file():
        return _failed(
            path, None, [], "input-missing", f"input is not a readable file: {path}"
        )
    try:
        media, flags = sniff_media_type(path)
    except OSError as exc:
        return _failed(path, None, [], "input-unreadable", str(exc))
    if media != PDF_MEDIA_TYPE:
        code = "media-type-unknown" if "media-type-unknown" in flags else "not-a-pdf"
        return _failed(
            path,
            media,
            flags,
            code,
            f"input media type is {media}, not {PDF_MEDIA_TYPE}",
        )
    try:
        inspection = page_texts(path)
    except EncryptedPdfError as exc:
        return IdentifyResult(
            str(path),
            media,
            tuple(flags),
            "blocked",
            "password-required",
            str(exc),
            "password-protected",
            exc.inspection,
        )
    except DegeneratePdfError as exc:
        return IdentifyResult(
            str(path),
            media,
            tuple(flags),
            "blocked",
            "zero-page",
            str(exc),
            "degenerate-input",
            exc.inspection,
        )
    except MalformedPdfError as exc:
        return _failed(path, media, flags, "malformed-pdf", str(exc), exc.inspection)
    except PdfReadOperationalError as exc:
        return _failed(
            path, media, flags, "pdf-read-operational", str(exc), exc.inspection
        )
    except (ConverterUnavailable, PdfOpenOperationalError, OSError) as exc:
        return _failed(
            path,
            media,
            flags,
            "pdf-open-operational",
            str(exc),
            getattr(exc, "inspection", None),
        )
    except ConversionOperationalError as exc:
        return _failed(
            path,
            media,
            flags,
            "pdf-processing-operational",
            str(exc),
            getattr(exc, "inspection", None),
        )
    return IdentifyResult(
        str(path), media, tuple(flags), "processable", None, None, None, inspection
    )


# Containers libmagic can only name generically. The parts a package actually carries decide
# which document it is; the filename suffix is never consulted.
_OOXML_PARTS: tuple[tuple[str, str], ...] = (
    (
        "word/document.xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    (
        "xl/workbook.xml",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    (
        "ppt/presentation.xml",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ),
)
_OLE_STREAMS: tuple[tuple[str, str], ...] = (
    ("WordDocument", "application/msword"),
    ("Workbook", "application/vnd.ms-excel"),
    ("Book", "application/vnd.ms-excel"),
)
_GENERIC_ZIP = frozenset({"application/zip", "application/x-zip-compressed"})
_GENERIC_OLE = frozenset(
    {"application/CDFV2", "application/x-ole-storage", "application/vnd.ms-office"}
)
_MAIL_HEADERS = frozenset(
    {"from", "to", "subject", "date", "message-id", "mime-version", "received"}
)


def _ooxml_media_type(path: Path) -> str | None:
    import zipfile

    try:
        with zipfile.ZipFile(path) as archive:
            names = frozenset(archive.namelist())
    except (OSError, zipfile.BadZipFile):
        return None
    if "[Content_Types].xml" not in names:
        return None
    return next((media for part, media in _OOXML_PARTS if part in names), None)


def _ole_media_type(path: Path) -> str | None:
    import olefile

    try:
        if not olefile.isOleFile(str(path)):
            return None
        with olefile.OleFileIO(str(path)) as ole:
            return next(
                (media for stream, media in _OLE_STREAMS if ole.exists(stream)), None
            )
    except OSError:
        return None


def _looks_like_mail(path: Path) -> bool:
    with path.open("rb") as handle:
        head = handle.read(8192).decode("utf-8", errors="replace")
    block = head.replace("\r\n", "\n").split("\n\n", 1)[0]
    names = {
        line.split(":", 1)[0].strip().lower()
        for line in block.split("\n")
        if ":" in line and not line[:1].isspace()
    }
    return len(names & _MAIL_HEADERS) >= 3


def refine_media_type(path: Path, media: str) -> str:
    """Resolve a generic container or text type to the document it actually is, by content."""
    if media in _GENERIC_ZIP:
        return _ooxml_media_type(path) or media
    if media in _GENERIC_OLE or media in {
        "application/msword",
        "application/vnd.ms-excel",
    }:
        return _ole_media_type(path) or media
    if media == "text/plain" and _looks_like_mail(path):
        return "message/rfc822"
    return media
