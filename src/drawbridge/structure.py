"""The structure stage: a groomed, chunkable rendering derived from a fidelity mirror.

The model never writes words. It is shown numbered lines and returns annotations only (this line
is a heading, these lines are one paragraph, this is a list item). Code applies them, so the only
things that can change are Markdown syntax and whitespace. A gate then proves it: the groomed
section's word sequence must equal the fidelity section's, or the section falls back to the
fidelity text and is listed in ``verify``. The fidelity mirror is never modified.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .calls import chat_completion
from .errors import ConversionOperationalError
from .mirror import Mirror, now_iso, parse_mirror_header
from .native import BULLETS
from .profile import Endpoint, Plan, Profile, ProfileError
from .progress import advance

KINDS = frozenset({"heading", "paragraph", "list", "list_item", "quote", "keep"})
PROMPT = """You restore structure to text recovered from a document. You are given numbered lines.
Return JSON only: {"blocks": [{"lines": [first, last], "kind": KIND, "level": N}]}.
KIND is one of: heading (level 1-3), paragraph (the lines are one paragraph broken by line wrapping),
list (each line is one whole list item), list_item (the lines are ONE list item broken by line
wrapping; use one block per item), quote, keep (leave exactly as it is: tables, addresses, signature
blocks, captions, anything whose line breaks carry meaning).
Blocks must cover every line exactly once, in order, without overlap. Never write, correct or omit
a word: you only say which lines belong together and what they are."""
_SYNTAX = re.compile(r"^(#{1,6} |- |> )", re.M)
_HEADING = re.compile(r"^## (.+)\n", re.M)
_LINK_TARGET = re.compile(r"\]\([^()\s]*\)")
_INLINE = re.compile(
    rf"[*`|\\\[\]{BULLETS}]"
)  # a bullet glyph is often set tight against its first word
_RULE = re.compile(r"[-:]+")
_PAGE = re.compile(r"Page (\d+)")
NATIVE_METHOD = "structure:native:pymupdf-typography"

Annotator = Callable[[list[str]], dict[str, Any]]


class StructureResponseError(ConversionOperationalError):
    """The model's annotations were unusable; the section keeps its fidelity text."""


def json_object(content: Any) -> dict[str, Any]:
    """The JSON object in a model's answer. Some models fence it or add a sentence around it despite being asked not to."""
    text = str(content)
    first, last = text.find("{"), text.rfind("}")
    if first < 0 or last < first:
        raise ValueError("no JSON object in the answer")
    value = json.loads(text[first : last + 1])
    if not isinstance(value, dict):
        raise ValueError("the answer is not a JSON object")
    return value


def words(text: str, *, inline: bool = False) -> list[str]:
    """The word sequence the gate compares. ``inline`` also sets aside the inline Markdown the native
    pass writes (emphasis, code, link targets, table rules, bullet glyphs), on both sides alike."""
    text = _SYNTAX.sub("", text)
    if not inline:
        return text.split()
    text = _INLINE.sub("", _LINK_TARGET.sub("]", text))
    return [token for token in text.split() if not _RULE.fullmatch(token)]


def apply_blocks(lines: Sequence[str], blocks: Any) -> str:
    """Apply annotations to the retained lines. Anything short of a clean, complete cover is refused."""
    if not isinstance(blocks, list) or not blocks:
        raise StructureResponseError("no blocks returned")
    out: list[str] = []
    expected = 1
    for block in blocks:
        try:
            first, last = (int(value) for value in block["lines"])
            kind = block["kind"]
        except (KeyError, TypeError, ValueError) as exc:
            raise StructureResponseError("malformed block") from exc
        if kind not in KINDS or first != expected or last < first or last > len(lines):
            raise StructureResponseError(
                f"blocks do not cover the lines in order at line {expected}"
            )
        chunk = [line.strip() for line in lines[first - 1 : last]]
        expected = last + 1
        if not any(chunk):
            continue
        if kind == "heading":
            level = min(3, max(1, int(block.get("level", 1))))
            out.append(
                "#" * (level + 2) + " " + " ".join(part for part in chunk if part)
            )
        elif kind == "paragraph":
            out.append(" ".join(part for part in chunk if part))
        elif kind == "list_item":
            out.append("- " + " ".join(part for part in chunk if part))
        elif kind == "list":
            out.append("\n".join(f"- {part}" for part in chunk if part))
        elif kind == "quote":
            out.append("\n".join(f"> {part}" for part in chunk if part))
        else:
            out.append("\n".join(lines[first - 1 : last]).strip("\n"))
    if expected != len(lines) + 1:
        raise StructureResponseError("blocks stop before the last line")
    joined = "\n\n".join(out)
    return re.sub(
        r"(^- .*)\n\n(?=- )", r"\1\n", joined, flags=re.M
    )  # consecutive items form one list


