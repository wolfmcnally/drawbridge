from __future__ import annotations

import json

import pytest

from drawbridge import cli
from drawbridge.mirror import page_sections, parse_mirror_header


def test_convert_native_writes_mirror(fixtures, tmp_path, capsys):
    out = tmp_path / "nested" / "rfc.md"
    code = cli.main(["convert", str(fixtures / "rfc8785.pdf"), "-o", str(out), "--json"])
    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["method"] == "pymupdf-text" and summary["page_count"] == 20 and summary["ocr_pages"] == []
    header, body = parse_mirror_header(out)
    assert len(page_sections(body)) == 20


def test_convert_default_output_and_prose(fixtures, tmp_path, capsys):
    source = tmp_path / "copy.pdf"
    source.write_bytes((fixtures / "rfc8785.pdf").read_bytes())
    assert cli.main(["convert", str(source)]) == 0
    assert (tmp_path / "copy.md").is_file()
    assert "20 pages, method pymupdf-text" in capsys.readouterr().out


def test_convert_stdout(fixtures, capsys):
    assert cli.main(["convert", str(fixtures / "rfc8785.pdf"), "--stdout", "--title", "JCS"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("---\n") and "\n# JCS\n" in out


def test_convert_blocked_exit_code(encrypted_pdf, capsys):
    assert cli.main(["convert", str(encrypted_pdf), "--json"]) == cli.EXIT_BLOCKED
    assert json.loads(capsys.readouterr().out)["reason"] == "password-protected"


def test_convert_failed_exit_code(fixtures, capsys):
    assert cli.main(["convert", str(fixtures / "invalid.pdf")]) == cli.EXIT_FAILED
    assert "failed:" in capsys.readouterr().err


def test_convert_no_ocr_refuses_scans(fixtures, capsys):
    assert cli.main(["convert", str(fixtures / "ccitt.pdf"), "--no-ocr", "--stdout"]) == cli.EXIT_OPERATIONAL
    assert "OCR is unavailable" in capsys.readouterr().err


def test_convert_usage_conflict(fixtures, tmp_path):
    code = cli.main([
        "convert", str(fixtures / "ccitt.pdf"), "--skip-preflight", "--searchable-pdf", str(tmp_path / "s.pdf"),
    ])
    assert code == cli.EXIT_USAGE


def test_inspect_reports_selection(fixtures, capsys):
    assert cli.main(["inspect", str(fixtures / "graph_ocred.pdf")]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["outcome"] == "processable" and data["ocr_pages"] == [1]
    assert data["inspection"]["has_text_layer"] is True and "page_texts" not in data["inspection"]


def test_inspect_exit_codes(fixtures, encrypted_pdf, capsys):
    assert cli.main(["inspect", str(fixtures / "invalid.pdf")]) == cli.EXIT_FAILED
    assert cli.main(["inspect", str(encrypted_pdf)]) == cli.EXIT_BLOCKED
    capsys.readouterr()


def test_verify_ok_and_mismatch(fixtures, tmp_path, capsys):
    out = tmp_path / "rfc.md"
    assert cli.main(["convert", str(fixtures / "rfc8785.pdf"), "-o", str(out)]) == 0
    assert cli.main(["verify", str(out), "--pdf", str(fixtures / "rfc8785.pdf")]) == 0
    assert cli.main(["verify", str(out), "--pdf", str(fixtures / "trivial.pdf")]) == cli.EXIT_VERIFY
    err = capsys.readouterr().err
    assert "content_hash differs" in err and "page sections" in err
    truncated = tmp_path / "short.md"
    text = out.read_text()
    truncated.write_text(text[: text.index("## Page 20")])
    assert cli.main(["verify", str(truncated), "--pdf", str(fixtures / "rfc8785.pdf")]) == cli.EXIT_VERIFY


def test_verify_rejects_non_mirror(tmp_path, fixtures, capsys):
    bogus = tmp_path / "x.md"
    bogus.write_text("just text")
    assert cli.main(["verify", str(bogus), "--pdf", str(fixtures / "trivial.pdf")]) == cli.EXIT_VERIFY


def test_version(capsys):
    with pytest.raises(SystemExit) as info:
        cli.main(["--version"])
    assert info.value.code == 0


def test_convert_a_non_pdf_keeps_the_whole_input_name(tmp_path, capsys):
    source = tmp_path / "note.eml"
    source.write_bytes(b"From: a@example.org\r\nTo: b@example.org\r\nSubject: hello\r\nDate: Thu, 01 Jan 2026 10:00:00 +0000\r\n\r\nBody text.\r\n")
    assert cli.main(["convert", str(source), "--json"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert (summary["media_type"], summary["unit"], summary["method"]) == ("message/rfc822", "message", "email-rfc822")
    assert summary["output"] == str(tmp_path / "note.eml.md")
    assert "page_count" not in summary
    header, body = parse_mirror_header(tmp_path / "note.eml.md")
    assert header["format"] == "drawbridge.mirror.v1" and "Body text." in body


AUDIO_PROFILE = """
endpoints:
  leveler: {kind: auphonic, api_key_env: DB_CLI_LEVELER, egress: cloud}
  scribe: {kind: elevenlabs, api_key_env: DB_CLI_SCRIBE, egress: cloud, cost_per_audio_hour_usd: 0.4}
stages:
  audio_cleanup: {provider: auphonic, endpoint: leveler}
  transcription: {provider: elevenlabs, endpoint: scribe}
"""


@pytest.fixture
def recording(tmp_path):
    import shutil
    import wave

    if shutil.which("ffprobe") is None:
        pytest.skip("ffprobe measures recordings")
    path = tmp_path / "call.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        import math
        import struct

        handle.writeframes(b"".join(struct.pack("<h", int(16000 * math.sin(2 * math.pi * 440 * i / 8000))) for i in range(8000 * 6)))  # a steady tone: even
    profile = tmp_path / "profile.yaml"
    profile.write_text(AUDIO_PROFILE)
    return path, profile


def test_dry_run_lists_cloud_stages_minutes_and_estimate_and_writes_nothing(recording, tmp_path, capsys, monkeypatch):
    path, profile = recording
    monkeypatch.setenv("DB_CLI_SCRIBE", "secret-value")
    monkeypatch.delenv("DB_CLI_LEVELER", raising=False)
    before = sorted(item.name for item in tmp_path.iterdir())
    assert cli.main(["convert", str(path), "--profile", str(profile), "--dry-run"]) == 0
    out = capsys.readouterr().out
    report = json.loads(out)
    assert report["sends_bytes_off_machine"] == ["transcription"]  # measured even, so the leveling hop will not happen
    assert (report["decision"]["will_level"], report["decision"]["will_transcribe_twice"]) == (False, False)
    assert report["decision"]["levels"]["spread_db"] < 1.0
    assert report["estimate"]["stages"] == [{"stage": "transcription", "endpoint": "scribe", "passes": 1, "usd": pytest.approx(0.0007, abs=0.0002)}]
    assert report["estimate"]["audio_minutes"] == pytest.approx(0.1, abs=0.01)
    assert "secret-value" not in out
    assert sorted(item.name for item in tmp_path.iterdir()) == before


def test_local_only_refuses_audio_and_shows_the_plan(recording, capsys):
    path, profile = recording
    assert cli.main(["convert", str(path), "--profile", str(profile), "--local-only", "--json"]) == cli.EXIT_USAGE
    refusal = json.loads(capsys.readouterr().out)
    assert refusal["outcome"] == "refused"
    assert refusal["plan"]["sends_bytes_off_machine"] == ["audio_cleanup", "transcription"]


def test_audio_without_a_profile_is_refused_and_documents_are_unaffected(recording, tmp_path, capsys, monkeypatch):
    path, _ = recording
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DRAWBRIDGE_PROFILE", raising=False)
    assert cli.main(["convert", str(path), "--no-profile"]) == cli.EXIT_OPERATIONAL
    note = tmp_path / "note.txt"
    note.write_text("plain\n")
    assert cli.main(["convert", str(note), "--no-profile"]) == 0


def test_a_bad_profile_is_a_usage_error_before_anything_runs(recording, tmp_path, capsys):
    path, _ = recording
    bad = tmp_path / "bad.yaml"
    bad.write_text("stages:\n  transcription: {provider: elevenlabs, endpoint: nowhere}\n")
    assert cli.main(["convert", str(path), "--profile", str(bad)]) == cli.EXIT_USAGE
    assert "endpoint nowhere is not declared" in capsys.readouterr().err
