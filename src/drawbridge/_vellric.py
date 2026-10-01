"""Read complete document jobs from an independently installed Vellric CLI.

This module uses only the standard library and imports no Vellric/PDF engine.
The documented JSON/text artifacts, not Python objects, form the boundary.
"""

from __future__ import annotations

import json
import math
import os
import selectors
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .errors import (
    ConversionOperationalError,
    ConverterUnavailable,
    OcrOperationalError,
    OcrPreflightError,
)
from .mirror import sha256_file as _mirror_sha256_file
from .progress import advance

SCHEMA = "vellric.document/1.0"
STATUS = "vellric.status/1.0"
BEHAVIOR = "drawbridge-0.4.3-pymupdf-1.28.2/v1"


def sha256_file(path: Path) -> str:
    from .pdf_tools import PdfOpenOperationalError

    try:
        return _mirror_sha256_file(path).removeprefix("sha256:")
    except OSError as exc:
        raise PdfOpenOperationalError("PDF source could not be hashed") from exc


def _json(value: str):
    def refuse(constant):
        raise ValueError("non-finite JSON")

    def pairs(entries):
        result = {}
        for key, item in entries:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = item
        return result

    return json.loads(value, parse_constant=refuse, object_pairs_hook=pairs)


def configured_number(name: str, default: float) -> float:
    raw = os.environ.get("DRAWBRIDGE_VELLRIC_" + name)
    if raw is None:
        return default
    try:
        value = float(raw)
        if not math.isfinite(value) or value <= 0:
            raise ValueError()
        return value
    except ValueError as exc:
        raise ConverterUnavailable("Invalid Vellric limit configuration: " + name) from exc


def configured_options(options: tuple[str, ...], *, command: str = "convert") -> tuple[str, ...]:
    result = list(options)
    for name, flag in [
        ("MEMORY_MIB", "--memory-mib"),
        ("MAX_INPUT_BYTES", "--max-input-bytes"),
        ("MAX_OUTPUT_BYTES", "--max-output-bytes"),
        ("MAX_PAGES", "--max-pages"),
    ]:
        if "DRAWBRIDGE_VELLRIC_" + name in os.environ and flag not in result:
            number = configured_number(name, 1)
            if not number.is_integer():
                raise ConverterUnavailable("Vellric integer limit configuration required: " + name)
            result += [flag, str(int(number))]
    data = os.environ.get("DRAWBRIDGE_VELLRIC_TESSDATA_DIR") or os.environ.get("TESSDATA_PREFIX")
    if command == "convert" and data and "--tessdata-dir" not in result:
        result += ["--tessdata-dir", str(Path(data).resolve())]
    return tuple(result)


def executable() -> str:
    configured = os.environ.get("DRAWBRIDGE_VELLRIC")
    found = configured or shutil.which("vellric")
    if not found or not Path(found).is_file() or not os.access(found, os.X_OK):
        raise ConverterUnavailable(
            "Vellric CLI unavailable; install it independently or set DRAWBRIDGE_VELLRIC "
            "to its executable"
        )
    return str(Path(found).resolve())


