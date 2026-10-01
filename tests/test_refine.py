from __future__ import annotations

import pytest

from drawbridge.mirror import Mirror, build_header, parse_mirror_header, render_mirror, sections
from drawbridge.profile import ProfileError, build_plan, parse_profile
from drawbridge.refine import Turn, paragraphs, proposals, run_refinement, shown, windows

PROFILE = {
    "endpoints": {"router": {"kind": "openai-compatible", "base_url": "https://example.invalid/v1", "api_key_env": "DB_TEST_ROUTER", "egress": "cloud"}},
    "stages": {"transcript_refinement": {"endpoint": "router", "model": "some/model", "cache": False}},
}
LONG = ("The first item tonight is the road budget. We spent less than planned on gravel. The {culvert | covert} work came in over. "
        "Turning to the library, the roof was repaired in spring. Attendance is up by a tenth. The reading room reopens in the fall. "
        "Last, the harvest fair. Volunteers are still needed for the gate. Anyone willing should see the clerk after we adjourn tonight. "
        "That concludes the report from the committee for this quarter and I will take questions now if there are any from the floor.")
BODY = "\n".join([
    "# Meeting", "", "## Speakers", "", "| Speaker | Name |", "| --- | --- |", "| speaker_0 | Pat Example |", "| speaker_1 | |", "| speaker_2 | |",
    "", "## 00:00:01.000 --> 00:00:04.000 · Pat Example (speaker_0)", "", "Call to order. Is the treasurer",
    "", "## 00:00:04.000 --> 00:00:05.000 · speaker_2", "", "here tonight?",
    "", "## 00:00:05.000 --> 00:01:30.000 · speaker_1", "", LONG,
    "", "## 00:01:30.000 --> 00:01:34.000 · speaker_0 or speaker_2", "", "Thank you. Any questions on the colvert?",
])


@pytest.fixture
def fidelity(fixtures):
    header = build_header(fixtures / "trivial.pdf", method="transcribe", media_type="audio/mpeg", unit="turn")
    return render_mirror(Mirror(header, BODY))


def _run(fidelity, answer, **stage):
    raw = {**PROFILE, "stages": {"transcript_refinement": {**PROFILE["stages"]["transcript_refinement"], **stage}}}
    profile = parse_profile(raw)
    seen = []
    mirror = run_refinement(fidelity, profile=profile, plan=build_plan(profile, "audio/mpeg"), review=lambda window: seen.append(window) or answer)
    return mirror, seen


def test_the_model_sees_identities_never_names_and_long_turns_by_sentence(fidelity):
    _, seen = _run(fidelity, {})
    assert "Pat Example" not in seen[0]
    assert "T1 [00:00:01] speaker_0: Call to order." in seen[0]
    assert "speaker_0 or speaker_2: Thank you." in seen[0]
    assert "(3) The {culvert | covert} work came in over. (4) Turning" in seen[0]


def test_paragraph_breaks_are_applied_and_every_word_and_disagreement_survives(fidelity):
    mirror, _ = _run(fidelity, {"paragraphs": [{"turn": 3, "starts": [4, 7, 99, "x"]}]})
    header, body = parse_mirror_header(render_mirror(mirror))
    turn = dict(sections(body))["00:00:05.000 --> 00:01:30.000 · speaker_1"].strip()
    assert turn.split("\n\n")[1].startswith("Turning to the library") and turn.count("\n\n") == 2
    assert turn.replace("\n\n", " ") == LONG and "{culvert | covert}" in turn
    assert [heading for heading, _ in sections(body)] == [heading for heading, _ in sections(parse_mirror_header(fidelity)[1])]
    assert header["refinement"] == {"paragraphed_turns": 1, "proposals": 0, "proposals_refused": 0}
    assert header["processing"][-1]["method"] == "transcript_refinement:annotate:some/model" and header["derived_from"].startswith("sha256:")


def test_proposals_are_listed_with_a_time_to_listen_at_and_nothing_is_applied(fidelity):
    answer = {"same_speaker": [{"a": "speaker_2", "b": "speaker_0", "turns": [1, 2]}],
              "boundary": [{"turn": 2, "edge": "start", "words": 1}],
              "spelling": [{"turn": 4, "heard": "colvert", "suggest": "culvert"}]}
    mirror, _ = _run(fidelity, answer)
    header, body = parse_mirror_header(render_mirror(mirror))
    table = dict(sections(body))["Proposals"]
    assert "| same-speaker | 00:00:01, 00:00:04 | `speaker_0` and `speaker_2` may be one voice |" in table
    assert "| boundary | 00:00:04 | the first 1 words of this turn (“here”) may belong to the previous speaker, `speaker_0` |" in table
    assert "| spelling | 00:01:30 | “colvert” may be “culvert” |" in table
    assert "Any questions on the colvert?" in body and "transcript-proposals:3" in header["verify"]
    assert body.index("## Proposals") < body.index("## 00:00:01.000")


