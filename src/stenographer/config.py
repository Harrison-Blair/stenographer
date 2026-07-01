# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import os
import pathlib
import re
import tomllib
from dataclasses import asdict, dataclass
from typing import Any

CUE_NAMES: tuple[str, ...] = (
    "ptt_on",
    "ptt_off",
    "toggle_on",
    "toggle_off",
    "error",
    "segment",
    "transcribe_done",
)

ALLOWED_COMPUTE_TYPES: frozenset[str] = frozenset(
    {"int8", "int8_float16", "float16", "float32", "default"}
)

ALLOWED_SAMPLE_RATES: frozenset[int] = frozenset({8000, 16000, 22050, 44100, 48000})

ALLOWED_UPDATE_CHANNELS: frozenset[str] = frozenset({"stable", "latest"})


class ConfigError(ValueError):
    def __init__(self, path: pathlib.Path, key: str, reason: str) -> None:
        self.path = path
        self.key = key
        self.reason = reason
        super().__init__(f"{path}: {key}: {reason}")


@dataclass(frozen=True)
class HotkeyConfig:
    binding: str
    toggle_threshold_seconds: float
    device: str | None


@dataclass(frozen=True)
class AudioConfig:
    sample_rate: int
    frames_per_buffer: int
    input_device: str | None


@dataclass(frozen=True)
class AsrConfig:
    model: str
    language: str
    beam_size: int
    compute_type: str
    silence_threshold: float


@dataclass(frozen=True)
class FeedbackConfig:
    volume: float
    cues: dict[str, str | None]
    mute: bool


ALLOWED_INJECTION_METHODS: frozenset[str] = frozenset({"text", "paste"})


@dataclass(frozen=True)
class OutputConfig:
    injection_method: str
    append_trailing_space: bool
    max_chars: int


@dataclass(frozen=True)
class ClipboardConfig:
    enabled: bool


@dataclass(frozen=True)
class UpdateConfig:
    repo: str
    channel: str
    base_url: str
    asset_pattern: str
    timeout_seconds: int


@dataclass(frozen=True)
class Config:
    hotkey: HotkeyConfig
    audio: AudioConfig
    asr: AsrConfig
    feedback: FeedbackConfig
    output: OutputConfig
    clipboard: ClipboardConfig
    update: UpdateConfig

    @classmethod
    def defaults(cls) -> Config:
        return cls(
            hotkey=HotkeyConfig(
                binding="KEY_RIGHTCTRL",
                toggle_threshold_seconds=0.5,
                device=None,
            ),
            audio=AudioConfig(
                sample_rate=16000,
                frames_per_buffer=1024,
                input_device=None,
            ),
            asr=AsrConfig(
                model="Systran/faster-whisper-large-v3",
                language="en",
                beam_size=5,
                compute_type="int8",
                silence_threshold=0.6,
            ),
            feedback=FeedbackConfig(
                volume=0.6,
                cues=dict.fromkeys(CUE_NAMES, None),
                mute=False,
            ),
            output=OutputConfig(
                injection_method="paste",
                append_trailing_space=True,
                max_chars=4096,
            ),
            clipboard=ClipboardConfig(enabled=True),
            update=UpdateConfig(
                repo="Harrison-Blair/stenographer",
                channel="stable",
                base_url="https://api.github.com",
                asset_pattern="stenographer-{version}-linux-x86_64.tar.gz",
                timeout_seconds=60,
            ),
        )

    @classmethod
    def load(cls, path: pathlib.Path) -> Config:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as e:
            raise ConfigError(path, "<file>", f"cannot read: {e}") from e

        # TOML 1.0 has no null; rewrite bare `null` values to "" so the
        # spec's example syntax parses. Looks only at token boundaries so
        # the word "null" inside a string is left alone.
        content = _NULL_VALUE_RE.sub('""', content)

        try:
            raw = tomllib.loads(content)
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(path, "<toml>", f"malformed TOML: {e}") from e

        if not isinstance(raw, dict):
            raise ConfigError(path, "<file>", "top-level value must be a table")

        table = raw.get("stenographer", {})
        if not isinstance(table, dict):
            raise ConfigError(path, "stenographer", f"must be a table, got {type(table).__name__}")

        merged = _merge(asdict(cls.defaults()), table)
        return cls._from_dict(merged, path)

    @classmethod
    def write_default(cls, path: pathlib.Path) -> None:
        path.write_text(_format_default_toml(), encoding="utf-8")

    @classmethod
    def _from_dict(cls, table: dict[str, Any], path: pathlib.Path) -> Config:
        return cls(
            hotkey=_build_hotkey(table["hotkey"], path),
            audio=_build_audio(table["audio"], path),
            asr=_build_asr(table["asr"], path),
            feedback=_build_feedback(table["feedback"], path),
            output=_build_output(table["output"], path),
            clipboard=_build_clipboard(table["clipboard"], path),
            update=_build_update(table["update"], path),
        )


