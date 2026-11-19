"""Read complete document jobs from an independently installed Vellric CLI.

This module imports no Vellric/PDF engine.
The documented JSON/text artifacts, not Python objects, form the boundary.
"""

from __future__ import annotations

import json
import math
import os
import re
import selectors
import signal
import subprocess
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

SCHEMA = "vellric.document/1.1"
STATUS = "vellric.status/1.0"
BEHAVIOR = "drawbridge-0.4.3-pymupdf-1.28.2/v1"
DEFAULT_MAX_PAGES = 10_000
DEFAULT_MAX_OUTPUT_BYTES = 2 * 1024**3
MAX_MANIFEST_BYTES = 64 * 1024**2


class VellricOperationLimit(ConversionOperationalError):
    """A finite working limit of the current complete-job protocol."""


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


def configured_limit(name: str) -> int | float | None:
    from .configuration import current_configuration

    limit = current_configuration().vellric.limits.get(name.lower())
    if limit is not None:
        return limit
    raw = os.environ.get("DRAWBRIDGE_VELLRIC_" + name)
    if raw is None:
        return None
    try:
        value = float(raw)
        if not math.isfinite(value) or not 0 < value <= 2**63 - 1:
            raise ValueError()
    except (ValueError, OverflowError) as exc:
        raise ConverterUnavailable("Invalid Vellric limit configuration: " + name) from exc
    if name == "TIMEOUT_SECONDS":
        return value
    if not value.is_integer():
        raise ConverterUnavailable("Vellric integer limit configuration required: " + name)
    return int(value)


def configured_number(name: str, default: float) -> float:
    return configured_limit(name) or default


def configured_tessdata() -> Path | str | None:
    from .configuration import current_configuration

    return (
        current_configuration().vellric.tessdata_dir
        or os.environ.get("DRAWBRIDGE_VELLRIC_TESSDATA_DIR")
        or os.environ.get("TESSDATA_PREFIX")
    )


def configured_options(options: tuple[str, ...], *, command: str = "convert") -> tuple[str, ...]:
    from .configuration import current_configuration

    result = list(options)
    for name, flag in [
        ("MEMORY_MIB", "--memory-mib"),
        ("MAX_INPUT_BYTES", "--max-input-bytes"),
        ("MAX_OUTPUT_BYTES", "--max-output-bytes"),
        ("MAX_PAGES", "--max-pages"),
    ]:
        if flag not in result and (number := configured_limit(name)) is not None:
            result += [flag, str(number)]
    data = configured_tessdata()
    if command == "convert" and data and "--tessdata-dir" not in result:
        result += ["--tessdata-dir", str(Path(data).resolve())]
    if command == "convert":
        result += current_configuration().convert_options()
    return tuple(result)


def executable() -> str:
    from .configuration import current_configuration, executable_path

    configured = current_configuration().vellric.executable or os.environ.get("DRAWBRIDGE_VELLRIC")
    # A relative value was accepted for standalone invocations before explicit configuration.
    if configured and not current_configuration().files:
        configured = Path(configured).absolute()
    found = executable_path("vellric", configured)
    if not found:
        raise ConverterUnavailable(
            "Vellric CLI unavailable; install it independently or select its executable "
            "with drawbridge.vellric.executable or DRAWBRIDGE_VELLRIC"
        )
    return str(Path(found).resolve())


def _environment(exe: str, work: Path) -> dict[str, str]:
    from .configuration import child_environment, current_configuration

    environment = child_environment(work)
    if current_configuration().paths.path is None:
        environment["PATH"] = str(Path(exe).parent) + ":/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
    return environment


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
            cwd=work,
            close_fds=True,
            start_new_session=True,
        )
    except OSError as exc:
        raise ConverterUnavailable("Vellric CLI could not be started") from exc
    output = bytearray()
    pending = bytearray()
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
                        pending.extend(data)
                        if len(pending) > 128 * 1024:
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
    if code == "resource-limit":
        raise VellricOperationLimit(f"Vellric per-operation guard: {message}")
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

    @property
    def anchors(self) -> tuple[str, ...]:
        return tuple(p["anchor"] for p in self.manifest["pages"])