def test_a_proposal_has_nowhere_to_put_a_name_or_an_argument():
    turns = {1: Turn(1, "00:00:01.000", ("speaker_0",), "Good evening to the borde"), 2: Turn(2, "00:00:03.000", ("speaker_1",), "Thank you all")}
    smuggled = {"same_speaker": [{"a": "speaker_0", "b": "Pat Example", "turns": [1]}, {"a": "speaker_0", "b": "speaker_1", "turns": [9]},
                                 {"a": "speaker_0", "b": "speaker_1", "turns": [1], "reason": "this is Pat Example"}],
                "boundary": [{"turn": 2, "edge": "end", "words": 1}, {"turn": 1, "edge": "start", "words": 2}, {"turn": 1, "edge": "end", "words": 40}],
                "spelling": [{"turn": 1, "heard": "borde", "suggest": "Pat Example said this"}, {"turn": 1, "heard": "absent", "suggest": "absent"},
                             {"turn": 1, "heard": "borde", "suggest": "board"}]}
    rows, refused = proposals(smuggled, turns, speaker_resolution=True)
    assert rows == [("same-speaker", "00:00:01", "`speaker_0` and `speaker_1` may be one voice"), ("spelling", "00:00:01", "“borde” may be “board”")]
    assert refused == 7
    assert proposals(smuggled, turns, speaker_resolution=False)[0] == [("spelling", "00:00:01", "“borde” may be “board”")]


def test_a_disagreement_is_one_unit_that_can_end_no_sentence():
    turn = Turn(1, "00:00:00.000", ("speaker_0",), "We met {on Monday. | —} It rained. " + "More words follow here. " * 20)
    assert turn.sentences[0] == "We met {on Monday. | —} It rained."
    assert "{on Monday. | —}" in paragraphs(turn, [2]) and "(1) We met {on Monday. | —} It rained. (2)" in shown(turn)


def test_the_gate_keeps_the_fidelity_turn_if_paragraphing_ever_changed_a_word(fidelity, monkeypatch):
    import drawbridge.refine as refine

    real = refine.paragraphs
    monkeypatch.setattr(refine, "paragraphs", lambda turn, starts: real(turn, starts).replace("{culvert | covert}", "culvert"))
    mirror, _ = _run(fidelity, {"paragraphs": [{"turn": 3, "starts": [4]}]})
    header, body = parse_mirror_header(render_mirror(mirror))
    assert LONG in body and header["verify"] == ["refinement-fallback:00:00:05.000"]


def test_long_recordings_go_in_windows_and_an_unanswered_window_is_flagged(fidelity):
    turns = [Turn(n, "00:00:00.000", ("speaker_0",), "word " * 50) for n in range(1, 9)]
    assert [len(window) for window in windows(turns, limit=700)] == [2, 2, 2, 2]
    from drawbridge.errors import ConversionOperationalError

    profile = parse_profile(PROFILE)

    def silent(window):
        raise ConversionOperationalError("no answer")

    mirror = run_refinement(fidelity, profile=profile, plan=build_plan(profile, "audio/mpeg"), review=silent)
    assert mirror.header["verify"] == ["refinement-incomplete"] and LONG in mirror.body


def test_the_stage_is_silent_without_a_plan_and_refuses_to_assert_identities(fidelity):
    profile = parse_profile(PROFILE)
    assert run_refinement(fidelity, profile=profile, plan=build_plan(profile, "audio/mpeg", no_ai=True), review=lambda w: {}) is None
    assert run_refinement(fidelity, profile=profile, plan=build_plan(profile, "application/pdf"), review=lambda w: {}) is None
    for bad in ({"speaker_resolution": "assert"}, {"mode": "rewrite"}):
        with pytest.raises(ProfileError):
            _run(fidelity, {}, **bad)


def test_windows_are_reviewed_side_by_side_and_applied_in_order(fidelity, monkeypatch):
    # Every window's review must be in flight at once to pass the barrier, which one window at a
    # time never does (one long recording's windows once queued for most of ten minutes); the
    # mirror is the one the sequential reviews produce.
    import threading

    from drawbridge import refine

    monkeypatch.setattr(refine, "windows", lambda turns: [[turn] for turn in turns])
    profile = parse_profile(PROFILE)
    plan = build_plan(profile, "audio/mpeg")
    monkeypatch.setattr(refine, "REVIEW_WORKERS", 1, raising=False)
    sequential = run_refinement(fidelity, profile=profile, plan=plan, review=lambda window: {"paragraphs": []})
    together = threading.Barrier(4, timeout=10)

    def review(window):
        together.wait()
        return {"paragraphs": []}

    monkeypatch.setattr(refine, "REVIEW_WORKERS", 8, raising=False)
    parallel = run_refinement(fidelity, profile=profile, plan=plan, review=review)
    assert parallel.body == sequential.body and parallel.header["verify"] == sequential.header["verify"]


def test_refinement_reports_each_reviewed_window(fidelity):
    """Progress (phase 4): a listener hears the refinement step's windows done of all windows, in window
    order, while the reviews run side by side."""
    from drawbridge import report_progress
    heard = []
    with report_progress(lambda *progress: heard.append(progress)):
        _mirror, seen = _run(fidelity, {"paragraphs": []})
    total = len(seen)
    assert total >= 1
    assert heard == [("refinement", done, total) for done in range(total + 1)]
