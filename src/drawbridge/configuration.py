"""Explicit composition and scoped CLI settings; leaf schemas stay with their owners."""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from ipaddress import ip_address
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from conric import ConfigError, SchemaError, SecretRef, load

from .profile import EMPTY_PROFILE, STAGE_NAMES, Profile, ProfileError, parse_profile


class ConfigurationError(ProfileError):
    """Explicit configuration was rejected locally or by the independent CLI."""


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: Any) -> None:
    if isinstance(value, SecretRef):
        raise SchemaError("unresolved_drawbridge_reference")
    if isinstance(value, dict):
        for item in value.values():
            _plain(item)
    elif isinstance(value, list):
        for item in value:
            _plain(item)


def _loopback(url: str | None) -> bool:
    if not isinstance(url, str):
        return False
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or parts.username or parts.password:
            return False
        host = parts.hostname
        if host == "localhost":
            return True
        return bool(host and ip_address(host).is_loopback)
    except ValueError:
        return False


def _profile(value: dict) -> Profile:
    """Reuse the profile schema without emitting private scalars on refusal."""
    # Only a Bedrock bearer key can carry a SecretRef in Drawbridge's leaf.
    endpoints = value.get("endpoints")
    refs = {}
    if isinstance(endpoints, dict):
        endpoints = dict(endpoints)
        for name, item in endpoints.items():
            if isinstance(item, dict) and item.get("kind") == "bedrock-converse" and item.get("transport") == "bearer":
                secret = item.get("api_key_env")
                if isinstance(secret, SecretRef):
                    refs[name] = secret
                    endpoints[name] = {**item, "api_key_env": secret.name}
        value = {**value, "endpoints": endpoints}
    _plain(value)
    try:
        profile = parse_profile(value)
        for endpoint in profile.endpoints.values():
            for item in (endpoint.base_url, endpoint.api_key_env):
                if item is not None and (not isinstance(item, str) or not item):
                    raise ValueError()
            if endpoint.egress == "local" and not _loopback(endpoint.base_url):
                raise SchemaError("local_endpoint_must_be_loopback")
        for name, stage in profile.stages.items():
            endpoint = profile.endpoint_for(name)
            needs_model = endpoint is not None and name != "audio_cleanup"
            if name == "ocr" and stage.get("engine", "tesseract") == "tesseract":
                needs_model = False
            if needs_model and (not isinstance(stage.get("model"), str) or not stage["model"].strip()):
                raise SchemaError("explicit_model_required")
    except SchemaError:
        raise
    except Exception:
        raise SchemaError("invalid_drawbridge_profile") from None
    endpoints = {
        name: replace(endpoint, api_key_env=None, api_key_ref=refs[name]) if name in refs else endpoint
        for name, endpoint in profile.endpoints.items()
    }
    return replace(profile, endpoints=_freeze(endpoints), stages=_freeze(dict(profile.stages)))


_EMPTY_PROFILE = replace(EMPTY_PROFILE, endpoints=MappingProxyType({}), stages=MappingProxyType({}))
_EMPTY = MappingProxyType({})
_CONVERT_DEFAULTS = {
    "out": None, "stdout": False, "title": None, "mirror_of": None,
    "acquired_from": None, "acquired_at": None, "no_ocr": False,
    "skip_preflight": False, "searchable_pdf": None, "tessdata_dir": None,
    "lang": None, "dpi": 300, "workers": 1, "ocr_page_workers": 1, "raster_threshold": 0.5,
    "json": False, "stages": None, "skip": None, "notes": None,
    "no_ai": False, "local_only": False, "dry_run": False, "artifacts_dir": None,
}
_CONVERT_PATHS = {"out", "searchable_pdf", "tessdata_dir", "artifacts_dir"}
_VELLRIC_LIMITS = {"timeout_seconds", "memory_mib", "max_input_bytes", "max_output_bytes", "max_pages"}


