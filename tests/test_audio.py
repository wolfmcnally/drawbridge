from __future__ import annotations

import json
import os
import shutil
import wave
from pathlib import Path

import pytest

transcribe = pytest.importorskip("transcribe")
from transcribe import package as package_module  # noqa: E402

from drawbridge.audio import (  # noqa: E402
    AudioLimitExceeded,
    RunBudget,
    audio_estimate,
    audio_minutes,
    convert_audio,
    rerender,
)
from drawbridge.convert import ConversionOptions  # noqa: E402
from drawbridge.errors import ConversionOperationalError  # noqa: E402
from drawbridge.mirror import parse_mirror_header, render_mirror, sections  # noqa: E402
from drawbridge.profile import ProfileError, build_plan, parse_profile  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe measures recordings")

PROFILE = {
    "endpoints": {
        "leveler": {"kind": "auphonic", "api_key_env": "DB_TEST_LEVELER", "egress": "cloud", "cost_per_audio_hour_usd": 1.2},
        "scribe": {"kind": "elevenlabs", "api_key_env": "DB_TEST_SCRIBE", "egress": "cloud", "cost_per_audio_hour_usd": 0.4},
    },
    "stages": {
        "audio_cleanup": {"provider": "auphonic", "endpoint": "leveler", "settings": {"levelerstrength_speech": 110}},
        "transcription": {"provider": "elevenlabs", "endpoint": "scribe", "model": "scribe_v2", "diarization": {"threshold": 0.22}},
    },
    "limits": {"max_audio_minutes": 1},
}
SETTINGS = {
    "production_id": "prod", "algorithms": {"leveler": True}, "mp3_bitrate": 128, "model_id": "scribe_v2", "language_code": None,
    "diarization_threshold": 0.22, "max_speakers": None, "audio_events": False, "clean_transcript": False, "speaker_library": False, "speaker_roles": False,
}


def word(text, start, end, speaker):
    return {"type": "word", "text": text, "start": start, "end": end, "speaker_id": speaker}


TRANSCRIPT = {
    "language_code": "eng", "language_probability": 0.99, "audio_duration_secs": 6.0, "transcription_id": "t-1",
    "words": [word("Good", 0.0, 0.4, "speaker_0"), {"type": "spacing", "text": " ", "speaker_id": "speaker_0"}, word("morning.", 0.5, 1.0, "speaker_0"),
              word("Morning.", 2.0, 2.5, "speaker_1"), word("Shall", 4.0, 4.3, "speaker_2"), {"type": "spacing", "text": " ", "speaker_id": "speaker_2"}, word("we?", 4.4, 4.8, "speaker_2")],
}


def make_wav(path: Path, seconds: float, uneven: bool = False) -> Path:
    """A steady tone, or a loud half followed by a half 28 dB quieter: loudness we control exactly."""
    import math
    import struct

    frames = bytearray()
    for index in range(int(8000 * seconds)):
        amplitude = 0.5 / 10 ** (28 / 20) if uneven and index >= 4000 * seconds else 0.5
        frames += struct.pack("<h", int(amplitude * 32767 * math.sin(2 * math.pi * 440 * index / 8000)))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(bytes(frames))
    return path


