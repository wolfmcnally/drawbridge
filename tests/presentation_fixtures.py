"""Small first-party authored presentations; no downloaded/client deck bytes."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.util import Inches


def build_deck(target: Path) -> Path:
    deck = Presentation()
    first = deck.slides.add_slide(deck.slide_layouts[6])
    first.shapes.add_textbox(Inches(1), Inches(1), Inches(7), Inches(2)).text = (
        "Alpha source text\n雪🌉\n## Not another slide\n" + chr(96) * 4 + "\n<a id='fake'>"
    )
    first.notes_slide.notes_text_frame.text = "Private alpha presenter note"
    group = first.shapes.add_group_shape()
    group.shapes.add_textbox(Inches(1), Inches(3), Inches(2), Inches(1)).text = "Grouped text"
    nested = group.shapes.add_group_shape()
    nested.shapes.add_textbox(Inches(1), Inches(3), Inches(2), Inches(1)).text = "Nested group text"
    table = first.shapes.add_table(1, 2, Inches(1), Inches(4), Inches(3), Inches(1)).table
    table.cell(0, 0).text = "Cell alpha"
    table.cell(0, 1).text = "Cell beta"
    first._element.set("show", "0")
    image = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(image, "PNG")
    second = deck.slides.add_slide(deck.slide_layouts[6])
    second.shapes.add_picture(io.BytesIO(image.getvalue()), Inches(1), Inches(1))
    second.shapes.add_picture(io.BytesIO(image.getvalue()), Inches(2), Inches(1))
    deck.slides.add_slide(deck.slide_layouts[6])
    last = deck.slides.add_slide(deck.slide_layouts[6])
    last.shapes.add_textbox(
        Inches(1), Inches(1), Inches(4), Inches(2)
    ).text = "Last authored; first in canonical order"
    # Canonical order deliberately differs from part filenames and ZIP order.
    ids = deck.slides._sldIdLst
    ids.insert(0, ids[-1])
    deck.save(target)
    with zipfile.ZipFile(target) as archive:
        slide = archive.read("ppt/slides/slide1.xml")
    # Two paragraph-build records on one source slide, without claiming
    # animation playback or render fidelity from the native test producer.
    timing = (
        b'<p:timing><p:bldLst><p:bldP spid="2" grpId="0"/>'
        b'<p:bldP spid="2" grpId="1"/></p:bldLst></p:timing>'
    )
    rewrite(target, {"ppt/slides/slide1.xml": slide.replace(b"</p:sld>", timing + b"</p:sld>")})
    return target


def rewrite(target: Path, replacements: dict[str, bytes] | None = None, *, extra=None) -> Path:
    with zipfile.ZipFile(target) as archive:
        parts = [(item.filename, archive.read(item)) for item in archive.infolist()]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in reversed(parts):
            archive.writestr(name, (replacements or {}).get(name, data))
        if extra:
            archive.writestr(*extra)
    target.write_bytes(output.getvalue())
    return target