_NULL_VALUE_RE = re.compile(r'(?<=\s=\s)null(?=[^\w"]|\Z)', re.MULTILINE)


def _build_hotkey(table: dict[str, Any], path: pathlib.Path) -> HotkeyConfig:
    binding = _expect_str(table, "binding", "hotkey.binding", path)
    if not binding:
        raise ConfigError(path, "hotkey.binding", "must be a non-empty string")
    threshold = _expect_number(
        table, "toggle_threshold_seconds", "hotkey.toggle_threshold_seconds", path
    )
    if not (0 < threshold <= 5):
        raise ConfigError(path, "hotkey.toggle_threshold_seconds", "must satisfy 0 < x <= 5")
    device = _expect_optional_path(table, "device", "hotkey.device", path)
    return HotkeyConfig(binding=binding, toggle_threshold_seconds=threshold, device=device)


def _build_audio(table: dict[str, Any], path: pathlib.Path) -> AudioConfig:
    sample_rate = _expect_int(table, "sample_rate", "audio.sample_rate", path)
    if sample_rate not in ALLOWED_SAMPLE_RATES:
        raise ConfigError(
            path,
            "audio.sample_rate",
            f"must be one of {sorted(ALLOWED_SAMPLE_RATES)}",
        )
    frames_per_buffer = _expect_int(table, "frames_per_buffer", "audio.frames_per_buffer", path)
    if not (64 <= frames_per_buffer <= 8192):
        raise ConfigError(path, "audio.frames_per_buffer", "must satisfy 64 <= x <= 8192")
    input_device = _expect_optional_str(table, "input_device", "audio.input_device", path)
    return AudioConfig(
        sample_rate=sample_rate,
        frames_per_buffer=frames_per_buffer,
        input_device=input_device,
    )


def _build_asr(table: dict[str, Any], path: pathlib.Path) -> AsrConfig:
    model = _expect_str(table, "model", "asr.model", path)
    language = _expect_str(table, "language", "asr.language", path)
    beam_size = _expect_int(table, "beam_size", "asr.beam_size", path)
    if not (1 <= beam_size <= 10):
        raise ConfigError(path, "asr.beam_size", "must satisfy 1 <= x <= 10")
    compute_type = _expect_str(table, "compute_type", "asr.compute_type", path)
    if compute_type not in ALLOWED_COMPUTE_TYPES:
        raise ConfigError(
            path,
            "asr.compute_type",
            f"must be one of {sorted(ALLOWED_COMPUTE_TYPES)}",
        )
    silence_threshold = _expect_number(table, "silence_threshold", "asr.silence_threshold", path)
    if not (0.0 <= silence_threshold <= 1.0):
        raise ConfigError(path, "asr.silence_threshold", "must satisfy 0.0 <= x <= 1.0")
    return AsrConfig(
        model=model,
        language=language,
        beam_size=beam_size,
        compute_type=compute_type,
        silence_threshold=silence_threshold,
    )


def _build_feedback(table: dict[str, Any], path: pathlib.Path) -> FeedbackConfig:
    volume = _expect_number(table, "volume", "feedback.volume", path)
    if not (0.0 <= volume <= 1.0):
        raise ConfigError(path, "feedback.volume", "must satisfy 0.0 <= x <= 1.0")
    cues = _build_cues(table.get("cues", {}), path)
    mute = _expect_bool(table, "mute", "feedback.mute", path)
    return FeedbackConfig(volume=volume, cues=cues, mute=mute)