def _section(value: Any, keys: set[str]) -> dict:
    if not isinstance(value, dict) or value.keys() - keys:
        raise SchemaError("invalid_drawbridge_settings")
    return value


def _path(value: Any, base: Path, *, executable: bool = False) -> Path:
    if not isinstance(value, str) or not value or value.startswith("~") or "\x00" in value:
        raise SchemaError("invalid_drawbridge_path")
    path = Path(value)
    if executable and not path.is_absolute():
        raise SchemaError("absolute_executable_required")
    return base / path


def _positive(value: Any, *, integral: bool = False) -> int | float:
    if type(value) not in (int, float) or value <= 0 or value > 2**63 - 1 or not math.isfinite(value):
        raise SchemaError("invalid_drawbridge_limit")
    if integral and type(value) is not int:
        raise SchemaError("invalid_drawbridge_limit")
    return value


@dataclass(frozen=True)
class RuntimePaths:
    work_dir: Path | None = None
    cache_dir: Path | None = None
    output_dir: Path | None = None
    path: tuple[Path, ...] | None = None


@dataclass(frozen=True)
class VellricSettings:
    executable: Path | None = None
    tessdata_dir: Path | None = None
    limits: Mapping[str, int | float] = field(default_factory=lambda: _EMPTY)


def stage_selection(value: str | None) -> list[str] | None:
    return [part.strip() for part in value.split(",") if part.strip()] if value else None


def _convert_settings(value: Any, base: Path) -> Mapping[str, Any]:
    result = {}
    for name, item in _section(value, set(_CONVERT_DEFAULTS)).items():
        if name in _CONVERT_PATHS:
            item = _path(item, base)
        elif type(_CONVERT_DEFAULTS[name]) is bool:
            if type(item) is not bool:
                raise SchemaError("invalid_drawbridge_boolean")
        elif name in {"dpi", "workers", "ocr_page_workers"}:
            _positive(item, integral=True)
        elif name == "raster_threshold":
            if type(item) not in (int, float) or not 0 <= item <= 1:
                raise SchemaError("invalid_drawbridge_threshold")
        elif not isinstance(item, str) or (name == "notes" and item not in {"include", "exclude"}):
            raise SchemaError("invalid_drawbridge_option")
        if name in {"stages", "skip"} and set(stage_selection(item) or ()) - set(STAGE_NAMES):
            raise SchemaError("invalid_drawbridge_stage")
        result[name] = item
    return MappingProxyType(result)


def _settings(value: Any, base: Path) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SchemaError("invalid_drawbridge_settings")
    value = dict(value)
    paths = _section(value.pop("paths", {}), {"work_dir", "cache_dir", "output_dir", "path"})
    search = paths.get("path")
    if "path" in paths and not isinstance(search, list):
        raise SchemaError("invalid_drawbridge_path")
    search_path = None if search is None else tuple(_path(item, base, executable=True) for item in search)
    if search_path is not None and any(os.pathsep in str(item) for item in search_path):
        raise SchemaError("invalid_drawbridge_path")
    runtime = RuntimePaths(
        **{key: _path(item, base) for key, item in paths.items() if key != "path"},
        path=search_path,
    )
    vellric = _section(value.pop("vellric", {}), {"executable", "tessdata_dir", "limits"})
    limits = {
        key: _positive(item, integral=key != "timeout_seconds")
        for key, item in _section(vellric.get("limits", {}), _VELLRIC_LIMITS).items()
    }
    pdf = VellricSettings(
        _path(vellric["executable"], base, executable=True) if "executable" in vellric else None,
        _path(vellric["tessdata_dir"], base) if "tessdata_dir" in vellric else None,
        MappingProxyType(limits),
    )
    identify = _section(value.pop("identify", {}), {"file_executable"})
    tool = _path(identify["file_executable"], base, executable=True) if "file_executable" in identify else None
    convert = _convert_settings(value.pop("convert", {}), base)
    inspect = _section(value.pop("inspect", {}), {"page_texts"})
    if type(inspect.get("page_texts", False)) is not bool:
        raise SchemaError("invalid_drawbridge_boolean")
    speakers = _section(value.pop("speakers", {}), {"package", "clear"})
    clear = speakers.get("clear", [])
    if not isinstance(clear, list) or any(not isinstance(item, str) or not item for item in clear):
        raise SchemaError("invalid_speaker_ids")
    profile = _profile(value)
    cache = runtime.cache_dir
    if cache is None and "cache_dir" in (value.get("limits") or {}):
        cache = _path(str(profile.limits.cache_dir), base)
    if cache is None and runtime.work_dir is not None:
        cache = runtime.work_dir / "cache"
    profile = replace(profile, limits=replace(profile.limits, cache_dir=cache))
    return dict(
        profile=profile, paths=runtime, vellric=pdf, file_executable=tool, convert=convert,
        inspect_page_texts=inspect.get("page_texts", False), speakers_clear=tuple(clear),
        speakers_package=_path(speakers["package"], base) if "package" in speakers else None,
    )