def groom_section(text: str, annotate: Annotator) -> tuple[str, str | None]:
    """Return (text, None) when the groomed text passed the gate, else (fidelity text, reason)."""
    lines = text.split("\n")
    if not text.strip():
        return text, None
    try:
        groomed = apply_blocks(
            lines, annotate(list(lines)).get("blocks")
        )  # a copy: the model's side cannot reach our lines
    except (StructureResponseError, AttributeError) as exc:
        return text, f"unusable-annotations: {exc}"
    if words(groomed) != words(text):
        return text, "words-changed"
    return groomed, None


def openai_compatible_annotator(
    endpoint: Endpoint, model: str, prompt: str = PROMPT
) -> Annotator:
    """One implementation covers OpenAI, OpenRouter, Ollama's OpenAI endpoint, LM Studio and vLLM."""
    if not endpoint.base_url:
        raise ProfileError(f"endpoint {endpoint.name} needs a base_url")

    def annotate(lines: list[str]) -> dict[str, Any]:
        numbered = "\n".join(
            f"{number}: {line}" for number, line in enumerate(lines, 1)
        )
        payload = {
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": numbered},
            ],
        }
        try:
            body = chat_completion(endpoint, model, payload, stage="structure")
            return json_object(body["choices"][0]["message"]["content"])
        except (
            urllib.error.URLError,
            TimeoutError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        ) as exc:
            raise StructureResponseError(
                f"endpoint {endpoint.name} gave no usable answer"
            ) from exc

    return annotate


@dataclass
class Cache:
    """Results keyed by the exact input, stage, model and prompt, so a re-run does not pay twice."""

    directory: Path
    hits: int = 0
    _hits_lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )

    def key(self, *parts: str) -> Path:
        digest = hashlib.sha256("\x1f".join(parts).encode()).hexdigest()
        return Path(self.directory).expanduser() / digest[:2] / f"{digest}.json"

    def fetch(
        self, compute: Callable[[], dict[str, Any]], *parts: str
    ) -> dict[str, Any]:
        path = self.key(*parts)
        if path.is_file():
            with self._hits_lock:
                self.hits += 1
            return json.loads(path.read_text(encoding="utf-8"))
        answer = compute()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Callers fetch from several threads; a reader must never see a half-written answer.
        pending = path.with_name(
            f"{path.name}.{os.getpid()}.{threading.get_ident()}.pending"
        )
        pending.write_text(json.dumps(answer), encoding="utf-8")
        pending.replace(path)
        return answer

    def wrap(self, annotate: Annotator, *scope: str) -> Annotator:
        return lambda lines: self.fetch(
            lambda: annotate(lines), *scope, "\n".join(lines)
        )


def native_section(text: str, proposals: Sequence[str]) -> tuple[str, str | None]:
    """The first proposal whose words are the fidelity text's words, else the fidelity text."""
    for proposal in proposals:
        if words(proposal, inline=True) == words(text, inline=True):
            return proposal, None
    return text, "words-changed"


