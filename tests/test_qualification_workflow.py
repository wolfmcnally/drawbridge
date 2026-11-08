"""Exercise the actual CI shell boundary without contacting external services."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/qualification.yml"
SOURCE = "442afd5fcbc726a3683b209102eb0f42125b5aff"
TAG = "55693cadf79bdeb0cbb84cabf5c99702f4ec1dd0"
CONTROLLER = "a" * 40
BLOB = "c" * 40
PAYLOAD = b"independent asset fixture\n"


def step_script(name):
    workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    return next(
        step["run"] for step in workflow["jobs"]["linux"]["steps"] if step.get("name") == name
    )


def executable(directory, name, body):
    target = directory / name
    target.write_text(f"#!{sys.executable}\n" + body)
    target.chmod(0o700)


def invoke(tmp_path, script, extra_env):
    env = {**os.environ, **extra_env, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    return subprocess.run(
        ["/bin/bash", "-c", script], env=env, text=True, capture_output=True, timeout=8
    )


def asset_probe(tmp_path, responses):
    assert shutil.which("sha256sum"), "Real sha256sum is required"
    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps(responses))
    executable(
        tmp_path,
        "curl",
        """import json, os, pathlib, sys
args = sys.argv[1:]
if args == ["--version"]:
    print("fixture curl, no network")
    sys.exit(0)
expected = {
    "--retry": "0", "--proto": "=https", "--proto-redir": "=https",
    "--connect-timeout": "10", "--max-filesize": str(len(b"independent asset fixture\\n")),
}
flags = {"--fail", "--silent", "--show-error", "--location"}
values = {}
while len(args) > 1:
    flag = args.pop(0)
    if flag in flags:
        continue
    assert flag in {*expected, "--max-time", "--output", "--write-out"}, flag
    values[flag] = args.pop(0)
assert args == ["https://fixture.invalid/asset"]
assert all(values[k] == v for k, v in expected.items())
assert 0 < int(values["--max-time"]) <= 45
assert values["--write-out"] == r"%{http_code}\\n%{remote_ip}\\n%{num_redirects}\\n%{url_effective}"
output = pathlib.Path(values["--output"])
assert output.name.startswith("asset.attempt-") and output.exists()
log = pathlib.Path(os.environ["PROBE_LOG"])
prior = log.read_text().splitlines() if log.exists() else []
with log.open("a") as stream:
    stream.write(json.dumps(values) + "\\n")
responses = json.loads(pathlib.Path(os.environ["SCENARIO"]).read_text())
assert len(prior) < len(responses), "Unexpected extra curl invocation"
response = responses[len(prior)]
payload = b"independent asset fixture\\n"
if response.get("payload") == "short":
    payload = payload[:-1]
output.write_bytes(payload if response.get("payload") in {"good", "short"} else b"X" * len(payload))
if not response.get("no_telemetry"):
    print(str(response["http"]) + "\\n192.0.2.1\\n1\\nhttps://download.invalid/asset?DO_NOT_LOG_QUERY")
sys.exit(response["exit"])
""",
    )
    executable(
        tmp_path,
        "sleep",
        """import os, pathlib, sys
assert sys.argv[1:] in (["20"], ["40"])
with pathlib.Path(os.environ["SLEEP_LOG"]).open("a") as stream:
    stream.write(sys.argv[1] + "\\n")
""",
    )
    target = tmp_path / "asset"
    script = step_script("Fetch the exact Vellric 0.2.4 release").split("\nfetch_exact_asset ", 1)[
        0
    ]
    script += (
        "\nfetch_exact_asset https://fixture.invalid/asset "
        '"$ASSET_TARGET" "$ASSET_SHA" "$ASSET_BYTES"\n'
    )
    log = tmp_path / "curl.jsonl"
    result = invoke(
        tmp_path,
        script,
        {
            "SCENARIO": str(scenario),
            "PROBE_LOG": str(log),
            "SLEEP_LOG": str(tmp_path / "sleep.log"),
            "ASSET_TARGET": str(target),
            "ASSET_SHA": hashlib.sha256(PAYLOAD).hexdigest(),
            "ASSET_BYTES": str(len(PAYLOAD)),
        },
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    assert "DO_NOT_LOG_QUERY" not in result.stdout + result.stderr
    return result, calls, target


@pytest.mark.parametrize("first", [{"exit": 22, "http": 504}, {"exit": 56, "http": 200}])
def test_transient_asset_recovers(tmp_path, first):
    result, calls, target = asset_probe(
        tmp_path, [first, {"exit": 0, "http": 200, "payload": "good"}]
    )
    assert result.returncode == 0, "Valid scenario must pass: " + result.stdout + result.stderr
    assert target.read_bytes() == PAYLOAD
    assert len(calls) == 2, "Transient response must retry exactly once before success"
    assert (tmp_path / "sleep.log").read_text() == "20\n"
    assert "host=download.invalid" in result.stdout


@pytest.mark.parametrize(
    "responses,reason,count",
    [
        ([{"exit": 22, "http": 403}], "fatal-or-unclassified", 1),
        ([{"exit": 2, "http": 0, "no_telemetry": True}], "fatal-or-unclassified", 1),
        ([{"exit": 0, "http": 200, "payload": "bad"}], "digest-mismatch", 1),
        ([{"exit": 56, "http": 0}] * 3, "attempts-exhausted", 3),
        ([{"exit": 0, "http": 200, "payload": "short"}], "size-mismatch", 1),
    ],
)
def test_asset_failures_are_bounded(tmp_path, responses, reason, count):
    result, calls, target = asset_probe(tmp_path, responses)
    assert result.returncode != 0, "Invalid asset must fail closed"
    assert len(calls) == count, "Failure classification must bound curl invocations"
    assert f"ASSET REFUSED {reason}" in result.stderr, result.stdout + result.stderr
    assert not target.exists(), "Unverified asset must never be promoted"
    if count == 3:
        assert (tmp_path / "sleep.log").read_text() == "20\n40\n", (
            "Exhaustion uses bounded20/40 backoff"
        )


@pytest.mark.parametrize(
    "case,reason",
    [
        ("ordinary", None),
        ("release", None),
        ("stray", "ORDINARY_RELEASE_INPUTS"),
        ("controller", "CONTROLLER"),
        ("workflow-sha", "CONTROLLER"),
        ("workflow-ref", "WORKFLOW_REF"),
        ("event", "RELEASE_EVENT"),
        ("blob", "WORKFLOW_BLOB"),
        ("source", "RELEASE_SOURCE"),
        ("tag", "TAG_OBJECT"),
        ("peel", "TAG_SOURCE"),
        ("nonce", "INPUT_FORMAT"),
    ],
)
def test_exact_source_dispatch_identity(tmp_path, case, reason):
    executable(
        tmp_path,
        "git",
        """import json, os, pathlib, sys
