from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest

from drawbridge import cli
from drawbridge.convert import convert_pdf
from drawbridge.mirror import Mirror, build_header, page_body, parse_mirror_header, render_mirror
from drawbridge.native import candidates
from drawbridge.pdf_tools import page_layouts
from drawbridge.profile import ProfileError, build_plan, parse_profile
from drawbridge.structure import NATIVE_METHOD, native_section, run_structure, words

LOCAL = {"stages": {"structure": {}}}
MODEL = {
    "endpoints": {"router": {"kind": "openai-compatible", "base_url": "https://example.invalid/v1", "api_key_env": "DB_TEST_ROUTER", "egress": "cloud"}},
    "stages": {"structure": {"endpoint": "router", "model": "some/model"}},
}
EXPECTED = """### Annual Report

#### Findings

The committee met on nine occasions during the year and heard from forty witnesses, whose evidence is set out below in full.

It found the **central claim** to be *unsupported* by `run_check()`.

- first exhibit
- second exhibit

See the [archive](https://example.org/archive) for more.

| Year | Hearings | Witnesses |
| --- | --- | --- |
| 2019 | 4 | 17 |
| 2020 | 5 | 23 |

Jane Example
Clerk of the Committee
12 Long Example Street North"""


def _styled(page, origin, pieces, size=11):
    x, y = origin
    for text, font in pieces:
        page.insert_text((x, y), text, fontname=font, fontsize=size)
        x += pymupdf.get_text_length(text, fontname=font, fontsize=size)


def _rich_page(page) -> None:
    page.insert_text((72, 80), "Annual Report", fontname="hebo", fontsize=20)
    page.insert_text((72, 110), "Findings", fontname="helv", fontsize=15)
    y = 140
    for line in ["The committee met on nine occasions during the year and", "heard from forty witnesses, whose evidence is set out", "below in full."]:
        page.insert_text((72, y), line, fontname="helv", fontsize=11)
        y += 14
    y += 10
    _styled(page, (72, y), [("It found the ", "helv"), ("central claim", "hebo"), (" to be ", "helv"), ("unsupported", "heit"), (" by ", "helv"), ("run_check()", "cour"), (".", "helv")])
    y += 24
    for item in ["• first exhibit", "• second exhibit"]:
        page.insert_text((72, y), item, fontname="helv", fontsize=11)
        y += 14
    y += 10
    page.insert_text((72, y), "See the archive for more.", fontname="helv", fontsize=11)
    lead = pymupdf.get_text_length("See the ", fontname="helv", fontsize=11)
    word = pymupdf.get_text_length("archive", fontname="helv", fontsize=11)
    page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(72 + lead, y - 10, 72 + lead + word, y + 3), "uri": "https://example.org/archive"})
    y += 30
    rows = [["Year", "Hearings", "Witnesses"], ["2019", "4", "17"], ["2020", "5", "23"]]
    shape = page.new_shape()
    for r in range(len(rows) + 1):
        shape.draw_line((72, y + r * 20), (372, y + r * 20))
    for c in range(4):
        shape.draw_line((72 + c * 100, y), (72 + c * 100, y + len(rows) * 20))
    shape.finish(color=(0, 0, 0))
    shape.commit()
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            page.insert_text((78 + c * 100, y + r * 20 + 14), cell, fontname="helv", fontsize=11)
    y += 90
    for line in ["Jane Example", "Clerk of the Committee", "12 Long Example Street North"]:
        page.insert_text((72, y), line, fontname="helv", fontsize=11)
        y += 14


@pytest.fixture
def rich_pdf(tmp_path: Path) -> Path:
    target = tmp_path / "report.pdf"
    with pymupdf.open() as document:
        _rich_page(document.new_page())
        document.new_page().insert_text((72, 80), "A plain second page.", fontname="helv", fontsize=11)
        document.save(target)
    return target


def _fidelity(pdf: Path) -> str:
    return render_mirror(convert_pdf(pdf, ocr=None).mirror)


