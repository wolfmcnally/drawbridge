from __future__ import annotations

import copy
import hashlib
import json
import os
import sys

import pytest
from drawbridge import _vellric
from drawbridge.errors import (
    ConversionOperationalError,
    ConverterUnavailable,
    OcrOperationalError,
    OcrPreflightError,
)
from drawbridge.pdf_tools import EncryptedPdfError


@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / "bundle"
    root.mkdir()
    page = root / "pages/000001"
    page.mkdir(parents=True)
    files = {
        "pages/000001/native.txt": "Native evidence.\n",
        "pages/000001/text.txt": "Native evidence.\n",
        "document.txt": "Native evidence.\n",
        "document.md": "# Example\n\n## Page 1\n\nNative evidence.\n",
    }
    entries = []
    for name, text in files.items():
        (root / name).write_text(text)
        raw = text.encode()
        entries.append({"path": name, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    manifest = {
        "schema": _vellric.SCHEMA,
        "status": "complete",
        "job": "inspect",
        "behavior": _vellric.BEHAVIOR,
        "tool": {"name": "vellric", "version": "0.0.0"},
        "engines": {"pymupdf": "1.28.2", "mupdf": "1.28.2"},
        "source": {"sha256": "a" * 64, "size": 10},
        "page_count": 1,
        "inspection": {
            "openable": True,
            "page_count": 1,
            "has_text_layer": True,
            "is_encrypted": False,
            "needs_password": False,
        },
        "provenance": {"processing_fingerprint": "b" * 64},
        "recognition_completeness": "not-requested",
        "outstanding_candidates": [],
        "pages": [
            {
                "number": 1,
                "method": "pymupdf-text",
                "ocr_candidate": False,
                "raster_coverage": 0.0,
                "geometry": {"displayed_rect": [0.0, 0.0, 100.0, 100.0]},
                "files": {
                    "native": "pages/000001/native.txt",
                    "text": "pages/000001/text.txt",
                },
            }
        ],
        "files": entries,
    }
    return root, manifest


def validate(bundle):
    root, m = bundle
    return _vellric.validate_bundle(root, m, job="inspect", source_hash="a" * 64, source_size=10)


def test_complete_bundle_reads_exact_text_and_allows_parent_alias(bundle, tmp_path):
    root, m = bundle
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    assert validate((alias / "bundle", m)).texts == ("Native evidence.\n",)


@pytest.mark.parametrize(
    "fault",
    [
        "count",
        "order",
        "source",
        "size",
        "digest",
        "duplicate",
        "escape",
        "extra",
        "text-changed",
        "status",
        "recognition",
        "fingerprint",
        "tool",
        "engine",
        "inspection",
    ],
)
def test_inconsistent_or_unsafe_bundle_refuses(bundle, fault):
    root, m = bundle
    if fault == "count":
        m["page_count"] = True
    elif fault == "order":
        m["pages"][0]["number"] = 2
    elif fault == "source":
        m["source"]["sha256"] = "c" * 64
    elif fault == "size":
        m["files"][0]["size"] += 1
    elif fault == "digest":
        m["files"][0]["sha256"] = "d" * 64
    elif fault == "duplicate":
        m["files"].append(copy.deepcopy(m["files"][0]))
    elif fault == "escape":
        m["files"][0]["path"] = "../private"
    elif fault == "extra":
        (root / "unlisted").write_text("foreign")
    elif fault == "text-changed":
        p = root / "pages/000001/text.txt"
        p.write_text("Changed evidence.\n")
        f = next(f for f in m["files"] if f["path"].endswith("/text.txt"))
        f["size"] = p.stat().st_size
        f["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
    elif fault == "status":
        m["status"] = "failed"
    elif fault == "recognition":
        m["outstanding_candidates"] = [1]
    elif fault == "fingerprint":
        m["provenance"]["processing_fingerprint"] = "invalid"
    elif fault == "tool":
        m["tool"]["name"] = "other"
    elif fault == "engine":
        m["engines"]["pymupdf"] = "unqualified"
    elif fault == "inspection":
        m["inspection"]["has_text_layer"] = False
    with pytest.raises(ConversionOperationalError):
        validate((root, m))


def test_artifact_symlink_refused_even_with_matching_bytes(bundle, tmp_path):
    root, m = bundle
    p = root / "pages/000001/text.txt"
    outside = tmp_path / "outside"
    outside.write_bytes(p.read_bytes())
    p.unlink()
    p.symlink_to(outside)
    with pytest.raises(ConversionOperationalError):
        validate((root, m))


def cli(tmp_path, monkeypatch, status, returncode=0, *, doctor=None, body=""):
    exe = tmp_path / "fake vellric"
    doctor = doctor or {
        "schema": _vellric.SCHEMA,
        "behavior": _vellric.BEHAVIOR,
        "tool": {"name": "vellric", "version": "0.0.0"},
    }
    exe.write_text(
        f'#!{sys.executable}\nimport json,sys,os,time\nif sys.argv[1]=="doctor":\n print({json.dumps(json.dumps(doctor))});sys.exit(0)\n'
        + body
        + "\n"
        + f"print({json.dumps(json.dumps(status))});sys.exit({returncode})\n"
    )
    exe.chmod(0o700)
    monkeypatch.setenv("DRAWBRIDGE_VELLRIC", str(exe))
    return exe


@pytest.mark.parametrize(
    "code,exit_code,error,stage",
    [
        ("password-protected", 3, EncryptedPdfError, "inspection"),
        ("dependency-unavailable", 5, OcrOperationalError, "recognition"),
        ("ocr-preflight-refused", 5, OcrPreflightError, "preflight"),
    ],
)
def test_structured_failure_preserves_blast_radius(
    tmp_path, monkeypatch, code, exit_code, error, stage
):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    status = {
        "schema": _vellric.STATUS,
        "status": "blocked" if exit_code == 3 else "failed",
        "code": code,
        "stage": stage,
        "message": "synthetic refusal",
        "details": {"backend_returncode": 6},
    }
    cli(tmp_path, monkeypatch, status, exit_code)
    with pytest.raises(error) as result:
        with _vellric.document_job(source, "inspect"):
            pass
    if code == "ocr-preflight-refused":
        assert result.value.returncode == 6


@pytest.mark.parametrize(
    "status,code",
    [
        ({"schema": _vellric.STATUS, "status": "complete", "code": "complete"}, 5),
        (
            {
                "schema": _vellric.STATUS,
                "status": "blocked",
                "code": "password-protected",
            },
            4,
        ),
        (
            {
                "schema": _vellric.STATUS,
                "status": "failed",
                "code": "password-protected",
            },
            3,
        ),
        ({"schema": "unknown", "status": "failed", "code": "malformed-pdf"}, 4),
        ([], 0),
    ],
)
def test_terminal_contradiction_refused(tmp_path, monkeypatch, status, code):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    cli(tmp_path, monkeypatch, status, code)
    with pytest.raises(ConversionOperationalError):
        with _vellric.document_job(source, "inspect"):
            pass


@pytest.mark.parametrize(
    "doctor",
    [
        {"schema": "unknown", "tool": {"name": "vellric"}},
        {"schema": _vellric.SCHEMA, "behavior": _vellric.BEHAVIOR, "tool": "bad"},
    ],
)
def test_capability_shape_refuses(tmp_path, monkeypatch, doctor):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    cli(tmp_path, monkeypatch, {}, doctor=doctor)
    with pytest.raises(ConverterUnavailable):
        with _vellric.document_job(source, "inspect"):
            pass


def test_duplicate_and_nonfinite_json_refuse():
    for text in ['{"status":"complete","status":"failed"}', '{"score":NaN}']:
        with pytest.raises(ValueError):
            _vellric._json(text)


def test_progress_runs_on_caller_thread_and_ambient_credentials_are_absent(tmp_path, monkeypatch):
    import threading

    from drawbridge import report_progress

    exe = tmp_path / "stream"
    exe.write_text(
        f'#!{sys.executable}\nimport json,os,sys\nprint(json.dumps({{"schema":"vellric.progress/1.0","stage":"recognition","done":1,"total":2}}),file=sys.stderr,flush=True)\nprint(json.dumps(sorted(os.environ)))\n'
    )
    exe.chmod(0o700)
    monkeypatch.setenv("DB_TEST_SECRET", "synthetic")
    monkeypatch.setenv("PYTHONPATH", "/synthetic/injection")
    heard = []
    caller = threading.get_ident()
    with report_progress(lambda s, d, t: heard.append((s, d, t, threading.get_ident() == caller))):
        code, out = _vellric._run([str(exe)], tmp_path, 5)
    assert (
        code == 0
        and "DB_TEST_SECRET" not in json.loads(out)
        and "PYTHONPATH" not in json.loads(out)
    )
    assert heard == [("recognition", 1, 2, True)]


def test_parent_deadline_stops_its_cli_process(tmp_path):
    exe = tmp_path / "hang"
    pidfile = tmp_path / "pid"
    exe.write_text(
        f'#!{sys.executable}\nimport os,time\nopen({str(pidfile)!r},"w").write(str(os.getpid()))\ntime.sleep(20)\n'
    )
    exe.chmod(0o700)
    with pytest.raises(ConversionOperationalError, match="timed out"):
        _vellric._run([str(exe)], tmp_path, 0.2)
    pid = int(pidfile.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.parametrize("mode", ["RGBA", "P", "RGB"])
def test_permissive_image_jpeg_bounds_and_alpha(tmp_path, mode):
    import io

    from drawbridge.images import image_jpeg
    from PIL import Image

    image = Image.new(mode, (300, 100))
    source = tmp_path / "image"
    image.save(source, format="PNG")
    data = image_jpeg(source, max_side=60)
    with Image.open(io.BytesIO(data)) as decoded:
        assert decoded.mode == "RGB" and decoded.size == (60, 20)
        if mode == "RGBA":
            assert min(decoded.getpixel((10, 10))) >= 250


@pytest.mark.parametrize(
    "fault",
    ["missing-encryption", "missing-geometry", "nan-geometry", "missing-render-path"],
)
def test_consumed_manifest_fields_fail_with_typed_error(bundle, fault):
    root, m = bundle
    if fault == "missing-encryption":
        del m["inspection"]["needs_password"]
    elif fault == "missing-geometry":
        del m["pages"][0]["geometry"]
    elif fault == "nan-geometry":
        m["pages"][0]["geometry"]["displayed_rect"][2] = float("nan")
    else:
        m["pages"][0]["renders"] = [{}]
    with pytest.raises(ConversionOperationalError):
        validate((root, m))


def test_bundle_text_retains_carriage_returns(bundle):
    root, m = bundle
    for entry in m["files"]:
        if entry["path"].endswith(".txt"):
            data = b"Native\revidence.\r\n"
            (root / entry["path"]).write_bytes(data)
            entry["size"] = len(data)
            entry["sha256"] = hashlib.sha256(data).hexdigest()
    assert validate((root, m)).texts == ("Native\revidence.\r\n",)


@pytest.mark.parametrize("code", ["resource-limit", "deadline", "internal-error"])
def test_identification_returns_document_local_cli_failures(tmp_path, monkeypatch, code):
    from drawbridge.identify import identify

    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    status = {
        "schema": _vellric.STATUS,
        "status": "failed",
        "code": code,
        "stage": "inspection",
        "message": "synthetic document-local fault",
    }
    cli(tmp_path, monkeypatch, status, 5)
    result = identify(source)
    assert result.outcome == "failed" and result.code == "pdf-processing-operational"
    with pytest.raises(ConversionOperationalError):
        result.raise_for_outcome()


def test_runtime_imports_do_not_load_pdf_engines():
    import subprocess

    script = """import sys, pkgutil
for name in ("pymupdf", "fitz", "vellric"):
    sys.modules[name] = None
import drawbridge
for info in pkgutil.iter_modules(drawbridge.__path__):
    if info.name != "__main__":
        __import__("drawbridge." + info.name)
"""
    subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True)


def test_global_limits_and_language_data_forward_explicitly(monkeypatch, tmp_path):
    monkeypatch.setenv("DRAWBRIDGE_VELLRIC_MEMORY_MIB", "4096")
    monkeypatch.setenv("DRAWBRIDGE_VELLRIC_MAX_INPUT_BYTES", "1073741824")
    monkeypatch.setenv("DRAWBRIDGE_VELLRIC_MAX_PAGES", "20000")
    monkeypatch.setenv("TESSDATA_PREFIX", str(tmp_path))
    options = _vellric.configured_options(())
    for flag, value in [
        ("--memory-mib", "4096"),
        ("--max-input-bytes", "1073741824"),
        ("--max-pages", "20000"),
        ("--tessdata-dir", str(tmp_path.resolve())),
    ]:
        assert options[options.index(flag) + 1] == value
    assert _vellric.configured_options(("--memory-mib", "8192"))[1] == "8192"


def test_oversize_or_undecodable_image_returns_pending_mirror(tmp_path, monkeypatch):
    from drawbridge import CliOcrBackend, convert_file, images
    from PIL import Image

    source = tmp_path / "oversize.png"
    Image.new("RGB", (20, 20), "white").save(source)
    monkeypatch.setattr(images, "MAX_IMAGE_PIXELS", 100)
    result = convert_file(source, ocr=CliOcrBackend())
    assert "ocr-pending" in result.mirror.header["verify"]
    assert "[No text detected.]" in result.mirror.body


def test_native_structure_refuses_a_source_changed_after_fidelity(native_pdf, monkeypatch):
    import pymupdf
    from drawbridge.convert import convert_pdf
    from drawbridge.mirror import render_mirror
    from drawbridge.profile import build_plan, parse_profile
    from drawbridge.structure import run_structure

    source = native_pdf(["Original native words."])
    result = convert_pdf(source, ocr=None)
    with pymupdf.open(source) as document:
        document[0].insert_text((72, 100), "Later changed words.")
        document.saveIncr()
    profile = parse_profile(
        {
            "endpoints": {
                "router": {
                    "kind": "openai-compatible",
                    "base_url": "https://example.invalid/v1",
                    "api_key_env": "DB_TEST_ROUTER",
                    "egress": "cloud",
                }
            },
            "stages": {"structure": {"endpoint": "router", "model": "some/model"}},
        }
    )
    with pytest.raises(ConversionOperationalError):
        run_structure(
            render_mirror(result.mirror),
            profile=profile,
            plan=build_plan(profile, "application/pdf"),
            source=source,
        )


def test_noninteger_memory_limit_refuses_before_launch(monkeypatch):
    monkeypatch.setenv("DRAWBRIDGE_VELLRIC_MEMORY_MIB", "2048.5")
    with pytest.raises(ConverterUnavailable, match="integer limit"):
        _vellric.configured_options(())


def test_stale_ambient_tessdata_does_not_break_native_jobs(monkeypatch, tmp_path):
    monkeypatch.setenv("TESSDATA_PREFIX", str(tmp_path / "absent"))
    assert "--tessdata-dir" not in _vellric.configured_options((), command="render")
    assert "--tessdata-dir" not in _vellric.configured_options((), command="image")


def test_compatibility_probe_cache_invalidates_when_cli_changes(monkeypatch, tmp_path):
    executable = tmp_path / "vellric"
    executable.write_text("first")
    calls = []

    def run(argv, work, timeout):
        calls.append(argv)
        return 0, json.dumps(
            {"schema": _vellric.SCHEMA, "behavior": _vellric.BEHAVIOR, "tool": {"name": "vellric"}}
        )

    monkeypatch.setattr(_vellric, "_run", run)
    _vellric._check_doctor(str(executable), tmp_path)
    _vellric._check_doctor(str(executable), tmp_path)
    assert len(calls) == 1
    executable.write_text("second changed executable")
    _vellric._check_doctor(str(executable), tmp_path)
    assert len(calls) == 2
