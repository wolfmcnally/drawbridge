"""The profile: which optional stages run, against which endpoints, within which limits.

No profile means no networked or model stage runs. Validation is fail-closed: an unknown key, an
endpoint reference that does not resolve, or a stage widened beyond what it can act on is an error
at load time, never a surprise mid-run. A profile never holds a secret; endpoints name the
environment variable that does.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .errors import DrawbridgeError

ENDPOINT_KINDS = frozenset({"openai-compatible", "anthropic", "ollama", "elevenlabs", "auphonic", "command"})
EGRESS = frozenset({"cloud", "local"})
_ENDPOINT_KEYS = frozenset({"kind", "base_url", "api_key_env", "egress", "timeout_seconds", "max_concurrency", "command", "cost_per_audio_hour_usd"})
_LIMIT_KEYS = frozenset({"max_pages_per_document", "max_audio_minutes", "max_audio_minutes_per_run", "cache_dir"})
_TOP_KEYS = frozenset({"endpoints", "stages", "limits"})

#: Stage order is pipeline order. ``acts_on`` is the widest set a stage may apply to; ``default`` is
#: what it applies to when the profile does not say. A profile may narrow ``applies_to``, never widen.
_STAGES: dict[str, dict[str, Any]] = {
    "ocr": {
        "acts_on": {"pdf-scan-page", "image"},
        "default": {"pdf-scan-page", "image"},
        "keys": {"engine", "endpoint", "model", "applies_to", "orientation", "dpi", "prompt", "fallback", "max_pages", "cache"},
        "needs_endpoint": lambda stage: stage.get("engine", "tesseract") != "tesseract",
    },
    "structure": {
        "acts_on": {"pdf-scan-page", "pdf-native-page"},
        "default": {"pdf-scan-page"},
        "keys": {"endpoint", "model", "applies_to", "native_pass", "mode", "preservation", "elements", "render_page_image", "output", "prompt", "cache"},
        "needs_endpoint": lambda stage: "model" in stage or "endpoint" in stage,
    },
    "image_description": {
        "acts_on": {"image"},
        "default": {"image"},
        "keys": {"endpoint", "model", "applies_to", "prompt", "max_words", "cache"},
        "needs_endpoint": lambda stage: True,
    },
    "audio_cleanup": {
        "acts_on": {"audio", "video"},
        "default": {"audio", "video"},
        "keys": {"provider", "endpoint", "applies_to", "mode", "preset", "settings", "keep_adjusted_audio", "output_format", "bitrate_kbps"},
        "needs_endpoint": lambda stage: True,
    },
    "transcription": {
        "acts_on": {"audio", "video"},
        "default": {"audio", "video"},
        "keys": {"provider", "endpoint", "model", "applies_to", "language", "diarization", "timestamps", "verbatim", "audio_events", "keep_raw_response", "max_duration_minutes", "second_pass", "uneven_threshold_db"},
        "needs_endpoint": lambda stage: True,
    },
    "transcript_refinement": {
        "acts_on": {"audio", "video"},
        "default": {"audio", "video"},
        "keys": {"endpoint", "model", "applies_to", "mode", "preservation", "speaker_resolution", "prompt", "cache"},
        "needs_endpoint": lambda stage: True,
    },
}
STAGE_NAMES: tuple[str, ...] = tuple(_STAGES)


class ProfileError(DrawbridgeError):
    """The profile is missing, malformed, or asks for something that cannot be done."""


class EgressRefused(ProfileError):
    """``--local-only`` was given and the plan contains a stage that sends bytes off the machine."""

    def __init__(self, message: str, plan: "Plan") -> None:
        super().__init__(message)
        self.plan = plan


@dataclass(frozen=True)
class Endpoint:
    name: str
    kind: str
    egress: str
    base_url: str | None = None
    api_key_env: str | None = None
    timeout_seconds: int = 120
    max_concurrency: int = 4
    command: tuple[str, ...] = ()
    cost_per_audio_hour_usd: float | None = None  # declared by the user, never assumed

    @property
    def key_is_set(self) -> bool | None:
        """``None`` when the endpoint needs no key."""
        return None if self.api_key_env is None else bool(os.environ.get(self.api_key_env))

    def key(self) -> str:
        if self.api_key_env is None:
            raise ProfileError(f"endpoint {self.name} declares no api_key_env")
        value = os.environ.get(self.api_key_env)
        if not value:
            raise ProfileError(f"endpoint {self.name}: environment variable {self.api_key_env} is not set")
        return value


@dataclass(frozen=True)
class Limits:
    max_pages_per_document: int = 500
    max_audio_minutes: float = 240.0
    max_audio_minutes_per_run: float | None = None
    cache_dir: Path = Path("~/.cache/drawbridge")


@dataclass(frozen=True)
class Profile:
    path: Path | None
    endpoints: Mapping[str, Endpoint] = field(default_factory=dict)
    stages: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    limits: Limits = field(default_factory=Limits)

    def endpoint_for(self, stage: str) -> Endpoint | None:
        name = self.stages.get(stage, {}).get("endpoint")
        return self.endpoints[name] if name else None

    def redacted(self) -> dict[str, Any]:
        """The resolved profile for display: variable names and whether they are set, never values."""
        return {
            "path": str(self.path) if self.path else None,
            "endpoints": {
                name: {
                    "kind": endpoint.kind,
                    "egress": endpoint.egress,
                    "base_url": endpoint.base_url,
                    "api_key_env": endpoint.api_key_env,
                    "api_key_set": endpoint.key_is_set,
                }
                for name, endpoint in self.endpoints.items()
            },
            "stages": {name: dict(stage) for name, stage in self.stages.items()},
            "limits": {
                "max_pages_per_document": self.limits.max_pages_per_document,
                "max_audio_minutes": self.limits.max_audio_minutes,
                "max_audio_minutes_per_run": self.limits.max_audio_minutes_per_run,
                "cache_dir": str(self.limits.cache_dir),
            },
        }


EMPTY_PROFILE = Profile(path=None)


def locate_profile(explicit: Path | None = None, *, cwd: Path | None = None, environ: Mapping[str, str] | None = None) -> Path | None:
    """First match wins, no merging: ``--profile``, ``$DRAWBRIDGE_PROFILE``, ``./drawbridge.yaml``, the user config."""
    environ = os.environ if environ is None else environ
    if explicit is not None:
        if not explicit.is_file():
            raise ProfileError(f"profile not found: {explicit}")
        return explicit
    named = environ.get("DRAWBRIDGE_PROFILE")
    if named:
        if not Path(named).is_file():
            raise ProfileError(f"$DRAWBRIDGE_PROFILE names a missing file: {named}")
        return Path(named)
    local = (cwd or Path.cwd()) / "drawbridge.yaml"
    if local.is_file():
        return local
    config_home = Path(environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    user = config_home / "drawbridge" / "profile.yaml"
    return user if user.is_file() else None


def load_dotenv(directories: Iterable[Path]) -> list[str]:
    """Load ``.env`` from each directory without overriding variables already set. Returns the names added."""
    added: list[str] = []
    for directory in directories:
        path = Path(directory) / ".env"
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.removeprefix("export ").partition("=")
            name, value = name.strip(), value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if name and name not in os.environ:
                os.environ[name] = value
                added.append(name)
    return added


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProfileError(f"{where} must be a mapping")
    return value


def _unknown(keys: Iterable[str], allowed: frozenset[str] | set[str], where: str) -> None:
    extra = sorted(set(keys) - set(allowed))
    if extra:
        raise ProfileError(f"{where}: unknown key {', '.join(extra)}")


def _endpoint(name: str, raw: Any) -> Endpoint:
    data = _mapping(raw, f"endpoint {name}")
    _unknown(data, _ENDPOINT_KEYS, f"endpoint {name}")
    kind, egress = data.get("kind"), data.get("egress")
    if kind not in ENDPOINT_KINDS:
        raise ProfileError(f"endpoint {name}: kind must be one of {', '.join(sorted(ENDPOINT_KINDS))}")
    if egress not in EGRESS:
        raise ProfileError(f"endpoint {name}: egress must be declared as cloud or local; it is never inferred")
    command = data.get("command") or ()
    if kind == "command" and not command:
        raise ProfileError(f"endpoint {name}: a command endpoint needs a command")
    if isinstance(command, str) or not all(isinstance(part, str) for part in command):
        raise ProfileError(f"endpoint {name}: command must be a list of strings")
    for secret in ("api_key", "key", "token", "secret"):
        if secret in data:
            raise ProfileError(f"endpoint {name}: a profile never holds a secret; name the variable with api_key_env")
    return Endpoint(
        name=name,
        kind=kind,
        egress=egress,
        base_url=data.get("base_url"),
        api_key_env=data.get("api_key_env"),
        timeout_seconds=int(data.get("timeout_seconds", 120)),
        max_concurrency=int(data.get("max_concurrency", 4)),
        command=tuple(command),
        cost_per_audio_hour_usd=float(data["cost_per_audio_hour_usd"]) if data.get("cost_per_audio_hour_usd") is not None else None,
    )


def _stage(name: str, raw: Any, endpoints: Mapping[str, Endpoint]) -> Mapping[str, Any]:
    if name not in _STAGES:
        raise ProfileError(f"unknown stage {name}; stages are {', '.join(STAGE_NAMES)}")
    spec = _STAGES[name]
    data = dict(_mapping(raw, f"stage {name}"))
    _unknown(data, spec["keys"], f"stage {name}")
    applies = data.get("applies_to")
    if applies is not None:
        if isinstance(applies, str) or not all(isinstance(item, str) for item in applies):
            raise ProfileError(f"stage {name}: applies_to must be a list")
        widened = sorted(set(applies) - spec["acts_on"])
        if widened:
            raise ProfileError(f"stage {name} cannot act on {', '.join(widened)}")
    choices = {"structure": {"native_pass": {"deterministic", "none"}}, "audio_cleanup": {"mode": {"auto", "on"}}, "transcription": {"second_pass": {"off", "auto", "on"}}}
    for key, allowed in choices.get(name, {}).items():
        if key in data and data[key] not in allowed:
            raise ProfileError(f"stage {name}: {key} must be one of {', '.join(sorted(allowed))}")
    reference = data.get("endpoint")
    if reference is not None and reference not in endpoints:
        raise ProfileError(f"stage {name}: endpoint {reference} is not declared")
    if reference is None and spec["needs_endpoint"](data):
        raise ProfileError(f"stage {name} needs an endpoint")
    return data


def parse_profile(raw: Any, path: Path | None = None) -> Profile:
    data = _mapping(raw, "profile")
    _unknown(data, _TOP_KEYS, "profile")
    endpoints = {name: _endpoint(name, value) for name, value in _mapping(data.get("endpoints"), "endpoints").items()}
    stages = {name: _stage(name, value, endpoints) for name, value in _mapping(data.get("stages"), "stages").items()}
    limits_raw = _mapping(data.get("limits"), "limits")
    _unknown(limits_raw, _LIMIT_KEYS, "limits")
    defaults = Limits()
    per_run = limits_raw.get("max_audio_minutes_per_run")
    limits = Limits(
        max_pages_per_document=int(limits_raw.get("max_pages_per_document", defaults.max_pages_per_document)),
        max_audio_minutes=float(limits_raw.get("max_audio_minutes", defaults.max_audio_minutes)),
        max_audio_minutes_per_run=float(per_run) if per_run is not None else None,
        cache_dir=Path(str(limits_raw.get("cache_dir", defaults.cache_dir))),
    )
    ordered = {name: stages[name] for name in STAGE_NAMES if name in stages}
    return Profile(path=path, endpoints=endpoints, stages=ordered, limits=limits)


def load_profile(path: Path) -> Profile:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProfileError(f"profile is not valid YAML: {path}") from exc
    return parse_profile(raw, Path(path))


def resolve_profile(explicit: Path | None = None, *, no_profile: bool = False, cwd: Path | None = None) -> Profile:
    """Locate and load the profile, loading ``.env`` from the working directory and then the profile's own."""
    if no_profile:
        return EMPTY_PROFILE
    path = locate_profile(explicit, cwd=cwd)
    load_dotenv([cwd or Path.cwd(), *([path.parent] if path else [])])
    return load_profile(path) if path else EMPTY_PROFILE


