"""Fail-closed splitting preserves registry hash enforcement for source installs."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/split_conric_requirements.py"
spec = importlib.util.spec_from_file_location("split_conric_requirements", SCRIPT)
splitter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(splitter)

REGISTRY = b"# exported registry requirements\r\npyyaml==6.0.3 \\\r\n    --hash=sha256:111 \\\r\n    --hash=sha256:222\r\n    # via conric\r\nother==1.0 ; python_version >= '3.12' \\\r\n    --hash=sha256:333\r\n"


def test_registry_bytes_and_hash_continuations_are_preserved_exactly():
    before, after = b"# exact export metadata\r\n", REGISTRY
    assert splitter.registry_requirements(before + splitter.CONRIC + b"\r\n" + after) == before + after


@pytest.mark.parametrize("content", [
    REGISTRY,
    splitter.CONRIC + b"\n" + splitter.CONRIC + b"\n" + REGISTRY,
    splitter.CONRIC.replace(b"ed928629", b"deadbeef") + b"\n" + REGISTRY,
    splitter.CONRIC + b" \\\n    --hash=sha256:123\n" + REGISTRY,
    splitter.CONRIC + b"\n    --hash=sha256:123\n" + REGISTRY,
    splitter.CONRIC + b"\nother @ https://example.invalid/pkg.whl\n" + REGISTRY,
    splitter.CONRIC + b"\ngit+https://example.invalid/other.git\n" + REGISTRY,
    splitter.CONRIC + b"\n-e ./unapproved-source\n" + REGISTRY,
    splitter.CONRIC + b"\nother @ file:///unapproved-source\n" + REGISTRY,
    splitter.CONRIC + b"\nconric==0.1.0\n" + REGISTRY,
    splitter.CONRIC + b"\nftp://example.invalid/pkg.whl\n" + REGISTRY,
])
def test_missing_duplicate_mutated_or_other_direct_requirements_fail_closed(content):
    with pytest.raises(ValueError):
        splitter.registry_requirements(content)


def test_cli_only_writes_validated_output_and_preserves_input(tmp_path):
    source, output = tmp_path / "export.txt", tmp_path / "registry.txt"
    content = splitter.CONRIC + b"\n" + REGISTRY
    source.write_bytes(content)
    result = subprocess.run([sys.executable, str(SCRIPT), str(source), str(output)], capture_output=True)
    assert result.returncode == 0 and output.read_bytes() == REGISTRY
    assert source.read_bytes() == content
    output.write_bytes(b"retained on validation failure")
    source.write_bytes(REGISTRY)
    result = subprocess.run([sys.executable, str(SCRIPT), str(source), str(output)], capture_output=True)
    assert result.returncode == 2 and output.read_bytes() == b"retained on validation failure"


def test_cli_rejects_overwriting_export(tmp_path):
    source = tmp_path / "export.txt"
    content = splitter.CONRIC + b"\n" + REGISTRY
    source.write_bytes(content)
    result = subprocess.run([sys.executable, str(SCRIPT), str(source), str(source)], capture_output=True)
    assert result.returncode == 2 and source.read_bytes() == content
