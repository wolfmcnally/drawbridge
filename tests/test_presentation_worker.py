"""Actual OS controls; one bounded native child, no external service."""

from __future__ import annotations

import errno
import json
import platform
import subprocess
import sys
from pathlib import Path

import pytest

from drawbridge.presentation_worker import _mac_profile


def test_native_presentation_boundary_denies_socket_and_private_file(tmp_path):
    work = tmp_path / "job"
    work.mkdir()
    secret = tmp_path / "outside-job"
    secret.write_text("synthetic noncredential sentinel")
    code = """
import errno,json,socket,sys
from pathlib import Path
try:
    with socket.socket() as handle:
        network = handle.connect_ex(('127.0.0.1',9))
except OSError as exc:
    network = exc.errno
private = None
if sys.platform == 'darwin':
    try:
        Path(sys.argv[1]).read_bytes()
        private = 0
    except OSError as exc:
        private = exc.errno
print(json.dumps({'network':network,'private':private}))
"""
    system = platform.system()
    if system == "Darwin":
        profile = work / "parser.sb"
        profile.write_text(_mac_profile(work))
        argv = [
            "/usr/bin/sandbox-exec",
            "-f",
            str(profile),
            sys.executable,
            "-I",
            "-B",
            "-c",
            code,
            str(secret),
        ]
    elif system == "Linux":
        # Linux promises syscall/network isolation, not filesystem isolation.
        root = str(Path(__file__).resolve().parents[1] / "src")
        setup = (
            "import sys;sys.path.insert(0,"
            + repr(root)
            + ");from drawbridge.presentation_worker import _linux_network_filter;"
            "_linux_network_filter();"
        )
        argv = [sys.executable, "-I", "-B", "-c", setup + code, str(secret)]
    else:
        from drawbridge import ConversionOptions
        from drawbridge.presentations import PresentationUnavailable, presentation_mirror

        with pytest.raises(PresentationUnavailable, match="unavailable on this platform"):
            presentation_mirror(secret, ConversionOptions())
        return
    result = subprocess.run(
        argv,
        cwd=work,
        env={"HOME": str(work), "TMPDIR": str(work), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=10,
        close_fds=True,
    )
    assert result.returncode == 0, result.stderr
    observation = json.loads(result.stdout)
    assert observation["network"] in {errno.EPERM, errno.EACCES}, "native socket denial"
    if system == "Darwin":
        assert observation["private"] in {errno.EPERM, errno.EACCES}, "private file denial"


@pytest.mark.parametrize("mode", ["startup", "cpu-signal", "reader-exit"])
def test_native_child_terminal_state_keeps_its_failure_class(tmp_path, monkeypatch, mode):
    from pptx import Presentation

    from drawbridge import ConversionOptions, presentation_worker
    from drawbridge.errors import ConversionOperationalError
    from drawbridge.presentations import (
        PresentationLimitError,
        PresentationUnavailable,
        presentation_mirror,
    )

    source = tmp_path / "source.pptx"
    deck = Presentation()
    deck.slides.add_slide(deck.slide_layouts[6])
    deck.save(source)
    real_launch = presentation_worker.subprocess.Popen

    def launch(argv, **kwargs):
        assert Path(argv[-3]).name == "presentation_worker.py"
        assert Path(argv[-2]).read_bytes() == source.read_bytes(), (
            "copied real source reached launch"
        )
        helper = Path(kwargs["cwd"]) / "terminal-probe.py"
        code = "import os,signal,sys,resource\nresource.setrlimit(resource.RLIMIT_CORE,(0,0))\n"
        if mode != "startup":
            code += 'sys.stdout.buffer.write(b\'{"status":"ready"}\\n\');sys.stdout.flush()\n'
        if mode == "cpu-signal":
            code += "os.kill(os.getpid(),signal.SIGXCPU)\n"
        else:
            code += "raise SystemExit(2)\n"
        helper.write_text(code)
        changed = list(argv)
        changed[-3] = str(helper)
        return real_launch(changed, **kwargs)

    monkeypatch.setattr(presentation_worker.subprocess, "Popen", launch)
    expected = {
        "startup": PresentationUnavailable,
        "cpu-signal": PresentationLimitError,
        "reader-exit": ConversionOperationalError,
    }[mode]
    with pytest.raises(expected) as caught:
        presentation_mirror(source, ConversionOptions())
    assert type(caught.value) is expected, "native child failure classification"
