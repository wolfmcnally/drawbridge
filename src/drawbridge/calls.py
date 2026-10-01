"""Every paid call a conversion makes, reported to whoever is listening.

A conversion may call a model to describe images, structure a document or refine a transcript, and
a transcription service to transcribe a recording. Each such call produces one ``ModelCall``: what
it was for, where it went, what it used and, when the provider says, what it cost. A caller that
does cost accounting wraps its conversions in ``record_calls``; the calls are reported to its
recorder in the thread that made them, including threads the conversion starts itself.

Nothing is reported for answers served from a cache: no call was made.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable, Iterator

from .profile import Endpoint


@dataclass(frozen=True)
class ModelCall:
    """One call to a paid model or service.

    ``stage`` is the profile stage (``description``, ``structure``, ``transcript_refinement``,
    ``transcription``, ``audio_cleanup``). ``outcome`` is ``succeeded``, ``failed`` (the call was
    made and may have been charged), or ``reused`` (a kept result stood in for the call, so nothing
    was charged). Token counts and ``reported_cost_usd`` are what the provider's response said, or
    ``None`` when it said nothing. Audio calls carry the recording's length and the rate the profile
    declares for that endpoint, from which their cost is computed.
    """

    stage: str
    endpoint: str | None
    model: str | None
    outcome: str
    duration_seconds: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reported_cost_usd: str | None = None
    audio_seconds: float | None = None
    declared_usd_per_audio_hour: float | None = None
    failure: str | None = None


CallRecorder = Callable[[ModelCall], None]

_RECORDER: ContextVar[CallRecorder | None] = ContextVar("drawbridge_call_recorder", default=None)


@contextmanager
def record_calls(recorder: CallRecorder) -> Iterator[None]:
    """Report every call made in this context, and in threads started from it, to ``recorder``."""
    token = _RECORDER.set(recorder)
    try:
        yield
    finally:
        _RECORDER.reset(token)


def report(call: ModelCall) -> None:
    recorder = _RECORDER.get()
    if recorder is not None:
        recorder(call)


def _usage(body: Any) -> tuple[int | None, int | None, str | None]:
    usage = body.get("usage") if isinstance(body, dict) else None
    if not isinstance(usage, dict):
        return None, None, None

    def count(key: str) -> int | None:
        value = usage.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    cost = usage.get("cost")
    return count("prompt_tokens"), count("completion_tokens"), (
        str(cost) if isinstance(cost, (int, float, str)) and not isinstance(cost, bool) else None)


def chat_completion(endpoint: Endpoint, model: str, payload: dict[str, Any], *, stage: str) -> dict[str, Any]:
    """POST one OpenAI-compatible chat completion and report it. Returns the response body; raises
    what the transport or the body raises, after reporting the failed call."""
    body_payload = dict(payload, model=model)
    if "openrouter.ai" in (endpoint.base_url or ""):
        body_payload["usage"] = {"include": True}  # OpenRouter reports the charged cost only when asked
    headers = {"Content-Type": "application/json"}
    if endpoint.api_key_env:
        headers["Authorization"] = f"Bearer {endpoint.key()}"
    request = urllib.request.Request((endpoint.base_url or "").rstrip("/") + "/chat/completions",
                                     data=json.dumps(body_payload).encode(), headers=headers)
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=endpoint.timeout_seconds) as response:
            body = json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        report(ModelCall(stage, endpoint.name, model, "failed", round(time.monotonic() - started, 3),
                         failure=type(exc).__name__))
        raise
    prompt, completion, cost = _usage(body)
    report(ModelCall(stage, endpoint.name, model, "succeeded", round(time.monotonic() - started, 3),
                     prompt_tokens=prompt, completion_tokens=completion, reported_cost_usd=cost))
    return body
