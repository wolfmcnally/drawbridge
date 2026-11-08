"""Public presentation contracts, using small independently authored decks."""

from __future__ import annotations

import copy
import hashlib
import sys
import zipfile
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from presentation_fixtures import build_deck, rewrite  # noqa: E402

from drawbridge import (  # noqa: E402
    ConversionOptions,
    convert_file,
    parse_mirror_header,
    render_mirror,
    sections,
    slide_sections,
    sniff_media_type,
)
from drawbridge.configuration import configuration_context, load_configuration  # noqa: E402
from drawbridge.errors import MirrorFormatError  # noqa: E402
from drawbridge.presentations import PresentationError, PresentationLimitError  # noqa: E402
from drawbridge.slide_mirror import NO_SLIDE_TEXT, PPTX_MEDIA_TYPE  # noqa: E402


def mirror(path, **kwargs):
    return parse_mirror_header(render_mirror(convert_file(path, **kwargs).mirror))


def test_public_slides_preserve_order_notes_assets_and_original(tmp_path):
    source = build_deck(tmp_path / "content-without-extension")
    before = source.read_bytes()
    assert sniff_media_type(source)[0] == PPTX_MEDIA_TYPE
    header, body = mirror(source)
    records = header["slide_map"]["slides"]
    assert [r["slide_id"] for r in records] == [259, 256, 257, 258], "canonical source order"
    assert header["content_hash"] == "sha256:" + hashlib.sha256(before).hexdigest()
    assert source.read_bytes() == before, "original presentation bytes"
    payloads = slide_sections(body, header=header)
    assert len(payloads) == len(sections(body, header=header)) == 4
    assert "Last authored; first in canonical order" in payloads[0]
    assert "Alpha source text" in payloads[1] and "Grouped text" in payloads[1]
    assert "Nested group text" in payloads[1], "nested group text"
    assert "unrendered-content:timing" in records[1]["features"], "build metadata limitation"
    assert not any(
        flag.startswith("unrendered-content:graphic") for flag in records[1]["features"]
    ), "table native text is not unsupported graphic"
    assert "Cell alpha" in payloads[1] and "Cell beta" in payloads[1]
    assert records[1]["hidden"] is True
    note = records[1]
    assert body[note["notes_start"] : note["notes_end"]] == "Private alpha presenter note", (
        "attached notes"
    )
    assert all("Private alpha" not in payloads[i] for i in (0, 2, 3))
    assert records[2]["text_free"] and records[3]["text_free"]
    assert NO_SLIDE_TEXT in payloads[2]
    images = [a for a in header["presentation_assets"] if a["media_type"] == "image/png"]
    assert len(images) == 1 and len(images[0]["occurrences"]) == 2, "repeated image occurrences"
    assert {x["slide_id"] for x in images[0]["occurrences"]} == {257}


def test_notes_configuration_and_explicit_override(tmp_path):
    source = build_deck(tmp_path / "deck.pptx")
    config = tmp_path / "config.yaml"
    config.write_text("drawbridge:\n  presentation_notes: false\n")
    with configuration_context(load_configuration([config])):
        excluded, body = mirror(source)
        included, other = mirror(source, options=ConversionOptions(include_notes=True))
    assert excluded["presentation"]["notes_policy"] == "exclude", "configuration excludes notes"
    assert "Private alpha presenter note" not in body, "configuration excludes notes"
    assert all(r["notes_start"] is None for r in excluded["slide_map"]["slides"])
    assert included["presentation"]["notes_policy"] == "include"
    assert "Private alpha presenter note" in other, "explicit option wins"


