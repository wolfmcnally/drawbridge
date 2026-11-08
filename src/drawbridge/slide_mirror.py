"""Versioned slide identity and separately framed native text and presenter notes.

Offsets are Unicode code points into citations.normalize(body), just as for PDF
maps. A map is framing/integrity metadata, not a signature or proof of source
content; source verification separately re-admits the original deck.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from .citations import normalize
from .errors import MirrorFormatError

SLIDE_FORMAT = "drawbridge.mirror.v2"
SLIDE_MAP = "drawbridge.slide-map/1.0"
PPTX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
NO_SLIDE_TEXT = "[No native text recovered; this does not mean the slide is visually blank.]"
NO_NOTES_TEXT = "[The existing notes part contains no presenter text.]"
_KEYS = {
    "number",
    "slide_id",
    "part",
    "hidden",
    "text_free",
    "notes_present",
    "notes_included",
    "content_start",
    "content_end",
    "notes_start",
    "notes_end",
    "end",
    "anchor",
    "features",
}


def _fence(text: str) -> str:
    return "`" * max(3, max((len(x) + 1 for x in re.findall(r"`+", text)), default=3))


def _prefix(record: dict) -> str:
    hidden = "[Hidden source slide.]\n\n" if record["hidden"] else ""
    return (
        f'\n\n<a id="{record["anchor"]}"></a>\n\n## Slide {record["number"]}\n\n'
        + hidden
        + "### Slide content\n\n"
    )


def _payload(text: str) -> str:
    fence = _fence(text)
    return fence + "text\n" + text + "\n" + fence


def assemble_slides(title: str, slides: list[dict], source_digest: str) -> tuple[str, dict]:
    """Frame every slide once; source text cannot manufacture structural headings."""
    body = "# " + normalize(title).replace("\n", " ").strip()
    records = []
    for number, slide in enumerate(slides, 1):
        text = normalize(slide["text"]).strip() or NO_SLIDE_TEXT
        record = {
            "number": number,
            "slide_id": slide["slide_id"],
            "part": slide["part"],
            "hidden": slide["hidden"],
            "text_free": not bool(normalize(slide["text"]).strip()),
            "notes_present": slide["notes_present"],
            "notes_included": slide["notes_included"],
            "anchor": f"drawbridge-pptx-{source_digest}-slide-{slide['slide_id']}",
            "features": sorted(set(slide["features"])),
            "notes_start": None,
            "notes_end": None,
        }
        body += _prefix(record) + _fence(text) + "text\n"
        record["content_start"] = len(body)
        body += text
        record["content_end"] = len(body)
        body += "\n" + _fence(text)
        if record["notes_present"] and record["notes_included"]:
            notes = normalize(slide["notes"]).strip() or NO_NOTES_TEXT
            body += "\n\n### Speaker notes (presenter only)\n\n" + _fence(notes) + "text\n"
            record["notes_start"] = len(body)
            body += notes
            record["notes_end"] = len(body)
            body += "\n" + _fence(notes)
        record["end"] = len(body)
        records.append(record)
    return body, {"schema": SLIDE_MAP, "offset_unit": "unicode-code-points", "slides": records}


def split_slides(header: dict, body: str) -> tuple[str, list[str], list[dict]]:
    """Validate every map field and all framing before returning authoritative spans."""
    try:
        if header.get("format") != SLIDE_FORMAT or header.get("unit") != "slide":
            raise ValueError("slide format/unit mismatch")
        if header.get("media_type") != PPTX_MEDIA_TYPE:
            raise ValueError("slide map requires an admitted ordinary presentation")
        digest = header["content_hash"]
        if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValueError("invalid original source digest")
        mapping = header["slide_map"]
        if not isinstance(mapping, dict) or set(mapping) != {"schema", "offset_unit", "slides"}:
            raise ValueError("invalid slide map keys")
        if mapping["schema"] != SLIDE_MAP or mapping["offset_unit"] != "unicode-code-points":
            raise ValueError("unsupported slide map")
        count, records = header["slide_count"], mapping["slides"]
        if type(count) is not int or not 1 <= count <= 1000:
            raise ValueError("invalid slide count")
        if not isinstance(records, list) or len(records) != count:
            raise ValueError("incomplete slide map")
        if normalize(body) != body:
            raise ValueError("noncanonical slide body")
        ids, parts, payloads = set(), set(), []
        cursor, preamble = None, ""
        for number, record in enumerate(records, 1):
            if not isinstance(record, dict) or set(record) != _KEYS:
                raise ValueError("invalid slide record keys")
            identifier, part = record["slide_id"], record["part"]
            if type(record["number"]) is not int or record["number"] != number:
                raise ValueError("slide ordinal differs from canonical order")
            if (
                type(identifier) is not int
                or not 256 <= identifier < 2147483648
                or identifier in ids
            ):
                raise ValueError("invalid or repeated source slide identity")
            if (
                not isinstance(part, str)
                or not part
                or part in parts
                or "\\" in part
                or part.startswith("/")
                or PurePosixPath(part).as_posix() != part
                or any(x in {"", ".", ".."} for x in part.split("/"))
            ):
                raise ValueError("invalid or repeated slide part")
            ids.add(identifier)
            parts.add(part)
            for key in ("hidden", "text_free", "notes_present", "notes_included"):
                if type(record[key]) is not bool:
                    raise ValueError("nonboolean slide metadata")
            policy = header["presentation"]["notes_policy"]
            if policy not in {"include", "exclude"} or record["notes_included"] != (
                policy == "include"
            ):
                raise ValueError("notes selection differs from provenance")
            if record["anchor"] != f"drawbridge-pptx-{digest[7:]}-slide-{identifier}":
                raise ValueError("slide anchor differs from original identity")
            features = record["features"]
            if not isinstance(features, list) or not all(isinstance(x, str) for x in features):
                raise ValueError("invalid slide feature inventory")
            if sorted(set(features)) != features:
                raise ValueError("noncanonical feature inventory")
            start, end, section_end = record["content_start"], record["content_end"], record["end"]
            if any(type(x) is not int for x in (start, end, section_end)):
                raise ValueError("noninteger slide span")
            if not 0 <= start < end < section_end <= len(body):
                raise ValueError("invalid slide content span")
            text = body[start:end]
            if text != text.strip() or (record["text_free"] and text != NO_SLIDE_TEXT):
                raise ValueError("noncanonical native text")
            lead = _prefix(record) + _fence(text) + "text\n"
            if cursor is None:
                cursor = start - len(lead)
                preamble = body[:cursor]
                if cursor <= 0 or not preamble.startswith("# ") or preamble != preamble.strip():
                    raise ValueError("invalid slide preamble")
            section_start = cursor
            if body[cursor:start] != lead:
                raise ValueError("slide framing differs from map")
            rebuilt = _prefix(record) + _payload(text)
            if record["notes_present"] and record["notes_included"]:
                a, b = record["notes_start"], record["notes_end"]
                if type(a) is not int or type(b) is not int or not end < a < b < section_end:
                    raise ValueError("invalid notes span")
                notes = body[a:b]
                if notes != notes.strip():
                    raise ValueError("noncanonical notes text")
                notes_lead = "\n\n### Speaker notes (presenter only)\n\n" + _fence(notes) + "text\n"
                if section_start + len(rebuilt) + len(notes_lead) != a:
                    raise ValueError("notes framing differs from map")
                rebuilt += "\n\n### Speaker notes (presenter only)\n\n" + _payload(notes)
            elif record["notes_start"] is not None or record["notes_end"] is not None:
                raise ValueError("excluded or absent notes carry a span")
            if body[section_start:section_end] != rebuilt:
                raise ValueError("uncovered or changed slide section")
            payloads.append(body[section_start + len(_prefix(record)) : section_end])
            cursor = section_end
        if body[cursor:] not in {"", "\n"}:
            raise ValueError("uncovered trailing slide content")
        return preamble, payloads, records
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise MirrorFormatError("invalid slide mirror: " + str(exc)) from exc


def slide_sections(body: str, *, header: dict) -> list[str]:
    """Full slide payloads in source order, including independently mapped notes."""
    return split_slides(header, body)[1]
