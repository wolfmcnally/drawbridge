"""Transcript refinement: paragraphs for long turns, and proposals a reviewer can check by listening.

The model changes nothing. It sees the turns with provider identities only (never assigned names) and
returns structured answers with no free prose. Code applies the one thing that is safe to apply,
paragraph breaks between sentences, and proves the words of every turn are unchanged. Everything
else is a proposal, listed in its own section with the time to listen at: two identities that may be
one voice, a few words at a turn's edge that may belong to the neighbouring speaker, a word that may
be misspelled. No proposal can carry a name, and none is applied. A disagreement between two
transcription passes, ``{first | second}``, is one unit that is never split, judged or resolved.
"""

from __future__ import annotations

import hashlib
import re
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Callable

from .calls import chat_completion
from .errors import ConversionOperationalError
from .mirror import Mirror, now_iso, parse_mirror_header
from .profile import Endpoint, Plan, Profile, ProfileError
from .structure import Cache, json_object, words
from .progress import advance

STAGE = "transcript_refinement"
SECTION = "Proposals"
PROMPT = """You review a diarised transcript. Speakers are anonymous provider identities; never try to name them.
Each turn is "T<number> [start] <identity>:" then its text. In long turns the sentences are numbered "(1)", "(2)".
Text like {heard one way | heard another} records a disagreement between two transcriptions: leave it alone.
Return JSON only, with any of these keys, and nothing you are not confident of:
"paragraphs": [{"turn": N, "starts": [sentence numbers that begin a new paragraph]}] for long turns where the subject shifts.
"same_speaker": [{"a": identity, "b": identity, "turns": [turn numbers that show it]}] when two identities are plainly one voice, for example one sentence continuing across a change of identity.
"boundary": [{"turn": N, "edge": "start" or "end", "words": count}] when the first or last few words of a turn plainly belong to the neighbouring turn's speaker.
"spelling": [{"turn": N, "heard": the exact word as written, "suggest": a corrected spelling}] when a term is spelled inconsistently or is plainly a recognition error for a word used elsewhere in the transcript.
You never rewrite text. Every answer is a proposal that a person will check by listening."""
WINDOW_CHARS = 24_000
LONG_TURN_WORDS = 60
MAX_BOUNDARY_WORDS = 12
_TURN = re.compile(r"^(\d\d:\d\d:\d\d\.\d{3}) --> (\d\d:\d\d:\d\d\.\d{3}) · (.+)$")
_IDENTITY = re.compile(r"(?:second:)?speaker_\d+|unassigned")
_TOKEN = re.compile(r"\{(?:\\.|[^{}\\])*\}|\S+")
_SENTENCE_END = re.compile(r"[.?!][\"'”’)\]]*$")
_HEADING = re.compile(r"^## (.+)\n", re.M)

Reviewer = Callable[[str], dict[str, Any]]


@dataclass(frozen=True)
class Turn:
    number: int
    start: str
    identities: tuple[str, ...]
    text: str

    @property
    def sentences(self) -> list[str]:
        out, current = [], []
        for token in _TOKEN.findall(self.text):
            current.append(token)
            if not token.startswith("{") and _SENTENCE_END.search(token):
                out.append(" ".join(current))
                current = []
        if current:
            out.append(" ".join(current))
        return out

    @property
    def is_long(self) -> bool:
        return len(self.text.split()) >= LONG_TURN_WORDS and len(self.sentences) >= 3


def shown(turn: Turn) -> str:
    text = " ".join(f"({index}) {sentence}" for index, sentence in enumerate(turn.sentences, 1)) if turn.is_long else " ".join(turn.sentences)
    return f"T{turn.number} [{turn.start[:8]}] {' or '.join(turn.identities)}: {text}"


def paragraphs(turn: Turn, starts: Any) -> str:
    sentences = turn.sentences
    if not turn.is_long or not isinstance(starts, list):
        return turn.text
    breaks = {int(value) for value in starts if isinstance(value, int) and 2 <= value <= len(sentences)}
    out: list[list[str]] = [[]]
    for index, sentence in enumerate(sentences, 1):
        if index in breaks:
            out.append([])
        out[-1].append(sentence)
    return "\n\n".join(" ".join(group) for group in out)


def _bare(token: str) -> str:
    return token.strip(".,;:?!\"'“”‘’()[]").lower()


