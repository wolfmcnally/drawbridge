"""Exercise Converse policy and its helper protocol without provider calls."""

import base64
import io
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

import pytest
from PIL import Image

from drawbridge import bedrock, cli
from drawbridge.calls import call_converse
from drawbridge.configuration import load_configuration
from drawbridge.describe import PENDING, describe_image
from drawbridge.profile import EgressRefused, ProfileError, build_plan, parse_profile

MODEL = "amazon.nova-lite-v1:0"
HELPER = """
import base64
import json
import os
import sys
import time

request = json.load(sys.stdin)
assert set(request) == {"schema", "region", "model", "body"}
assert request["schema"] == "bedrock-converse-request/1"
assert request["region"] == "us-west-2"
assert request["model"] == "amazon.nova-lite-v1:0"
assert request["body"]["inferenceConfig"]["maxTokens"] == 25
mode = sys.argv[1]
response = {"schema": "bedrock-converse-response/1"}
if mode == "error":
    print(json.dumps(dict(response, status="error", category="throttled")))
    sys.exit()
if mode == "oversize":
    sys.stdout.write("x" * (16 * 1024 * 1024 + 1))
    sys.exit()
if mode == "timeout":
    time.sleep(60)
if mode == "invalid":
    print(json.dumps(dict(response, status="error", category="limit", detail="do not disclose")))
    sys.exit()
if mode == "invalid-success":
    print(json.dumps(dict(response, status="ok", body={
        "output": {
            "message": {"role": "assistant", "content": [{"text": "ignored"}], "extra": "bad"}
        },
        "stopReason": "end_turn",
    })))
    sys.exit()
if mode == "fds":
    listed, unlisted = map(int, sys.argv[2:])
    assert os.read(listed, 40) == b"descriptor payload"
    try:
        os.fstat(unlisted)
    except OSError:
        pass
    else:
        raise AssertionError("unlisted descriptor was inherited")
    assert os.environ.get("DRAWBRIDGE_TEST_ALLOWED") == "synthetic"
    assert "DRAWBRIDGE_TEST_DENIED" not in os.environ
if mode == "image":
    image = request["body"]["messages"][0]["content"][1]["image"]
    assert image["format"] == "jpeg"
    data = base64.b64decode(image["source"]["bytes"], validate=True)
    print(json.dumps(dict(response, status="ok", body={
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": base64.b64encode(data).decode()}],
            }
        },
        "stopReason": "end_turn",
    })))
    sys.exit()
body = {
    "output": {"message": {"role": "assistant", "content": [{"text": "synthetic reply"}]}},
    "stopReason": "end_turn", "usage": {"inputTokens": 10, "outputTokens": 4},
}
print(json.dumps(dict(response, status="ok", body=body)))
"""


def settings(mode="text", *args, fds=(), allow=True, time_limit=8, stage="image_description"):
    return {
        "allow_brokered": allow,
        "endpoints": {
            "model": {
                "kind": "bedrock-converse",
                "transport": "command",
                "region": "us-west-2",
                "command": {
                    "argv": [sys.executable, "-c", HELPER, mode, *map(str, args)],
                    "pass_env": ["DRAWBRIDGE_TEST_ALLOWED"],
                    "pass_fds": list(fds),
                },
                "limits": {
                    "max_output_tokens": 25,
                    "max_concurrency": 1,
                    "timeout_seconds": time_limit,
                    "max_image_side_px": 24,
                    "max_image_bytes": 1500,
                },
            }
        },
        "stages": {stage: {"endpoint": "model", "model": MODEL, "cache": False}},
    }


def endpoint(*args, **kwargs):
    return parse_profile(settings(*args, **kwargs)).endpoints["model"]


def test_only_configured_descriptor_and_environment_reach_helper(tmp_path, monkeypatch):
    fcntl = pytest.importorskip("fcntl")
    source = tmp_path / "descriptor"
    source.write_bytes(b"descriptor payload")
    monkeypatch.setenv("DRAWBRIDGE_TEST_ALLOWED", "synthetic")
    monkeypatch.setenv("DRAWBRIDGE_TEST_DENIED", "private synthetic value")
    with source.open("rb") as handle:
        listed = fcntl.fcntl(handle, fcntl.F_DUPFD_CLOEXEC, 120)
        unlisted = fcntl.fcntl(handle, fcntl.F_DUPFD_CLOEXEC, 120)
        try:
            # Make close_fds the control that keeps the unrelated descriptor out.
            os.set_inheritable(listed, True)
            os.set_inheritable(unlisted, True)
            selected = endpoint("fds", listed, unlisted, fds=[listed])
            assert (
                call_converse(selected, MODEL, "synthetic", stage="structure") == "synthetic reply"
            )
            assert os.get_inheritable(listed)
        finally:
            os.close(unlisted)
            os.close(listed)


