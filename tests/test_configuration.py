"""Synthetic configuration qualification; no provider calls or private documents."""

from __future__ import annotations

import asyncio
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from drawbridge import _vellric, cli
from drawbridge.configuration import (
    Configuration, ConfigurationError, configuration_context,
    current_configuration, load_configuration,
)
from drawbridge.convert import convert_pdf
from drawbridge.errors import ConversionOperationalError
from drawbridge.identify import IdentifyResult
from drawbridge.ocr import CliOcrBackend, OcrResult
from drawbridge.pdf_tools import PdfInspection
from drawbridge.profile import Endpoint, EgressRefused, Plan, StagePlan, build_plan, parse_profile


def config_file(tmp_path, text="vellric: {}\n", name="settings.yaml"):
    file = tmp_path / name
    file.write_text(text)
    return file


def test_composition_include_order_and_root(tmp_path):
    base = config_file(tmp_path, "drawbridge:\n  limits:\n    max_pages_per_document: 4\n", "base.yaml")
    first = config_file(tmp_path, "include: [base.yaml]\ndrawbridge:\n  limits:\n    max_audio_minutes: 12\n", "first.yaml")
    last = config_file(tmp_path, "drawbridge:\n  limits:\n    max_pages_per_document: 9\n", "last.yaml")
    selected = load_configuration([first, last], root=tmp_path)
    assert selected.profile.limits.max_pages_per_document == 9
    assert selected.profile.limits.max_audio_minutes == 12
    assert selected.files == (first.resolve(), last.resolve())
    assert base not in selected.files  # Original inputs, not a serialized merged replacement.
    assert selected.root == tmp_path.resolve()
    with pytest.raises(ConfigurationError, match="requires"):
        load_configuration([], root=tmp_path)
    outside = config_file(tmp_path.parent, "drawbridge: {}\n", "outside-configuration.yaml")
    try:
        with pytest.raises(ConfigurationError, match="include_escape"):
            load_configuration([outside], root=tmp_path)
    finally:
        outside.unlink()


@pytest.mark.parametrize("text", [
    "drawbridge: {private-unrecognized-field: sensitive-scalar}\n",
    "drawbridge: {limits: {max_pages_per_document: sensitive-scalar}}\n",
    "drawbridge: {limits: {cache_dir: !env SYNTHETIC_REFERENCE}}\n",
])
def test_own_schema_errors_never_echo_scalars_or_keys(tmp_path, text):
    with pytest.raises(ConfigurationError) as error:
        load_configuration([config_file(tmp_path, text)])
    message = str(error.value)
    assert "sensitive-scalar" not in message
    assert "private-unrecognized-field" not in message
    assert "SYNTHETIC_REFERENCE" not in message