@pytest.mark.parametrize(
    "fault", ["duplicate", "traversal", "entity", "missing-target", "duplicate-id", "xml-limit"]
)
def test_hostile_packages_refuse_without_partial_mirrors(tmp_path, fault):
    source = build_deck(tmp_path / "hostile.pptx")
    with zipfile.ZipFile(source) as archive:
        slide = archive.read("ppt/slides/slide1.xml")
        main = archive.read("ppt/presentation.xml")
    if fault == "duplicate":
        with pytest.warns(UserWarning, match="Duplicate name"):
            rewrite(source, extra=("ppt/slides/slide1.xml", slide))
    elif fault == "traversal":
        rewrite(source, extra=("../outside.xml", b"<x/>"))
    elif fault == "entity":
        rewrite(
            source,
            {
                "ppt/slides/slide1.xml": slide.replace(
                    b"?>", b"?><!DOCTYPE p:sld [<!ENTITY stolen SYSTEM 'file:///etc/passwd'>]>", 1
                )
            },
        )
    elif fault == "missing-target":
        with zipfile.ZipFile(source) as archive:
            rels = archive.read("ppt/_rels/presentation.xml.rels")
        rewrite(
            source,
            {
                "ppt/_rels/presentation.xml.rels": rels.replace(
                    b"</Relationships>",
                    b'<Relationship Id="missing-audit" '
                    b'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                    b'relationships/image" '
                    b'Target="media/absent.png"/></Relationships>',
                )
            },
        )
    elif fault == "duplicate-id":
        rewrite(source, {"ppt/presentation.xml": main.replace(b'id="257"', b'id="256"')})
    else:
        rewrite(source, extra=("large.xml", b"<x>" + b" " * (8 * 1024**2) + b"</x>"))
        # Declare the part so the intended XML byte guard, not a missing type, refuses.
        with zipfile.ZipFile(source) as archive:
            types = archive.read("[Content_Types].xml")
        rewrite(
            source,
            {
                "[Content_Types].xml": types.replace(
                    b"</Types>",
                    b'<Override PartName="/large.xml" ContentType="application/xml"/></Types>',
                )
            },
        )
    error = PresentationLimitError if fault == "xml-limit" else PresentationError
    with pytest.raises(error) as caught:
        convert_file(source, media_type=PPTX_MEDIA_TYPE)
    assert (
        caught.value.code
        == {
            "duplicate": "duplicate-member",
            "traversal": "unsafe-member",
            "entity": "xml-doctype",
            "missing-target": "missing-internal-target",
            "duplicate-id": "ambiguous-slide-identity",
            "xml-limit": "xml-byte-limit",
        }[fault]
    ), "specific admission guard"


@pytest.mark.parametrize(
    ("content", "actual"),
    [
        (
            "application/vnd.ms-powerpoint.presentation.macroEnabled.main+xml",
            "application/vnd.ms-powerpoint.presentation.macroEnabled.12",
        ),
        (
            "application/vnd.openxmlformats-officedocument.presentationml.template.main+xml",
            "application/vnd.openxmlformats-officedocument.presentationml.template",
        ),
    ],
)
def test_renamed_unsupported_families_are_truthfully_deferred(tmp_path, content, actual):
    source = build_deck(tmp_path / "ordinary.pptx")
    with zipfile.ZipFile(source) as archive:
        types = archive.read("[Content_Types].xml")
    rewrite(
        source,
        {
            "[Content_Types].xml": types.replace(
                b"application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
                content.encode(),
            )
        },
    )
    result = convert_file(source, media_type=PPTX_MEDIA_TYPE)
    assert result.media_type == actual, "admitted unsupported media type"
    assert result.method == "conversion-deferred:unsupported-presentation-family"


@pytest.mark.parametrize("fault", ["identity", "span", "count", "notes-policy", "framing"])
def test_slide_map_rejects_identity_span_and_framing_tampering(tmp_path, fault):
    header, body = mirror(build_deck(tmp_path / "deck"))
    assert len(slide_sections(body, header=header)) == 4
    changed = copy.deepcopy(header)
    text = body
    rows = changed["slide_map"]["slides"]
    if fault == "identity":
        rows[1]["slide_id"] = rows[0]["slide_id"]
    elif fault == "span":
        rows[1]["content_start"] += 1
    elif fault == "count":
        changed["slide_count"] = 0
    elif fault == "notes-policy":
        changed["presentation"]["notes_policy"] = "exclude"
    else:
        text = body + "\n\n## Injected section"
    with pytest.raises(MirrorFormatError):
        slide_sections(text, header=changed)