def _environment(exe: str, work: Path) -> dict[str, str]:
    # No provider credentials, Python/loader injection, account home or plugins.
    return {
        "PATH": str(Path(exe).parent) + ":/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        "HOME": str(work),
        "TMPDIR": str(work),
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "OMP_THREAD_LIMIT": "1",
    }


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()  # Allow the CLI supervisor to clean its own worker group.
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def _run(argv: list[str], work: Path, timeout: float) -> tuple[int, str]:
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_environment(argv[0], work),
            start_new_session=True,
        )
    except OSError as exc:
        raise ConverterUnavailable("Vellric CLI could not be started") from exc
    output = bytearray()
    pending = bytearray()
    stderr_size = 0
    try:
        with selectors.DefaultSelector() as selector:
            for stream in (process.stdout, process.stderr):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            while selector.get_map():
                if time.monotonic() - started > timeout:
                    raise ConversionOperationalError("Vellric document job timed out")
                for key, _ in selector.select(timeout=0.1):
                    data = os.read(key.fileobj.fileno(), 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    if key.fileobj is process.stdout:
                        output.extend(data)
                        if len(output) > 1024 * 1024:
                            raise ConversionOperationalError(
                                "Vellric terminal output exceeds protocol limit"
                            )
                    else:
                        stderr_size += len(data)
                        pending.extend(data)
                        if stderr_size > 16 * 1024 * 1024 or len(pending) > 128 * 1024:
                            raise ConversionOperationalError(
                                "Vellric progress exceeds protocol limit"
                            )
                        while b"\n" in pending:
                            line, _, rest = pending.partition(b"\n")
                            pending[:] = rest
                            try:
                                event = _json(line.decode("utf-8"))
                            except (ValueError, UnicodeError):
                                continue  # Diagnostics are not terminal status or error authority.
                            if (
                                isinstance(event, dict)
                                and event.get("schema") == "vellric.progress/1.0"
                            ):
                                done, total = event.get("done"), event.get("total")
                                if (
                                    event.get("stage") == "recognition"
                                    and type(done) is int
                                    and type(total) is int
                                    and 0 <= done <= total
                                ):
                                    advance("recognition", done, total)
            return process.wait(
                timeout=max(1.0, timeout - (time.monotonic() - started))
            ), output.decode("utf-8")
    except (OSError, UnicodeError, subprocess.SubprocessError) as exc:
        raise ConversionOperationalError(
            "Vellric document job did not return a usable protocol result"
        ) from exc
    finally:
        _stop(process)
        process.stdout.close()
        process.stderr.close()


def _failure(status: dict, returncode: int) -> None:
    from .pdf_tools import (
        DegeneratePdfError,
        EncryptedPdfError,
        MalformedPdfError,
        PdfInspection,
        PdfOpenOperationalError,
        PdfReadOperationalError,
    )

    code = status.get("code")
    message = status.get("message") or f"Vellric job failed ({code})"
    details = status.get("details") or {}
    if not isinstance(details, dict) or not isinstance(message, str):
        raise ConversionOperationalError("Vellric returned malformed failure details")
    raw = details.get("inspection") if isinstance(details, dict) else None
    partial = None
    if isinstance(raw, dict):
        partial = PdfInspection(
            raw.get("openable", False),
            raw.get("is_encrypted"),
            raw.get("needs_password"),
            raw.get("page_count"),
            raw.get("has_text_layer"),
            None,
        )
    if code == "password-protected":
        raise EncryptedPdfError(message, partial)
    if code == "degenerate-input":
        raise DegeneratePdfError(message, partial)
    if code in {"not-pdf", "malformed-pdf"}:
        raise MalformedPdfError(message, partial)
    if code == "pdf-open-operational":
        raise PdfOpenOperationalError(message)
    if code == "pdf-read-operational":
        raise PdfReadOperationalError(
            message, partial or PdfInspection(True, None, None, None, None, None)
        )
    if code == "dependency-unavailable":
        if status.get("stage") in {"preflight", "recognition", "ocr"}:
            raise OcrOperationalError(message)
        raise ConverterUnavailable(message)
    if code == "ocr-preflight-refused":
        raise OcrPreflightError(
            message,
            returncode=details.get("backend_returncode", returncode),
            stderr=details.get("backend_stderr", ""),
        )
    if code == "ocr-operational" or (
        code == "deadline" and status.get("stage") in {"preflight", "recognition", "ocr"}
    ):
        raise OcrOperationalError(message)
    raise ConversionOperationalError(message)


@dataclass(frozen=True)
class Bundle:
    root: Path
    manifest: dict

    def text(self, page: dict, kind: str = "text") -> str:
        return (self.root / page["files"][kind]).read_bytes().decode("utf-8")

    @property
    def texts(self) -> tuple[str, ...]:
        return tuple(self.text(p) for p in self.manifest["pages"])


def validate_bundle(
    root: Path, manifest: dict, *, job: str, source_hash: str, source_size: int
) -> Bundle:
    """Independently validate custody before using a CLI artifact; no engine import."""
    try:
        if not isinstance(manifest, dict):
            raise ValueError("manifest is not an object")
        if (
            manifest.get("schema") != SCHEMA
            or manifest.get("status") != "complete"
            or manifest.get("job") != job
            or manifest.get("behavior") != BEHAVIOR
        ):
            raise ValueError("unsupported complete manifest")
        if (
            manifest.get("tool", {}).get("name") != "vellric"
            or manifest.get("engines", {}).get("pymupdf") != "1.28.2"
        ):
            raise ValueError("unqualified tool/engine")
        fingerprint = manifest["provenance"]["processing_fingerprint"]
        if (
            not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or any(c not in "0123456789abcdef" for c in fingerprint)
        ):
            raise ValueError("invalid processing identity")
        source = manifest["source"]
        if source.get("sha256") != source_hash or source.get("size") != source_size:
            raise ValueError("source identity mismatch")
        count = manifest["page_count"]
        pages = manifest["pages"]
        if (
            type(count) is not int
            or not 1 <= count <= 10000
            or len(pages) != count
            or [p["number"] for p in pages] != list(range(1, count + 1))
        ):
            raise ValueError("page count/order mismatch")
        if type(manifest.get("outstanding_candidates")) is not list or any(
            type(n) is not int or not 1 <= n <= count for n in manifest["outstanding_candidates"]
        ):
            raise ValueError("invalid recognition completeness")
        seen = set()
        total = 0
        for entry in manifest["files"]:
            name = entry["path"]
            rel = PurePosixPath(name)
            if (
                not isinstance(name, str)
                or not name
                or rel.is_absolute()
                or ".." in rel.parts
                or "\\" in name
                or str(rel) != name
                or name in seen
            ):
                raise ValueError("unsafe artifact path")
            seen.add(name)
            p = root
            for part in rel.parts:
                p = p / part
                if p.is_symlink():
                    raise ValueError("artifact symlink")
            size = entry["size"]
            total += size
            if (
                type(size) is not int
                or size < 0
                or total > 2 * 1024**3
                or not p.is_file()
                or p.stat().st_size != size
                or sha256_file(p) != entry["sha256"]
            ):
                raise ValueError("artifact size/digest mismatch")
        if any(p.is_symlink() for p in root.rglob("*")):
            raise ValueError("artifact symlink")
        actual = {
            str(p.relative_to(root))
            for p in root.rglob("*")
            if p.is_file() and p != root / "manifest.json"
        }
        if seen != actual or root.is_symlink():
            raise ValueError("unlisted artifacts")
        if not {"document.txt", "document.md"} <= seen:
            raise ValueError("missing complete document artifacts")
        for page in pages:
            if type(page.get("number")) is not int:
                raise ValueError("invalid page number")
            if (
                page.get("method")
                not in ({"native-image"} if job == "image" else {"pymupdf-text", "ocr"})
                or type(page.get("ocr_candidate")) is not bool
            ):
                raise ValueError("invalid page record")
            geometry = page["geometry"]
            rect = geometry["displayed_rect"]
            if (
                not isinstance(rect, list)
                or len(rect) != 4
                or any(type(v) not in {int, float} or not math.isfinite(v) for v in rect)
                or rect[2] <= rect[0]
                or rect[3] <= rect[1]
            ):
                raise ValueError("invalid displayed page geometry")
            for render in page.get("renders", []):
                if render["path"] not in seen:
                    raise ValueError("unlisted render artifact")
            coverage = page["raster_coverage"]
            if (
                not isinstance(coverage, (int, float))
                or isinstance(coverage, bool)
                or not math.isfinite(coverage)
                or coverage < 0
            ):
                raise ValueError("invalid raster coverage")
            for kind in ["native", "text"]:
                if page["files"].get(kind) not in seen:
                    raise ValueError("missing page text")
            for name in page["files"].values():
                if name not in seen:
                    raise ValueError("unlisted page artifact")
            if page["method"] == "ocr":
                record = page["ocr"]
                if (
                    type(record.get("page")) is not int
                    or record["page"] != page["number"]
                    or type(record.get("bands")) is not int
                    or record["bands"] < 1
                    or record.get("rotation") not in {0, 90, 180, 270}
                ):
                    raise ValueError("invalid recognition record")
                score = record["score"]
                if type(score) not in {int, float} or not math.isfinite(score) or score < 0:
                    raise ValueError("invalid recognition score")
        bundle = Bundle(root, manifest)
        native = tuple(bundle.text(p, "native") for p in pages)
        bundle.texts
        inspection = manifest["inspection"]
        if inspection.get("page_count") != count or inspection.get("openable") is not True:
            raise ValueError("invalid complete inspection")
        if (
            any(type(inspection.get(key)) is not bool for key in ("is_encrypted", "needs_password"))
            or inspection["needs_password"]
        ):
            raise ValueError("invalid complete encryption inspection")
        if inspection.get("has_text_layer") is not any(text.strip() for text in native):
            raise ValueError("native inspection contradicts page text")
        selected = {p["number"] for p in pages if p["method"] == "ocr"}
        outstanding = set(manifest["outstanding_candidates"])
        expected_recognition = (
            "unrecognized-candidates"
            if outstanding
            else "complete"
            if selected
            else "not-requested"
        )
        if manifest.get("recognition_completeness") != expected_recognition:
            raise ValueError("invalid recognition status")
        if outstanding != {
            p["number"] for p in pages if p["ocr_candidate"] and p["number"] not in selected
        }:
            raise ValueError("outstanding OCR mismatch")
        if job != "convert" and selected:
            raise ValueError("unexpected recognition")
        for page in pages:
            if page["method"] == "pymupdf-text" and bundle.text(page) != native[page["number"] - 1]:
                raise ValueError("native text changed")
        return bundle
    except (
        KeyError,
        TypeError,
        ValueError,
        AttributeError,
        OSError,
        UnicodeError,
    ) as exc:
        raise ConversionOperationalError("Vellric artifacts failed independent validation") from exc


_DOCTOR_CACHE: dict[tuple, None] = {}


def _check_doctor(exe: str, work: Path) -> None:
    facts = Path(exe).stat()
    identity = (exe, facts.st_ino, facts.st_size, facts.st_mtime_ns)
    if identity in _DOCTOR_CACHE:
        return
    try:
        rc, out = _run([exe, "doctor", "--json"], work, 90)
    except ConversionOperationalError as exc:
        raise ConverterUnavailable("Vellric capability diagnosis failed: " + str(exc)) from exc
    try:
        doctor = _json(out)
    except (ValueError, TypeError):
        raise ConverterUnavailable("Vellric capability diagnosis is invalid") from None
    if (
        rc != 0
        or not isinstance(doctor, dict)
        or doctor.get("schema") != SCHEMA
        or doctor.get("behavior") != BEHAVIOR
        or not isinstance(doctor.get("tool"), dict)
        or doctor["tool"].get("name") != "vellric"
    ):
        raise ConverterUnavailable("Vellric CLI schema/behavior is unsupported")
    if len(_DOCTOR_CACHE) >= 32:
        _DOCTOR_CACHE.pop(next(iter(_DOCTOR_CACHE)))
    _DOCTOR_CACHE[identity] = None


@contextmanager
def document_job(
    source: Path,
    command: str,
    *options: str,
    timeout: float | None = None,
    expected_sha256: str | None = None,
) -> Iterator[Bundle]:
    source = Path(source)
    timeout = timeout if timeout is not None else configured_number("TIMEOUT_SECONDS", 3600)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("document timeout must be finite and positive")
    options = configured_options(options, command=command)
    source_hash = expected_sha256 or sha256_file(source)
    from .pdf_tools import PdfOpenOperationalError

    try:
        source_size = source.stat().st_size
    except OSError as exc:
        raise PdfOpenOperationalError("PDF source could not be inspected") from exc
    exe = executable()
    with tempfile.TemporaryDirectory(prefix="drawbridge-vellric-") as directory:
        work = Path(directory).resolve()
        root = work / "result"
        _check_doctor(exe, work)
        argv = [
            exe,
            command,
            str(source.resolve()),
            "--out",
            str(root),
            "--schema",
            "1",
            "--expected-sha256",
            source_hash,
            "--status-json",
            "--progress",
            "json",
            "--timeout-seconds",
            str(timeout),
            *map(str, options),
        ]
        rc, out = _run(argv, work, timeout + 10)
        try:
            status = _json(out)
        except (ValueError, TypeError):
            raise ConversionOperationalError(
                "Vellric terminal status is missing or invalid"
            ) from None
        if not isinstance(status, dict) or status.get("schema") != STATUS:
            raise ConversionOperationalError("Vellric terminal schema is unsupported")
        if rc:
            if status.get("status") not in {"blocked", "failed"} or status.get("code") in {
                None,
                "complete",
            }:
                raise ConversionOperationalError("Vellric failure status contradicts its exit code")
            code = status.get("code")
            expected_exit = (
                2
                if code == "usage"
                else 3
                if code in {"password-protected", "degenerate-input"}
                else 4
                if code
                in {
                    "not-pdf",
                    "malformed-pdf",
                    "pdf-open-operational",
                    "pdf-read-operational",
                    "source-hash-mismatch",
                }
                else 5
            )
            expected_state = "blocked" if expected_exit == 3 else "failed"
            if rc != expected_exit or status.get("status") != expected_state:
                raise ConversionOperationalError(
                    "Vellric typed failure contradicts its exit/status"
                )
            _failure(status, rc)
        if (
            status.get("status") != "complete"
            or status.get("code") != "complete"
            or status.get("source_sha256") != source_hash
        ):
            raise ConversionOperationalError("Vellric completion status is inconsistent")
        if sha256_file(source) != source_hash:
            raise ConversionOperationalError("Source changed during the Vellric job")
        if root.is_symlink() or (root / "manifest.json").is_symlink():
            raise ConversionOperationalError("Vellric manifest symlink refused")
        try:
            manifest = _json((root / "manifest.json").read_text())
        except (OSError, ValueError, UnicodeError):
            raise ConversionOperationalError("Vellric manifest is missing or invalid") from None
        bundle = validate_bundle(
            root,
            manifest,
            job=command,
            source_hash=source_hash,
            source_size=source_size,
        )
        if status.get("page_count") != manifest["page_count"]:
            raise ConversionOperationalError("Vellric terminal/manifest count mismatch")
        yield bundle
