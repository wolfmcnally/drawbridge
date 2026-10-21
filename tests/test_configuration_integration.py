"""Exercise the independently installed CLI with synthetic PDF/configuration fixtures."""

from __future__ import annotations

import json
import shlex

import pytest

from drawbridge import _vellric, cli, convert_file
from drawbridge.configuration import ConfigurationError, configuration_context, load_configuration
from drawbridge.convert import ConversionOptions
from drawbridge.mirror import parse_mirror_header, render_mirror


def settings(tmp_path, text="vellric: {}\n", name="settings.yaml"):
    file = tmp_path / name
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text)
    return file


def test_actual_native_cli_and_api_keep_fidelity_text(native_pdf, tmp_path, capsys):
    source = native_pdf(["Synthetic native evidence.", "Second page remains exact."])
    config = settings(tmp_path)
    baseline = convert_file(source)
    with configuration_context(load_configuration([config])):
        configured = convert_file(source)
    assert configured.mirror.body == baseline.mirror.body
    assert configured.method == baseline.method == "pymupdf-text"
    assert configured.pdf.page_count == baseline.pdf.page_count == 2
    assert configured.extras["pdf_processor"]["processing_fingerprint"]
    output = tmp_path / "configured.md"
    assert cli.main(["convert", str(source), "--config", str(config), "--no-ocr", "--out", str(output)]) == 0
    capsys.readouterr()
    header, body = parse_mirror_header(output)
    assert body == parse_mirror_header(render_mirror(baseline.mirror))[1]
    assert header["processing"][0]["method"] == baseline.mirror.header["processing"][0]["method"]


@pytest.mark.parametrize("repeat_first,expected", [(False, False), (True, True)])
def test_actual_ordered_repeated_layers_and_explicit_sibling_root(native_pdf, tmp_path, repeat_first, expected):
    source = native_pdf(["Ordered configuration evidence."])
    first = settings(tmp_path, "vellric: {local_only: true}\n", "left/first.yaml")
    settings(tmp_path, "vellric: {local_only: true}\n", "right/base.yaml")
    last = settings(tmp_path, "include: [base.yaml]\nvellric: {local_only: false}\n", "right/last.yaml")
    with pytest.raises(ConfigurationError, match="include_escape"):
        load_configuration([first, last])
    selected = load_configuration([first, last, *([first] if repeat_first else [])], root=tmp_path)
    with configuration_context(selected):
        with _vellric.document_job(source, "convert", "--ocr", "never", "--preflight", "off") as bundle:
            assert bundle.manifest["settings"]["local_only"] is expected
            assert bundle.texts == ("Ordered configuration evidence.\n",)


def test_actual_unknown_leaf_is_cli_usage_without_scalar_or_reference_disclosure(native_pdf, tmp_path, capsys):
    source = native_pdf(["Leaf rejection evidence."])
    config = settings(tmp_path, "vellric: {synthetic-private-key: synthetic-private-scalar}\n")
    output = tmp_path / "must-not-exist.md"
    assert cli.main(["convert", str(source), "--config", str(config), "--no-ocr", "--out", str(output)]) == 2
    shown = capsys.readouterr()
    assert "Vellric rejected its configuration" in shown.err
    assert "synthetic-private-key" not in shown.err and "synthetic-private-scalar" not in shown.err
    assert not output.exists()


def configured_command(tmp_path):
    marker = tmp_path / "provider-executed"
    command = tmp_path / "synthetic-provider"
    command.write_text(f"#!/bin/sh\n/usr/bin/touch {shlex.quote(str(marker))}\nexit 9\n")
    command.chmod(0o700)
    config = settings(tmp_path, f"vellric:\n  vision:\n    provider: command\n    command: {json.dumps(str(command))}\n")
    return marker, config


def test_actual_no_ai_overrides_configured_vision_without_executing_provider(native_pdf, tmp_path):
    source = native_pdf(["No AI fidelity evidence."])
    marker, config = configured_command(tmp_path)
    baseline = convert_file(source)
    with configuration_context(load_configuration([config], no_ai=True)):
        result = convert_file(source)
    assert result.mirror.body == baseline.mirror.body
    assert not marker.exists()


def capture_terminal(monkeypatch):
    observed = []
    run = _vellric._run
    def recording(argv, work, timeout):
        code, out = run(argv, work, timeout)
        if argv[1] != "doctor":
            observed.append((argv[1], code, _vellric._json(out)))
        return code, out
    monkeypatch.setattr(_vellric, "_run", recording)
    return observed


def test_actual_local_only_refuses_configured_vision_in_settings_before_provider(native_pdf, tmp_path, monkeypatch):
    source = native_pdf(["Local-only evidence."])
    marker, config = configured_command(tmp_path)
    observed = capture_terminal(monkeypatch)
    with configuration_context(load_configuration([config], local_only=True)):
        with pytest.raises(ConfigurationError):
            convert_file(source)
    assert not marker.exists()
    command, code, terminal = observed[-1]
    assert command == "convert" and code == 2
    assert terminal["code"] == "usage" and terminal["stage"] == "settings"


def test_actual_unresolved_reference_fails_in_settings_before_worker_or_http(native_pdf, tmp_path, monkeypatch, capsys):
    source = native_pdf(["Unresolved reference evidence."])
    reference = "DRAWBRIDGE_SYNTHETIC_MISSING_REFERENCE"
    config = settings(tmp_path, f"vellric:\n  vision:\n    provider: openai\n    model: explicit-synthetic-model\n    base_url: https://example.invalid/v1\n    api_key: !env {reference}\n")
    # The adapter's fixed environment excludes this name; do not inject any value.
    observed = capture_terminal(monkeypatch)
    output = tmp_path / "must-not-exist.md"
    assert cli.main(["convert", str(source), "--config", str(config), "--no-ocr", "--out", str(output)]) == 2
    shown = capsys.readouterr()
    assert reference not in shown.err and "example.invalid" not in shown.err
    command, code, terminal = observed[-1]
    assert command == "convert" and code == 2
    assert terminal["code"] == "usage" and terminal["stage"] == "settings"
    assert not output.exists()


def test_actual_manifest_and_mirror_omit_configuration_paths_and_unresolved_references(native_pdf, tmp_path):
    source = native_pdf(["Manifest privacy evidence."])
    reference = "DRAWBRIDGE_SYNTHETIC_PRIVATE_REFERENCE"
    config = settings(tmp_path, f"vellric:\n  vision:\n    provider: openai\n    model: explicit-synthetic-model\n    api_key: !env {reference}\n", "private-layer.yaml")
    selected = load_configuration([config], root=tmp_path, no_ai=True)
    with configuration_context(selected):
        with _vellric.document_job(source, "convert", "--ocr", "never", "--preflight", "off") as bundle:
            manifest = json.dumps(bundle.manifest)
            assert reference not in manifest and str(config) not in manifest and config.name not in manifest
            assert not {"config", "config_root", "vision_api_key_env"} & bundle.manifest["settings"].keys()
        result = convert_file(source, options=ConversionOptions(acquired_from="synthetic-source"))
    assert reference not in json.dumps(result.mirror.header) and str(config) not in json.dumps(result.mirror.header)
    assert config.name not in result.mirror.body