def test_missing_descriptor_defers_without_spawning(tmp_path, monkeypatch):
    fcntl = pytest.importorskip("fcntl")
    source = tmp_path / "picture.png"
    Image.new("RGB", (2, 2)).save(source)
    with source.open("rb") as handle:
        missing = fcntl.fcntl(handle, fcntl.F_DUPFD_CLOEXEC, 120)
        os.close(missing)
    profile = parse_profile(settings(fds=[missing]))
    plan = build_plan(profile, "image/png")
    monkeypatch.setattr(bedrock.subprocess, "Popen", lambda *a, **k: pytest.fail("spawn"))
    monkeypatch.setattr(bedrock, "_cloud", lambda *a, **k: pytest.fail("cloud fallback"))
    assert describe_image(source, "synthetic", profile=profile, plan=plan) == (None, None, PENDING)


@pytest.mark.parametrize(
    ("mode", "category"),
    [
        ("error", "throttled"),
        ("invalid", "invalid"),
        ("invalid-success", "invalid"),
        ("oversize", "limit"),
        ("timeout", "unavailable"),
    ],
)
def test_command_failure_is_categorical_and_never_falls_back(mode, category, monkeypatch):
    monkeypatch.setattr(bedrock, "_cloud", lambda *a, **k: pytest.fail("cloud fallback"))
    selected = endpoint(mode, time_limit=2 if mode == "timeout" else 8)
    with pytest.raises(bedrock.BedrockError, match=f"^{category}$"):
        call_converse(selected, MODEL, "synthetic", stage="structure")


def test_command_concurrency_is_shared_between_stages(monkeypatch):
    selected = endpoint()
    ready = Barrier(3)
    guard = Lock()
    counts = {"active": 0, "peak": 0}

    def fake(_endpoint, _model, _prompt, **_kwargs):
        with guard:
            counts["active"] += 1
            counts["peak"] = max(counts["peak"], counts["active"])
        time.sleep(0.05)
        with guard:
            counts["active"] -= 1
        return "synthetic", 1, 1

    def task(stage):
        ready.wait(timeout=5)
        return call_converse(selected, MODEL, "synthetic", stage=stage)

    monkeypatch.setattr(bedrock, "converse", fake)
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert (
            list(pool.map(task, ("structure", "transcript_refinement", "image_description")))
            == ["synthetic"] * 3
        )
    assert counts == {"active": 0, "peak": 1}


def test_image_limits_bound_bytes_and_dimensions(tmp_path):
    source = tmp_path / "picture.png"
    pixels = random.Random(0).randbytes(200 * 150 * 3)
    Image.frombytes("RGB", (200, 150), pixels).save(source)
    # Isolate the settings so the side cap cannot make byte fitting vacuous.
    for max_side, max_bytes in ((24, 1500), (96, 1000)):
        raw = settings("image")
        raw["endpoints"]["model"]["limits"].update(
            max_image_side_px=max_side,
            max_image_bytes=max_bytes,
        )
        profile = parse_profile(raw)
        plan = build_plan(profile, "image/png")
        result, _, _ = describe_image(source, "synthetic", profile=profile, plan=plan)
        assert result, f"unable to package JPEG within {max_side}px and {max_bytes} bytes"
        data = base64.b64decode(result, validate=True)
        assert len(data) <= max_bytes
        with Image.open(io.BytesIO(data)) as image:
            assert max(image.size) <= max_side


@pytest.mark.parametrize("fds", [[0], [256], [True], ["3"], [3, 4, 5, 6, 7]])
def test_bad_descriptors_fail_configuration(fds):
    with pytest.raises(ProfileError, match="file descriptors"):
        parse_profile(settings(fds=fds))


@pytest.mark.parametrize(
    "model", ["us.amazon.nova-lite-v1:0", "arn:aws:bedrock:example", "amazon.*", " latest "]
)
def test_non_foundation_model_refused(model):
    data = settings()
    data["stages"]["image_description"]["model"] = model
    with pytest.raises(ProfileError, match="foundation"):
        parse_profile(data)


def test_brokered_policy_before_stage():
    with pytest.raises(EgressRefused, match="allow_brokered"):
        build_plan(parse_profile(settings(allow=False)), "image/png")
    with pytest.raises(EgressRefused, match="local-only"):
        build_plan(parse_profile(settings()), "image/png", local_only=True)