def test_typography_links_and_tables_become_markdown_with_no_word_changed(rich_pdf):
    source = _fidelity(rich_pdf)
    profile = parse_profile(LOCAL)
    mirror = run_structure(source, profile=profile, plan=build_plan(profile, "application/pdf"), source=rich_pdf)
    header, body = parse_mirror_header(render_mirror(mirror))
    assert body == f"# Report\n\n## Page 1\n\n{EXPECTED}\n\n## Page 2\n\nA plain second page.\n"
    assert header["verify"] == []
    assert header["processing"][-1]["method"] == NATIVE_METHOD and header["processing"][-1]["egress"] == "local" and header["processing"][-1]["endpoint"] is None
    assert header["content_hash"] == parse_mirror_header(source)[0]["content_hash"]


def test_a_proposal_that_changes_a_word_is_never_used(rich_pdf, monkeypatch):
    import drawbridge.native as native

    real = native.candidates
    monkeypatch.setattr(native, "candidates", lambda layouts: {page: [text.replace("unsupported", "supported") for text in texts] for page, texts in real(layouts).items()})
    source = _fidelity(rich_pdf)
    profile = parse_profile(LOCAL)
    header, body = parse_mirror_header(render_mirror(run_structure(source, profile=profile, plan=build_plan(profile, "application/pdf"), source=rich_pdf)))
    assert header["verify"] == ["structure-fallback:Page 1"]
    assert body == parse_mirror_header(source)[1]          # page 1 kept its fidelity text; page 2 had nothing to add


def test_the_first_proposal_whose_words_match_wins():
    text = "Year Total\n2019 4"
    assert native_section(text, ["| Year | Total |\n| --- | --- |\n| 2019 | 5 |", "Year Total 2019 4"]) == ("Year Total 2019 4", None)
    assert native_section(text, ["Year Total 2019 5"]) == (text, "words-changed")


def test_the_gate_sets_aside_only_the_markdown_the_pass_writes():
    assert words("- **Bold** [link](https://example.org/a_%28b%29) `code`\n| a | b |\n| --- | --- |", inline=True) == ["Bold", "link", "code", "a", "b"]
    assert words("•Tight bullet \\| pipe", inline=True) == ["Tight", "bullet", "pipe"]
    assert words("plain *starred* word") == ["plain", "*starred*", "word"]   # the model's gate stays strict


def test_a_bold_document_is_not_emphasis_everywhere(tmp_path):
    target = tmp_path / "bold.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((72, 80), "Every word here is bold,", fontname="hebo", fontsize=11)
        _styled(page, (72, 110), [("so only ", "hebo"), ("this", "hebi"), (" stands out.", "hebo")])
        document.save(target)
    [text] = candidates(page_layouts(target, [1]))[1]
    assert text == "Every word here is bold,\n\nso only *this* stands out."


def test_a_page_set_mostly_in_large_type_has_no_headings(tmp_path):
    target = tmp_path / "cover.pdf"
    with pymupdf.open() as document:
        cover = document.new_page()
        cover.insert_text((72, 200), "Notice of Annual Meeting", fontname="helv", fontsize=28)
        cover.insert_text((72, 260), "All members are invited", fontname="helv", fontsize=28)
        body = document.new_page()
        body.insert_text((72, 80), "Agenda", fontname="helv", fontsize=28)
        for row in range(12):
            body.insert_text((72, 120 + row * 14), "The ordinary business of the meeting follows in the usual order.", fontname="helv", fontsize=11)
        document.save(target)
    pages = candidates(page_layouts(target, [1, 2]))
    assert "#" not in pages[1][0]
    assert pages[2][0].startswith("### Agenda\n\n")


