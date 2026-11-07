"""Physical PDF identity and unambiguous slices of an untrusted Markdown body.

No PDF engine, HTML renderer or sanitizer is involved. Offsets are Unicode code
points into the normalized body, not bytes, UTF-16 units or rendered positions.
"""
from __future__ import annotations

import re
from collections.abc import Sequence

from .errors import MirrorFormatError

CITATIONS = {"schema": "vellric.pdf-page-citations/1.0"}
MAP_SCHEMA = "drawbridge.pdf-page-map/1.0"


def anchor(source_hash: str, number: int) -> str:
    if not isinstance(source_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", source_hash):
        raise ValueError("invalid original PDF digest")
    if type(number) is not int or number < 1:
        raise ValueError("invalid physical page ordinal")
    return f"vellric-pdf-{source_hash}-page-{number:06d}"


def normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")


def separator(destination: str, number: int) -> str:
    return f'\n\n<a id="{destination}"></a>\n\n## Page {number}\n\n'


def assemble(preamble: str, pages: Sequence[str], source_hash: str,
             anchors: Sequence[str] | None = None) -> tuple[str, dict]:
    from .mirror import EMPTY_PAGE_MARKER

    expected = tuple(anchor(source_hash, n) for n in range(1, len(pages) + 1))
    if not pages or (anchors is not None and tuple(anchors) != expected):
        raise ValueError("PDF citation mapping differs from original pages")
    body = normalize(preamble).strip()
    records = []
    for number, (text, destination) in enumerate(zip(pages, expected, strict=True), 1):
        body += separator(destination, number)
        start = len(body)
        body += normalize(text).strip() or EMPTY_PAGE_MARKER
        records.append({"number": number, "anchor": destination, "start": start, "end": len(body)})
    return body, {"schema": MAP_SCHEMA, "pages": records}


def split(header: dict, body: str) -> tuple[str, list[str], tuple[str, ...]]:
    """Validate canonical metadata and exact framing; never search page text for IDs."""
    try:
        if header.get("page_citations") != CITATIONS:
            raise ValueError("unsupported citation schema")
        source_hash = header["content_hash"]
        if not isinstance(source_hash, str) or not source_hash.startswith("sha256:"):
            raise ValueError("missing PDF identity")
        source_hash = source_hash[7:]
        mapping = header["pdf_page_map"]
        if not isinstance(mapping, dict) or set(mapping) != {"schema", "pages"} or mapping["schema"] != MAP_SCHEMA:
            raise ValueError("unsupported page map")
        records = mapping["pages"]
        count = header["page_count"]
        if type(count) is not int or count < 1 or not isinstance(records, list) or len(records) != count:
            raise ValueError("incomplete page map")
        if header.get("unit") != "page" or header.get("media_type") != "application/pdf":
            raise ValueError("PDF citations on non-PDF mirror")
        pages, destinations = [], []
        cursor = None
        preamble = ""
        for number, record in enumerate(records, 1):
            if not isinstance(record, dict) or set(record) != {"number", "anchor", "start", "end"}:
                raise ValueError("invalid page-map record")
            destination = anchor(source_hash, number)
            start, end = record["start"], record["end"]
            if type(record["number"]) is not int or record["number"] != number or record["anchor"] != destination:
                raise ValueError("wrong page citation identity/order")
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(body):
                raise ValueError("invalid page span")
            boundary = separator(destination, number)
            if cursor is None:
                cursor = start - len(boundary)
                if cursor < 0:
                    raise ValueError("missing page prefix")
                preamble = body[:cursor]
                if not preamble or preamble != preamble.strip():
                    raise ValueError("noncanonical page preamble")
            if body[cursor:start] != boundary:
                raise ValueError("page framing differs from mapping")
            payload = body[start:end]
            if payload != payload.strip():
                raise ValueError("noncanonical page payload")
            pages.append(payload)
            destinations.append(destination)
            cursor = end
        if body[cursor:] not in {"", "\n"} or normalize(body) != body:
            raise ValueError("noncanonical or uncovered page content")
        return preamble, pages, tuple(destinations)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise MirrorFormatError("invalid PDF page citations: " + str(exc)) from exc