@dataclass(frozen=True)
class Configuration:
    """An immutable per-call selection. No credentials or opaque leaf data are retained."""

    files: tuple[Path, ...] = ()
    root: Path | None = None
    profile: Profile = _EMPTY_PROFILE
    local_only: bool = False
    no_ai: bool = False
    paths: RuntimePaths = RuntimePaths()
    vellric: VellricSettings = VellricSettings()
    file_executable: Path | None = None
    convert: Mapping[str, Any] = field(default_factory=lambda: _EMPTY)
    has_quillric: bool = False
    inspect_page_texts: bool = False
    speakers_package: Path | None = None
    speakers_clear: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "files", tuple(Path(file).absolute() for file in self.files))
        object.__setattr__(self, "convert", _freeze(self.convert))
        if self.root is not None:
            object.__setattr__(self, "root", Path(self.root).absolute())
        object.__setattr__(self, "profile", replace(
            self.profile, endpoints=_freeze(self.profile.endpoints), stages=_freeze(self.profile.stages),
        ))

    def _file_options(self) -> tuple[str, ...]:
        result: list[str] = []
        for file in self.files:
            result += ["--config", str(file)]
        if self.root is not None:
            result += ["--config-root", str(self.root)]
        return tuple(result)

    def quillric_options(self) -> tuple[str, ...]:
        """Original composition arguments for the future Quillric handoff."""
        return self._file_options() if self.has_quillric else ()

    def cli_conversion_settings(self) -> dict[str, Any]:
        return {**_CONVERT_DEFAULTS, **self.convert}

    def convert_options(self) -> tuple[str, ...]:
        if not self.files:
            return ()
        result = list(self._file_options())
        if self.local_only:
            result.append("--local-only")
        if self.no_ai:
            result += ["--vision-provider", "none"]
        return tuple(result)

    def report(self) -> dict[str, Any]:
        routes = "not evaluated by Drawbridge; may execute configured provider routes"
        if self.files and self.no_ai:
            routes = "not evaluated by Drawbridge; forwarded --vision-provider none disables provider routes"
        elif self.files and self.local_only:
            routes = "not evaluated by Drawbridge; forwarded --local-only refuses every provider route"
        return {
            "files": [str(file) for file in self.files],
            "root": str(self.root) if self.root else None,
            "vellric_validation": "deferred until the independent Vellric convert job",
            "provider_credentials": "not accessed or forwarded to Vellric",
            "vellric_routes": routes,
        }


