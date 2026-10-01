"""Audio and video to a mirror, through Quillric (compatibility import ``transcribe``).

Nothing here runs without a profile that declares a transcription stage. Before any call the
recording is measured locally: its length against the limits, and how uneven its speech level is.
Leveling at a second provider happens only when the profile declares the cleanup stage and either
asks for it always (``mode: on``) or the recording is uneven (``mode: auto``, the default), so the
plan shows exactly the hops that will be made. An uneven recording is transcribed twice, and the
places where the passes differ are carried into the mirror as uncertain passages.

The mirror's words come from the package's raw provider response and never change. Names change
by editing the package's speaker table and rendering the body again.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .convert import ConversionOptions
from .calls import ModelCall, report
from .errors import ConversionOperationalError, ConverterUnavailable, DrawbridgeError
from .mirror import Mirror, build_header, now_iso, parse_mirror_header, render_mirror, title_from_name
from .profile import Plan, Profile, ProfileError
from .progress import advance

VIDEO_FLAG = "video-visual-content-not-captured"
METHOD = "transcribe"
#: Per-call credentials, passed directly without changing the process environment.
_DEPENDENCY_KEYS = {"audio_cleanup": "auphonic_api_key", "transcription": "elevenlabs_api_key"}


class AudioLimitExceeded(ConversionOperationalError):
    """The recording is longer than the profile allows; refused before any call was made."""


@dataclass
class RunBudget:
    """Audio minutes spent across one run, for a caller converting many recordings."""

    limit_minutes: float | None
    spent_minutes: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def reserve(self, minutes: float) -> None:
        """Check and charge in one step, so concurrent conversions cannot both slip under the limit."""
        with self._lock:
            if self.limit_minutes is not None and self.spent_minutes + minutes > self.limit_minutes:
                raise AudioLimitExceeded(
                    f"run budget of {self.limit_minutes:g} audio minutes would be exceeded: "
                    f"{self.spent_minutes:.1f} spent, {minutes:.1f} requested"
                )
            self.spent_minutes += minutes


def audio_minutes(path: Path) -> float:
    """Duration from the container, read locally. A file whose length cannot be read is refused."""
    executable = shutil.which("ffprobe")
    if executable is None:
        raise ConverterUnavailable("ffprobe is required to measure a recording before transcribing it")
    try:
        result = subprocess.run(
            [executable, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=True, timeout=60,
        )
        return float(result.stdout.strip()) / 60.0
    except (subprocess.SubprocessError, ValueError, OSError) as exc:
        raise ConversionOperationalError(f"could not measure the recording's duration: {path.name}") from exc


@dataclass(frozen=True)
class AudioDecision:
    """What will be done to one recording, settled locally before anything is sent."""

    leveling_mode: str  # "off" | "auto" | "on"
    second_pass_mode: str  # "off" | "auto" | "on"
    threshold_db: float
    levels: dict[str, Any] | None
    will_level: bool
    will_transcribe_twice: bool

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    @property
    def cloud_stages(self) -> tuple[str, ...]:
        return (("audio_cleanup",) if self.will_level else ()) + ("transcription",)


def decide(path: Path, profile: Profile, plan: Plan) -> AudioDecision:
    dependency = _load_dependency()
    stage = profile.stages.get("transcription", {})
    leveling = str(profile.stages["audio_cleanup"].get("mode", "auto")) if plan.runs("audio_cleanup") else "off"
    second = str(stage.get("second_pass", "auto"))
    threshold = float(stage.get("uneven_threshold_db", dependency.levels.DEFAULT_UNEVEN_DB))
    measured = None
    if "auto" in {leveling, second}:
        try:
            measured = dependency.levels.measure(path)
        except dependency.levels.LevelsError as exc:
            raise ConversionOperationalError(f"could not measure the recording's speech levels: {exc}") from exc
    uneven = measured is not None and measured.uneven(threshold)
    return AudioDecision(leveling, second, threshold, measured.as_dict() if measured else None,
                         leveling == "on" or (leveling == "auto" and uneven), second == "on" or (second == "auto" and uneven))


def audio_estimate(profile: Profile, decision: AudioDecision, minutes: float) -> dict[str, Any]:
    """What a conversion would spend. Rates are whatever the profile declares; none are assumed."""
    lines, total, complete = [], 0.0, True
    passes = {"audio_cleanup": 1 if decision.will_level else 0, "transcription": 2 if decision.will_transcribe_twice else 1}
    for stage, count in passes.items():
        if not count:
            continue
        endpoint = profile.endpoint_for(stage)
        rate = endpoint.cost_per_audio_hour_usd if endpoint else None
        cost = round(rate * count * minutes / 60.0, 4) if rate is not None else None
        complete = complete and cost is not None
        total += cost or 0.0
        lines.append({"stage": stage, "endpoint": endpoint.name if endpoint else None, "passes": count, "usd": cost})
    return {"audio_minutes": round(minutes, 2), "stages": lines, "estimated_usd": round(total, 4) if complete and lines else None}


def check_audio_plan(profile: Profile, plan: Plan, minutes: float, decision: AudioDecision, budget: RunBudget | None = None) -> None:
    """Every refusal that can be made before a byte leaves the machine."""
    if not plan.runs("transcription"):
        raise ConversionOperationalError("audio and video need a profile with a transcription stage; none is enabled for this run")
    ceiling = min(profile.limits.max_audio_minutes, float(profile.stages["transcription"].get("max_duration_minutes", profile.limits.max_audio_minutes)))
    if minutes > ceiling:
        raise AudioLimitExceeded(f"recording is {minutes:.1f} minutes; the profile allows {ceiling:g}")
    unset = [stage for stage in decision.cloud_stages if profile.endpoint_for(stage).key_is_set is False]
    if unset:
        raise ProfileError(f"no key is set for: {', '.join(unset)}")
    if budget is not None:
        budget.reserve(minutes * (2 if decision.will_transcribe_twice else 1))


def _dependency_options(profile: Profile, package_dir: Path, decision: AudioDecision) -> list[str]:
    cleanup, stage = profile.stages.get("audio_cleanup", {}), profile.stages["transcription"]
    # The modes and threshold go through unchanged: the dependency makes the same measurement with the same
    # code, reaches the same decision, and records the measured levels in its package.
    options = ["--output-dir", str(package_dir), "--leveling", decision.leveling_mode,
               "--second-pass", decision.second_pass_mode, "--uneven-threshold", str(decision.threshold_db)]
    if cleanup.get("preset"):
        options += ["--auphonic-config", str(Path(str(cleanup["preset"])).expanduser())]
    for key, value in (cleanup.get("settings") or {}).items():
        options += ["--auphonic-set", f"{key}={json.dumps(value)}"]
    if cleanup.get("bitrate_kbps"):
        options += ["--mp3-bitrate", str(int(cleanup["bitrate_kbps"]))]
    if stage.get("model"):
        options += ["--model", str(stage["model"])]
    if stage.get("language") not in (None, "auto"):
        options += ["--language-code", str(stage["language"])]
    diarization = stage.get("diarization") or {}
    if diarization.get("max_speakers"):
        options += ["--max-speakers", str(int(diarization["max_speakers"]))]
    elif diarization.get("threshold") is not None:
        options += ["--diarization-threshold", str(diarization["threshold"])]
    if stage.get("audio_events"):
        options.append("--audio-events")
    if stage.get("verbatim") is False:
        options.append("--clean-transcript")
    return options


def _load_dependency() -> Any:
    try:
        import transcribe
    except ImportError as exc:
        raise ConverterUnavailable("audio needs Quillric: install drawbridge[audio]") from exc
    return transcribe


def _cell(value: object) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def _clock(seconds: float | int | None) -> str:
    total = round(max(0.0, float(seconds or 0.0)) * 1000)
    rest, millis = divmod(total, 1000)
    minutes, secs = divmod(rest, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def transcript_body(title: str, package: Any) -> str:
    """The Speakers table, then one section per turn of the transcript merged from every pass that was made.

    Where two passes heard different words, both readings sit in the flow as ``{first | second}``. Where they gave
    the same words to different speakers, that stretch is its own turn headed with both identities. A named
    identity keeps the provider's identity beside the name.
    """
    from transcribe import merge

    rows = package.speakers.get("speakers", [])
    names = {str(row["id"]): str(row["name"]) for row in rows if row.get("name")}
    lines = [f"# {title}", "", "## Speakers", "", "| Speaker | Name | Turns | Words | Speaking time | First heard | Note |", "| --- | --- | ---: | ---: | --- | --- | --- |"]
    for row in rows:
        lines.append(
            f"| {_cell(row.get('id'))} | {_cell(row.get('name'))} | {row.get('turns', 0)} | {row.get('words', 0)} | "
            f"{_clock(row.get('speaking_seconds'))[:8]} | {_clock(row.get('first_start'))} | {_cell(row.get('note'))} |"
        )
    turns = package.merged_turns()
    if package.second_transcript() is not None:
        counts = merge.summary(turns)
        lines += ["", "Two transcriptions of this recording were merged. Where they heard different words, both readings are shown as `{first | second}`, "
                  "with `—` where one heard nothing; where they gave the same words to different speakers, that stretch is its own turn headed with both. "
                  f"Word disagreements: {counts['word_disagreements']}. Speaker disagreements: {counts['speaker_disagreements']}."]
    for turn in turns:
        text = str(turn.get("text") or "").strip()
        if text:
            lines += ["", f"## {_clock(turn.get('start'))} --> {_clock(turn.get('end'))} · {merge.speaker_label(turn['speakers'], names)}", "", text]
    return "\n".join(lines)


def mirror_from_package(
    source: Path,
    package: Any,
    *,
    options: ConversionOptions,
    media_type: str,
    processing: list[dict[str, Any]],
    verify: tuple[str, ...] = (),
) -> Mirror:
    sidecar = package.sidecar
    header = build_header(
        source,
        method=METHOD,
        mirror_of=options.mirror_of,
        media_type=media_type,
        acquired_at=options.acquired_at,
        acquisition_method=options.acquisition_method,
        acquired_from=options.acquired_from,
        agent=options.agent,
        verify=(*options.verify, *verify),
        unit="turn",
        extra={
            "audio_duration_seconds": sidecar["transcript"].get("audio_duration_seconds"),
            "detected_language": sidecar["transcript"].get("detected_language"),
            "speaker_count": len(package.speakers.get("speakers", [])),
            "transcription_package": package.directory.name,
            "speech_level_spread_db": ((sidecar.get("leveling") or {}).get("levels") or {}).get("spread_db"),
            "leveling_applied": bool((sidecar.get("leveling") or {}).get("applied")),
            "second_pass_agreement": (sidecar.get("second_pass") or {}).get("agreement"),
        },
        extensions=options.extensions,
    )
    if header["content_hash"] != f"sha256:{package.source_sha256}":
        raise ConversionOperationalError("the transcription package describes a different recording")
    header["processing"] = processing
    return Mirror(header, transcript_body(options.title or title_from_name(source.name), package))


def convert_audio(
    path: Path,
    *,
    profile: Profile,
    plan: Plan,
    options: ConversionOptions,
    media_type: str,
    artifacts_dir: Path,
    budget: RunBudget | None = None,
    run: Callable[..., Any] | None = None,
) -> tuple[Mirror, Any]:
    """Transcribe one recording and return (mirror, package). ``run`` replaces the paid call in tests."""
    minutes = audio_minutes(path)
    if not plan.runs("transcription"):
        raise ConversionOperationalError("audio and video need a profile with a transcription stage; none is enabled for this run")
    decision = decide(path, profile, plan)
    check_audio_plan(profile, plan, minutes, decision)
    dependency = _load_dependency()
    package_dir = Path(artifacts_dir) / f"{path.name}.transcribe"
    if package_dir.exists():
        # The cache: a package for these exact bytes is reused, free of charge; any other occupant is refused.
        try:
            package = dependency.Package.load(package_dir)
        except RuntimeError as exc:  # the dependency's own error family; one recording's failure, not the run's
            raise ConversionOperationalError(f"the kept transcription package could not be read: {exc}") from exc
        if f"sha256:{package.source_sha256}" != build_header(path, method=METHOD)["content_hash"]:
            raise ConversionOperationalError(f"{package_dir} holds a package for a different recording")
        reused = True
    else:
        if budget is not None:
            budget.reserve(minutes * (2 if decision.will_transcribe_twice else 1))  # only a paid run is charged
        started = time.monotonic()
        seconds = round(minutes * 60)
        advance("transcription", 0, seconds)  # the dependency transcribes the recording as a whole
        try:
            credentials = {_DEPENDENCY_KEYS[stage]: profile.endpoint_for(stage).key()
                           for stage in decision.cloud_stages}
            package = (run or dependency.transcribe_file)(
                path, *_dependency_options(profile, package_dir, decision), **credentials)
        except RuntimeError as exc:  # provider, leveling and packaging errors all derive from RuntimeError
            endpoint = profile.endpoint_for("transcription")
            report(ModelCall("transcription", endpoint.name if endpoint else None, None, "failed",
                             round(time.monotonic() - started, 3), audio_seconds=round(minutes * 60, 3),
                             declared_usd_per_audio_hour=endpoint.cost_per_audio_hour_usd if endpoint else None,
                             failure=type(exc).__name__))
            if isinstance(exc, DrawbridgeError):
                raise
            raise ConversionOperationalError(f"transcription failed: {exc}") from exc
        reused = False
        advance("transcription", seconds, seconds)
    elapsed = 0.0 if reused else round(time.monotonic() - started, 3)
    sidecar = package.sidecar
    applied = bool((sidecar.get("leveling") or {}).get("applied"))
    second = sidecar.get("second_pass")
    steps = ([("audio_cleanup", "audio_cleanup:{kind}")] if applied else []) + [("transcription", "transcription:{kind}:" + str(sidecar["settings"].get("model_id")))]
    if second:
        steps.append(("transcription", "transcription-second-pass:{kind}:" + str(sidecar["settings"].get("model_id"))))
    processing = []
    for seq, (stage, method) in enumerate(steps, 1):
        endpoint = profile.endpoint_for(stage)
        # One report per pass the package holds; a kept package stood in for all of them at no charge.
        report(ModelCall(stage, endpoint.name if endpoint else None,
                         str(sidecar["settings"].get("model_id")) if stage == "transcription" else None,
                         "reused" if reused else "succeeded", elapsed if seq == len(steps) else 0.0,
                         audio_seconds=round(minutes * 60, 3),
                         declared_usd_per_audio_hour=endpoint.cost_per_audio_hour_usd if endpoint else None))
        if endpoint is None:  # a reused package was leveled under an earlier profile
            processing.append({"seq": seq, "method": method.format(kind="unknown"), "endpoint": None, "egress": "cloud", "performed_at": sidecar["generated_at"], "agent": options.agent, "reused_package": reused})
            continue
        processing.append({"seq": seq, "method": method.format(kind=endpoint.kind), "endpoint": endpoint.name, "egress": endpoint.egress, "performed_at": sidecar["generated_at"], "agent": options.agent, "reused_package": reused})
    verify = (VIDEO_FLAG,) if media_type.startswith("video/") else ()
    if second:
        from transcribe import merge

        counts = merge.summary(package.merged_turns())
        verify = (*verify, *(f"transcript-{kind.replace('_', '-')}:{count}" for kind, count in counts.items() if count))
    return mirror_from_package(path, package, options=options, media_type=media_type, processing=processing, verify=verify), package


def rerender(mirror_path: Path, package_dir: Path) -> str:
    """Render the body again from the package, after names changed. The header is kept except for a dated note."""
    dependency = _load_dependency()
    header, body = parse_mirror_header(Path(mirror_path))
    package = dependency.Package.load(Path(package_dir))
    if header["content_hash"] != f"sha256:{package.source_sha256}":
        raise ConversionOperationalError("that package belongs to a different recording than this mirror")
    title = body.split("\n", 1)[0].removeprefix("# ").strip() or title_from_name(str(header["mirror_of"]))
    header["speakers_rendered_at"] = now_iso()
    return render_mirror(Mirror(header, transcript_body(title, package)))
