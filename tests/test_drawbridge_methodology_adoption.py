"""Receiving boundary absent from the generic workflow fixture estate."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_real_test_entrypoint_scrubs_parent_secrets_and_home(tmp_path: Path) -> None:
    """A real nested wrapper must not read the operator's credentials or config home."""
    probe = tmp_path / "test_private_environment.py"
    probe.write_text(
        "import os\nimport tempfile\nfrom pathlib import Path\n\n"
        "def test_private_environment():\n"
        "    secret_present = 'DRAWBRIDGE_TEST_FAKE_SECRET' in os.environ\n"
        "    assert secret_present is False, 'TEST SECRET LEAK'\n"
        "    actual_home = Path(os.environ['HOME']).resolve()\n"
        "    private_root = Path(__file__).resolve().parent.parent\n"
        "    assert actual_home.parent == private_root, 'TEST HOME LEAK'\n"
        "    temporary_root = Path(tempfile.gettempdir()).resolve()\n"
        "    assert temporary_root.parent == private_root, 'TEST TEMP ROOT NOT PRIVATE'\n"
        "    assert not actual_home.is_relative_to(temporary_root), 'TEST TEMP AND STATE OVERLAP'\n"
    )
    environment = os.environ.copy()
    environment["DRAWBRIDGE_TEST_FAKE_SECRET"] = "synthetic-only-value"
    foreign_home = tmp_path / "foreign-home"
    foreign_home.mkdir()
    environment["HOME"] = str(foreign_home)
    interpreter = ROOT / ".venv/bin/python"
    original_interpreter = interpreter.resolve(strict=True)
    completed = subprocess.run(
        [str(ROOT / "bin/test"), str(probe), "-q", "-n", "0"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert interpreter.is_file() and interpreter.resolve() == original_interpreter, (
        "TEST RUNTIME CHANGED"
    )


def test_parallel_workers_do_not_rebuild_each_others_script_environments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import conftest

    private_root = tmp_path / "private-uv"
    monkeypatch.setenv("DRAWBRIDGE_TEST_UV_CACHE_ROOT", str(private_root))
    monkeypatch.setenv("UV_CACHE_DIR", "unowned-cache")
    selected = []
    for worker in ("gw0", "gw1"):
        conftest.pytest_configure(SimpleNamespace(workerinput={"workerid": worker}))
        selected.append(Path(os.environ["UV_CACHE_DIR"]).resolve())
    assert selected[0] != selected[1], "SCRIPT CACHES SHARED BETWEEN WORKERS"
    assert all(private_root.resolve() in p.parents for p in selected), (
        "SCRIPT CACHE ESCAPED PRIVATE ROOT"
    )
