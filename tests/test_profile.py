from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from drawbridge.profile import (
    EMPTY_PROFILE,
    EgressRefused,
    ProfileError,
    build_plan,
    load_dotenv,
    locate_profile,
    parse_profile,
    resolve_profile,
)

GOOD = {
    "endpoints": {
        "router": {"kind": "openai-compatible", "base_url": "https://example.invalid/v1", "api_key_env": "DB_TEST_ROUTER_KEY", "egress": "cloud"},
        "scribe": {"kind": "elevenlabs", "api_key_env": "DB_TEST_SCRIBE_KEY", "egress": "cloud"},
        "leveler": {"kind": "auphonic", "api_key_env": "DB_TEST_LEVELER_KEY", "egress": "cloud"},
        "laptop": {"kind": "ollama", "base_url": "http://127.0.0.1:11434", "egress": "local"},
    },
    "stages": {
        "transcription": {"provider": "elevenlabs", "endpoint": "scribe"},
        "structure": {"endpoint": "router", "model": "some/model"},
        "audio_cleanup": {"provider": "auphonic", "endpoint": "leveler"},
        "image_description": {"endpoint": "laptop", "model": "vlm"},
    },
    "limits": {"max_audio_minutes": 90},
}


def variant(**changes):
    import copy

    data = copy.deepcopy(GOOD)
    for dotted, value in changes.items():
        node = data
        *parents, leaf = dotted.split("__")
        for key in parents:
            node = node[key]
        if value is None:
            node.pop(leaf)
        else:
            node[leaf] = value
    return data


def test_no_profile_plans_nothing():
    plan = build_plan(EMPTY_PROFILE, "audio/mpeg")
    assert plan.stages == () and plan.cloud_stages == ()


def test_stages_come_out_in_pipeline_order_and_limits_resolve():
    profile = parse_profile(GOOD)
    assert list(profile.stages) == ["structure", "image_description", "audio_cleanup", "transcription"]
    assert profile.limits.max_audio_minutes == 90 and profile.limits.max_pages_per_document == 500


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (variant(surprise={}), "unknown key surprise"),
        (variant(endpoints__router__egress=None), "egress must be declared"),
        (variant(endpoints__router__kind="carrier-pigeon"), "kind must be one of"),
        (variant(endpoints__router__api_key="sk-live-123"), "unknown key api_key"),
        (variant(stages__structure__endpoint="nowhere"), "endpoint nowhere is not declared"),
        (variant(stages__transcription__endpoint=None), "needs an endpoint"),
        (variant(stages__transcription__applies_to=["image"]), "cannot act on image"),
        (variant(stages__structure__colour="red"), "unknown key colour"),
        (variant(stages__summarise={}), "unknown stage summarise"),
        (variant(limits__max_cats=3), "unknown key max_cats"),
    ],
)
def test_validation_is_fail_closed(data, message):
    with pytest.raises(ProfileError, match=message):
        parse_profile(data)


def test_plan_applies_stages_by_media_type_and_reports_egress(monkeypatch):
    monkeypatch.setenv("DB_TEST_SCRIBE_KEY", "present")
    monkeypatch.delenv("DB_TEST_LEVELER_KEY", raising=False)
    plan = build_plan(parse_profile(GOOD), "audio/mpeg")
    assert [(item.stage, item.runs) for item in plan.stages] == [("structure", False), ("image_description", False), ("audio_cleanup", True), ("transcription", True)]
    assert plan.cloud_stages == ("audio_cleanup", "transcription")
    assert plan.missing_keys == ("audio_cleanup",)
    assert build_plan(parse_profile(GOOD), "application/pdf").cloud_stages == ("structure",)
    assert build_plan(parse_profile(GOOD), "image/png").cloud_stages == ()


def test_switches_narrow_the_plan():
    profile = parse_profile(GOOD)
    assert build_plan(profile, "audio/mpeg", skip=["audio_cleanup"]).cloud_stages == ("transcription",)
    assert build_plan(profile, "audio/mpeg", only=["audio_cleanup"]).cloud_stages == ("audio_cleanup",)
    assert build_plan(profile, "audio/mpeg", no_ai=True).cloud_stages == ()
    with pytest.raises(ProfileError, match="unknown stage"):
        build_plan(profile, "audio/mpeg", skip=["nonsense"])


def test_local_only_refuses_cloud_and_shows_what_it_would_have_run():
    profile = parse_profile(GOOD)
    with pytest.raises(EgressRefused) as refused:
        build_plan(profile, "audio/mpeg", local_only=True)
    assert refused.value.plan.cloud_stages == ("audio_cleanup", "transcription")
    assert build_plan(profile, "image/png", local_only=True).runs("image_description")


def test_redacted_view_never_holds_a_key_value(monkeypatch):
    monkeypatch.setenv("DB_TEST_ROUTER_KEY", "sk-very-secret-value")
    shown = yaml.safe_dump(parse_profile(GOOD).redacted())
    assert "sk-very-secret-value" not in shown
    assert "api_key_set: true" in shown and "DB_TEST_ROUTER_KEY" in shown


def test_dotenv_never_overrides_the_environment(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text('export DB_TEST_A="from-file"\nDB_TEST_B=from-file\n# comment\n')
    monkeypatch.setenv("DB_TEST_A", "already-set")
    monkeypatch.delenv("DB_TEST_B", raising=False)
    assert load_dotenv([tmp_path]) == ["DB_TEST_B"]
    assert (os.environ["DB_TEST_A"], os.environ["DB_TEST_B"]) == ("already-set", "from-file")
    monkeypatch.delenv("DB_TEST_B")


def test_resolution_order_first_match_wins(tmp_path, monkeypatch):
    explicit, named, local = tmp_path / "explicit.yaml", tmp_path / "named.yaml", tmp_path / "drawbridge.yaml"
    for path in (explicit, named, local):
        path.write_text("stages: {}\n")
    environ = {"DRAWBRIDGE_PROFILE": str(named), "XDG_CONFIG_HOME": str(tmp_path / "config")}
    assert locate_profile(explicit, cwd=tmp_path, environ=environ) == explicit
    assert locate_profile(None, cwd=tmp_path, environ=environ) == named
    assert locate_profile(None, cwd=tmp_path, environ={"XDG_CONFIG_HOME": str(tmp_path / "config")}) == local
    local.unlink()
    assert locate_profile(None, cwd=tmp_path, environ={"XDG_CONFIG_HOME": str(tmp_path / "config")}) is None
    with pytest.raises(ProfileError, match="not found"):
        locate_profile(tmp_path / "absent.yaml")
    assert resolve_profile(explicit, no_profile=True) is EMPTY_PROFILE


def test_profile_errors_belong_to_the_package_error_family_and_the_run_budget_is_safe_to_share():
    import threading

    import drawbridge

    assert issubclass(drawbridge.ProfileError, drawbridge.DrawbridgeError) and issubclass(drawbridge.EgressRefused, drawbridge.ProfileError)
    budget = drawbridge.RunBudget(limit_minutes=100.0)
    refused = []

    def spend():
        for _ in range(50):
            try:
                budget.reserve(1.0)
            except drawbridge.AudioLimitExceeded:
                refused.append(1)

    threads = [threading.Thread(target=spend) for _ in range(8)]
    [thread.start() for thread in threads]
    [thread.join() for thread in threads]
    assert budget.spent_minutes == 100.0 and len(refused) == 300
