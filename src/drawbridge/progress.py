"""How far a conversion has got, reported to whoever is listening.

Some steps work through a document unit by unit and can take a long time: recognising scanned pages,
structuring sections through a model, reviewing a transcript's windows, transcribing a recording. Each
reports ``(step, done, total)`` as a unit finishes, so a caller running many conversions can say which
document is at which step and how far through. A caller wraps a conversion in ``report_progress``; the
reports reach its listener in the thread that made them, including threads the conversion starts itself.
Reporting never changes what a conversion produces, and a listener that fails is not the conversion's
failure.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterator

ProgressListener = Callable[[str, int, int], None]

_LISTENER: ContextVar[ProgressListener | None] = ContextVar("drawbridge_progress_listener", default=None)


@contextmanager
def report_progress(listener: ProgressListener) -> Iterator[None]:
    """Report every step's progress in this context, and in threads started from it, to ``listener``."""
    token = _LISTENER.set(listener)
    try:
        yield
    finally:
        _LISTENER.reset(token)


def advance(step: str, done: int, total: int) -> None:
    """``done`` of ``total`` units of ``step`` have finished."""
    listener = _LISTENER.get()
    if listener is None:
        return
    try:
        listener(step, done, total)
    except Exception:  # noqa: BLE001 - a listener's failure is never the conversion's
        pass
