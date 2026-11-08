"""One presentation job: private bytes, bounded output, actual OS network denial.

Linux denies network/child-creation syscalls; it is not a filesystem sandbox.
macOS uses a generated Seatbelt read allowlist and a sampled RSS watchdog. RSS
sampling cannot promise a zero-overshoot allocation ceiling. No fallback runs
an uncontained parser when a required control is unavailable.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import platform
import selectors
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "drawbridge"

DEADLINE = 60.0
MEMORY = 2 * 1024**3
OUTPUT = 16 * 1024**2
READY_FRAME = b'{"status":"ready"}'


def _linux_network_filter() -> None:
    """Install classic BPF through libc; no libseccomp or executable dependency."""

    class Instruction(ctypes.Structure):
        _fields_ = [
            ("code", ctypes.c_ushort),
            ("jt", ctypes.c_ubyte),
            ("jf", ctypes.c_ubyte),
            ("k", ctypes.c_uint),
        ]

    class Program(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.POINTER(Instruction))]

    machine = platform.machine().lower()
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        raise OSError("unsupported presentation worker ABI")
    if machine == "x86_64":
        architecture = 0xC000003E
        refused = [41, 53, 56, 57, 58, 59, 322, 425, 426, 427, 435]
    elif machine in {"aarch64", "arm64"}:
        architecture = 0xC00000B7
        refused = [198, 199, 220, 221, 281, 425, 426, 427, 435]
    else:
        raise OSError("unsupported presentation worker architecture")
    # seccomp_data.arch, then syscall number; unknown ABIs and x32 fail closed.
    rows = [
        (0x20, 0, 0, 4),
        (0x15, 1, 0, architecture),
        (0x06, 0, 0, 0x80000000),
        (0x20, 0, 0, 0),
        (0x35, 0, 1, 0x40000000),
        (0x06, 0, 0, 0x00050000 | errno.EPERM),
    ]
    for number in refused:
        rows.extend([(0x15, 0, 1, number), (0x06, 0, 0, 0x00050000 | errno.EPERM)])
    rows.append((0x06, 0, 0, 0x7FFF0000))
    code = (Instruction * len(rows))(*(Instruction(*row) for row in rows))
    program = Program(len(rows), code)
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.restype = ctypes.c_int
    if libc.prctl(38, 1, 0, 0, 0) or libc.prctl(22, 2, ctypes.byref(program), 0, 0):
        raise OSError(ctypes.get_errno(), "presentation network filter unavailable")


def _mac_profile(work: Path) -> str:
    reads = {
        Path(sys.base_prefix).resolve(),
        Path(sys.prefix).resolve(),
        Path(__file__).resolve().parent,
        work.resolve(),
        Path("/usr"),
        Path("/System"),
        Path("/Library/Apple/System"),
    }
    allow = " ".join(
        "(subpath " + json.dumps(str(p), ensure_ascii=False) + ")" for p in sorted(reads)
    )
    return (
        '(version 1)(deny default)(import "dyld-support.sb")'
        "(allow process-exec)(allow sysctl-read)"
        "(allow file-read-metadata)(allow file-read-data file-map-executable " + allow + ")"
        "(allow file-read-data (literal "
        + json.dumps(str(Path(__file__).resolve().parent.parent))
        + "))"
        '(allow file-read-data (literal "/dev/urandom") (literal "/dev/null") '
        '(literal "/dev/zero") (literal "/private/etc/localtime"))'
    )


def _rss(pid: int) -> int:
    """Darwin rusage_info_v0 resident size; caller handles process-exit races."""

    class Usage(ctypes.Structure):
        _fields_ = [("uuid", ctypes.c_ubyte * 16)] + [
            (name, ctypes.c_uint64)
            for name in (
                "user",
                "system",
                "idle",
                "interrupt",
                "pageins",
                "wired",
                "resident",
                "footprint",
                "start",
                "exit",
            )
        ]

    usage = Usage()
    libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    libproc.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    libproc.proc_pid_rusage.restype = ctypes.c_int
    if libproc.proc_pid_rusage(pid, 0, ctypes.byref(usage)):
        raise OSError(ctypes.get_errno(), "presentation RSS query failed")
    return usage.resident


def _stop(process: subprocess.Popen) -> None:
    # This worker has no child supervisor or protocol cleanup to await.
    if process.poll() is not None:
        return  # Never signal a reaped leader's potentially reused process group.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=2)
    # Native controls deny fork before input parsing. There are no untrusted
    # descendants to signal after wait() releases the leader's process identity.


def _unique(items):
    result = dict(items)
    if len(result) != len(items):
        raise ValueError("duplicate presentation result key")
    return result


def run_presentation(source: Path, include_notes: bool) -> tuple[dict, str, int]:
    from .errors import ConversionOperationalError
    from .presentations import (
        MAX_INPUT,
        PresentationError,
        PresentationLimitError,
        PresentationUnavailable,
        UnsupportedPresentation,
    )

    with source.open("rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise PresentationError("presentation input must be a regular file")
        blob = handle.read(MAX_INPUT + 1)
    if len(blob) > MAX_INPUT:
        raise PresentationLimitError("presentation input byte limit exceeded")
    digest, size = hashlib.sha256(blob).hexdigest(), len(blob)
    system = platform.system()
    if system not in {"Darwin", "Linux"}:
        raise PresentationUnavailable("presentation containment is unavailable on this platform")
    with tempfile.TemporaryDirectory(prefix="drawbridge-pptx-") as directory:
        work = Path(directory).resolve()
        snapshot = work / "source.pptx"
        snapshot.write_bytes(blob)
        snapshot.chmod(0o400)
        del blob
        argv = [
            sys.executable,
            "-I",
            "-B",
            str(Path(__file__).resolve()),
            str(snapshot),
            "include" if include_notes else "exclude",
        ]
        if system == "Darwin":
            if not Path("/usr/bin/sandbox-exec").is_file():
                raise PresentationUnavailable("presentation sandbox-exec is unavailable")
            profile = work / "parser.sb"
            profile.write_text(_mac_profile(work))
            argv = ["/usr/bin/sandbox-exec", "-f", str(profile), *argv]
        environment = {
            "HOME": str(work),
            "TMPDIR": str(work),
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "OMP_THREAD_LIMIT": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        }
        try:
            process = subprocess.Popen(
                argv,
                cwd=work,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                start_new_session=True,
            )
        except OSError as exc:
            raise PresentationUnavailable("presentation worker could not start") from exc
        output, diagnostics = bytearray(), bytearray()
        started, next_sample = time.monotonic(), 0.0
        try:
            with selectors.DefaultSelector() as selector:
                for stream in (process.stdout, process.stderr):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ)
                while selector.get_map():
                    now = time.monotonic()
                    if now - started > DEADLINE:
                        raise PresentationLimitError("presentation worker deadline exceeded")
                    if system == "Darwin" and now >= next_sample:
                        try:
                            resident = _rss(process.pid)
                        except OSError as exc:
                            if process.poll() is None:
                                raise PresentationUnavailable(
                                    "presentation memory monitor unavailable"
                                ) from exc
                        else:
                            if resident > MEMORY:
                                raise PresentationLimitError(
                                    "presentation resident-memory watchdog exceeded"
                                )
                        next_sample = now + 0.1
                    for key, _ in selector.select(timeout=0.1):
                        data = os.read(key.fileobj.fileno(), 65536)
                        if not data:
                            selector.unregister(key.fileobj)
                            continue
                        target = output if key.fileobj is process.stdout else diagnostics
                        target.extend(data)
                        if len(output) > OUTPUT or len(diagnostics) > 256 * 1024:
                            raise PresentationLimitError(
                                "presentation worker output limit exceeded"
                            )
                code = process.wait(timeout=max(0.1, DEADLINE - (time.monotonic() - started)))
        except subprocess.TimeoutExpired as exc:
            raise PresentationLimitError("presentation worker deadline exceeded") from exc
        except OSError as exc:
            raise PresentationUnavailable("presentation worker communication failed") from exc
        finally:
            try:
                _stop(process)
            except OSError as exc:
                raise PresentationUnavailable("presentation worker cleanup incomplete") from exc
            process.stdout.close()
            process.stderr.close()
        lines = output.splitlines()
        ready = bool(lines) and lines[0] == READY_FRAME
        if code:
            if code in {-signal.SIGXCPU, -signal.SIGXFSZ}:
                raise PresentationLimitError("presentation native resource limit exceeded")
            if ready:
                raise ConversionOperationalError(
                    "presentation worker terminated unexpectedly after startup"
                )
            raise PresentationUnavailable("presentation containment/runtime startup unavailable")
        try:
            if len(lines) != (2 if ready else 1):
                raise ValueError()
            result = json.loads(lines[-1].decode(), object_pairs_hook=_unique)
            if not isinstance(result, dict):
                raise ValueError()
            if not ready and result.get("status") != "unavailable":
                raise ValueError()
            if not isinstance(result, dict) or result.get("status") not in {
                "ok",
                "malformed",
                "limit",
                "unsupported",
                "unavailable",
            }:
                raise ValueError()
            if result["status"] == "unsupported":
                raise UnsupportedPresentation(result["media_type"], result["reason"])
            if result["status"] in {"limit", "malformed"}:
                reason = result.get("reason", "malformed-package")
                if (
                    not isinstance(reason, str)
                    or not 1 <= len(reason) <= 64
                    or not reason.isascii()
                    or not reason.replace("-", "").isalnum()
                ):
                    raise ValueError()
            if result["status"] == "limit":
                raise PresentationLimitError(
                    "presentation package resource limit exceeded",
                    code=reason,
                )
            if result["status"] == "unavailable":
                raise PresentationUnavailable("presentation required worker control unavailable")
            if result["status"] != "ok":
                raise PresentationError(
                    "presentation package is malformed or unreadable",
                    code=reason,
                )
            payload = result["data"]
            if not isinstance(payload, dict) or set(payload) != {
                "slides",
                "assets",
                "external",
                "custom_shows",
                "deck_features",
            }:
                raise ValueError()
            if any(not isinstance(payload[k], list) for k in payload):
                raise ValueError()
            if not 1 <= len(payload["slides"]) <= 1000:
                raise ValueError()
        except (ValueError, KeyError, UnicodeError) as exc:
            raise ConversionOperationalError("invalid presentation worker result") from exc
        return payload, digest, size


def _main() -> int:
    if len(sys.argv) != 3 or sys.argv[2] not in {"include", "exclude"}:
        return 2
    import resource

    try:
        resource.setrlimit(resource.RLIMIT_CPU, (30, 31))
        resource.setrlimit(resource.RLIMIT_FSIZE, (OUTPUT, OUTPUT))
        if platform.system() == "Linux":
            resource.setrlimit(resource.RLIMIT_AS, (MEMORY, MEMORY))
            _linux_network_filter()
        elif platform.system() != "Darwin":
            raise OSError("unsupported presentation host")
        # An actual C-backed socket operation proves denial before untrusted parsing.
        try:
            with socket.socket() as probe:
                denied = probe.connect_ex(("127.0.0.1", 9)) in {errno.EPERM, errno.EACCES}
        except OSError as exc:
            denied = exc.errno in {errno.EPERM, errno.EACCES}
        if not denied:
            raise OSError("presentation network control is not active")
    except (OSError, ValueError):
        print(json.dumps({"status": "unavailable"}))
        return 0
    # Avoid import-time host MIME databases in office-library dependencies. The
    # package's content-type declarations, not host configuration, own admission.
    import mimetypes

    mimetypes.knownfiles = []
    mimetypes.init(files=[])
    try:
        from .presentations import (
            MAX_INPUT,
            PresentationError,
            PresentationLimitError,
            UnsupportedPresentation,
            _extract,
        )

        for module in ("pptx", "lxml.etree"):
            __import__(module)  # Finish trusted dependency startup before the ready frame.
    except (ImportError, OSError):
        print(json.dumps({"status": "unavailable"}))
        return 0
    print(READY_FRAME.decode(), flush=True)

    try:
        data = Path(sys.argv[1]).read_bytes()
        if len(data) > MAX_INPUT:
            raise PresentationLimitError("input limit")
        result = {"status": "ok", "data": _extract(data, sys.argv[2] == "include")}
    except UnsupportedPresentation as exc:
        result = {"status": "unsupported", "media_type": exc.media_type, "reason": exc.reason}
    except PresentationLimitError as exc:
        result = {"status": "limit", "reason": exc.code}
    except (MemoryError, RecursionError):
        result = {"status": "limit", "reason": "parser-resource-limit"}
    except PresentationError as exc:
        result = {"status": "malformed", "reason": exc.code}
    except (
        ValueError,
        KeyError,
        AttributeError,
        TypeError,
        StopIteration,
        OSError,
    ):
        result = {"status": "malformed"}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
