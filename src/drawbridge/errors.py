"""Typed failure taxonomy.

Membership in an exception class is the declaration of blast radius. A caller
processing many documents treats every ``DrawbridgeError`` as local to one
document; anything else is a defect in the caller's environment or code.

Two families matter for routing:

* ``InherentlyUnprocessableError`` marks an input property no retry can repair
  (a password we do not have, a document with no pages). Callers should record
  a terminal ``blocked`` outcome keyed by the input's content hash so the same
  bytes can be re-admitted later if the blocker is lifted.
* Everything else is operational or malformed input and should be recorded as
  ``failed``: a replacement file, a repaired environment, or a retry may succeed.
"""

from __future__ import annotations

from typing import ClassVar, Literal

BlockedReason = Literal["password-protected", "degenerate-input"]
BLOCKED_REASONS: frozenset[str] = frozenset({"password-protected", "degenerate-input"})


class DrawbridgeError(Exception):
    """Base class for every document-local failure this package raises."""


class InherentlyUnprocessableError(DrawbridgeError):
    """The input has a property that retrying cannot repair."""

    blocked_reason: ClassVar[str]


class ConverterUnavailable(DrawbridgeError):
    """A required independently installed converter cannot be started."""


class OcrOperationalError(DrawbridgeError):
    """OCR cannot run because an external tool is unavailable or timed out."""


class ConversionOperationalError(DrawbridgeError):
    """One document cannot be converted by an otherwise healthy pipeline."""


class OcrPreflightError(ConversionOperationalError):
    """The ocrmypdf preflight refused the document."""

    def __init__(self, message: str, *, returncode: int | None = None, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(message)


class MediaTypeError(DrawbridgeError):
    """The input is not a PDF or its media type could not be established."""


class MirrorFormatError(DrawbridgeError, ValueError):
    """A mirror document does not satisfy the header contract."""


def blocked_reason(exc: BaseException) -> str | None:
    """Classify only the explicit inherent-input hierarchy; everything else is None."""
    if not isinstance(exc, InherentlyUnprocessableError):
        return None
    reason = exc.blocked_reason
    if reason not in BLOCKED_REASONS:
        raise ValueError("inherently unprocessable exception has an unknown reason")
    return reason
