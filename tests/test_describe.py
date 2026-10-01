from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest

from drawbridge import cli
from drawbridge.describe import PENDING, WRITTEN, DescriptionError, describe_image, tidy
from drawbridge.documents import convert_file
from drawbridge.mirror import sections
from drawbridge.profile import build_plan, parse_profile

PROFILE = {
    "endpoints": {"eyes": {"kind": "openai-compatible", "base_url": "https://example.invalid/v1", "api_key_env": "DB_TEST_EYES", "egress": "cloud"}},
    "stages": {"image_description": {"endpoint": "eyes", "model": "some/vlm", "max_words": 12}},
}


@pytest.fixture
def picture(tmp_path: Path) -> Path:
    target = tmp_path / "chart.png"
    with pymupdf.open() as document:
        page = document.new_page(width=200, height=120)
        page.draw_rect(pymupdf.Rect(20, 20, 180, 100), color=(0, 0, 1), fill=(0.8, 0.8, 1))
        page.get_pixmap().save(target)
    return target


def _profile(tmp_path, **stage):
    raw = json.loads(json.dumps(PROFILE))
    raw["stages"]["image_description"].update(stage)
    raw["limits"] = {"cache_dir": str(tmp_path / "cache")}
    return parse_profile(raw)


def test_a_description_is_fenced_in_its_own_section_and_named_in_the_header(picture, tmp_path, monkeypatch):
    import drawbridge.describe as describe

    sent = []
    monkeypatch.setattr(describe, "openai_compatible_describer", lambda endpoint, model, prompt: lambda jpeg: sent.append((jpeg[:3], prompt)) or "## A chart\n- A blue rectangle on white.\n\nNo text is visible.")
    profile = _profile(tmp_path)
    result = convert_file(picture, profile=profile, plan=build_plan(profile, "image/png"))
    parts = dict(sections(result.mirror.body))
    assert parts["Description"].strip() == "A chart A blue rectangle on white.\n\nNo text is visible."
    assert "OCR" in parts and "blue rectangle" not in parts["OCR"]
    assert result.mirror.header["verify"] == ["description-model-written", "ocr-pending"]
    last = result.mirror.header["processing"][-1]
    assert (last["seq"], last["method"], last["endpoint"], last["egress"], last["words"]) == (2, "image_description:some/vlm", "eyes", "cloud", 11)
    assert sent[0][0] == b"\xff\xd8\xff" and "at most 12 words" in sent[0][1]          # a JPEG went out, with the word limit in the prompt
    convert_file(picture, profile=profile, plan=build_plan(profile, "image/png"))
    assert len(sent) == 1                                                               # the second conversion was served from the cache


def test_without_the_stage_an_image_mirror_is_what_it_always_was(picture):
    result = convert_file(picture)
    assert [heading for heading, _ in sections(result.mirror.body)] == ["OCR"]
    assert result.mirror.header["verify"] == ["ocr-pending"] and len(result.mirror.header["processing"]) == 1


def test_a_failed_description_costs_nothing_but_a_flag(picture, tmp_path):
    profile = _profile(tmp_path)
    plan = build_plan(profile, "image/png")

    def broken(jpeg):
        raise DescriptionError("no answer")

    assert describe_image(picture, "0" * 64, profile=profile, plan=plan, describe=broken) == (None, None, PENDING)
    assert describe_image(picture, "1" * 64, profile=profile, plan=plan, describe=lambda jpeg: "  \n ") == (None, None, PENDING)
    text, entry, flag = describe_image(picture, "2" * 64, profile=profile, plan=plan, describe=lambda jpeg: "A blue box.")
    assert (text, flag, entry["words"]) == ("A blue box.", WRITTEN, 3)
    silent = build_plan(profile, "image/png", no_ai=True)
    assert describe_image(picture, "3" * 64, profile=profile, plan=silent, describe=broken) == (None, None, None)


def test_tidy_caps_the_length_and_removes_structure_that_could_pass_for_the_mirrors():
    assert tidy("# Title\n> quoted\n* item", 50) == "Title quoted item"
    assert tidy("one two three four five", 3) == "one two three […]"


def test_cli_plans_the_stage_without_calling_it_and_local_only_refuses_it(picture, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("DB_TEST_EYES", "k")
    path = tmp_path / "p.yaml"
    path.write_text(json.dumps(PROFILE))
    assert cli.main(["convert", str(picture), "--profile", str(path), "--dry-run"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["sends_bytes_off_machine"] == ["image_description"] and not picture.with_name("chart.png.md").exists()
    assert cli.main(["convert", str(picture), "--profile", str(path), "--local-only"]) == cli.EXIT_USAGE