def test_opaque_leaves_and_unresolved_references_are_not_validated_or_displayed(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHETIC_REFERENCE", "synthetic-private-value")
    file = config_file(tmp_path, "vellric: {future-schema: [!env SYNTHETIC_REFERENCE]}\nother: {opaque: true}\n")
    selected = load_configuration([file])
    assert not selected.profile.stages
    assert "SYNTHETIC_REFERENCE" not in repr(selected)
    assert "synthetic-private-value" not in json.dumps(selected.report())
    assert "deferred" in selected.report()["vellric_validation"]


def nested_profile():
    return parse_profile({
        "endpoints": {"remote": {"kind": "elevenlabs", "egress": "cloud"}},
        "stages": {
            "audio_cleanup": {"endpoint": "remote", "settings": {"nested": {"filters": [{"enabled": True}]}}},
            "transcription": {"endpoint": "remote", "model": "explicit"},
        },
    })


def test_frozen_nested_profile_redaction_materializes_json_containers():
    selected = Configuration(profile=nested_profile())
    shown = selected.profile.redacted()
    assert json.loads(json.dumps(shown))["stages"]["audio_cleanup"]["settings"]["nested"] == {"filters": [{"enabled": True}]}
    shown["stages"]["audio_cleanup"]["settings"]["nested"]["filters"][0]["enabled"] = False
    assert selected.profile.stages["audio_cleanup"]["settings"]["nested"]["filters"][0]["enabled"] is True


def test_frozen_audio_settings_materialize_at_dependency_serialization(tmp_path):
    from drawbridge.audio import AudioDecision, _dependency_options

    selected = Configuration(profile=nested_profile())
    decision = AudioDecision("on", "off", 12, None, True, False)
    options = _dependency_options(selected.profile, tmp_path, decision)
    encoded = options[options.index("--auphonic-set") + 1]
    key, _, value = encoded.partition("=")
    assert key == "nested" and json.loads(value) == {"filters": [{"enabled": True}]}


@pytest.mark.parametrize("url,model,accepted", [
    ("http://127.0.0.1:11434", "explicit-model", True),
    ("http://[::1]:11434", "explicit-model", True),
    ("http://localhost:11434", "explicit-model", True),
    ("https://example.invalid", "explicit-model", False),
    ("http://192.168.1.2:11434", "explicit-model", False),
    ("http://127.0.0.1:11434", None, False),
])
def test_composed_own_local_claim_and_model_policy(tmp_path, url, model, accepted):
    import yaml

    data = {"endpoints": {"local": {"kind": "ollama", "egress": "local", "base_url": url}},
            "stages": {"image_description": {"endpoint": "local", **({"model": model} if model else {})}}}
    file = config_file(tmp_path, yaml.safe_dump({"drawbridge": data}))
    if accepted:
        assert load_configuration([file]).profile.stages["image_description"]["model"] == model
    else:
        with pytest.raises(ConfigurationError):
            load_configuration([file])
    # The added explicit-mode requirements do not change the legacy parser.
    assert parse_profile(data).stages


def test_context_is_immutable_nested_and_exception_safe(tmp_path):
    first = load_configuration([config_file(tmp_path, "drawbridge: {stages: {ocr: {engine: tesseract}}}\n")])
    second = Configuration(local_only=True)
    original = current_configuration()
    with configuration_context(first):
        with pytest.raises(TypeError):
            first.profile.stages["ocr"]["engine"] = "other"
        with pytest.raises(FrozenInstanceError):
            first.no_ai = True
        with pytest.raises(RuntimeError):
            with configuration_context(second):
                assert current_configuration() is second
                raise RuntimeError("synthetic")
        assert current_configuration() is first
    assert current_configuration() is original


def test_concurrent_tasks_and_new_threads_have_explicit_context_semantics():
    async def run():
        async def task(selected):
            with configuration_context(selected):
                await asyncio.sleep(0)
                return current_configuration()
        first, second = Configuration(no_ai=True), Configuration(local_only=True)
        assert await asyncio.gather(task(first), task(second)) == [first, second]
    asyncio.run(run())
    with configuration_context(Configuration(no_ai=True)):
        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(current_configuration).result().no_ai is False


def test_forward_original_paths_and_explicit_restrictions_only_to_convert(tmp_path, monkeypatch):
    first = config_file(tmp_path, name="first.yaml")
    second = config_file(tmp_path, name="second.yaml")
    selected = load_configuration([second, first, second], root=tmp_path, local_only=True, no_ai=True)
    expected = ("--config", str(second), "--config", str(first), "--config", str(second),
                "--config-root", str(tmp_path), "--local-only", "--vision-provider", "none")
    with configuration_context(selected):
        assert _vellric.configured_options(())[-len(expected):] == expected
        for command in ("inspect", "render", "image"):
            assert "--config" not in _vellric.configured_options((), command=command)
            assert "--local-only" not in _vellric.configured_options((), command=command)
        assert _vellric.configured_options(("--vision-provider", "synthetic"))[-2:] == ("--vision-provider", "none")
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    monkeypatch.delenv("DRAWBRIDGE_VELLRIC_TESSDATA_DIR", raising=False)
    with configuration_context(Configuration(local_only=True, no_ai=True)):
        assert _vellric.configured_options(()) == ()


@pytest.mark.parametrize("local_only,no_ai,expected", [
    (False, False, "may execute configured provider routes"),
    (True, False, "forwarded --local-only"),
    (False, True, "forwarded --vision-provider none"),
    (True, True, "forwarded --vision-provider none"),
])
def test_dry_run_reports_opaque_vellric_routes_and_forwarded_restrictions(tmp_path, capsys, local_only, no_ai, expected):
    source = tmp_path / "source.txt"
    source.write_text("Synthetic dry-run evidence.")
    file = config_file(tmp_path, "vellric: {opaque-future-route: true}\n")
    flags = [*( ["--local-only"] if local_only else []), *( ["--no-ai"] if no_ai else [])]
    assert cli.main(["convert", str(source), "--config", str(file), "--dry-run", *flags]) == 0
    report = json.loads(capsys.readouterr().out)
    assert expected in report["configuration"]["vellric_routes"]
    assert "not evaluated" in report["configuration"]["vellric_routes"]


def test_actual_conric_owns_symlink_confinement_and_original_paths_are_forwarded(tmp_path):
    inside, outside = tmp_path / "inside", tmp_path / "outside"
    inside.mkdir()
    outside.mkdir()
    target = config_file(inside)
    alias = inside / "alias.yaml"
    alias.symlink_to(target)
    root_alias = tmp_path / "root-alias"
    root_alias.symlink_to(inside, target_is_directory=True)
    selected = load_configuration([alias], root=root_alias)
    assert selected.files == (alias.absolute(),) and selected.files != (target.resolve(),)
    assert selected.root == root_alias.absolute()
    assert selected.convert_options() == ("--config", str(alias.absolute()), "--config-root", str(root_alias.absolute()))
    escaped = config_file(outside)
    alias.unlink()
    alias.symlink_to(escaped)
    with pytest.raises(ConfigurationError, match="include_escape"):
        load_configuration([alias], root=root_alias)
    included = config_file(inside, "include: [alias.yaml]\nvellric: {}\n", "including.yaml")
    with pytest.raises(ConfigurationError, match="include_escape"):
        load_configuration([included], root=root_alias)


@pytest.mark.parametrize("extra", [["--profile", "missing.yaml"], ["--no-profile"]])
def test_cli_source_conflicts(tmp_path, capsys, extra):
    file = config_file(tmp_path)
    assert cli.main(["convert", str(tmp_path / "absent"), "--config", str(file), *extra]) == 2
    assert "conflicts" in capsys.readouterr().err


def test_cli_explicit_mode_skips_ambient_profile_and_dotenv(tmp_path, monkeypatch, capsys):
    file = config_file(tmp_path)
    source = tmp_path / "source.txt"
    source.write_text("Synthetic evidence.")
    (tmp_path / "drawbridge.yaml").write_text("invalid: profile")
    (tmp_path / ".env").write_text("SYNTHETIC_NOT_LOADED=synthetic\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SYNTHETIC_NOT_LOADED", raising=False)
    monkeypatch.setattr(cli, "resolve_profile", lambda *a, **k: pytest.fail("ambient discovery"))
    assert cli.main(["convert", str(source), "--config", str(file), "--dry-run"]) == 0
    assert "deferred" in json.loads(capsys.readouterr().out)["configuration"]["vellric_validation"]
    import os
    assert "SYNTHETIC_NOT_LOADED" not in os.environ


def test_local_only_refuses_before_any_key_presence_lookup(monkeypatch):
    profile = parse_profile({"endpoints": {"remote": {"kind": "openai-compatible", "egress": "cloud", "api_key_env": "SYNTHETIC_KEY"}},
                             "stages": {"image_description": {"endpoint": "remote", "model": "explicit"}}})
    def forbidden(self):
        pytest.fail("credential presence inspected before policy refusal or for a disabled stage")
    monkeypatch.setattr(Endpoint, "key_is_set", property(forbidden))
    with pytest.raises(EgressRefused):
        build_plan(profile, "image/png", local_only=True)
    assert not build_plan(profile, "image/png", no_ai=True).cloud_stages
    assert not build_plan(profile, "image/png", skip=["image_description"]).cloud_stages


def test_library_scoped_policy_rechecks_a_caller_supplied_plan_before_conversion(tmp_path, monkeypatch):
    from drawbridge.documents import convert_file

    profile = parse_profile({"endpoints": {"remote": {"kind": "openai-compatible", "egress": "cloud"}},
                             "stages": {"structure": {"endpoint": "remote", "model": "explicit"}}})
    supplied = build_plan(profile, "application/pdf")
    monkeypatch.setattr(Endpoint, "key_is_set", property(lambda self: pytest.fail("credential lookup before refusal")))
    with configuration_context(Configuration(local_only=True)):
        with pytest.raises(EgressRefused):
            convert_file(tmp_path / "not-opened.pdf", profile=profile, plan=supplied, media_type="application/pdf")


def test_library_uses_scoped_profile_and_no_ai_without_widening_supplied_plan(tmp_path, monkeypatch):
    import drawbridge.documents as documents

    profile = parse_profile({"endpoints": {"remote": {"kind": "openai-compatible", "egress": "cloud"}},
                             "stages": {"image_description": {"endpoint": "remote", "model": "explicit"}}})
    supplied = build_plan(profile, "image/png")
    seen = []
    def image(*args, **kwargs):
        seen.append(kwargs)
        return "synthetic-result"
    monkeypatch.setattr(documents, "_image", image)
    monkeypatch.setattr(Endpoint, "key_is_set", property(lambda self: pytest.fail("suppressed endpoint inspected")))
    with configuration_context(Configuration(profile=profile, no_ai=True)):
        assert documents.convert_file(tmp_path / "not-opened.png", plan=supplied, media_type="image/png") == "synthetic-result"
    assert seen[0]["profile"].stages == profile.stages
    assert not seen[0]["plan"].runs("image_description")


@pytest.mark.parametrize("enabled", [True, False])
def test_scoped_plan_intersects_model_restrictions_per_stage(tmp_path, monkeypatch, enabled):
    import drawbridge.documents as documents

    profile = parse_profile({
        "endpoints": {"remote": {"kind": "openai-compatible", "egress": "cloud"}},
        "stages": {"ocr": {"engine": "tesseract"}, "image_description": {"endpoint": "remote", "model": "explicit"}},
    })
    prior = Plan("image/png", (StagePlan("ocr", True, "deterministic", model=False),
                               StagePlan("image_description", enabled, "caller selection")))
    seen = []
    monkeypatch.setattr(documents, "_image", lambda *a, **kw: seen.append(kw) or "synthetic-result")
    with configuration_context(Configuration(profile=profile)):
        assert documents.convert_file(tmp_path / "not-opened.png", plan=prior, media_type="image/png") == "synthetic-result"
    plan = seen[0]["plan"]
    assert plan.runs("ocr") and not plan.runs_model("ocr")
    assert plan.runs_model("image_description") is enabled
    assert seen[0]["profile"].stages == profile.stages


def test_explicit_profile_only_context_is_used_without_files_or_flags(tmp_path, monkeypatch):
    import drawbridge.documents as documents

    profile = parse_profile({"stages": {"ocr": {"engine": "tesseract"}}})
    seen = []
    monkeypatch.setattr(documents, "_image", lambda *a, **kw: seen.append(kw) or "synthetic-result")
    with configuration_context(Configuration(profile=profile)):
        documents.convert_file(tmp_path / "not-opened.png", media_type="image/png")
    assert seen[0]["plan"].runs("ocr")
    assert seen[0]["profile"].stages == profile.stages


@pytest.mark.parametrize("exit_code,stage,configured,error", [(2, "settings", True, ConfigurationError), (5, "settings", True, ConversionOperationalError), (2, "job", True, ConversionOperationalError), (2, "settings", False, ConversionOperationalError)])
def test_structured_settings_usage_preserves_exit_consistency(tmp_path, monkeypatch, exit_code, stage, configured, error):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(_vellric, "executable", lambda: sys.executable)
    monkeypatch.setattr(_vellric, "_check_doctor", lambda *a: None)
    message = {"schema": _vellric.STATUS, "status": "failed", "code": "usage", "stage": stage,
               "message": "private-looking synthetic scalar must not be echoed"}
    monkeypatch.setattr(_vellric, "_run", lambda *a: (exit_code, json.dumps(message)))
    settings = load_configuration([config_file(tmp_path)]) if configured else Configuration()
    with configuration_context(settings):
        with pytest.raises(error) as caught:
            with _vellric.document_job(source, "convert"):
                pytest.fail("unexpected complete job")
    if error is ConfigurationError:
        assert "private-looking" not in str(caught.value)


def native_admission(tmp_path, *, scan=False):
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"%PDF-1.4\nsynthetic document bytes\n")
    text = "" if scan else "Native evidence.\n"
    inspection = PdfInspection(True, False, False, 1, bool(text), (text,),
                               _vellric.sha256_file(source), (1.0 if scan else 0.0,),
                               ({"displayed_rect": [0, 0, 100, 100]},))
    return source, IdentifyResult(str(source), "application/pdf", (), "processable", None, None, None, inspection)


