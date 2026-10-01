"""The image description stage: what an image shows, in a model's words, kept apart from the evidence.

This is the one stage where a model writes prose, so the prose is fenced: it lives in its own
``## Description`` section, the header names the model and endpoint that wrote it, and the flag
``description-model-written`` stays in ``verify``. The recognised text in ``## OCR`` is never touched.
"""

from __future__ import annotations

import base64
import hashlib
import re
import urllib.error
from pathlib import Path
from typing import Any, Callable

from .calls import chat_completion
from .errors import ConversionOperationalError, DrawbridgeError
from .profile import Endpoint, Plan, Profile, ProfileError
from .structure import Cache

STAGE = "image_description"
SECTION = "Description"
WRITTEN, PENDING = "description-model-written", "description-pending"
DEFAULT_MAX_WORDS = 200
PROMPT = """Describe this image for someone who cannot see it, in at most {max_words} words of plain prose.
Say what kind of image it is (photograph, screenshot, chart, diagram, map, form, handwriting), what it
shows, and any visible text that matters to understanding it. Describe only what is visible. Do not
name a person from their appearance, and do not guess at anything the image does not show."""

Describer = Callable[[bytes], str]


class DescriptionError(ConversionOperationalError):
    """The endpoint gave no usable description; the mirror is written without one and says so."""


def openai_compatible_describer(endpoint: Endpoint, model: str, prompt: str) -> Describer:
    if not endpoint.base_url:
        raise ProfileError(f"endpoint {endpoint.name} needs a base_url")

    def describe(jpeg: bytes) -> str:
        image = {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")}}
        payload = {"temperature": 0, "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, image]}]}
        try:
            return str(chat_completion(endpoint, model, payload, stage=STAGE)["choices"][0]["message"]["content"])
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise DescriptionError(f"endpoint {endpoint.name} gave no usable description") from exc

    return describe


def tidy(text: str, max_words: int) -> str:
    """Plain paragraphs, no Markdown that could pass for the mirror's own structure, and a hard length cap."""
    lines = [re.sub(r"^\s*(#{1,6}\s+|[-*>]\s+)", "", line).strip() for line in text.replace("\r", "").split("\n")]
    paragraphs = [" ".join(part.split()) for part in re.split(r"\n\s*\n", "\n".join(lines)) if part.strip()]
    words = " ".join(paragraphs).split()
    if len(words) > max_words:
        return " ".join(words[:max_words]) + " […]"
    return "\n\n".join(paragraphs)


def describe_image(path: Path, content_hash: str, *, profile: Profile, plan: Plan, describe: Describer | None = None) -> tuple[str | None, dict[str, Any] | None, str | None]:
    """(description, processing entry, verify flag). All ``None`` when the plan does not run the stage.

    A failure here never costs the image its mirror: the description is simply pending.
    """
    if not plan.runs(STAGE):
        return None, None, None
    from .pdf_tools import image_jpeg

    stage, endpoint = profile.stages[STAGE], profile.endpoint_for(STAGE)
    model, max_words = str(stage.get("model", "")), int(stage.get("max_words", DEFAULT_MAX_WORDS))
    chosen = stage.get("prompt", "default")
    prompt = (PROMPT if chosen == "default" else str(chosen)).replace("{max_words}", str(max_words))
    describe = describe or openai_compatible_describer(endpoint, model, prompt)
    ask = lambda: {"text": describe(image_jpeg(path))}  # noqa: E731
    try:
        if stage.get("cache", True):
            answer = Cache(profile.limits.cache_dir).fetch(ask, content_hash, STAGE, model, hashlib.sha256(prompt.encode()).hexdigest())
        else:
            answer = ask()
        text = tidy(str(answer.get("text", "")), max_words)
    except DrawbridgeError:
        return None, None, PENDING
    if not text:
        return None, None, PENDING
    entry = {"method": f"{STAGE}:{model}", "endpoint": endpoint.name, "egress": endpoint.egress, "words": len(text.split())}
    return text, entry, WRITTEN
