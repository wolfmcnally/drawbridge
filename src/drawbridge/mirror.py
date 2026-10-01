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
    extra: dict[str, Any] | None = None,
    extensions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The provenance header. ``extra`` holds drawbridge's own per-converter fields; ``extensions``
    is the area for anyone else: one mapping per namespace, preserved and never interpreted here."""
    if unit not in UNITS:
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
        "format": MIRROR_FORMAT,
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
    if declared != MIRROR_FORMAT:
        raise MirrorFormatError(f"unsupported mirror format: {declared}")
    if header.get("unit", "page") not in UNITS:
        raise MirrorFormatError(f"unknown mirror unit: {header['unit']}")
    if not isinstance(header.get("extensions", {}), dict):
        raise MirrorFormatError("mirror extensions must be a mapping")
    return header, match.group(2).lstrip("\n")


def mirror_text(body: bytes) -> str:
    """The normalised reading view of a retained body; the bytes stay unchanged."""
    return body.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").lstrip("\n")


def page_sections(body: str) -> list[str]:
    """The text of each ``## Page N`` section, in order."""
    parts = re.split(r"^## Page (\d+)\n", body, flags=re.M)
    sections: list[str] = []
    for index in range(1, len(parts), 2):
        expected = len(sections) + 1
        if int(parts[index]) != expected:
            raise MirrorFormatError(f"page sections out of order at page {parts[index]}")
        sections.append(parts[index + 1].strip("\n"))
    return sections


def sections(body: str) -> list[tuple[str, str]]:
    """Every ``## Heading`` section of a body as (heading, text), in order, whatever the unit."""
    parts = re.split(r"^## (.+)\n", body, flags=re.M)
    return [(parts[i].strip(), parts[i + 1].strip("\n")) for i in range(1, len(parts), 2)]