def test_born_digital_pages_never_reach_the_model_and_scanned_pages_never_reach_the_typography_pass(rich_pdf, fixtures, tmp_path):
    header = build_header(rich_pdf, method="ocr", extra={"page_count": 2, "ocr_pages": [{"page": 2}]})
    source = render_mirror(Mirror(header, page_body("Report", [parse_mirror_header(_fidelity(rich_pdf))[1].split("## Page 1\n\n")[1].split("\n\n## Page 2")[0], "Scanned words\nwrapped here."])))
    profile = parse_profile({**MODEL, "limits": {"cache_dir": str(tmp_path / "routing-cache")}})
    seen = []

    def annotate(lines):
        seen.append(list(lines))
        return {"blocks": [{"lines": [1, 2], "kind": "paragraph"}]}

    mirror = run_structure(source, profile=profile, plan=build_plan(profile, "application/pdf"), annotate=annotate, source=rich_pdf)
    head, body = parse_mirror_header(render_mirror(mirror))
    assert seen == [["Scanned words", "wrapped here."]]
    assert "### Annual Report" in body and "Scanned words wrapped here." in body
    assert [entry["method"] for entry in head["processing"][-2:]] == [NATIVE_METHOD, "structure:annotate:some/model"]


def test_no_ai_keeps_the_typography_pass_and_drops_the_model(rich_pdf):
    profile = parse_profile(MODEL)
    plan = build_plan(profile, "application/pdf", no_ai=True)
    assert plan.runs("structure") and not plan.runs_model("structure") and plan.cloud_stages == ()
    called = []
    mirror = run_structure(_fidelity(rich_pdf), profile=profile, plan=plan, annotate=lambda lines: called.append(1), source=rich_pdf)
    assert called == [] and "### Annual Report" in mirror.body
    off = parse_profile({**MODEL, "stages": {"structure": {**MODEL["stages"]["structure"], "native_pass": "none"}}})
    assert not build_plan(off, "application/pdf", no_ai=True).runs("structure")


def test_nothing_to_do_means_no_semantic_mirror(rich_pdf):
    profile = parse_profile(LOCAL)
    plan = build_plan(profile, "application/pdf")
    assert run_structure(_fidelity(rich_pdf), profile=profile, plan=plan) is None          # no source to read typography from
    off = parse_profile({"stages": {"structure": {"native_pass": "none"}}})
    assert run_structure(_fidelity(rich_pdf), profile=off, plan=build_plan(off, "application/pdf"), source=rich_pdf) is None
    with pytest.raises(ProfileError, match="native_pass"):
        parse_profile({"stages": {"structure": {"native_pass": "guess"}}})


def test_cli_writes_the_semantic_mirror_with_no_endpoint_and_keeps_stdout_clean(rich_pdf, tmp_path, capsys):
    profile = tmp_path / "profile.yaml"
    profile.write_text("stages:\n  structure: {}\n")
    assert cli.main(["convert", str(rich_pdf), "--profile", str(profile), "--json"]) == 0
    summary = json.loads(capsys.readouterr().out)                                           # nothing but the summary was printed
    semantic = Path(summary["semantic_output"])
    assert semantic.name == "report.semantic.md" and "| 2019 | 4 | 17 |" in semantic.read_text()
    assert "| 2019" not in Path(summary["output"]).read_text()                              # the fidelity mirror is untouched


def test_the_library_call_returns_the_groomed_rendering_beside_an_untouched_fidelity_mirror(rich_pdf):
    import hashlib

    import drawbridge

    profile = drawbridge.parse_profile(LOCAL)
    result = drawbridge.convert_file(rich_pdf, profile=profile)
    assert "### Annual Report" in result.semantic.body and "### Annual Report" not in result.mirror.body
    stored_body = parse_mirror_header(render_mirror(result.mirror))[1]                 # the body as any reader of the mirror file sees it
    assert result.semantic.header["derived_from_body"] == "sha256:" + hashlib.sha256(stored_body.encode()).hexdigest()
    assert drawbridge.convert_file(rich_pdf, profile=profile, stages=False).semantic is None
    assert drawbridge.convert_file(rich_pdf).semantic is None                     # no profile, no grooming
    report = drawbridge.plan_report(rich_pdf, profile, drawbridge.build_plan(profile, "application/pdf"))
    assert report["sends_bytes_off_machine"] == [] and [stage["stage"] for stage in report["stages"] if stage["runs"]] == ["structure"]