def load_configuration(
    files: Sequence[Path | str], *, root: Path | str | None = None,
    local_only: bool = False, no_ai: bool = False,
) -> Configuration:
    """Compose explicit files only; do not discover profiles, dotenv files or credentials."""
    try:
        if isinstance(files, (str, bytes, Path)):
            raise ValueError()
        paths = tuple(Path(file).absolute() for file in files)
        resolved_root = Path(root).absolute() if root is not None else None
    except (OSError, TypeError, ValueError, RuntimeError):
        raise ConfigurationError("Invalid explicit configuration paths") from None
    if resolved_root is not None and not paths:
        raise ConfigurationError("--config-root requires --config")
    if not paths:
        return Configuration(local_only=local_only, no_ai=no_ai)
    try:
        config = load(paths, root=resolved_root)
        leaf = config.data
        base = resolved_root or paths[0].parent
        settings = (
            config.validate(lambda value: _settings(value, base), path=("drawbridge",))
            if "drawbridge" in leaf else _settings({}, base)
        )
        convert = settings["convert"]
    except ConfigError as exc:
        # Conric is scalar-safe, but key names can themselves be private; expose only category/source.
        source = exc.source
        location = f" at {source.file}:{source.line}:{source.column}" if source else ""
        reason = f" ({exc.reason})" if exc.reason else ""
        raise ConfigurationError(f"Configuration {exc.code}{reason}{location}") from None
    return Configuration(
        paths, resolved_root, local_only=local_only or convert.get("local_only", False),
        no_ai=no_ai or convert.get("no_ai", False), has_quillric="quillric" in leaf, **settings,
    )


_DEFAULT_CONFIGURATION = Configuration()
_CURRENT: ContextVar[Configuration] = ContextVar("drawbridge_configuration", default=_DEFAULT_CONFIGURATION)


def current_configuration() -> Configuration:
    return _CURRENT.get()


def configuration_active() -> bool:
    """Distinguish an explicit scope (including profile-only settings) from the default."""
    return _CURRENT.get() is not _DEFAULT_CONFIGURATION


@contextmanager
def configuration_context(configuration: Configuration) -> Iterator[Configuration]:
    """Reset on every exit. Tasks inherit context; new threads require explicit propagation."""
    token = _CURRENT.set(configuration)
    try:
        yield configuration
    finally:
        _CURRENT.reset(token)


def executable_path(name: str, configured: Path | str | None = None) -> str | None:
    if configured is not None:
        path = Path(configured)
        if path.is_absolute() and path.is_file() and os.access(path, os.X_OK):
            return str(path)
        return None
    active = current_configuration()
    if active.files or active.paths.path is not None:
        path = child_path()
        return shutil.which(name, path=path) if path else None
    return shutil.which(name)


def child_path() -> str:
    active = current_configuration()
    if active.paths.path is not None:
        return os.pathsep.join(map(str, active.paths.path))
    if active.files:
        return os.defpath
    path = os.environ.get("PATH", os.defpath)
    return os.pathsep.join(item for item in path.split(os.pathsep) if Path(item).is_absolute())


def temporary_directory(prefix: str) -> tempfile.TemporaryDirectory:
    active = current_configuration()
    parent = active.paths.work_dir
    if parent is not None:
        parent.mkdir(parents=True, exist_ok=True)
    elif active.files and os.name == "posix":
        parent = Path("/tmp")
    return tempfile.TemporaryDirectory(prefix=prefix, dir=parent)


def child_environment(work: Path, *, locale: str = "en_US.UTF-8") -> dict[str, str]:
    return {
        "PATH": child_path(),
        "HOME": str(work),
        "TMPDIR": str(work),
        "XDG_CACHE_HOME": str(work),
        "XDG_CONFIG_HOME": str(work),
        "XDG_DATA_HOME": str(work),
        "LANG": locale,
        "LC_ALL": locale,
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "OMP_THREAD_LIMIT": "1",
    }


def run_local_tool(argv: list[str], **options: Any) -> subprocess.CompletedProcess:
    if not current_configuration().files:
        return subprocess.run(argv, **options)
    with temporary_directory("drawbridge-tool-") as directory:
        work = Path(directory)
        return subprocess.run(argv, cwd=work, env=child_environment(work), **options)