def test_cli_verifies_source_slides_and_rejects_changed_source(tmp_path, capsys):
    from drawbridge import cli

    source = build_deck(tmp_path / "deck.pptx")
    output = tmp_path / "mirror.md"
    assert cli.main(["convert", str(source), "--notes", "exclude", "-o", str(output)]) == 0
    header, body = parse_mirror_header(output)
    assert "Private alpha presenter note" not in body
    assert header["presentation"]["notes_policy"] == "exclude"
    assert cli.main(["verify", str(output), "--source", str(source)]) == 0
    assert "(4 slides)" in capsys.readouterr().out, "slide verification count"
    with zipfile.ZipFile(source) as archive:
        xml = archive.read("ppt/slides/slide4.xml")
    rewrite(source, {"ppt/slides/slide4.xml": xml.replace(b"Last authored", b"Changed source")})
    assert cli.main(["verify", str(output), "--source", str(source)]) == cli.EXIT_VERIFY, (
        "presentation inventory mismatch is refused"
    )
    assert "identity differs" in capsys.readouterr().err


def test_deadline_refuses_and_reaps_the_real_worker_group(tmp_path, monkeypatch):
    import os

    from drawbridge import presentation_worker

    source = build_deck(tmp_path / "deadline.pptx")
    started = []
    real_launch = presentation_worker.subprocess.Popen

    def observe(*args, **kwargs):
        process = real_launch(*args, **kwargs)
        started.append(process.pid)
        return process

    monkeypatch.setattr(presentation_worker.subprocess, "Popen", observe)
    monkeypatch.setattr(presentation_worker, "DEADLINE", 0)
    with pytest.raises(PresentationLimitError, match="deadline exceeded"):
        convert_file(source, media_type=PPTX_MEDIA_TYPE)
    assert len(started) == 1, "real owned worker was launched"
    with pytest.raises(ProcessLookupError):
        os.killpg(started[0], 0)


@pytest.mark.parametrize("kind", ["smartart", "ink", "unknown-shape", "chart"])
def test_unrendered_constructs_keep_slide_content_with_limitations(tmp_path, kind):
    from lxml import etree

    source = build_deck(tmp_path / "constructs.pptx")
    if kind == "chart":
        from pptx import Presentation
        from pptx.chart.data import CategoryChartData
        from pptx.enum.chart import XL_CHART_TYPE
        from pptx.util import Inches

        deck = Presentation(source)
        data = CategoryChartData()
        data.categories = ["First", "Second"]
        data.add_series("Series", [1, 2])
        deck.slides[1].shapes.add_chart(
            XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(1), Inches(1), Inches(2), Inches(2), data
        )
        deck.save(source)
        header, body = mirror(source, media_type=PPTX_MEDIA_TYPE)
        assert "Alpha source text" in body
        assert "unrendered-content:chart" in header["slide_map"]["slides"][1]["features"], (
            "unsupported-content flag"
        )
        assert any(row["part"].endswith(".xlsx") for row in header["presentation_assets"])
        return
    with zipfile.ZipFile(source) as archive:
        root = etree.fromstring(archive.read("ppt/slides/slide1.xml"))
    p = "http://schemas.openxmlformats.org/presentationml/2006/main"
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    tree = root.find(f"{{{p}}}cSld/{{{p}}}spTree")
    if kind == "smartart":
        node = etree.fromstring(
            f'<p:graphicFrame xmlns:p="{p}" xmlns:a="{a}">'
            '<p:nvGraphicFramePr><p:cNvPr id="500" name="Diagram"/>'
            "<p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>"
            '<p:xfrm><a:off x="0" y="0"/><a:ext cx="100" cy="100"/></p:xfrm>'
            "<a:graphic><a:graphicData "
            'uri="http://schemas.openxmlformats.org/drawingml/2006/diagram"/>'
            "</a:graphic></p:graphicFrame>"
        )
        expected = "unrendered-content:smartart"
    elif kind == "ink":
        node = etree.Element(f"{{{p}}}contentPart")
        expected = "unrendered-content:contentPart"
    else:
        node = etree.fromstring(
            f'<p:sp xmlns:p="{p}" xmlns:a="{a}">'
            '<p:nvSpPr><p:cNvPr id="501" name="Unknown geometry"/>'
            "<p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr/>"
            "<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r>"
            "<a:t>Unknown shape native text</a:t></a:r></a:p></p:txBody></p:sp>"
        )
        expected = None
    tree.append(node)
    rewrite(source, {"ppt/slides/slide1.xml": etree.tostring(root)})
    header, body = mirror(source, media_type=PPTX_MEDIA_TYPE)
    assert header["slide_count"] == 4 and "Alpha source text" in body
    if expected:
        assert expected in header["slide_map"]["slides"][1]["features"], "unsupported-content flag"
    else:
        assert "Unknown shape native text" in body, "unknown shape native text"