def semantic_mirror(
    fidelity_text: str,
    annotate: Annotator | None,
    *,
    method: str | None,
    endpoint: Endpoint | None,
    agent: str = "drawbridge",
    native: Mapping[int, Sequence[str]] | None = None,
    model_pages: Callable[[int | None], bool] = lambda page: True,
) -> Mirror:
    """Groom every section of a rendered fidelity mirror. Headings, order and anchors are kept exactly.

    ``native`` holds the typography pass's proposals by page; a page that has them is settled by them
    and never reaches the model. ``model_pages`` says which of the remaining pages the model may see.
    """
    header, body = parse_mirror_header(fidelity_text)
    parts = _HEADING.split(body)
    rebuilt, fallbacks, used = [parts[0].rstrip("\n")], [], set()
    total = (len(parts) - 1) // 2
    advance("structure", 0, total)
    for index in range(1, len(parts), 2):
        heading, text = parts[index], parts[index + 1].strip("\n")
        match = _PAGE.fullmatch(heading.strip())
        page = int(match.group(1)) if match else None
        groomed, reason = text, None
        if native and page in native:
            groomed, reason = native_section(text, native[page])
            used.add("native")
        elif annotate is not None and model_pages(page):
            groomed, reason = groom_section(text, annotate)
            used.add("model")
        if reason:
            fallbacks.append(f"structure-fallback:{heading.strip()}")
        rebuilt += ["", f"## {heading}", "", groomed]
        advance("structure", (index + 1) // 2, total)
    derived = dict(header)
    derived["derived_from"] = (
        "sha256:" + hashlib.sha256(fidelity_text.encode("utf-8")).hexdigest()
    )
    derived["derived_from_body"] = (
        "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
    )  # the body as parsed from the mirror file; survives a consumer regenerating the header
    processing = list(header["processing"])
    if "native" in used:
        processing.append(
            {
                "seq": len(processing) + 1,
                "method": NATIVE_METHOD,
                "endpoint": None,
                "egress": "local",
                "preservation": "strict",
                "performed_at": now_iso(),
                "agent": agent,
            }
        )
    if "model" in used:
        processing.append(
            {
                "seq": len(processing) + 1,
                "method": method,
                "endpoint": endpoint.name if endpoint else None,
                "egress": endpoint.egress if endpoint else "local",
                "preservation": "strict",
                "performed_at": now_iso(),
                "agent": agent,
            }
        )
    derived["processing"] = processing
    derived["verify"] = sorted({*header["verify"], *fallbacks})
    return Mirror(derived, "\n".join(rebuilt))


def native_pages(header: Mapping[str, Any], count: int) -> list[int]:
    """Pages whose fidelity text came from the PDF's text layer rather than from recognition."""
    if header.get("method") == "pymupdf-text":
        return list(range(1, count + 1))
    if "ocr_pages" not in header:
        return []
    scanned = {int(entry["page"]) for entry in header["ocr_pages"]}
    return [page for page in range(1, count + 1) if page not in scanned]


def run_structure(
    fidelity_text: str,
    *,
    profile: Profile,
    plan: Plan,
    annotate: Annotator | None = None,
    source: Path | None = None,
) -> Mirror | None:
    """The stage as the pipeline calls it. ``None`` when nothing in it runs. ``annotate`` replaces the
    endpoint in tests; ``source`` is the PDF, which the typography pass reads and the model never sees."""
    if not plan.runs("structure"):
        return None
    stage = profile.stages["structure"]
    if stage.get("mode", "annotate") != "annotate":
        raise ProfileError(
            "structure supports mode: annotate only; a mode that lets a model write words is not implemented"
        )
    if stage.get("preservation", "strict") != "strict":
        raise ProfileError("structure supports preservation: strict only")
    header, body = parse_mirror_header(fidelity_text)
    count = len(_HEADING.findall(body))
    born_digital = native_pages(header, count)
    native: dict[int, list[str]] = {}
    if (
        source is not None
        and born_digital
        and stage.get("native_pass", "deterministic") == "deterministic"
    ):
        from .native import candidates
        from .pdf_tools import page_layouts

        native = candidates(
            page_layouts(
                Path(source),
                born_digital,
                expected_sha256=header["content_hash"].removeprefix("sha256:"),
            )
        )
    model_runs = plan.runs_model("structure") and (
        annotate is not None or profile.endpoint_for("structure") is not None
    )
    applies = set(stage.get("applies_to") or {"pdf-scan-page"})
    allowed = {
        page
        for page in range(1, count + 1)
        if ("pdf-native-page" if page in born_digital else "pdf-scan-page") in applies
    }
    to_model = [page for page in allowed if page not in native] if model_runs else []
    if not native and not to_model:
        return None
    endpoint, model = None, ""
    if to_model:
        if len(to_model) > profile.limits.max_pages_per_document:
            raise ConversionOperationalError(
                f"{len(to_model)} sections exceed the profile's limit of {profile.limits.max_pages_per_document}; nothing was sent"
            )
        endpoint, model = profile.endpoint_for("structure"), str(stage.get("model", ""))
        annotate = annotate or openai_compatible_annotator(endpoint, model)
        if stage.get("cache", True):
            annotate = Cache(profile.limits.cache_dir).wrap(
                annotate,
                str(header["content_hash"]),
                "structure",
                model,
                hashlib.sha256(PROMPT.encode()).hexdigest(),
            )
    else:
        annotate = None
    return semantic_mirror(
        fidelity_text,
        annotate,
        method=f"structure:annotate:{model}",
        endpoint=endpoint,
        native=native,
        model_pages=lambda page: page is None or page in to_model,
    )