def test_unknown_transport_refused_before_document_read(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    data = {
        "endpoints": {
            "model": {"kind": "bedrock-converse", "region": "us-west-2", "transport": "automatic"},
        },
        "stages": {"image_description": {"endpoint": "model", "model": MODEL}},
    }
    config.write_text(json.dumps({"drawbridge": data}))
    monkeypatch.setattr(
        cli,
        "sniff_media_type",
        lambda path: pytest.fail("unknown Bedrock transport reached document read"),
    )
    assert cli.main(["convert", "unopened.png", "--config", str(config)]) == 2


def test_bearer_secret_ref_remains_unresolved_until_use(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text("""
drawbridge:
  endpoints:
    model:
      kind: bedrock-converse
      region: us-west-2
      transport: bearer
      api_key_env: !env DRAWBRIDGE_TEST_SECRET_REFERENCE
  stages:
    image_description:
      endpoint: model
      model: amazon.nova-lite-v1:0
""")
    monkeypatch.delenv("DRAWBRIDGE_TEST_SECRET_REFERENCE", raising=False)
    profile = load_configuration([config]).profile
    assert "DRAWBRIDGE_TEST_SECRET_REFERENCE" not in repr(profile.redacted())
    assert build_plan(profile, "image/png").missing_keys == ("image_description",)
    monkeypatch.setenv("DRAWBRIDGE_TEST_SECRET_REFERENCE", "")
    assert build_plan(profile, "image/png").missing_keys == ("image_description",)
    monkeypatch.setenv("DRAWBRIDGE_TEST_SECRET_REFERENCE", "synthetic-bearer")
    assert build_plan(profile, "image/png").missing_keys == ()
    assert profile.endpoints["model"].key() == "synthetic-bearer"


def test_audio_dry_run_includes_brokered_refinement(monkeypatch):
    from pathlib import Path

    from drawbridge import audio
    from drawbridge.documents import plan_report

    data = settings(stage="transcript_refinement")
    data["endpoints"]["transcriber"] = {"kind": "elevenlabs", "egress": "cloud"}
    data["stages"]["transcription"] = {"endpoint": "transcriber", "provider": "elevenlabs"}
    profile = parse_profile(data)
    plan = build_plan(profile, "audio/mpeg")
    monkeypatch.setattr(
        audio, "decide", lambda *a: audio.AudioDecision("off", "off", 10, None, False, False)
    )
    monkeypatch.setattr(audio, "audio_minutes", lambda _: 1)
    report = plan_report(Path("synthetic.mp3"), profile, plan, "audio/mpeg")
    assert report["sends_bytes_off_machine"] == ["transcription", "transcript_refinement"]
    assert report["brokered_stages"] == ["transcript_refinement"]


def _cloud_endpoint(transport):
    raw = {"kind": "bedrock-converse", "transport": transport, "region": "us-west-2"}
    if transport == "bearer":
        raw["api_key_env"] = "DRAWBRIDGE_FAKE_BEARER"
    return parse_profile({"endpoints": {"cloud": raw}}).endpoints["cloud"]


@pytest.mark.parametrize(
    "code, category",
    [
        (302, "unavailable"),
        (400, "invalid"),
        (401, "refused"),
        (403, "refused"),
        (429, "throttled"),
        (503, "unavailable"),
    ],
)
def test_bearer_http_errors_and_redirects_are_categorical(code, category, monkeypatch):
    import urllib.error
    import urllib.request

    monkeypatch.setenv("DRAWBRIDGE_FAKE_BEARER", "synthetic")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid")
    selected = _cloud_endpoint("bearer")

    class Opener:
        def open(self, request, *, timeout):
            assert (
                request.full_url
                == "https://bedrock-runtime.us-west-2.amazonaws.com/model/amazon.nova-lite-v1%3A0/converse"
            )
            assert request.get_header("Authorization") == "Bearer synthetic"
            assert timeout == selected.timeout_seconds
            raise urllib.error.HTTPError(
                request.full_url, code, "sensitive synthetic detail", {}, io.BytesIO()
            )

    def build(proxy, redirect):
        assert isinstance(proxy, urllib.request.ProxyHandler) and proxy.proxies == {}
        probe = urllib.request.Request("https://origin.invalid")
        assert redirect.redirect_request(probe, None, 302, "", {}, "https://other.invalid") is None
        return Opener()

    monkeypatch.setattr(urllib.request, "build_opener", build)
    with pytest.raises(bedrock.BedrockError, match=f"^{category}$"):
        call_converse(selected, MODEL, "synthetic", stage="image_description")


def test_bearer_reply_is_read_with_a_byte_limit(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setenv("DRAWBRIDGE_FAKE_BEARER", "synthetic")

    class OversizedReply(io.BytesIO):
        def read(self, size):
            assert size == bedrock.OUTPUT_LIMIT + 1
            return b"x" * size

    opener = SimpleNamespace(open=lambda *a, **k: OversizedReply())
    monkeypatch.setattr(bedrock.urllib.request, "build_opener", lambda *a: opener)
    with pytest.raises(bedrock.BedrockError, match="^limit$"):
        call_converse(_cloud_endpoint("bearer"), MODEL, "synthetic", stage="image_description")


@pytest.mark.parametrize("explicit", [True, False])
@pytest.mark.parametrize("has_credentials", [True, False])
def test_sigv4_selects_credential_chain_and_refuses_missing_keys(
    monkeypatch, explicit, has_credentials
):
    from pathlib import Path
    from types import ModuleType, SimpleNamespace

    from drawbridge.configuration import Configuration, configuration_context

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "synthetic-access-id")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "synthetic-secret")
    uses = []

    def credentials():
        if has_credentials:
            return SimpleNamespace(get_frozen_credentials=lambda: ("synthetic-access-id",))
        return None

    class EnvironmentProvider:
        def load(self):
            assert explicit
            uses.append("env")
            assert os.environ["AWS_ACCESS_KEY_ID"] == "synthetic-access-id"
            return credentials()

    class Signer:
        def __init__(self, credentials, service, region):
            assert credentials == ("synthetic-access-id",)
            assert (service, region) == ("bedrock", "us-west-2")

        def add_auth(self, request):
            assert request.method == "POST"
            request.headers["Authorization"] = "synthetic-signature"

    def session():
        assert not explicit
        uses.append("session")
        return SimpleNamespace(get_credentials=credentials)

    def module(name, **attributes):
        mock = ModuleType(name)
        vars(mock).update(attributes)
        monkeypatch.setitem(sys.modules, name, mock)

    module("botocore")
    module("botocore.session", get_session=session)
    module("botocore.auth", SigV4Auth=Signer)
    module("botocore.credentials", EnvProvider=EnvironmentProvider)
    module("botocore.awsrequest", AWSRequest=SimpleNamespace)
    module("botocore.exceptions", BotoCoreError=RuntimeError)

    class Opener:
        def open(self, request, *, timeout):
            assert request.get_header("Authorization") == "synthetic-signature"
            return io.BytesIO(
                json.dumps(
                    {
                        "output": {
                            "message": {
                                "role": "assistant",
                                "content": [{"text": "synthetic reply"}],
                            }
                        },
                        "stopReason": "end_turn",
                    }
                ).encode()
            )

    def build(*args):
        assert has_credentials
        return Opener()

    monkeypatch.setattr(bedrock.urllib.request, "build_opener", build)
    files = (Path("explicit.yaml"),) if explicit else ()
    with configuration_context(Configuration(files=files)):
        selected = _cloud_endpoint("sigv4")
        if has_credentials:
            assert (
                call_converse(selected, MODEL, "synthetic", stage="structure") == "synthetic reply"
            )
        else:
            with pytest.raises(bedrock.BedrockError, match="^refused$"):
                call_converse(selected, MODEL, "synthetic", stage="structure")
    assert uses == ["env" if explicit else "session"]


def test_decompression_bomb_is_a_categorical_limit(monkeypatch):
    def reject(*args, **kwargs):
        raise Image.DecompressionBombError("synthetic")

    monkeypatch.setattr(bedrock.Image, "open", reject)
    with pytest.raises(bedrock.BedrockError, match="^limit$"):
        call_converse(endpoint(), MODEL, "synthetic", stage="image_description", jpeg=b"small")


def test_bearer_success_and_missing_key(monkeypatch):
    from types import SimpleNamespace

    def open_reply(request, *, timeout):
        assert request.get_header("Authorization") == "Bearer synthetic"
        assert json.loads(request.data)["messages"][0]["content"] == [{"text": "local test"}]
        return io.BytesIO(
            b'{"output":{"message":{"role":"assistant","content":[{"text":"reply"}]}},"stopReason":"end_turn"}'
        )

    monkeypatch.setattr(
        bedrock.urllib.request, "build_opener", lambda *a: SimpleNamespace(open=open_reply)
    )
    selected = _cloud_endpoint("bearer")
    monkeypatch.delenv("DRAWBRIDGE_FAKE_BEARER", raising=False)
    with pytest.raises(bedrock.BedrockError, match="^refused$"):
        call_converse(selected, MODEL, "local test", stage="structure")
    monkeypatch.setenv("DRAWBRIDGE_FAKE_BEARER", "synthetic")
    assert call_converse(selected, MODEL, "local test", stage="structure") == "reply"