def _build_cues(raw: Any, path: pathlib.Path) -> dict[str, str | None]:
    if not isinstance(raw, dict):
        raise ConfigError(path, "feedback.cues", f"must be a table, got {type(raw).__name__}")
    cues: dict[str, str | None] = {}
    for name, value in raw.items():
        if value is None or value == "":
            cues[name] = None
        elif isinstance(value, str):
            p = pathlib.Path(value)
            if not p.is_file() or not os.access(value, os.R_OK):
                raise ConfigError(path, f"feedback.cues.{name}", f"not a readable file: {value}")
            cues[name] = value
        else:
            raise ConfigError(
                path,
                f"feedback.cues.{name}",
                f"must be a string or null, got {type(value).__name__}",
            )
    return cues


def _build_output(table: dict[str, Any], path: pathlib.Path) -> OutputConfig:
    injection_method = _expect_str(table, "injection_method", "output.injection_method", path)
    if injection_method not in ALLOWED_INJECTION_METHODS:
        raise ConfigError(
            path,
            "output.injection_method",
            f"must be one of {sorted(ALLOWED_INJECTION_METHODS)}",
        )
    append_trailing_space = _expect_bool(
        table, "append_trailing_space", "output.append_trailing_space", path
    )
    max_chars = _expect_int(table, "max_chars", "output.max_chars", path)
    if not (1 <= max_chars <= 100000):
        raise ConfigError(path, "output.max_chars", "must satisfy 1 <= x <= 100000")
    return OutputConfig(
        injection_method=injection_method,
        append_trailing_space=append_trailing_space,
        max_chars=max_chars,
    )


def _build_clipboard(table: dict[str, Any], path: pathlib.Path) -> ClipboardConfig:
    enabled = _expect_bool(table, "enabled", "clipboard.enabled", path)
    return ClipboardConfig(enabled=enabled)


def _build_update(table: dict[str, Any], path: pathlib.Path) -> UpdateConfig:
    repo = _expect_str(table, "repo", "update.repo", path)
    if "/" not in repo:
        raise ConfigError(path, "update.repo", f"must be OWNER/REPO, got {repo!r}")
    channel = _expect_str(table, "channel", "update.channel", path)
    if channel not in ALLOWED_UPDATE_CHANNELS:
        raise ConfigError(
            path,
            "update.channel",
            f"must be one of {sorted(ALLOWED_UPDATE_CHANNELS)}",
        )
    base_url = _expect_str(table, "base_url", "update.base_url", path)
    if not base_url.startswith(("http://", "https://")):
        raise ConfigError(
            path,
            "update.base_url",
            f"must be an http(s) URL, got {base_url!r}",
        )
    asset_pattern = _expect_str(table, "asset_pattern", "update.asset_pattern", path)
    if "{version}" not in asset_pattern:
        raise ConfigError(
            path,
            "update.asset_pattern",
            "must contain the literal '{version}'",
        )
    timeout_seconds = _expect_int(table, "timeout_seconds", "update.timeout_seconds", path)
    if not (1 <= timeout_seconds <= 600):
        raise ConfigError(path, "update.timeout_seconds", "must satisfy 1 <= x <= 600")
    return UpdateConfig(
        repo=repo,
        channel=channel,
        base_url=base_url.rstrip("/"),
        asset_pattern=asset_pattern,
        timeout_seconds=timeout_seconds,
    )


def _expect_str(table: dict, key: str, dotted: str, path: pathlib.Path) -> str:
    value = table.get(key)
    if not isinstance(value, str):
        raise ConfigError(path, dotted, f"expected string, got {type(value).__name__}: {value!r}")
    return value


def _expect_int(table: dict, key: str, dotted: str, path: pathlib.Path) -> int:
    value = table.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(path, dotted, f"expected int, got {type(value).__name__}: {value!r}")
    return value


