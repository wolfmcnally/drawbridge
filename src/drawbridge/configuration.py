"""Explicit composition and scoped CLI settings; leaf schemas stay with their owners."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from ipaddress import ip_address
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from conric import ConfigError, SchemaError, SecretRef, load

from .profile import EMPTY_PROFILE, Profile, ProfileError, parse_profile


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


def _profile(value: Any) -> Profile:
    """Reuse the legacy schema, adding explicit-mode policy without scalar diagnostics."""
    _plain(value)
    try:
        profile = parse_profile(value)
        for endpoint in profile.endpoints.values():
            for item in (endpoint.base_url, endpoint.api_key_env):
                if item is not None and (not isinstance(item, str) or not item):
                    raise ValueError()
            if endpoint.egress == "local" and endpoint.kind != "command" and not _loopback(endpoint.base_url):
                raise SchemaError("local_endpoint_must_be_loopback")
        for name, stage in profile.stages.items():
            endpoint = profile.endpoint_for(name)
            needs_model = endpoint is not None and endpoint.kind != "command" and name != "audio_cleanup"
            if name == "ocr" and stage.get("engine", "tesseract") == "tesseract":
                needs_model = False
            if needs_model and (not isinstance(stage.get("model"), str) or not stage["model"].strip()):
                raise SchemaError("explicit_model_required")
    except SchemaError:
        raise
    except Exception:
        raise SchemaError("invalid_drawbridge_profile") from None
    return replace(profile, endpoints=_freeze(dict(profile.endpoints)), stages=_freeze(dict(profile.stages)))


_EMPTY_PROFILE = replace(EMPTY_PROFILE, endpoints=MappingProxyType({}), stages=MappingProxyType({}))


@dataclass(frozen=True)
class Configuration:
    """An immutable per-call selection. No credentials or opaque leaf data are retained."""

    files: tuple[Path, ...] = ()
    root: Path | None = None
    profile: Profile = _EMPTY_PROFILE
    local_only: bool = False
    no_ai: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "files", tuple(Path(file).absolute() for file in self.files))
        if self.root is not None:
            object.__setattr__(self, "root", Path(self.root).absolute())
        object.__setattr__(self, "profile", replace(
            self.profile, endpoints=_freeze(self.profile.endpoints), stages=_freeze(self.profile.stages),
        ))

    def convert_options(self) -> tuple[str, ...]:
        if not self.files:
            return ()
        result: list[str] = []
        for file in self.files:
            result += ["--config", str(file)]
        if self.root is not None:
            result += ["--config-root", str(self.root)]
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
        profile = config.validate(_profile, path=("drawbridge",)) if "drawbridge" in config.data else _EMPTY_PROFILE
    except ConfigError as exc:
        # Conric is scalar-safe, but key names can themselves be private; expose only category/source.
        source = exc.source
        location = f" at {source.file}:{source.line}:{source.column}" if source else ""
        reason = f" ({exc.reason})" if exc.reason else ""
        raise ConfigurationError(f"Configuration {exc.code}{reason}{location}") from None
    return Configuration(paths, resolved_root, profile, local_only, no_ai)


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
