"""Markdown structure for born-digital PDF pages, read from the PDF's own typography. No model.

Font flags give bold, italic and monospace; how much text is set at each size gives the body size
and the heading levels above it; link rectangles give link targets; detected tables become tables.
Nothing here decides what a word is: every candidate this module proposes is checked against the
fidelity text by the structure stage's word gate before it is used.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Mapping, Sequence

from .pdf_tools import Line, PageLayout, Run, Table

BULLETS = "•▪◦‣·●○■□➢❖"
_BULLET = re.compile(rf"^\s*[{BULLETS}]\s*")
_NUMBERED = re.compile(r"^\s*\(?\d{1,3}[.)]\s+\S")
HEADING_RATIO = 1.15
MAX_HEADING_CHARS = 200
WRAPPED_LINE_SHARE = 0.75
MAX_HEADING_SHARE = 0.3


@dataclass(frozen=True)
class Typography:
    """Document-wide facts: the look most text is set in, and the sizes that stand above it."""

    body_size: float
    body_look: tuple[bool, bool, bool]
    heading_sizes: tuple[float, ...]

    def heading_level(self, line: Line) -> int | None:
        inked = [run for run in line.runs if run.text.strip()]
        if not inked or len(line.text.strip()) > MAX_HEADING_CHARS:
            return None
        size = min(run.size for run in inked)
        if size not in self.heading_sizes:
            return None
        return min(3, self.heading_sizes.index(size) + 1)


def typography(layouts: Mapping[int, PageLayout]) -> Typography:
    sizes: Counter[float] = Counter()
    looks: Counter[tuple[bool, bool, bool]] = Counter()
    for layout in layouts.values():
        for block in layout.blocks:
            for line in block:
                for run in line.runs:
                    weight = len(run.text.strip())
                    sizes[run.size] += weight
                    looks[(run.bold, run.italic, run.mono)] += weight
    if not sizes:
        return Typography(0.0, (False, False, False), ())
    body = sizes.most_common(1)[0][0]
    larger = sorted((size for size in sizes if size >= body * HEADING_RATIO), reverse=True)
    return Typography(body, looks.most_common(1)[0][0], tuple(larger))


def _target(uri: str) -> str:
    return uri.replace(" ", "%20").replace("(", "%28").replace(")", "%29")


def _inline(runs: Sequence[Run], body_look: tuple[bool, bool, bool], *, emphasis: bool = True) -> str:
    """Runs to Markdown. Only a look that departs from the body look is emphasis."""
    keyed: list[list] = []
    for run in runs:
        look = (run.bold and not body_look[0], run.italic and not body_look[1], run.mono and not body_look[2]) if emphasis else (False, False, False)
        keyed.append([run.text, (look, run.link)])
    for index, (text, _) in enumerate(keyed):  # white space between two alike runs belongs to them
        if not text.strip() and 0 < index < len(keyed) - 1 and keyed[index - 1][1] == keyed[index + 1][1]:
            keyed[index][1] = keyed[index - 1][1]
    merged: list[list] = []
    for text, key in keyed:
        if merged and merged[-1][1] == key:
            merged[-1][0] += text
        else:
            merged.append([text, key])
    out = []
    for text, ((bold, italic, mono), link) in merged:
        core = text.strip()
        if not core:
            out.append(text)
            continue
        lead, tail = text[: len(text) - len(text.lstrip())], text[len(text.rstrip()) :]
        if mono:
            core = f"`{core}`"
        marks = "*" * (2 * bold + italic)
        core = f"{marks}{core}{marks}"
        if link:
            core = f"[{core}]({_target(link)})"
        out.append(lead + core + tail)
    return re.sub(r"[ \t]+", " ", "".join(out)).strip()


def _join(lines: Sequence[Line]) -> list[Run]:
    runs: list[Run] = []
    for index, line in enumerate(lines):
        if index:
            runs.append(Run(" ", line.runs[0].size))
        runs.extend(line.runs)
    return runs


def _is_wrapped(lines: Sequence[Line]) -> bool:
    """Lines that all but fill the block's width are one paragraph; ragged ones mean their breaks."""
    if len(lines) < 2:
        return True
    widths = [line.bbox[2] - line.bbox[0] for line in lines]
    return all(width >= WRAPPED_LINE_SHARE * max(widths) for width in widths[:-1])