def _expect_number(table: dict, key: str, dotted: str, path: pathlib.Path) -> float:
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(path, dotted, f"expected number, got {type(value).__name__}: {value!r}")
    return float(value)


def _expect_bool(table: dict, key: str, dotted: str, path: pathlib.Path) -> bool:
    value = table.get(key)
    if not isinstance(value, bool):
        raise ConfigError(path, dotted, f"expected bool, got {type(value).__name__}: {value!r}")
    return value


def _expect_optional_str(table: dict, key: str, dotted: str, path: pathlib.Path) -> str | None:
    value = table.get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ConfigError(
            path,
            dotted,
            f"expected string or null, got {type(value).__name__}: {value!r}",
        )
    return value


def _expect_optional_path(table: dict, key: str, dotted: str, path: pathlib.Path) -> str | None:
    value = _expect_optional_str(table, key, dotted, path)
    if value is not None and not pathlib.Path(value).exists():
        raise ConfigError(path, dotted, f"path does not exist: {value}")
    return value


def _merge(base: dict, overlay: dict) -> dict:
    result = dict(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _format_default_toml() -> str:
    cfg = Config.defaults()
    h = cfg.hotkey
    a = cfg.audio
    r = cfg.asr
    f = cfg.feedback
    o = cfg.output
    c = cfg.clipboard
    u = cfg.update
    lines: list[str] = [
        "# stenographer configuration",
        "# See spec/07-configuration.md for the full schema.",
        "",
        "[stenographer]",
        "",
        "# Hotkey",
        f"hotkey.binding = {_toml_str(h.binding)}",
        f"hotkey.toggle_threshold_seconds = {h.toggle_threshold_seconds}",
        f"hotkey.device = {_toml_optional(h.device)}",
        "",
        "# Audio capture",
        f"audio.sample_rate = {a.sample_rate}",
        f"audio.frames_per_buffer = {a.frames_per_buffer}",
        f"audio.input_device = {_toml_optional(a.input_device)}",
        "",
        "# ASR",
        f"asr.model = {_toml_str(r.model)}",
        f"asr.language = {_toml_str(r.language)}",
        f"asr.beam_size = {r.beam_size}",
        f"asr.compute_type = {_toml_str(r.compute_type)}",
        f"asr.silence_threshold = {r.silence_threshold}",
        "",
        "# Audio feedback",
        f"feedback.volume = {f.volume}",
        f"feedback.mute = {_toml_bool(f.mute)}",
        "",
        "# Text output",
        f"output.injection_method = {_toml_str(o.injection_method)}",
        f"output.append_trailing_space = {_toml_bool(o.append_trailing_space)}",
        f"output.max_chars = {o.max_chars}",
        "",
        "# Clipboard",
        f"clipboard.enabled = {_toml_bool(c.enabled)}",
        "",
        "# Update (see spec/12-update.md)",
        f"update.repo = {_toml_str(u.repo)}",
        f"update.channel = {_toml_str(u.channel)}",
        f"update.base_url = {_toml_str(u.base_url)}",
        f"update.asset_pattern = {_toml_str(u.asset_pattern)}",
        f"update.timeout_seconds = {u.timeout_seconds}",
        "",
        "[stenographer.feedback.cues]",
    ]
    for name in CUE_NAMES:
        lines.append(f"{name} = {_toml_optional(f.cues[name])}")
    lines.append("")
    return "\n".join(lines)


def _toml_str(s: str) -> str:
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_optional(v: str | None) -> str:
    if v is None:
        return '""'
    return _toml_str(v)


def _toml_bool(b: bool) -> str:
    return "true" if b else "false"


def resolve_config_path() -> pathlib.Path:
    env_path = os.environ.get("STENOGRAPHER_CONFIG")
    if env_path:
        path = pathlib.Path(env_path)
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        base = pathlib.Path(xdg) if xdg else pathlib.Path.home() / ".config"
        path = base / "stenographer" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_or_default() -> Config:
    path = resolve_config_path()
    if path.is_file():
        return Config.load(path)
    Config.write_default(path)
    return Config.defaults()