class PaidCall:
    """Stands in for the dependency's pipeline: records what it was asked, builds a real package, spends nothing."""

    def __init__(self):
        self.calls = []

    def __call__(self, source, *options, **credentials):
        self.calls.append({"options": list(options), "keys": (credentials.get("auphonic_api_key"), credentials.get("elevenlabs_api_key"))})
        from transcribe import levels, second_pass

        value = lambda flag: options[options.index(flag) + 1]  # noqa: E731
        directory = Path(value("--output-dir"))
        directory.mkdir(parents=True)
        copy = directory / Path(source).name
        shutil.copyfile(source, copy)
        measured = levels.measure(copy)
        uneven = measured.uneven(float(value("--uneven-threshold")))
        leveled = value("--leveling") == "on" or (value("--leveling") == "auto" and uneven)
        twice = value("--second-pass") == "on" or (value("--second-pass") == "auto" and uneven)
        adjusted = None
        if leveled:
            adjusted = directory / "adjusted.mp3"
            adjusted.write_bytes(b"adjusted")
        other = json.loads(json.dumps(TRANSCRIPT))
        other["words"][0]["text"] = "Fine"
        return package_module.write_package_files(
            version="test", generated_at="2026-01-01T00:00:00+00:00", source=copy, adjusted=adjusted, raw_json=directory / f"{Path(source).stem}-raw.json",
            transcript=TRANSCRIPT, settings={**SETTINGS, "production_id": "prod" if leveled else None},
            leveling={"mode": value("--leveling"), "applied": leveled, "uneven_threshold_db": float(value("--uneven-threshold")), "levels": measured.as_dict()},
            second_pass=second_pass.compare(TRANSCRIPT, other) if twice else None, second_transcript=other if twice else None)


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("DB_TEST_LEVELER", "leveler-secret")
    monkeypatch.setenv("DB_TEST_SCRIBE", "scribe-secret")
    monkeypatch.delenv("AUPHONIC_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)


def convert(tmp_path, seconds=6.0, profile_data=PROFILE, media_type="audio/x-wav", paid=None, uneven=False, **plan_options):
    profile = parse_profile(profile_data)
    source = make_wav(tmp_path / "call.wav", seconds, uneven)
    paid = paid or PaidCall()
    mirror, package = convert_audio(source, profile=profile, plan=build_plan(profile, media_type, **plan_options), options=ConversionOptions(title="Call"),
                                    media_type=media_type, artifacts_dir=tmp_path / "out", run=paid)
    return source, mirror, package, paid


def test_duration_is_measured_locally(tmp_path):
    assert audio_minutes(make_wav(tmp_path / "a.wav", 6.0)) == pytest.approx(0.1, abs=0.005)


def test_mirror_carries_speaker_table_and_one_section_per_turn(tmp_path, keys):
    source, mirror, package, paid = convert(tmp_path)
    header, body = parse_mirror_header(render_mirror(mirror))
    assert (header["unit"], header["speaker_count"], header["transcription_package"]) == ("turn", 3, "call.wav.transcribe")
    assert header["content_hash"] == f"sha256:{package.source_sha256}"
    assert [(step["method"], step["egress"]) for step in header["processing"]] == [("transcription:elevenlabs:scribe_v2", "cloud")]  # even audio: no leveling hop
    assert (header["leveling_applied"], header["second_pass_agreement"]) == (False, None)
    assert header["speech_level_spread_db"] < 1.0
    headings = [heading for heading, _ in sections(body)]
    assert headings == ["Speakers", "00:00:00.000 --> 00:00:01.000 · speaker_0", "00:00:02.000 --> 00:00:02.500 · speaker_1", "00:00:04.000 --> 00:00:04.800 · speaker_2"]
    assert "| speaker_0 |  | 1 | 2 |" in body
    assert paid.calls[0]["keys"] == (None, "scribe-secret")  # the leveling key is not even handed over when no leveling will happen
    assert "--auphonic-set" in paid.calls[0]["options"] and "levelerstrength_speech=110" in paid.calls[0]["options"]
    assert os.environ.get("AUPHONIC_API_KEY") is None  # the process environment remains unchanged
    assert "leveler-secret" not in render_mirror(mirror)


def test_one_name_on_two_identities_shows_in_table_and_turns_without_changing_words(tmp_path, keys):
    source, mirror, package, _ = convert(tmp_path)
    mirror_path = tmp_path / "call.wav.md"
    mirror_path.write_text(render_mirror(mirror))
    package.assign({"speaker_0": "Jane Smith", "speaker_2": "Jane Smith"})
    header, body = parse_mirror_header(rerender(mirror_path, package.directory))
    before = [text for _, text in sections(mirror.body)][1:]
    assert [text for _, text in sections(body)][1:] == before
    headings = [heading for heading, _ in sections(body)]
    assert headings[1].endswith("· Jane Smith (speaker_0)") and headings[3].endswith("· Jane Smith (speaker_2)") and headings[2].endswith("· speaker_1")
    assert body.count("| Jane Smith |") == 2
    assert header["content_hash"] == mirror.header["content_hash"] and "speakers_rendered_at" in header


def test_an_existing_package_for_the_same_bytes_is_reused_not_paid_for_again(tmp_path, keys):
    from drawbridge.calls import record_calls

    calls = []
    with record_calls(calls.append):
        source, _, _, paid = convert(tmp_path)
        profile = parse_profile(PROFILE)
        mirror, _ = convert_audio(source, profile=profile, plan=build_plan(profile, "audio/x-wav"), options=ConversionOptions(), media_type="audio/x-wav", artifacts_dir=tmp_path / "out", run=paid)
    assert len(paid.calls) == 1
    assert all(step["reused_package"] for step in mirror.header["processing"])
    # Each pass is reported with the recording's length and the declared rate; the kept package is reused, not charged.
    assert [(call.stage, call.endpoint, call.outcome) for call in calls] == [("transcription", "scribe", "succeeded"),
                                                                          ("transcription", "scribe", "reused")]
    assert calls[0].model == "scribe_v2" and calls[0].audio_seconds and calls[0].declared_usd_per_audio_hour == 0.4


def test_video_says_its_pictures_were_not_captured(tmp_path, keys):
    _, mirror, _, _ = convert(tmp_path, media_type="video/mp4")
    assert "video-visual-content-not-captured" in mirror.header["verify"]


def test_too_long_a_recording_is_refused_before_any_call(tmp_path, keys):
    paid = PaidCall()
    with pytest.raises(AudioLimitExceeded, match="allows 1"):
        convert(tmp_path, seconds=90.0, paid=paid)
    assert paid.calls == []


def test_run_budget_refuses_the_recording_that_would_exceed_it():
    budget = RunBudget(limit_minutes=1.0)
    budget.reserve(0.6)
    with pytest.raises(AudioLimitExceeded, match="run budget"):
        budget.reserve(0.6)
    assert budget.spent_minutes == pytest.approx(0.6)


def test_an_uneven_recording_is_leveled_under_auto_transcribed_twice_and_its_differences_shown(tmp_path, keys):
    _, mirror, package, paid = convert(tmp_path, uneven=True)
    header, body = parse_mirror_header(render_mirror(mirror))
    assert [step["method"] for step in header["processing"]] == ["audio_cleanup:auphonic", "transcription:elevenlabs:scribe_v2", "transcription-second-pass:elevenlabs:scribe_v2"]
    assert header["leveling_applied"] is True and header["speech_level_spread_db"] > 25
    assert header["verify"] == ["transcript-word-disagreements:1"]
    assert paid.calls[0]["keys"] == ("leveler-secret", "scribe-secret")
    turns = sections(body)
    assert [heading for heading, _ in turns] == ["Speakers", "00:00:00.000 --> 00:00:01.000 · speaker_0", "00:00:02.000 --> 00:00:02.500 · speaker_1", "00:00:04.000 --> 00:00:04.800 · speaker_2"]
    assert turns[1][1] == "{Good | Fine} morning."  # both readings, in the flow of the turn
    assert "Word disagreements: 1. Speaker disagreements: 0." in body


def test_transcription_alone_is_a_valid_profile_and_never_levels(tmp_path, keys, monkeypatch):
    monkeypatch.delenv("DB_TEST_LEVELER")
    alone = {**PROFILE, "stages": {"transcription": PROFILE["stages"]["transcription"]}}
    _, mirror, _, paid = convert(tmp_path, profile_data=alone, uneven=True)
    assert [step["method"] for step in mirror.header["processing"]] == ["transcription:elevenlabs:scribe_v2", "transcription-second-pass:elevenlabs:scribe_v2"]
    assert mirror.header["leveling_applied"] is False
    assert "--leveling" in paid.calls[0]["options"] and paid.calls[0]["options"][paid.calls[0]["options"].index("--leveling") + 1] == "off"


def test_modes_can_be_forced_and_the_threshold_moved(tmp_path, keys):
    forced = json.loads(json.dumps(PROFILE))
    forced["stages"]["audio_cleanup"]["mode"] = "on"
    forced["stages"]["transcription"].update(second_pass="off", uneven_threshold_db=40)
    _, mirror, _, _ = convert(tmp_path, profile_data=forced)
    assert [step["method"] for step in mirror.header["processing"]] == ["audio_cleanup:auphonic", "transcription:elevenlabs:scribe_v2"]
    with pytest.raises(ProfileError, match="mode must be one of"):
        parse_profile({**PROFILE, "stages": {**PROFILE["stages"], "audio_cleanup": {"provider": "auphonic", "endpoint": "leveler", "mode": "sometimes"}}})


def test_missing_key_and_missing_stage_are_refused_before_any_call(tmp_path, keys, monkeypatch):
    paid = PaidCall()
    with pytest.raises(ConversionOperationalError, match="need a profile with a transcription stage"):
        convert(tmp_path, paid=paid, no_ai=True)
    monkeypatch.delenv("DB_TEST_SCRIBE")
    with pytest.raises(ProfileError, match="no key is set for: transcription"):
        convert(tmp_path, paid=paid)
    assert paid.calls == []


def test_estimate_follows_the_decision_and_uses_only_declared_rates(tmp_path):
    from drawbridge.audio import decide

    profile = parse_profile(PROFILE)
    plan = build_plan(profile, "audio/x-wav")
    even = decide(make_wav(tmp_path / "even.wav", 6.0), profile, plan)
    uneven = decide(make_wav(tmp_path / "uneven.wav", 6.0, uneven=True), profile, plan)
    assert (even.will_level, even.will_transcribe_twice, even.cloud_stages) == (False, False, ("transcription",))
    assert (uneven.will_level, uneven.will_transcribe_twice, uneven.cloud_stages) == (True, True, ("audio_cleanup", "transcription"))
    assert audio_estimate(profile, even, minutes=30)["estimated_usd"] == pytest.approx(0.2)          # one pass at $0.40/h
    assert audio_estimate(profile, uneven, minutes=30)["estimated_usd"] == pytest.approx(0.6 + 0.4)   # leveling, and two passes
    undeclared = {**PROFILE, "endpoints": {**PROFILE["endpoints"], "scribe": {"kind": "elevenlabs", "api_key_env": "DB_TEST_SCRIBE", "egress": "cloud"}}}
    profile = parse_profile(undeclared)
    assert audio_estimate(profile, decide(tmp_path / "even.wav", profile, build_plan(profile, "audio/x-wav")), minutes=30)["estimated_usd"] is None


def test_a_disputed_speaker_is_a_turn_headed_with_both_and_one_name_settles_it(tmp_path, keys):
    def said(text, start, speaker):
        return [word(token, start + i, start + i + 0.5, speaker) for i, token in enumerate(text.split())]

    first = {**TRANSCRIPT, "words": said("Please state your full name", 0, "speaker_0") + said("Doctor Alex Morgan of Springfield", 10, "speaker_1") + said("Thank you", 20, "speaker_0")}
    other = json.loads(json.dumps(first))
    for entry in other["words"][-2:]:
        entry["speaker_id"] = "speaker_1"   # the second pass hears "Thank you" as the witness

    class DisputedSpeaker(PaidCall):
        def __call__(self, source, *options, **credentials):
            from transcribe import levels
            from transcribe import second_pass as compare

            directory = Path(options[options.index("--output-dir") + 1])
            directory.mkdir(parents=True)
            copy = directory / Path(source).name
            shutil.copyfile(source, copy)
            return package_module.write_package_files(
                version="test", generated_at="2026-01-01T00:00:00+00:00", source=copy, adjusted=None, raw_json=directory / "call-raw.json", transcript=first,
                settings={**SETTINGS, "production_id": None}, leveling={"mode": "off", "applied": False, "uneven_threshold_db": 25.0, "levels": levels.measure(copy).as_dict()},
                second_pass=compare.compare(first, other), second_transcript=other)

    _, mirror, package, _ = convert(tmp_path, uneven=True, paid=DisputedSpeaker())
    turns = sections(mirror.body)
    assert [heading.split(" · ")[1] for heading, _ in turns[1:]] == ["speaker_0", "speaker_1", "speaker_0 or speaker_1"]
    assert turns[-1][1] == "Thank you"
    assert mirror.header["verify"] == ["transcript-speaker-disagreements:1"]
    mirror_path = tmp_path / "call.wav.md"
    mirror_path.write_text(render_mirror(mirror))
    package.assign({"speaker_0": "Jane Smith", "speaker_1": "Jane Smith"})
    _, body = parse_mirror_header(rerender(mirror_path, package.directory))
    assert sections(body)[-1][0].endswith("· Jane Smith (speaker_0, speaker_1)")


def test_a_reused_package_is_not_charged_and_a_provider_failure_is_one_recording_failing(tmp_path, keys):
    from drawbridge.audio import RunBudget
    from drawbridge.errors import ConversionOperationalError

    source, _, _, paid = convert(tmp_path)
    profile = parse_profile(PROFILE)
    budget = RunBudget(limit_minutes=0.01)                       # too small for any paid run
    convert_audio(source, profile=profile, plan=build_plan(profile, "audio/x-wav"), options=ConversionOptions(), media_type="audio/x-wav",
                  artifacts_dir=tmp_path / "out", run=paid, budget=budget)
    assert budget.spent_minutes == 0.0 and len(paid.calls) == 1

    class ProviderDown(RuntimeError):
        pass

    def failing(*_args, **_kwargs):
        raise ProviderDown("upload rejected")

    other = make_wav(tmp_path / "second.wav", 6.0, False)
    with pytest.raises(ConversionOperationalError, match="transcription failed: upload rejected"):
        convert_audio(other, profile=profile, plan=build_plan(profile, "audio/x-wav"), options=ConversionOptions(), media_type="audio/x-wav",
                      artifacts_dir=tmp_path / "out", run=failing)
    (tmp_path / "out" / "call.wav.transcribe" / "call-speakers.json").write_text("{}")
    with pytest.raises(ConversionOperationalError, match="kept transcription package could not be read"):
        convert_audio(source, profile=profile, plan=build_plan(profile, "audio/x-wav"), options=ConversionOptions(), media_type="audio/x-wav",
                      artifacts_dir=tmp_path / "out", run=paid)


def test_transcription_reports_the_recording_when_it_starts_and_when_its_package_is_ready(tmp_path, keys):
    """Progress (phase 4): the dependency transcribes a recording as a whole, so the transcription step
    reports its seconds as none done when it starts and all done when the package is ready; a kept package
    reports nothing."""
    from drawbridge import report_progress
    heard = []
    with report_progress(lambda *progress: heard.append(progress)):
        convert(tmp_path, seconds=6.0)
    assert heard == [("transcription", 0, 6), ("transcription", 6, 6)]
    heard.clear()
    with report_progress(lambda *progress: heard.append(progress)):
        convert(tmp_path, seconds=6.0)  # the package kept beside it is reused
    assert heard == []


def test_credentials_are_per_call_even_while_the_provider_runs(tmp_path, keys, monkeypatch):
    monkeypatch.setenv("AUPHONIC_API_KEY", "ambient-cleanup")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "ambient-transcription")
    original = dict(os.environ)

    class Observe(PaidCall):
        def __call__(self, source, *options, **credentials):
            assert dict(os.environ) == original
            assert credentials == {"elevenlabs_api_key": "scribe-secret"}
            return super().__call__(source, *options, **credentials)

    convert(tmp_path, paid=Observe())
    assert dict(os.environ) == original
