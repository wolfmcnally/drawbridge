from __future__ import annotations

import pytest

from drawbridge.errors import ConversionOperationalError
from drawbridge.mirror import Mirror, build_header, page_body, parse_mirror_header, render_mirror
from drawbridge.profile import ProfileError, build_plan, parse_profile
from drawbridge.structure import apply_blocks, groom_section, run_structure, words

PAGE = "NOTICE OF HEARING\nThe hearing in this matter is set\nfor nine in the morning.\nBring:\nyour exhibits\nyour witnesses\nClerk of Court"
GOOD = {"blocks": [
    {"lines": [1, 1], "kind": "heading", "level": 1},
    {"lines": [2, 3], "kind": "paragraph"},
    {"lines": [4, 4], "kind": "paragraph"},
    {"lines": [5, 6], "kind": "list"},
    {"lines": [7, 7], "kind": "keep"},
]}
PROFILE = {
    "endpoints": {"router": {"kind": "openai-compatible", "base_url": "https://example.invalid/v1", "api_key_env": "DB_TEST_ROUTER", "egress": "cloud"}},
    "stages": {"structure": {"endpoint": "router", "model": "some/model"}},
}


def fidelity(fixtures, pages):
    header = build_header(fixtures / "trivial.pdf", method="ocr")
    return render_mirror(Mirror(header, page_body("Notice", pages)))


def test_annotations_add_syntax_and_join_wrapped_lines_only():
    groomed, reason = groom_section(PAGE, lambda lines: GOOD)
    assert reason is None
    assert groomed == "### NOTICE OF HEARING\n\nThe hearing in this matter is set for nine in the morning.\n\nBring:\n\n- your exhibits\n- your witnesses\n\nClerk of Court"
    assert words(groomed) == words(PAGE)


@pytest.mark.parametrize(
    "blocks",
    [
        [{"lines": [1, 3], "kind": "paragraph"}],                                            # stops early
        [{"lines": [2, 7], "kind": "paragraph"}],                                            # skips line 1
        [{"lines": [1, 4], "kind": "paragraph"}, {"lines": [4, 7], "kind": "paragraph"}],    # overlaps
        [{"lines": [1, 7], "kind": "poem"}],                                                 # unknown kind
        [{"lines": [1, 9], "kind": "paragraph"}],                                            # past the end
        "not a list",
    ],
)
def test_an_incomplete_or_malformed_cover_falls_back_to_the_fidelity_text(blocks):
    groomed, reason = groom_section(PAGE, lambda lines: {"blocks": blocks})
    assert groomed == PAGE and reason.startswith("unusable-annotations")


def test_a_model_cannot_reach_the_retained_lines():
    def tampering(lines):
        lines[1] = "The hearing in this matter is CANCELLED"
        return GOOD

    groomed, reason = groom_section(PAGE, tampering)
    assert reason is None and "CANCELLED" not in groomed and words(groomed) == words(PAGE)


def test_the_gate_falls_back_when_a_word_changes_however_it_happened(fixtures, monkeypatch):
    """The gate, proved: even if the apply step itself emitted a different word, the section keeps its fidelity text."""
    import drawbridge.structure as structure

    real = structure.apply_blocks
    monkeypatch.setattr(structure, "apply_blocks", lambda lines, blocks: real(lines, blocks).replace("is set", "is CANCELLED"))
    profile = parse_profile(PROFILE)
    mirror = run_structure(fidelity(fixtures, [PAGE, "Second page\nstays whole."]), profile=profile, plan=build_plan(profile, "application/pdf"),
                           annotate=lambda lines: GOOD if lines[0].startswith("NOTICE") else {"blocks": [{"lines": [1, 2], "kind": "paragraph"}]})
    header, body = parse_mirror_header(render_mirror(mirror))
    assert "CANCELLED" not in body
    assert "The hearing in this matter is set\nfor nine in the morning." in body   # page 1 kept its fidelity text
    assert "Second page stays whole." in body                                        # page 2 was groomed
    assert header["verify"] == ["structure-fallback:Page 1"]