def proposals(answer: dict[str, Any], turns: dict[int, Turn], *, speaker_resolution: bool) -> tuple[list[tuple[str, str, str]], int]:
    """Validated proposals as (kind, where, sentence code wrote), and how many were refused.

    The model supplies numbers, identities from the table, and at most one short spelling; every sentence
    a reader sees is written here, so a proposal has nowhere to put a name or an argument."""
    rows: list[tuple[str, str, str]] = []
    refused = 0
    known = {identity for turn in turns.values() for identity in turn.identities}
    ordered = sorted(turns)
    for item in answer.get("same_speaker") or []:
        try:
            a, b, evidence = str(item["a"]), str(item["b"]), [int(number) for number in item["turns"]]
        except (KeyError, TypeError, ValueError):
            refused += 1
            continue
        if not speaker_resolution:
            continue
        if a == b or a not in known or b not in known or not evidence or any(number not in turns for number in evidence):
            refused += 1
            continue
        first, second = sorted((a, b))
        rows.append(("same-speaker", ", ".join(turns[number].start[:8] for number in sorted(set(evidence))[:6]), f"`{first}` and `{second}` may be one voice"))
    for item in answer.get("boundary") or []:
        try:
            number, edge, count = int(item["turn"]), str(item["edge"]), int(item["words"])
        except (KeyError, TypeError, ValueError):
            refused += 1
            continue
        position = ordered.index(number) if number in turns else -1
        neighbour = position + (-1 if edge == "start" else 1)
        tokens = _TOKEN.findall(turns[number].text) if number in turns else []
        if position < 0 or edge not in {"start", "end"} or not 0 <= neighbour < len(ordered) or not 1 <= count <= min(MAX_BOUNDARY_WORDS, len(tokens) - 1):
            refused += 1
            continue
        other = turns[ordered[neighbour]]
        if set(other.identities) == set(turns[number].identities):
            refused += 1
            continue
        span = tokens[:count] if edge == "start" else tokens[-count:]
        which, side = ("first", "previous") if edge == "start" else ("last", "next")
        rows.append(("boundary", turns[number].start[:8], f"the {which} {count} words of this turn (“{' '.join(span)}”) may belong to the {side} speaker, `{' or '.join(other.identities)}`"))
    for item in answer.get("spelling") or []:
        try:
            number, heard, suggest = int(item["turn"]), str(item["heard"]).strip(), str(item["suggest"]).strip()
        except (KeyError, TypeError, ValueError):
            refused += 1
            continue
        plain = [_bare(token) for token in _TOKEN.findall(turns[number].text) if not token.startswith("{")] if number in turns else []
        close = SequenceMatcher(None, heard.lower(), suggest.lower()).ratio() >= 0.5
        if not heard or _bare(heard) not in plain or not suggest or len(suggest) > 40 or len(suggest.split()) > 3 or suggest == heard or not close or re.search(r"[|`\n{}]", suggest):
            refused += 1
            continue
        rows.append(("spelling", turns[number].start[:8], f"“{heard}” may be “{suggest}”"))
    return list(dict.fromkeys(rows)), refused


def openai_compatible_reviewer(endpoint: Endpoint, model: str, prompt: str = PROMPT) -> Reviewer:
    if not endpoint.base_url:
        raise ProfileError(f"endpoint {endpoint.name} needs a base_url")

    def review(window: str) -> dict[str, Any]:
        payload = {"temperature": 0, "response_format": {"type": "json_object"},
                   "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": window}]}
        try:
            return json_object(chat_completion(endpoint, model, payload, stage=STAGE)["choices"][0]["message"]["content"])
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ConversionOperationalError(f"endpoint {endpoint.name} gave no usable answer") from exc

    return review


def windows(turns: list[Turn], limit: int = WINDOW_CHARS) -> list[list[Turn]]:
    out: list[list[Turn]] = [[]]
    size = 0
    for turn in turns:
        length = len(shown(turn))
        if out[-1] and size + length > limit:
            out.append([])
            size = 0
        out[-1].append(turn)
        size += length
    return [window for window in out if window]


REVIEW_WORKERS = 8  # concurrent window reviews for one transcript