def _table(table: Table) -> str:
    def row(cells: Sequence[str]) -> str:
        return "| " + " | ".join(re.sub(r"\s+", " ", cell).strip().replace("|", "\\|") for cell in cells) + " |"

    width = max(len(cells) for cells in table.rows)
    rows = [tuple(cells) + ("",) * (width - len(cells)) for cells in table.rows]
    return "\n".join([row(rows[0]), "| " + " | ".join(["---"] * width) + " |", *(row(cells) for cells in rows[1:])])


def _usable(table: Table) -> bool:
    cells = [cell for row in table.rows for cell in row]
    return len(table.rows) >= 2 and max((len(row) for row in table.rows), default=0) >= 2 and sum(1 for cell in cells if cell.strip()) * 2 >= len(cells)


def _block(lines: Sequence[Line], facts: Typography) -> list[str]:
    out: list[str] = []
    index = 0
    while index < len(lines):
        level = facts.heading_level(lines[index])
        if level is not None:
            end = index + 1
            while end < len(lines) and facts.heading_level(lines[end]) == level:
                end += 1
            out.append("#" * (level + 2) + " " + _inline(_join(lines[index:end]), facts.body_look, emphasis=False))
            index = end
            continue
        end = index + 1
        while end < len(lines) and facts.heading_level(lines[end]) is None:
            end += 1
        out.extend(_prose(lines[index:end], facts))
        index = end
    return out


def _prose(lines: Sequence[Line], facts: Typography) -> list[str]:
    starts = [i for i, line in enumerate(lines) if _BULLET.match(line.text) or _NUMBERED.match(line.text)]
    if not starts:
        if _is_wrapped(lines):
            return [_inline(_join(lines), facts.body_look)]
        return ["\n".join(_inline(line.runs, facts.body_look) for line in lines)]
    out = []
    if starts[0] > 0:
        out.extend(_prose(lines[: starts[0]], facts))
    items = []
    for position, start in enumerate(starts):
        stop = starts[position + 1] if position + 1 < len(starts) else len(lines)
        text = _inline(_join(lines[start:stop]), facts.body_look)
        items.append(_BULLET.sub("- ", text, count=1) if _BULLET.match(text) else text)
    out.append("\n".join(items))
    return out


def _headings_are_credible(layout: PageLayout, facts: Typography) -> bool:
    """Headings are the few large lines on a page. A page set mostly in large type (a cover, a slide,
    a notice) has no headings that its type size can reveal."""
    total = large = 0
    for block in layout.blocks:
        for line in block:
            weight = len(line.text.strip())
            total += weight
            large += weight if facts.heading_level(line) is not None else 0
    return total > 0 and large <= MAX_HEADING_SHARE * total


def render_page(layout: PageLayout, facts: Typography, *, tables: bool = True) -> str:
    if not _headings_are_credible(layout, facts):
        facts = Typography(facts.body_size, facts.body_look, ())
    usable = [table for table in layout.tables if _usable(table)] if tables else []
    placed: set[int] = set()
    parts: list[str] = []
    for block in layout.blocks:
        kept: list[Line] = []
        for line in block:
            centre = ((line.bbox[0] + line.bbox[2]) / 2, (line.bbox[1] + line.bbox[3]) / 2)
            owner = next((i for i, table in enumerate(usable) if table.bbox[0] <= centre[0] <= table.bbox[2] and table.bbox[1] <= centre[1] <= table.bbox[3]), None)
            if owner is None:
                kept.append(line)
                continue
            if kept:
                parts.extend(_block(kept, facts))
                kept = []
            if owner not in placed:
                placed.add(owner)
                parts.append(_table(usable[owner]))
        if kept:
            parts.extend(_block(kept, facts))
    joined = "\n\n".join(part for part in parts if part.strip())
    return re.sub(r"(^- .*)\n\n(?=- )", r"\1\n", joined, flags=re.M)


def candidates(layouts: Mapping[int, PageLayout]) -> dict[int, list[str]]:
    """For each page, renderings in order of preference. The caller uses the first whose words match."""
    facts = typography(layouts)
    out: dict[int, list[str]] = {}
    for number, layout in layouts.items():
        full = render_page(layout, facts)
        plain = render_page(layout, facts, tables=False)
        out[number] = [full] if full == plain else [full, plain]
    return out