def test_semantic_mirror_keeps_anchors_and_names_what_it_came_from(fixtures, tmp_path):
    import hashlib

    source = fidelity(fixtures, [PAGE])
    profile = parse_profile({**PROFILE, "limits": {"cache_dir": str(tmp_path / "cache")}})
    calls = []

    def annotate(lines):
        calls.append(len(lines))
        return GOOD

    plan = build_plan(profile, "application/pdf")
    first = run_structure(source, profile=profile, plan=plan, annotate=annotate)
    second = run_structure(source, profile=profile, plan=plan, annotate=annotate)
    header, body = parse_mirror_header(render_mirror(first))
    assert header["derived_from"] == "sha256:" + hashlib.sha256(source.encode()).hexdigest()
    assert header["content_hash"] == parse_mirror_header(source)[0]["content_hash"]
    assert header["processing"][-1]["method"] == "structure:annotate:some/model" and header["processing"][-1]["egress"] == "cloud"
    assert "## Page 1" in body and body.startswith("# Notice")
    assert calls == [7]                      # the second run was served from the cache
    assert render_mirror(second).split("performed_at")[0] == render_mirror(first).split("performed_at")[0]


def test_stage_is_silent_without_a_plan_and_refuses_what_it_does_not_implement(fixtures):
    source = fidelity(fixtures, [PAGE])
    profile = parse_profile(PROFILE)
    assert run_structure(source, profile=profile, plan=build_plan(profile, "application/pdf", no_ai=True), annotate=lambda lines: GOOD) is None
    rewriting = parse_profile({**PROFILE, "stages": {"structure": {"endpoint": "router", "model": "m", "mode": "rewrite"}}})
    with pytest.raises(ProfileError, match="annotate only"):
        run_structure(source, profile=rewriting, plan=build_plan(rewriting, "application/pdf"), annotate=lambda lines: GOOD)


def test_a_document_over_the_page_limit_sends_nothing(fixtures):
    profile = parse_profile({**PROFILE, "limits": {"max_pages_per_document": 1}})
    sent = []
    with pytest.raises(ConversionOperationalError, match="nothing was sent"):
        run_structure(fidelity(fixtures, ["a", "b"]), profile=profile, plan=build_plan(profile, "application/pdf"), annotate=lambda lines: sent.append(1) or GOOD)
    assert sent == []


def test_apply_blocks_requires_blocks():
    from drawbridge.structure import StructureResponseError

    with pytest.raises(StructureResponseError):
        apply_blocks(["x"], [])


def test_a_wrapped_list_item_becomes_one_bullet_and_items_stay_one_list():
    text = "Features:\nOperation is like a tape\nrecorder with PLAY and STOP.\nEach sequence holds\n32 tracks."
    blocks = {"blocks": [{"lines": [1, 1], "kind": "paragraph"}, {"lines": [2, 3], "kind": "list_item"}, {"lines": [4, 5], "kind": "list_item"}]}
    groomed, reason = groom_section(text, lambda lines: blocks)
    assert reason is None
    assert groomed == "Features:\n\n- Operation is like a tape recorder with PLAY and STOP.\n- Each sequence holds 32 tracks."


def test_a_fenced_or_chatty_answer_still_yields_its_json_object():
    from drawbridge.structure import json_object

    assert json_object('```json\n{"blocks": []}\n```') == {"blocks": []}
    assert json_object('Here you go: {"a": {"b": 1}} Hope that helps.') == {"a": {"b": 1}}
    for bad in ("no object here", "[1, 2]", "{broken"):
        with pytest.raises(ValueError):
            json_object(bad)


def test_structure_reports_each_section_and_a_failing_listener_changes_nothing(fixtures, tmp_path):
    """Progress (phase 4): a listener hears the structure step's sections done of the document's sections, one
    by one; a listener that raises is ignored and the mirror is the one produced without a listener."""
    from drawbridge import report_progress
    source = fidelity(fixtures, [PAGE, PAGE])
    profile = parse_profile({**PROFILE, "limits": {"cache_dir": str(tmp_path / "cache")}, "stages": {
        **PROFILE["stages"], "structure": {**PROFILE["stages"]["structure"], "cache": False}}})
    plan = build_plan(profile, "application/pdf")
    heard = []
    with report_progress(lambda *progress: heard.append(progress)):
        heard_mirror = run_structure(source, profile=profile, plan=plan, annotate=lambda lines: GOOD)
    assert heard == [("structure", 0, 2), ("structure", 1, 2), ("structure", 2, 2)]

    def failing(*_progress):
        raise RuntimeError("a listener that fails")
    with report_progress(failing):
        failed_mirror = run_structure(source, profile=profile, plan=plan, annotate=lambda lines: GOOD)
    plain = run_structure(source, profile=profile, plan=plan, annotate=lambda lines: GOOD)
    assert render_mirror(heard_mirror).split("performed_at")[0] == render_mirror(plain).split("performed_at")[0]
    assert render_mirror(failed_mirror).split("performed_at")[0] == render_mirror(plain).split("performed_at")[0]