def refined_mirror(fidelity_text: str, review: Reviewer, *, method: str, endpoint: Endpoint | None, speaker_resolution: bool = True, agent: str = "drawbridge") -> Mirror:
    header, body = parse_mirror_header(fidelity_text)
    parts = _HEADING.split(body)
    at: dict[int, Turn] = {}  # by position in the body; the model sees turns numbered 1, 2, 3
    for index in range(1, len(parts), 2):
        match = _TURN.match(parts[index].strip())
        if match:
            identities = tuple(_IDENTITY.findall(match.group(3))) or ("unassigned",)
            at[index] = Turn(len(at) + 1, match.group(1), identities, parts[index + 1].strip("\n"))
    turns = {turn.number: turn for turn in at.values()}
    starts: dict[int, Any] = {}
    rows: list[tuple[str, str, str]] = []
    refused, unanswered = 0, 0
    batches = windows(list(turns.values()))

    def ask(window: list[Turn]) -> dict[str, Any] | None:
        try:
            return review("\n".join(shown(turn) for turn in window))
        except ConversionOperationalError:
            return None

    # Windows hold disjoint turns and each answer is read only against its own window, so the
    # reviews run side by side and are applied in window order: the same mirror, without one long
    # recording's windows queueing behind each other for most of ten minutes.
    with ThreadPoolExecutor(max_workers=max(1, min(REVIEW_WORKERS, len(batches)))) as pool:
        futures = [pool.submit(copy_context().run, ask, batch) for batch in batches]
        advance("refinement", 0, len(futures))
        answers = []
        for future in futures:
            answers.append(future.result())
            advance("refinement", len(answers), len(futures))
    for window, answer in zip(batches, answers):
        if answer is None:
            unanswered += 1
            continue
        inside = {turn.number: turn for turn in window}
        for item in answer.get("paragraphs") or []:
            if isinstance(item, dict) and item.get("turn") in inside:
                starts[item["turn"]] = item.get("starts")
        found, bad = proposals(answer, inside, speaker_resolution=speaker_resolution)
        rows += found
        refused += bad
    rows = list(dict.fromkeys(rows))
    rebuilt, fallbacks, placed = [parts[0].rstrip("\n")], [], False
    table = [f"## {SECTION}", "", "Proposed by a model and not applied. Each gives the time to listen at; none names anyone.", "",
             "| Kind | Listen at | Proposal |", "| --- | --- | --- |", *(f"| {kind} | {where} | {text.replace('|', chr(92) + '|')} |" for kind, where, text in rows)]
    for index in range(1, len(parts), 2):
        heading, text = parts[index], parts[index + 1].strip("\n")
        if index in at:
            if rows and not placed:
                rebuilt += ["", *table]
                placed = True
            groomed = paragraphs(at[index], starts.get(at[index].number))
            if words(groomed) != words(text):
                fallbacks.append(f"refinement-fallback:{heading.strip()[:12]}")
                groomed = text
            text = groomed
        rebuilt += ["", f"## {heading}", "", text]
    derived = dict(header)
    derived["derived_from"] = "sha256:" + hashlib.sha256(fidelity_text.encode("utf-8")).hexdigest()
    derived["derived_from_body"] = "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()  # the body as parsed from the mirror file; survives a consumer regenerating the header
    derived["processing"] = [*header["processing"], {"seq": len(header["processing"]) + 1, "method": method, "endpoint": endpoint.name if endpoint else None,
                             "egress": endpoint.egress if endpoint else "local", "preservation": "strict", "performed_at": now_iso(), "agent": agent}]
    derived["refinement"] = {"paragraphed_turns": sum(1 for number, turn in turns.items() if "\n\n" in paragraphs(turn, starts.get(number))), "proposals": len(rows), "proposals_refused": refused}
    flags = [*fallbacks, *([f"transcript-proposals:{len(rows)}"] if rows else []), *(["refinement-incomplete"] if unanswered else [])]
    derived["verify"] = sorted({*header["verify"], *flags})
    return Mirror(derived, "\n".join(rebuilt))


def run_refinement(fidelity_text: str, *, profile: Profile, plan: Plan, review: Reviewer | None = None) -> Mirror | None:
    """The stage as the pipeline calls it. ``None`` when the plan does not run it. ``review`` replaces the endpoint in tests."""
    if not plan.runs(STAGE):
        return None
    stage, endpoint = profile.stages[STAGE], profile.endpoint_for(STAGE)
    if stage.get("mode", "annotate") != "annotate" or stage.get("preservation", "strict") != "strict":
        raise ProfileError(f"{STAGE} supports mode: annotate with preservation: strict only")
    resolution = stage.get("speaker_resolution", "propose")
    if resolution not in {"propose", "off"}:
        raise ProfileError(f"{STAGE}: speaker_resolution must be propose or off; identities are never asserted")
    model = str(stage.get("model", ""))
    review = review or openai_compatible_reviewer(endpoint, model)
    if stage.get("cache", True):
        cache, inner = Cache(profile.limits.cache_dir), review
        review = lambda window: cache.fetch(lambda: inner(window), STAGE, model, hashlib.sha256(PROMPT.encode()).hexdigest(), window)  # noqa: E731
    return refined_mirror(fidelity_text, review, method=f"{STAGE}:annotate:{model}", endpoint=endpoint, speaker_resolution=resolution == "propose")