@pytest.mark.parametrize("fault", ["shared", "wrong-backlink"])
def test_notes_ownership_refuses_ambiguous_attachment(tmp_path, fault):
    source = build_deck(tmp_path / "notes.pptx")
    with zipfile.ZipFile(source) as archive:
        if fault == "shared":
            part = "ppt/slides/_rels/slide2.xml.rels"
            xml = archive.read(part).replace(
                b"</Relationships>",
                b'<Relationship Id="shared-notes" '
                b'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                b'relationships/notesSlide" Target="../notesSlides/notesSlide1.xml"/>'
                b"</Relationships>",
            )
        else:
            part = "ppt/notesSlides/_rels/notesSlide1.xml.rels"
            xml = archive.read(part).replace(b"../slides/slide1.xml", b"../slides/slide2.xml")
    rewrite(source, {part: xml})
    with pytest.raises(PresentationError) as caught:
        convert_file(source, media_type=PPTX_MEDIA_TYPE)
    assert caught.value.code == "ambiguous-notes-owner", "notes ownership guard"


@pytest.mark.parametrize(
    "kind", ["strict", "vba", "encrypted-flag", "expansion", "forged-expansion"]
)
def test_excluded_profiles_and_expansion_refuse_truthfully(tmp_path, kind):
    source = build_deck(tmp_path / "excluded.pptx")
    with zipfile.ZipFile(source) as archive:
        main = archive.read("ppt/presentation.xml")
        types = archive.read("[Content_Types].xml")
    if kind == "strict":
        rewrite(
            source,
            {
                "ppt/presentation.xml": main.replace(
                    b"http://schemas.openxmlformats.org/presentationml/2006/main",
                    b"http://purl.oclc.org/ooxml/presentationml/main",
                )
            },
        )
        expected = "strict-ooxml"
    elif kind == "vba":
        rewrite(
            source,
            {
                "[Content_Types].xml": types.replace(
                    b"</Types>",
                    b'<Override PartName="/ppt/vbaProject.bin" '
                    b'ContentType="application/vnd.ms-office.vbaProject"/></Types>',
                )
            },
            extra=("ppt/vbaProject.bin", b"unexecuted synthetic macro sentinel"),
        )
        expected = "macro-bearing-package"
    elif kind == "encrypted-flag":
        data = bytearray(source.read_bytes())
        start = data.index(b"PK\x01\x02")
        data[start + 8] |= 1
        source.write_bytes(data)
        expected = "encrypted-office-package"
    else:
        rewrite(source, extra=("bomb.bin", b"0" * (65 * 1024**2)))
        if kind == "forged-expansion":
            with zipfile.ZipFile(source) as archive:
                local = archive.getinfo("bomb.bin").header_offset
            data = bytearray(source.read_bytes())
            central = data.rindex(b"bomb.bin") - 46
            assert data[central : central + 4] == b"PK\x01\x02"
            prefix_crc = zlib.crc32(b"0").to_bytes(4, "little")
            data[local + 14 : local + 18] = prefix_crc
            data[local + 22 : local + 26] = (1).to_bytes(4, "little")
            data[central + 16 : central + 20] = prefix_crc
            data[central + 24 : central + 28] = (1).to_bytes(4, "little")
            source.write_bytes(data)
            # This bounded control demonstrates why ZipExtFile output is not
            # an oracle for actual expansion of attacker-declared metadata.
            with zipfile.ZipFile(source) as archive, archive.open("bomb.bin") as stream:
                assert stream.read(2) == b"0"
        with pytest.raises(PresentationLimitError) as caught:
            convert_file(source, media_type=PPTX_MEDIA_TYPE)
        assert caught.value.code == "expanded-byte-limit", "expanded member byte guard"
        return
    result = convert_file(source, media_type=PPTX_MEDIA_TYPE)
    assert result.method == "conversion-deferred:" + expected, "excluded profile reason"