@pytest.mark.parametrize("fault", [None, "native-changed", "final-changed", "outstanding", "settings"])
def test_configured_native_complete_job_preserves_fidelity_and_provenance(tmp_path, monkeypatch, fault):
    monkeypatch.delenv("DRAWBRIDGE_VELLRIC_MEMORY_MIB", raising=False)
    source, admission = native_admission(tmp_path)
    calls = []
    @contextmanager
    def job(file, command, *options, **kwargs):
        calls.append((command, options, kwargs))
        if fault == "settings":
            raise ConfigurationError("synthetic leaf refusal")
        native = ("changed",) if fault == "native-changed" else admission.inspection.page_texts
        final = ("changed",) if fault == "final-changed" else native
        manifest = {"outstanding_candidates": [1] if fault == "outstanding" else []}
        bundle = SimpleNamespace(manifest=manifest, texts=final)
        bundle.inspection = PdfInspection(True, False, False, 1, True, native,
                                         processor={"processing_fingerprint": "qualified-convert"})
        yield bundle
    monkeypatch.setattr(_vellric, "document_job", job)
    import drawbridge.pdf_tools as tools
    monkeypatch.setattr(tools, "inspection_from_bundle", lambda bundle: bundle.inspection)
    with configuration_context(load_configuration([config_file(tmp_path)])):
        if fault:
            with pytest.raises(ConfigurationError if fault == "settings" else ConversionOperationalError):
                convert_pdf(source, ocr=None, identify_result=admission)
        else:
            result = convert_pdf(source, ocr=None, identify_result=admission)
            assert "Native evidence." in result.mirror.body
            assert result.extras["pdf_processor"]["processing_fingerprint"] == "qualified-convert"
    assert len(calls) == 1 and calls[0][0] == "convert"
    assert calls[0][1][:2] == ("--ocr", "never")
    assert calls[0][1][calls[0][1].index("--jobs") + 1] == "1"
    assert calls[0][1][calls[0][1].index("--memory-mib") + 1] == "2048"
    assert calls[0][2]["expected_sha256"] == admission.inspection.source_sha256