def validate_bundle(
    root: Path, manifest: dict, *, job: str, source_hash: str, source_size: int,
    max_pages: int = DEFAULT_MAX_PAGES, max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
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
            raise ValueError("unsupported complete manifest; rerun from the retained original with Vellric 0.2.4")
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
        if type(count) is int and count > max_pages:
            raise VellricOperationLimit("Vellric per-operation guard: page records exceed the complete-job limit")
        if (
            type(count) is not int
            or count < 1
            or len(pages) != count
            or any(page["number"] != index for index, page in enumerate(pages, 1))
        ):
            raise ValueError("page count/order mismatch")
        from .citations import CITATIONS, anchor

        if job == "image":
            if "page_citations" in manifest or any("anchor" in p for p in pages):
                raise ValueError("PDF citations on image job")
        else:
            if manifest.get("page_citations") != CITATIONS:
                raise ValueError("missing or unsupported PDF citations")
            for number, page in enumerate(pages, 1):
                if type(page.get("number")) is not int or page.get("anchor") != anchor(source_hash, number):
                    raise ValueError("invalid original PDF page anchor")
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
            if type(size) is not int or size < 0 or not p.is_file() or p.stat().st_size != size:
                raise ValueError("artifact size mismatch")
            total += size
            if total > max_output_bytes:
                raise VellricOperationLimit("Vellric per-operation guard: output exceeds the complete-job limit")
            if sha256_file(p) != entry["sha256"]:
                raise ValueError("artifact digest mismatch")
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
        has_native_text = False
        for page in pages:
            native = bundle.text(page, "native")
            final = bundle.text(page)
            has_native_text |= bool(native.strip())
            if page["method"] == "pymupdf-text" and final != native:
                raise ValueError("native text changed")
        inspection = manifest["inspection"]
        if inspection.get("page_count") != count or inspection.get("openable") is not True:
            raise ValueError("invalid complete inspection")
        if (
            any(type(inspection.get(key)) is not bool for key in ("is_encrypted", "needs_password"))
            or inspection["needs_password"]
        ):
            raise ValueError("invalid complete encryption inspection")
        if inspection.get("has_text_layer") is not has_native_text:
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
        return bundle
    except (
        KeyError,
        TypeError,
        ValueError,
        AttributeError,
        OSError,
        UnicodeError,
    ) as exc:
        raise ConversionOperationalError("Vellric artifacts failed independent validation; rerun a complete job from the retained original with qualified Vellric 0.2.4") from exc


_DOCTOR_CACHE: dict[tuple, bool] = {}


def _configuration_supported(doctor: dict) -> bool:
    version = doctor["tool"].get("version")
    if not isinstance(version, str) or len(version) > 32:
        return False
    if not re.fullmatch(r"(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})", version):
        return False
    return tuple(int(part) for part in version.split(".")) >= (0, 2, 2)


def _check_doctor(exe: str, work: Path, require_configuration: bool = False) -> None:
    facts = Path(exe).stat()
    identity = (exe, facts.st_ino, facts.st_size, facts.st_mtime_ns)
    if identity in _DOCTOR_CACHE:
        if require_configuration and not _DOCTOR_CACHE[identity]:
            raise ConverterUnavailable("Explicit configuration requires Vellric 0.2.2 or newer with a stable numeric doctor version")
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
        raise ConverterUnavailable("Vellric CLI schema/behavior is unsupported; install qualified Vellric 0.2.4 and rerun from the retained original")
    if len(_DOCTOR_CACHE) >= 32:
        _DOCTOR_CACHE.pop(next(iter(_DOCTOR_CACHE)))
    supported = _configuration_supported(doctor)
    _DOCTOR_CACHE[identity] = supported
    if require_configuration and not supported:
        raise ConverterUnavailable("Explicit configuration requires Vellric 0.2.2 or newer with a stable numeric doctor version")


def _job_limit(options: tuple[str, ...], flag: str, default: int) -> int:
    if flag not in options:
        return default
    try:
        value = int(options[options.index(flag) + 1])
        if value <= 0:
            raise ValueError()
        return value
    except (IndexError, ValueError) as exc:
        raise ConversionOperationalError(f"Invalid Vellric per-operation limit {flag}") from exc


def _read_manifest(path: Path) -> dict:
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(data) > MAX_MANIFEST_BYTES:
            raise VellricOperationLimit("Vellric per-operation guard: manifest exceeds the complete-job read limit")
        return _json(data.decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        raise ConversionOperationalError("Vellric manifest is missing or invalid") from None


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
    max_pages = _job_limit(options, "--max-pages", DEFAULT_MAX_PAGES)
    max_output = _job_limit(options, "--max-output-bytes", DEFAULT_MAX_OUTPUT_BYTES)
    exe = executable()
    from .configuration import temporary_directory

    with temporary_directory("drawbridge-vellric-") as directory:
        work = Path(directory).resolve()
        root = work / "result"
        if command == "convert" and ("--config" in options or "--config-root" in options):
            _check_doctor(exe, work, True)
        else:
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
            if code == "usage" and status.get("stage") == "settings":
                from .configuration import ConfigurationError, current_configuration

                if current_configuration().files:
                    raise ConfigurationError("Vellric rejected its configuration; check the independently installed CLI's leaf schema and unresolved references")
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
        bundle = validate_bundle(
            root,
            _read_manifest(root / "manifest.json"),
            job=command,
            source_hash=source_hash,
            source_size=source_size,
            max_pages=max_pages,
            max_output_bytes=max_output,
        )
        if status.get("page_count") != bundle.manifest["page_count"]:
            raise ConversionOperationalError("Vellric terminal/manifest count mismatch")
        yield bundle