def test_legacy_and_cli_notes_policy_and_malformed_exit(tmp_path, capsys):
    import json

    from drawbridge import cli
    from drawbridge.profile import ProfileError, parse_profile

    source = build_deck(tmp_path / "deck.pptx")
    legacy = tmp_path / "legacy.yaml"
    legacy.write_text("presentation_notes: false\n")
    assert cli.main(["convert", str(source), "--profile", str(legacy), "--dry-run"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["presentation_notes"] == {"include": False, "source": "profile"}, (
        "legacy notes policy"
    )
    output = tmp_path / "included.md"
    assert (
        cli.main(
            [
                "convert",
                str(source),
                "--profile",
                str(legacy),
                "--notes",
                "include",
                "--json",
                "-o",
                str(output),
            ]
        )
        == 0
    )
    summary = json.loads(capsys.readouterr().out)
    assert summary.get("slide_count") == 4, "CLI source slide count"
    assert "Private alpha presenter note" in output.read_text(), "CLI option overrides profile"
    with pytest.raises(ProfileError):
        parse_profile({"presentation_notes": "false"})
    assert (
        parse_profile({"presentation_notes": False}).redacted().get("presentation_notes") is False
    ), "notes policy is visible in profile report"
    rewrite(source, extra=("../unsafe.xml", b"<x/>"))
    assert cli.main(["convert", str(source), "--json"]) == cli.EXIT_FAILED, (
        "malformed presentation is failed"
    )
    error = json.loads(capsys.readouterr().out)
    assert error["reason"] == "unsafe-member", "CLI malformed reason"


@pytest.mark.parametrize("consumer", ["page", "semantic", "structure", "refinement", "transcript"])
def test_v1_consumers_refuse_slides_before_callbacks(tmp_path, monkeypatch, consumer):
    from drawbridge import audio
    from drawbridge.mirror import page_sections
    from drawbridge.profile import build_plan, parse_profile
    from drawbridge.refine import refined_mirror
    from drawbridge.structure import run_structure, semantic_mirror

    source = build_deck(tmp_path / "deck.pptx")
    result = convert_file(source, media_type=PPTX_MEDIA_TYPE)
    rendered = render_mirror(result.mirror)
    target = tmp_path / "deck.md"
    target.write_text(rendered)

    def forbidden(*args, **kwargs):
        raise AssertionError("v2 reached a v1 callback or dependency")

    monkeypatch.setattr(audio, "_load_dependency", forbidden)
    with pytest.raises(MirrorFormatError, match="slide mirrors"):
        if consumer == "page":
            page_sections(result.mirror.body, header=result.mirror.header)
        elif consumer == "semantic":
            semantic_mirror(rendered, forbidden, method="synthetic", endpoint=None)
        elif consumer == "structure":
            profile = parse_profile({"stages": {"structure": {}}})
            run_structure(
                rendered,
                profile=profile,
                plan=build_plan(profile, "application/pdf"),
                annotate=forbidden,
            )
        elif consumer == "refinement":
            refined_mirror(rendered, forbidden, method="synthetic", endpoint=None)
        else:
            audio.rerender(target, tmp_path / "absent-package")


def test_navigation_graph_uses_reader_dfs_not_longest_simple_path(tmp_path):
    from lxml import etree
    from pptx import Presentation
    from pptx.util import Inches

    source = tmp_path / "navigation.pptx"
    deck = Presentation()
    authored = [deck.slides.add_slide(deck.slide_layouts[6]) for _ in range(70)]
    for number, slide in enumerate(authored):
        box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(1))
        box.text = f"Navigation slide {number + 1}"
        if number + 1 < len(authored):
            box.click_action.target_slide = authored[number + 1]
    deck.save(source)
    with zipfile.ZipFile(source) as archive:
        rels = etree.fromstring(archive.read("ppt/_rels/presentation.xml.rels"))
    # Reader DFS sees the terminal slide first, then shallow links to visited
    # slides. Longest-simple-path exploration still invents a 70-slide depth.
    rels[:] = list(reversed(rels[:]))
    rewrite(source, {"ppt/_rels/presentation.xml.rels": etree.tostring(rels)})
    header, body = mirror(source, media_type=PPTX_MEDIA_TYPE)
    assert header["slide_count"] == 70, "navigation graph is bounded by reader DFS"
    assert [r["slide_id"] for r in header["slide_map"]["slides"]] == list(range(256, 326))
    assert "Navigation slide 70" in body


def test_unused_sibling_layout_asset_is_not_a_slide_occurrence(tmp_path):
    import io

    from lxml import etree
    from PIL import Image

    source = build_deck(tmp_path / "layouts.pptx")
    p = "http://schemas.openxmlformats.org/presentationml/2006/main"
    r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    pkg = "http://schemas.openxmlformats.org/package/2006/relationships"
    with zipfile.ZipFile(source) as archive:
        layout = etree.fromstring(archive.read("ppt/slideLayouts/slideLayout1.xml"))
        rels = etree.fromstring(archive.read("ppt/slideLayouts/_rels/slideLayout1.xml.rels"))
        slide = etree.fromstring(archive.read("ppt/slides/slide2.xml"))
    picture = copy.deepcopy(slide.find(f"{{{p}}}cSld/{{{p}}}spTree/{{{p}}}pic"))
    picture.find(f"{{{p}}}nvPicPr/{{{p}}}cNvPr").set("id", "999")
    for element in picture.iter():
        if f"{{{r}}}embed" in element.attrib:
            element.set(f"{{{r}}}embed", "layout-only")
    layout.find(f"{{{p}}}cSld/{{{p}}}spTree").append(picture)
    etree.SubElement(
        rels,
        f"{{{pkg}}}Relationship",
        Id="layout-only",
        Type=r + "/image",
        Target="../media/layout-only.png",
    )
    pixel = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(pixel, "PNG")
    rewrite(
        source,
        {
            "ppt/slideLayouts/slideLayout1.xml": etree.tostring(layout),
            "ppt/slideLayouts/_rels/slideLayout1.xml.rels": etree.tostring(rels),
        },
        extra=("ppt/media/layout-only.png", pixel.getvalue()),
    )
    header, _ = mirror(source, media_type=PPTX_MEDIA_TYPE)
    asset = next(x for x in header["presentation_assets"] if x["part"].endswith("/layout-only.png"))
    assert asset["occurrences"] == [], "unused sibling layout is not inherited content"


@pytest.mark.parametrize("kind", ["default", "override"])
def test_case_insensitive_content_types_admit_ordinary_media(tmp_path, kind):
    source = build_deck(tmp_path / "extension.pptx")
    with zipfile.ZipFile(source) as archive:
        types = archive.read("[Content_Types].xml")
    assert b'Extension="png"' in types
    changed = (
        types.replace(b'Extension="png"', b'Extension="PNG"')
        if kind == "default"
        else types.replace(b'PartName="/ppt/presentation.xml"', b'PartName="/PPT/PRESENTATION.XML"')
    )
    rewrite(source, {"[Content_Types].xml": changed})
    header, _ = mirror(source, media_type=PPTX_MEDIA_TYPE)
    assert any(x["media_type"] == "image/png" for x in header["presentation_assets"]), (
        "case-insensitive default extension"
    )


@pytest.mark.parametrize("field", ["external", "custom-shows"])
def test_verify_rejects_changed_presentation_inventory(tmp_path, capsys, field):
    from drawbridge import cli
    from drawbridge.mirror import Mirror

    source = build_deck(tmp_path / "deck.pptx")
    header, body = mirror(source, media_type=PPTX_MEDIA_TYPE)
    if field == "external":
        header["presentation_external"] = [{"part": "invented", "scheme": "https"}]
    else:
        header["presentation"]["custom_shows"] = [{"name": "Invented", "slide_ids": [256]}]
    output = tmp_path / "tampered.md"
    output.write_text(render_mirror(Mirror(header, body)))
    assert cli.main(["verify", str(output), "--source", str(source)]) == cli.EXIT_VERIFY, (
        "presentation inventory mismatch is refused"
    )
    assert "differs" in capsys.readouterr().err, "complete presentation inventory verification"


@pytest.mark.parametrize("variant", ["unicode-extra", "zip64-prepended", "zip64-legacy-location"])
def test_generic_zip_refinement_preserves_effective_names_and_offsets(
    tmp_path, monkeypatch, variant
):
    import struct
    import zlib

    from drawbridge import refine_media_type

    source = tmp_path / "container"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        if variant == "unicode-extra":
            info = zipfile.ZipInfo("raw.bin")
            payload = b"\x01" + struct.pack("<I", zlib.crc32(b"raw.bin")) + b"word/document.xml"
            info.extra = struct.pack("<HH", 0x7075, len(payload)) + payload
            archive.writestr(info, "<document/>")
        else:
            archive.writestr("word/document.xml", "<document/>")
    if variant.startswith("zip64"):
        data = source.read_bytes()
        end = data.rindex(b"PK\x05\x06")
        row = struct.unpack("<4s4H2IH", data[end : end + 22])
        count, size, offset = row[4], row[5], row[6]
        record = struct.pack(
            "<4sQ2H2I4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, count, count, size, offset
        )
        locator = struct.pack("<4sIQI", b"PK\x06\x07", 0, end, 1)
        source.write_bytes(b"Harmless prepended bytes" + data[:end] + record + locator + data[end:])
    if variant == "zip64-legacy-location":
        actual_end = zipfile._EndRecData

        def older_location(handle):
            row = actual_end(handle)
            handle.seek(row[zipfile._ECD_LOCATION])
            if handle.read(4) == zipfile.stringEndArchive64:
                row[zipfile._ECD_LOCATION] += (
                    zipfile.sizeEndCentDir64 + zipfile.sizeEndCentDir64Locator
                )
            return row

        # CPython v3.12.0 returns this physical EOCD location; this simulates
        # that source-documented helper shape, not an executed older interpreter.
        monkeypatch.setattr(zipfile, "_EndRecData", older_location)
    assert (
        refine_media_type(source, "application/zip")
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ), "effective ZIP part identification"


def test_source_alternate_shows_links_and_unextracted_comments_are_accounted(tmp_path):
    from lxml import etree

    source = build_deck(tmp_path / "metadata.pptx")
    p = "http://schemas.openxmlformats.org/presentationml/2006/main"
    r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    pkg = "http://schemas.openxmlformats.org/package/2006/relationships"
    with zipfile.ZipFile(source) as archive:
        main = etree.fromstring(archive.read("ppt/presentation.xml"))
        slide = etree.fromstring(archive.read("ppt/slides/slide1.xml"))
        rels = etree.fromstring(archive.read("ppt/slides/_rels/slide1.xml.rels"))
        types = archive.read("[Content_Types].xml")
    ids = {int(node.get("id")): node.get(f"{{{r}}}id") for node in main.find(f"{{{p}}}sldIdLst")}
    show_list = etree.SubElement(main, f"{{{p}}}custShowLst")
    show = etree.SubElement(show_list, f"{{{p}}}custShow", name="Alternate", id="0")
    sequence = etree.SubElement(show, f"{{{p}}}sldLst")
    for identifier in (256, 259):
        etree.SubElement(sequence, f"{{{p}}}sld", {f"{{{r}}}id": ids[identifier]})
    target = "https://example.invalid/synthetic-resource"
    etree.SubElement(
        rels,
        f"{{{pkg}}}Relationship",
        Id="external-fixture",
        Type=r + "/hyperlink",
        Target=target,
        TargetMode="External",
    )
    c_nv_pr = slide.find(f"{{{p}}}cSld/{{{p}}}spTree/{{{p}}}sp/{{{p}}}nvSpPr/{{{p}}}cNvPr")
    etree.SubElement(
        c_nv_pr,
        "{http://schemas.openxmlformats.org/drawingml/2006/main}hlinkClick",
        {f"{{{r}}}id": "external-fixture"},
    )
    etree.SubElement(
        rels,
        f"{{{pkg}}}Relationship",
        Id="comment-fixture",
        Type=r + "/comments",
        Target="../comments/comment1.xml",
    )
    rewrite(
        source,
        {
            "ppt/presentation.xml": etree.tostring(main),
            "ppt/slides/slide1.xml": etree.tostring(slide),
            "ppt/slides/_rels/slide1.xml.rels": etree.tostring(rels),
            "[Content_Types].xml": types.replace(
                b"</Types>",
                b'<Override PartName="/ppt/comments/comment1.xml" '
                b'ContentType="application/vnd.openxmlformats-officedocument.'
                b'presentationml.comments+xml"/></Types>',
            ),
        },
        extra=(
            "ppt/comments/comment1.xml",
            (
                f'<p:cmLst xmlns:p="{p}"><p:cm authorId="0" idx="1">'
                "<p:text>Reviewer-only comment</p:text></p:cm></p:cmLst>"
            ).encode(),
        ),
    )
    header, body = mirror(source, media_type=PPTX_MEDIA_TYPE)
    assert header["presentation"]["custom_shows"] == [
        {"name": "Alternate", "slide_ids": [256, 259]}
    ], "source custom-show sequence"
    assert [row["slide_id"] for row in header["slide_map"]["slides"]] == [259, 256, 257, 258]
    external = header["presentation_external"]
    assert (
        len(external) == 1
        and external[0]["target_sha256"] == hashlib.sha256(target.encode()).hexdigest()
    ), "unvisited external inventory"
    assert target not in str(header) and "Reviewer-only comment" not in body
    assert "comment-related-parts-not-extracted" in header["verify"], "comment limitation"


@pytest.mark.parametrize(
    ("declared", "unit"),
    [
        ("drawbridge.mirror.v1", "slide"),
        ("drawbridge.mirror.v2", "page"),
    ],
)
def test_format_units_do_not_alias_old_page_contracts(tmp_path, declared, unit):
    from drawbridge.mirror import build_header

    source = build_deck(tmp_path / "contract.pptx")
    with pytest.raises(ValueError, match="unknown mirror unit"):
        build_header(
            source,
            method="synthetic",
            media_type=PPTX_MEDIA_TYPE,
            mirror_format=declared,
            unit=unit,
        )
