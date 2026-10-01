from __future__ import annotations

import io
import json
import threading
import urllib.error

import pytest

from drawbridge import calls as calls_module
from drawbridge.calls import ModelCall, record_calls
from drawbridge.profile import parse_profile
from drawbridge.refine import openai_compatible_reviewer

PROFILE = {
    "endpoints": {"router": {"kind": "openai-compatible", "base_url": "https://openrouter.ai/api/v1", "api_key_env": "DB_TEST_ROUTER", "egress": "cloud"}},
    "stages": {"transcript_refinement": {"endpoint": "router", "model": "some/model", "cache": False}},
}


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_a_model_call_reports_its_usage_and_the_charged_cost(monkeypatch):
    monkeypatch.setenv("DB_TEST_ROUTER", "secret")
    sent = []

    def urlopen(request, timeout):
        sent.append(json.loads(request.data))
        return Response(json.dumps({"choices": [{"message": {"content": "{\"paragraphs\": []}"}}],
                                    "usage": {"prompt_tokens": 120, "completion_tokens": 8, "cost": 0.00042}}).encode())

    monkeypatch.setattr(calls_module.urllib.request, "urlopen", urlopen)
    endpoint = parse_profile(PROFILE).endpoints["router"]
    recorded: list[ModelCall] = []
    with record_calls(recorded.append):
        assert openai_compatible_reviewer(endpoint, "some/model")("a window") == {"paragraphs": []}
    # OpenRouter reports the charged cost only when asked.
    assert sent[0]["usage"] == {"include": True} and sent[0]["model"] == "some/model"
    [call] = recorded
    assert (call.stage, call.endpoint, call.model, call.outcome) == ("transcript_refinement", "router", "some/model", "succeeded")
    assert (call.prompt_tokens, call.completion_tokens, call.reported_cost_usd) == (120, 8, "0.00042")


def test_a_failed_call_is_reported_as_failed_and_nothing_is_reported_without_a_recorder(monkeypatch):
    monkeypatch.setenv("DB_TEST_ROUTER", "secret")

    def refused(request, timeout):
        raise urllib.error.URLError("unreachable")

    monkeypatch.setattr(calls_module.urllib.request, "urlopen", refused)
    endpoint = parse_profile(PROFILE).endpoints["router"]
    recorded: list[ModelCall] = []
    from drawbridge.errors import ConversionOperationalError

    with record_calls(recorded.append), pytest.raises(ConversionOperationalError):
        openai_compatible_reviewer(endpoint, "some/model")("a window")
    assert [(call.outcome, call.failure) for call in recorded] == [("failed", "URLError")]
    with pytest.raises(ConversionOperationalError):
        openai_compatible_reviewer(endpoint, "some/model")("a window")
    assert len(recorded) == 1


def test_calls_made_on_the_conversions_own_threads_reach_the_recorder(monkeypatch):
    # Transcript windows are reviewed side by side; each window's call must still be reported.
    from drawbridge import refine
    from drawbridge.mirror import Mirror, build_header, render_mirror

    monkeypatch.setenv("DB_TEST_ROUTER", "secret")
    threads = set()

    def urlopen(request, timeout):
        threads.add(threading.get_ident())
        return Response(json.dumps({"choices": [{"message": {"content": "{\"paragraphs\": []}"}}],
                                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0.0001}}).encode())

    monkeypatch.setattr(calls_module.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(refine, "windows", lambda turns: [[turn] for turn in turns])
    from pathlib import Path

    body = "\n".join(["# Call", "", *(line for n in range(4) for line in
                     ("", f"## 00:00:0{n}.000 --> 00:00:0{n + 1}.000 · speaker_0", "", f"Turn number {n} of the call."))])
    fixture = Path(__file__).parent / "fixtures" / "trivial.pdf"
    fidelity = render_mirror(Mirror(build_header(fixture, method="transcribe", media_type="audio/mpeg", unit="turn"), body))
    profile = parse_profile(PROFILE)
    from drawbridge.profile import build_plan

    recorded: list[ModelCall] = []
    with record_calls(recorded.append):
        refine.run_refinement(fidelity, profile=profile, plan=build_plan(profile, "audio/mpeg"))
    assert len(recorded) == 4 and all(call.reported_cost_usd == "0.0001" for call in recorded)