def media_classes(media_type: str) -> frozenset[str]:
    """What a stage's ``applies_to`` is matched against for one input."""
    if media_type == "application/pdf":
        return frozenset({"pdf-scan-page", "pdf-native-page"})
    family = media_type.split("/", 1)[0]
    return frozenset({family}) if family in {"image", "audio", "video"} else frozenset()


@dataclass(frozen=True)
class StagePlan:
    stage: str
    runs: bool
    reason: str
    endpoint: str | None = None
    egress: str | None = None
    key_set: bool | None = None
    model: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, "runs": self.runs, "reason": self.reason, "endpoint": self.endpoint, "egress": self.egress, "api_key_set": self.key_set}


@dataclass(frozen=True)
class Plan:
    media_type: str
    stages: tuple[StagePlan, ...]

    def runs(self, stage: str) -> bool:
        return any(item.stage == stage and item.runs for item in self.stages)

    def runs_model(self, stage: str) -> bool:
        return any(item.stage == stage and item.runs and item.model for item in self.stages)

    @property
    def cloud_stages(self) -> tuple[str, ...]:
        return tuple(item.stage for item in self.stages if item.runs and item.egress == "cloud")

    @property
    def missing_keys(self) -> tuple[str, ...]:
        return tuple(item.stage for item in self.stages if item.runs and item.key_set is False)

    def as_dict(self) -> dict[str, Any]:
        return {"media_type": self.media_type, "stages": [item.as_dict() for item in self.stages], "sends_bytes_off_machine": list(self.cloud_stages), "missing_keys": list(self.missing_keys)}


