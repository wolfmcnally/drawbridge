"""The mirror contract: provenance header, page-sectioned body, render and parse."""

from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

import yaml

from .errors import MirrorFormatError
from .slide_mirror import SLIDE_FORMAT

GENERATED_BY = "drawbridge"
MIRROR_FORMAT = "drawbridge.mirror.v1"
UNITS: frozenset[str] = frozenset({"page", "sheet", "message", "turn", "document"})
EMPTY_PAGE_MARKER = "[No text recovered from this page; check the original.]"
REQUIRED_HEADER_FIELDS: frozenset[str] = frozenset(
    {
        "mirror_of",
        "content_hash",
        "media_type",
        "byte_size",
        "acquired_at",
        "acquisition_method",
        "acquired_from",
        "processing",
        "verify",
        "generated_by",
    }
)
_FRONT_MATTER = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.S)


@dataclass
class Mirror:
    header: dict[str, Any]
    body: str


#: The safe loader, compiled when PyYAML has it: a consumer may parse thousands of large headers.
_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "document"


def title_from_name(name: str) -> str:
    """A generated H1 from a filename stem, the way a triage slug would title it."""
    return slugify(Path(name).stem).replace("-", " ").title()


def build_header(
    pdf_path: Path,
    *,
    method: str,
    mirror_of: str | int | None = None,
    media_type: str = "application/pdf",
    acquired_at: str | None = None,
    acquisition_method: str = "drawbridge-cli",
    acquired_from: str | None = None,
    agent: str = GENERATED_BY,
    verify: Iterable[str] = (),
    unit: str = "page",
    mirror_format: str = MIRROR_FORMAT,
    extra: dict[str, Any] | None = None,
    extensions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The provenance header. ``extra`` holds drawbridge's own per-converter fields; ``extensions``
    is the area for anyone else: one mapping per namespace, preserved and never interpreted here."""
    if not ((mirror_format == MIRROR_FORMAT and unit in UNITS) or (mirror_format == SLIDE_FORMAT and unit == "slide")):
        raise ValueError(f"unknown mirror unit: {unit}")
    pdf_path = Path(pdf_path)
    header: dict[str, Any] = {
        "mirror_of": mirror_of if mirror_of is not None else pdf_path.name,
        "content_hash": sha256_file(pdf_path),
        "media_type": media_type,
        "byte_size": pdf_path.stat().st_size,
        "acquired_at": acquired_at or now_iso(),
        "acquisition_method": acquisition_method,
        "acquired_from": acquired_from if acquired_from is not None else str(pdf_path),
        "processing": [
            {"seq": 1, "method": method, "performed_at": now_iso(), "agent": agent}
        ],
        "verify": sorted(set(verify)),
        "generated_by": GENERATED_BY,
        "format": mirror_format,
        "unit": unit,
    }
    if extra:
        for key, value in extra.items():
            if key in header:
                raise ValueError(f"extra header field collides with a required field: {key}")
            header[key] = value
    if extensions:
        for namespace, value in extensions.items():
            if not isinstance(value, dict):
                raise ValueError(f"extension {namespace!r} must be a mapping")
        header["extensions"] = copy.deepcopy(dict(extensions))
    return header


def page_body(title: str, pages: Sequence[str]) -> str:
    """One H1, then one ``## Page N`` section per original page, always."""
    body = [f"# {title}"]
    for number, text in enumerate(pages, 1):
        body.extend(["", f"## Page {number}", "", text.strip() or EMPTY_PAGE_MARKER])
    return "\n".join(body)


def render_mirror(mirror: Mirror) -> str:
    from .slide_mirror import split_slides
    if mirror.header.get("format") == SLIDE_FORMAT:
        split_slides(mirror.header, mirror.body)
    if "page_citations" in mirror.header or "pdf_page_map" in mirror.header:
        from .citations import split

        split(mirror.header, mirror.body)
    header = yaml.safe_dump(mirror.header, sort_keys=False, allow_unicode=True).strip()
    rendered = f"---\n{header}\n---\n\n{mirror.body.rstrip()}\n"
    return rendered.replace("\x00", "")


@lru_cache(maxsize=128)
def _parsed_header(text: str) -> dict:
    return yaml.load(text, Loader=_LOADER) or {}


def parse_mirror_header(value: str | Path) -> tuple[dict[str, Any], str]:
    """Split a mirror into (header, body), refusing anything off-contract."""
    text = Path(value).read_text(encoding="utf-8") if isinstance(value, Path) else value
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    match = _FRONT_MATTER.match(text)
    if not match:
        raise MirrorFormatError("mirror lacks YAML front matter")
    header_text = match.group(1)
    try:
        header = (
            yaml.load(header_text, Loader=_LOADER) or {}
            if len(header_text) > 65536
            else copy.deepcopy(_parsed_header(header_text))
        )
    except yaml.YAMLError as exc:
        raise MirrorFormatError("mirror front matter is not valid YAML") from exc
    if not isinstance(header, dict):
        raise MirrorFormatError("mirror front matter is not a mapping")
    missing = REQUIRED_HEADER_FIELDS - set(header)
    if missing:
        raise MirrorFormatError(f"mirror header missing: {', '.join(sorted(missing))}")
    # A mirror written before the format was versioned carries neither field; it is a page mirror.
    declared = header.get("format", MIRROR_FORMAT)
    from .slide_mirror import split_slides
    if declared not in {MIRROR_FORMAT, SLIDE_FORMAT}:
        raise MirrorFormatError(f"unsupported mirror format: {declared}")
    if declared == MIRROR_FORMAT and header.get("unit", "page") not in UNITS:
        raise MirrorFormatError(f"unknown mirror unit: {header['unit']}")
    if not isinstance(header.get("extensions", {}), dict):
        raise MirrorFormatError("mirror extensions must be a mapping")
    body = match.group(2).lstrip("\n")
    if declared == SLIDE_FORMAT:
        split_slides(header, body)
    if "page_citations" in header or "pdf_page_map" in header:
        from .citations import split

        split(header, body)
    return header, body


def mirror_text(body: bytes) -> str:
    """The normalised reading view of a retained body; the bytes stay unchanged."""
    return body.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").lstrip("\n")


def page_sections(body: str, *, header: dict | None = None) -> list[str]:
    """Page text in order. Pass the header for authoritative citation-aware boundaries.

    Body-only use is a legacy convenience, not an identity/security validator.
    """
    if header is not None:
        require_v1_semantics(header)
    if header is not None and ("page_citations" in header or "pdf_page_map" in header):
        from .citations import split

        return split(header, body)[1]
    parts = re.split(r'(?:^<a id="vellric-pdf-[0-9a-f]{64}-page-[0-9]+"></a>\n\n)?^## Page (\d+)\n', body, flags=re.M)
    sections: list[str] = []
    for index in range(1, len(parts), 2):
        expected = len(sections) + 1
        if int(parts[index]) != expected:
            raise MirrorFormatError(f"page sections out of order at page {parts[index]}")
        sections.append(parts[index + 1].strip("\n"))
    return sections


def sections(body: str, *, header: dict | None = None) -> list[tuple[str, str]]:
    """Sections in order; pass a PDF citation header for authoritative page boundaries.

    Body-only use remains a legacy Markdown convenience, not a security parser.
    """
    if header is not None and header.get("format") == SLIDE_FORMAT:
        from .slide_mirror import slide_sections
        return [(f"Slide {number}", text) for number, text in enumerate(slide_sections(body, header=header), 1)]
    if header is not None and ("page_citations" in header or "pdf_page_map" in header):
        return [(f"Page {number}", text) for number, text in enumerate(page_sections(body, header=header), 1)]
    parts = re.split(r"^## (.+)\n", body, flags=re.M)
    return [(parts[i].strip(), parts[i + 1].strip("\n")) for i in range(1, len(parts), 2)]


def require_v1_semantics(header: dict) -> None:
    """Existing semantic/transcript operations do not interpret slide maps."""
    if header.get("format") == SLIDE_FORMAT:
        raise MirrorFormatError("slide mirrors are not supported by this v1 operation")