def test_configured_native_job_uses_caller_grant_and_releases_it_on_failure(tmp_path, monkeypatch):
    from drawbridge.ocr import OcrCapacity
    import drawbridge.pdf_tools as tools

    source, admission = native_admission(tmp_path)
    capacity = OcrCapacity(3)
    backend = CliOcrBackend(available_cores=8, capacity=capacity, document_workers=2,
                            memory_mib=3072, document_timeout=19, max_input_bytes=1024, max_pages=5)
    calls = []
    @contextmanager
    def job(file, command, *options, **kwargs):
        assert capacity.available == 0  # The caller's three-token grant is held throughout validation.
        calls.append((command, options, kwargs))
        yield SimpleNamespace(manifest={"outstanding_candidates": []}, texts=("changed-final-text",))
    monkeypatch.setattr(_vellric, "document_job", job)
    monkeypatch.setattr(tools, "inspection_from_bundle", lambda bundle: admission.inspection)
    with configuration_context(load_configuration([config_file(tmp_path)])):
        with pytest.raises(ConversionOperationalError, match="native text changed"):
            convert_pdf(source, ocr=backend, identify_result=admission)
    assert capacity.available == 3
    command, options, kwargs = calls[0]
    assert command == "convert"
    for flag, value in (("--ocr", "never"), ("--preflight", "off"), ("--jobs", "3"),
                        ("--memory-mib", "3072"), ("--max-input-bytes", "1024"), ("--max-pages", "5")):
        assert options[options.index(flag) + 1] == value
    assert kwargs["timeout"] == 19


def test_configured_ocr_uses_existing_single_job_and_custom_backend_fails_closed(tmp_path, monkeypatch):
    source, admission = native_admission(tmp_path, scan=True)
    backend = CliOcrBackend(preflight=False)
    calls = []
    def document(self, file, **kwargs):
        calls.append((file, kwargs, current_configuration()))
        return None, OcrResult(("Recognized evidence.\n",), ()), {}
    monkeypatch.setattr(CliOcrBackend, "document", document)
    selected = load_configuration([config_file(tmp_path)], local_only=True, no_ai=True)
    with configuration_context(selected):
        result = convert_pdf(source, ocr=backend, identify_result=admission)
        assert result.selected_pages == (1,) and "Recognized evidence." in result.mirror.body
        assert len(calls) == 1 and calls[0][2] is selected
        with pytest.raises(ConfigurationError, match="CliOcrBackend"):
            convert_pdf(source, ocr=SimpleNamespace(extract=lambda *a: pytest.fail("custom OCR ran")), identify_result=admission)