def build_plan(
    profile: Profile,
    media_type: str,
    *,
    only: Iterable[str] | None = None,
    skip: Iterable[str] = (),
    no_ai: bool = False,
    local_only: bool = False,
) -> Plan:
    """Decide which stages run for one input. Raises ``EgressRefused`` when ``local_only`` forbids the plan."""
    only_set, skip_set = (set(only) if only is not None else None), set(skip)
    for name in (only_set or set()) | skip_set:
        if name not in _STAGES:
            raise ProfileError(f"unknown stage {name}; stages are {', '.join(STAGE_NAMES)}")
    classes = media_classes(media_type)
    planned: list[StagePlan] = []
    for name, stage in profile.stages.items():
        endpoint = profile.endpoint_for(name)
        applies = set(stage.get("applies_to") or _STAGES[name]["default"])
        detail = dict(endpoint=endpoint.name if endpoint else None, egress=endpoint.egress if endpoint else "local", key_set=endpoint.key_is_set if endpoint else None)
        if not applies & classes:
            planned.append(StagePlan(name, False, "does not apply to this media type", **detail))
        elif only_set is not None and name not in only_set:
            planned.append(StagePlan(name, False, "not named in --stages", **detail))
        elif name in skip_set:
            planned.append(StagePlan(name, False, "skipped by --skip", **detail))
        elif no_ai and endpoint is not None and name == "structure" and stage.get("native_pass", "deterministic") == "deterministic":
            planned.append(StagePlan(name, True, "typography pass only; the model is suppressed by --no-ai", endpoint=None, egress="local", key_set=None, model=False))
        elif no_ai and endpoint is not None:
            planned.append(StagePlan(name, False, "suppressed by --no-ai", **detail))
        else:
            planned.append(StagePlan(name, True, "profile enables it", **detail))
    plan = Plan(media_type, tuple(planned))
    if local_only and plan.cloud_stages:
        raise EgressRefused(f"--local-only refuses {', '.join(plan.cloud_stages)}: each would send bytes off this machine", plan)
    return plan