args = sys.argv[1:]
with pathlib.Path(os.environ["GIT_LOG"]).open("a") as stream:
    stream.write(json.dumps(args) + "\\n")
keys = ("PROBE_CONTROLLER", "PROBE_BLOB", "PROBE_SOURCE", "PROBE_TAG", "PROBE_PEEL")
controller, blob, source, tag, peel = [os.environ[k] for k in keys]
if args == ["rev-parse", "HEAD"]: print(source)
elif args == ["remote", "get-url", "origin"]: print("https://github.com/wolfmcnally/drawbridge.git")
elif args == ["fetch", "--no-tags", "--depth=1", "origin", controller]: pass
elif args == ["rev-parse", controller + ":.github/workflows/qualification.yml"]: print(blob)
elif args == ["fetch", "--no-tags", "--depth=1", "origin",
              "refs/tags/v0.3.0:refs/tags/v0.3.0"]: pass
elif args == ["rev-parse", "refs/tags/v0.3.0"]: print(tag)
elif args == ["rev-parse", "refs/tags/v0.3.0^{}"]: print(peel)
else: raise AssertionError(args)
""",
    )
    ordinary = case in {"ordinary", "stray"}
    env = {
        "QUALIFICATION_RELEASE_MODE": "false" if ordinary else "true",
        "QUALIFICATION_CONTROLLER": "" if case == "ordinary" else CONTROLLER,
        "QUALIFICATION_WORKFLOW_BLOB": "" if ordinary else BLOB,
        "QUALIFICATION_REQUEST": "" if ordinary else ("invalid" if case == "nonce" else "1" * 32),
        "GITHUB_SHA": "b" * 40 if case == "controller" else CONTROLLER,
        "GITHUB_WORKFLOW_SHA": "b" * 40 if case == "workflow-sha" else CONTROLLER,
        "GITHUB_EVENT_NAME": "push" if ordinary or case == "event" else "workflow_dispatch",
        "GITHUB_REPOSITORY": "wolfmcnally/drawbridge",
        "GITHUB_WORKFLOW_REF": (
            "wolfmcnally/drawbridge/.github/workflows/qualification.yml@refs/heads/other"
            if case == "workflow-ref"
            else "wolfmcnally/drawbridge/.github/workflows/qualification.yml@refs/heads/master"
        ),
        "PROBE_CONTROLLER": CONTROLLER,
        "PROBE_BLOB": "d" * 40 if case == "blob" else BLOB,
        "PROBE_SOURCE": CONTROLLER if ordinary else ("e" * 40 if case == "source" else SOURCE),
        "PROBE_TAG": "f" * 40 if case == "tag" else TAG,
        "PROBE_PEEL": "e" * 40 if case == "peel" else SOURCE,
        "GIT_LOG": str(tmp_path / "git.jsonl"),
    }
    result = invoke(
        tmp_path, step_script("Verify qualification source and controller identity"), env
    )
    if reason:
        assert result.returncode != 0, "Mismatched dispatch identity must fail closed"
        assert f"QUALIFICATION REFUSED {reason}" in result.stderr, result.stdout + result.stderr
    else:
        assert result.returncode == 0, "Valid scenario must pass: " + result.stdout + result.stderr
        assert f"mode={'ordinary' if ordinary else 'release'}" in result.stdout
        calls = [json.loads(line) for line in (tmp_path / "git.jsonl").read_text().splitlines()]
        assert len(calls) == (1 if ordinary else 8)
        if not ordinary:
            assert f"controller={CONTROLLER} workflow_blob={BLOB} source={SOURCE}" in result.stdout
            assert f"tag_object={TAG} request={'1' * 32}" in result.stdout
