# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
import os
import pathlib
import re
import tomllib
import typing
from dataclasses import asdict, dataclass
from typing import Any

from stenographer.audio.feedback import CueName
from stenographer.errors import ConfigError as _BaseConfigError

logger = logging.getLogger(__name__)

CUE_NAMES: tuple[str, ...] = typing.get_args(CueName)

ALLOWED_COMPUTE_TYPES: frozenset[str] = frozenset(
    {"int8", "int8_float16", "float16", "float32", "default"}
)

ALLOWED_ASR_MODES: frozenset[str] = frozenset({"eager", "lazy"})

ALLOWED_SAMPLE_RATES: frozenset[int] = frozenset({8000, 16000, 22050, 44100, 48000})

ALLOWED_UPDATE_CHANNELS: frozenset[str] = frozenset({"stable", "latest"})


class ConfigError(_BaseConfigError):
    """A validation error tied to a specific config file key.

    Subclasses :class:`stenographer.errors.ConfigError` so handlers
    catching the base class (exit code 78 policy) see both.
    """

    def __init__(self, path: pathlib.Path, key: str, reason: str) -> None:
        self.path = path
        self.key = key
        self.reason = reason
        super().__init__(f"{path}: {key}: {reason}")


ALLOWED_TRIGGER_MODES: frozenset[str] = frozenset({"hybrid", "toggle", "ptt"})


@dataclass(frozen=True)
class HotkeyConfig:
    binding: str
    toggle_threshold_seconds: float
    double_tap_window_seconds: float
    cancel_binding: str
    device: str | None
    trigger_mode: str


@dataclass(frozen=True)
class AudioConfig:
    sample_rate: int
    frames_per_buffer: int
    input_device: str | None
    max_recording_seconds: int
    min_speech_rms: float


@dataclass(frozen=True)
class AsrConfig:
    model: str
    language: str
    beam_size: int
    compute_type: str
    silence_threshold: float
    vad_filter: bool
    max_new_tokens: int
    mode: str
    idle_unload_seconds: int
    hotwords: str | None
    initial_prompt: str | None


@dataclass(frozen=True)
class FeedbackConfig:
    volume: float
    cues: dict[str, str | None]
    mute: bool


@dataclass(frozen=True)
class VisualizerConfig:
    enabled: bool
    frequency_bands: int
    min_frequency: float
    max_frequency: float
    margin_bottom: int


ALLOWED_INJECTION_METHODS: frozenset[str] = frozenset({"type", "clipboard_paste"})

# Pre-0.9.2 spellings, accepted with a warning (see _build_output).
_RENAMED_INJECTION_METHODS: dict[str, str] = {"text": "type", "paste": "clipboard_paste"}


@dataclass(frozen=True)
class OutputConfig:
    injection_method: str
    append_trailing_space: bool
    max_chars: int


@dataclass(frozen=True)
class ClipboardConfig:
    enabled: bool


@dataclass(frozen=True)
class IncrementalConfig:
    min_chunk_seconds: float
    agreement_n: int
    beam_size: int | None
    max_buffer_seconds: float


@dataclass(frozen=True)
class FormattingConfig:
    paragraph_pause_seconds: float
    capitalize_sentences: bool
    normalize_spacing: bool


@dataclass(frozen=True)
class UpdateConfig:
    check_on_startup: bool
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
    visualizer: VisualizerConfig
    output: OutputConfig
    clipboard: ClipboardConfig
    incremental: IncrementalConfig
    formatting: FormattingConfig
    update: UpdateConfig

    @classmethod
    def defaults(cls) -> Config:
        return cls(
            hotkey=HotkeyConfig(
                binding="KEY_RIGHTALT",
                toggle_threshold_seconds=0.5,
                double_tap_window_seconds=0.35,
                cancel_binding="KEY_ESC",
                device=None,
                trigger_mode="ptt",
            ),
            audio=AudioConfig(
                sample_rate=16000,
                frames_per_buffer=1024,
                input_device=None,
                max_recording_seconds=600,
                min_speech_rms=0.0005,
            ),
            asr=AsrConfig(
                model="Systran/faster-whisper-medium.en",
                language="en",
                beam_size=5,
                compute_type="int8",
                silence_threshold=0.6,
                vad_filter=True,
                max_new_tokens=128,
                mode="lazy",
                idle_unload_seconds=300,
                hotwords=None,
                initial_prompt=None,
            ),
            feedback=FeedbackConfig(
                volume=0.6,
                cues=dict.fromkeys(CUE_NAMES, None),
                mute=False,
            ),
            visualizer=VisualizerConfig(
                enabled=True,
                frequency_bands=16,
                min_frequency=80.0,
                max_frequency=8000.0,
                margin_bottom=32,
            ),
            output=OutputConfig(
                injection_method="clipboard_paste",
                append_trailing_space=True,
                max_chars=4096,
            ),
            clipboard=ClipboardConfig(enabled=True),
            incremental=IncrementalConfig(
                min_chunk_seconds=1.0,
                agreement_n=2,
                beam_size=None,
                max_buffer_seconds=20.0,
            ),
            formatting=FormattingConfig(
                paragraph_pause_seconds=0.0,
                capitalize_sentences=True,
                normalize_spacing=True,
            ),
            update=UpdateConfig(
                check_on_startup=True,
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

        # TOML 1.0 has no null; rewrite a bare `null` value to "" so users
        # can blank an optional key with `null`. Looks only at token
        # boundaries so the word "null" inside a string is left alone.
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

        # Whether the user set hotkey.cancel_binding themselves. A cancel
        # binding that came only from the defaults must not hard-fail on an
        # overlap with an explicit hotkey.binding (see _build_hotkey).
        user_hotkey = table.get("hotkey", {})
        cancel_explicit = isinstance(user_hotkey, dict) and bool(user_hotkey.get("cancel_binding"))

        table = _migrate_streaming_table(table)
        merged = _merge(asdict(cls.defaults()), table)
        return cls._from_dict(merged, path, cancel_explicit=cancel_explicit)

    @classmethod
    def write_default(cls, path: pathlib.Path) -> None:
        path.write_text(_format_default_toml(), encoding="utf-8")

    @classmethod
    def _from_dict(
        cls, table: dict[str, Any], path: pathlib.Path, *, cancel_explicit: bool = False
    ) -> Config:
        cfg = cls(
            hotkey=_build_hotkey(table["hotkey"], path, cancel_explicit=cancel_explicit),
            audio=_build_audio(table["audio"], path),
            asr=_build_asr(table["asr"], path),
            feedback=_build_feedback(table["feedback"], path),
            visualizer=_build_visualizer(table["visualizer"], path),
            output=_build_output(table["output"], path),
            clipboard=_build_clipboard(table["clipboard"], path),
            incremental=_build_incremental(table["incremental"], path),
            formatting=_build_formatting(table["formatting"], path),
            update=_build_update(table["update"], path),
        )
        _validate_cross_section(cfg, path)
        return cfg


def _validate_cross_section(cfg: Config, path: pathlib.Path) -> None:
    """Reject combinations that are individually valid but incoherent together.

    The per-section builders each see only their own table, so constraints
    that span sections have to be checked once the whole config is assembled.
    """
    if cfg.output.injection_method == "clipboard_paste" and not cfg.clipboard.enabled:
        # Paste mode delivers text *by* copying it and firing Shift+Insert, so
        # the clipboard is the transport, not a convenience copy. Silently
        # honouring clipboard.enabled here would fire the chord over stale
        # clipboard content; silently ignoring it would clobber the clipboard
        # the user asked us to leave alone. Neither is defensible, so the
        # combination is rejected rather than resolved.
        raise ConfigError(
            path,
            "clipboard.enabled",
            'must be true when output.injection_method = "clipboard_paste" '
            "(clipboard_paste mode delivers text via the clipboard); use "
            'injection_method = "type" '
            "to type without touching the clipboard",
        )


def _migrate_streaming_table(table: dict[str, Any]) -> dict[str, Any]:
    """Temporarily copy deprecated streaming tuning into incremental config."""
    legacy = table.get("streaming")
    if not isinstance(legacy, dict):
        return table
    logger.warning("[stenographer.streaming] is deprecated; use [stenographer.incremental]")
    if "enabled" in legacy:
        logger.warning(
            "streaming.enabled is deprecated and ignored; incremental decoding is always on"
        )
    migrated = dict(table)
    incremental = table.get("incremental")
    current = dict(incremental) if isinstance(incremental, dict) else {}
    for key in ("min_chunk_seconds", "agreement_n", "beam_size", "max_buffer_seconds"):
        if key in legacy and key not in current:
            current[key] = legacy[key]
            logger.warning("migrating deprecated streaming.%s to incremental.%s", key, key)
    migrated["incremental"] = current
    return migrated


_NULL_VALUE_RE = re.compile(r'(?<=\s=\s)null(?=[^\w"]|\Z)', re.MULTILINE)


def _build_hotkey(
    table: dict[str, Any], path: pathlib.Path, *, cancel_explicit: bool = False
) -> HotkeyConfig:
    binding = _expect_str(table, "binding", "hotkey.binding", path)
    if not binding:
        raise ConfigError(path, "hotkey.binding", "must be a non-empty string")
    threshold = _expect_number(
        table, "toggle_threshold_seconds", "hotkey.toggle_threshold_seconds", path
    )
    if not (0 < threshold <= 5):
        raise ConfigError(path, "hotkey.toggle_threshold_seconds", "must satisfy 0 < x <= 5")
    window = _expect_number(
        table, "double_tap_window_seconds", "hotkey.double_tap_window_seconds", path
    )
    if not (0 < window <= 2):
        raise ConfigError(path, "hotkey.double_tap_window_seconds", "must satisfy 0 < x <= 2")
    cancel_binding = _expect_str(table, "cancel_binding", "hotkey.cancel_binding", path)
    # Deferred import to avoid a hard evdev dependency at config-module
    # import time (mirrors how the main binding is parsed in cli.py).
    from stenographer.hotkey.binding import HotkeyBinding

    try:
        main = HotkeyBinding.parse(binding)
    except _BaseConfigError as exc:
        raise ConfigError(path, "hotkey.binding", str(exc)) from exc
    if cancel_binding:
        try:
            cancel = HotkeyBinding.parse(cancel_binding)
        except _BaseConfigError as exc:
            raise ConfigError(path, "hotkey.cancel_binding", str(exc)) from exc
        overlap = set(cancel.keys) & set(main.keys)
        if overlap:
            shared = ", ".join(sorted(overlap))
            if cancel_explicit:
                raise ConfigError(
                    path,
                    "hotkey.cancel_binding",
                    f"must not share keys with hotkey.binding: {shared}",
                )
            # The cancel binding came only from the defaults and collides
            # with the user's explicit hotkey.binding. Disable cancel rather
            # than refuse to start.
            logger.warning(
                "hotkey.cancel_binding default %r shares keys with hotkey.binding (%s); "
                "disabling cancel. Set hotkey.cancel_binding explicitly to re-enable.",
                cancel_binding,
                shared,
            )
            cancel_binding = ""
    device = _expect_optional_path(table, "device", "hotkey.device", path)
    trigger_mode = _expect_str(table, "trigger_mode", "hotkey.trigger_mode", path)
    if trigger_mode not in ALLOWED_TRIGGER_MODES:
        raise ConfigError(
            path, "hotkey.trigger_mode", f"must be one of {sorted(ALLOWED_TRIGGER_MODES)}"
        )
    return HotkeyConfig(
        binding=binding,
        toggle_threshold_seconds=threshold,
        double_tap_window_seconds=window,
        cancel_binding=cancel_binding,
        device=device,
        trigger_mode=trigger_mode,
    )


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
    max_recording_seconds = _expect_int(
        table, "max_recording_seconds", "audio.max_recording_seconds", path
    )
    if not (0 <= max_recording_seconds <= 86400):
        raise ConfigError(path, "audio.max_recording_seconds", "must satisfy 0 <= x <= 86400")
    min_speech_rms = _expect_number(table, "min_speech_rms", "audio.min_speech_rms", path)
    if not (0.0 <= min_speech_rms <= 1.0):
        raise ConfigError(path, "audio.min_speech_rms", "must satisfy 0.0 <= x <= 1.0")
    return AudioConfig(
        sample_rate=sample_rate,
        frames_per_buffer=frames_per_buffer,
        input_device=input_device,
        max_recording_seconds=max_recording_seconds,
        min_speech_rms=min_speech_rms,
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
    vad_filter = _expect_bool(table, "vad_filter", "asr.vad_filter", path)
    max_new_tokens = _expect_int(table, "max_new_tokens", "asr.max_new_tokens", path)
    if not (1 <= max_new_tokens <= 448):
        raise ConfigError(path, "asr.max_new_tokens", "must satisfy 1 <= x <= 448")
    mode = _expect_str(table, "mode", "asr.mode", path)
    if mode not in ALLOWED_ASR_MODES:
        raise ConfigError(path, "asr.mode", f"must be one of {sorted(ALLOWED_ASR_MODES)}")
    idle_unload_seconds = _expect_int(table, "idle_unload_seconds", "asr.idle_unload_seconds", path)
    if not (0 <= idle_unload_seconds <= 86400):
        raise ConfigError(path, "asr.idle_unload_seconds", "must satisfy 0 <= x <= 86400")
    hotwords = _expect_optional_str(table, "hotwords", "asr.hotwords", path)
    initial_prompt = _expect_optional_str(table, "initial_prompt", "asr.initial_prompt", path)
    return AsrConfig(
        model=model,
        language=language,
        beam_size=beam_size,
        compute_type=compute_type,
        silence_threshold=silence_threshold,
        vad_filter=vad_filter,
        max_new_tokens=max_new_tokens,
        mode=mode,
        idle_unload_seconds=idle_unload_seconds,
        hotwords=hotwords,
        initial_prompt=initial_prompt,
    )


def _build_feedback(table: dict[str, Any], path: pathlib.Path) -> FeedbackConfig:
    volume = _expect_number(table, "volume", "feedback.volume", path)
    if not (0.0 <= volume <= 1.0):
        raise ConfigError(path, "feedback.volume", "must satisfy 0.0 <= x <= 1.0")
    cues = _build_cues(table.get("cues", {}), path)
    mute = _expect_bool(table, "mute", "feedback.mute", path)
    return FeedbackConfig(volume=volume, cues=cues, mute=mute)


def _build_visualizer(table: dict[str, Any], path: pathlib.Path) -> VisualizerConfig:
    enabled = _expect_bool(table, "enabled", "visualizer.enabled", path)
    frequency_bands = _expect_int(table, "frequency_bands", "visualizer.frequency_bands", path)
    if not (6 <= frequency_bands <= 32):
        raise ConfigError(path, "visualizer.frequency_bands", "must satisfy 6 <= x <= 32")
    min_frequency = _expect_number(table, "min_frequency", "visualizer.min_frequency", path)
    if not (20 <= min_frequency <= 2000):
        raise ConfigError(path, "visualizer.min_frequency", "must satisfy 20 <= x <= 2000")
    max_frequency = _expect_number(table, "max_frequency", "visualizer.max_frequency", path)
    if not (1000 <= max_frequency <= 24000):
        raise ConfigError(path, "visualizer.max_frequency", "must satisfy 1000 <= x <= 24000")
    if max_frequency <= min_frequency:
        raise ConfigError(
            path,
            "visualizer.max_frequency",
            "must be greater than visualizer.min_frequency",
        )
    margin_bottom = _expect_int(table, "margin_bottom", "visualizer.margin_bottom", path)
    if not (0 <= margin_bottom <= 500):
        raise ConfigError(path, "visualizer.margin_bottom", "must satisfy 0 <= x <= 500")
    return VisualizerConfig(
        enabled=enabled,
        frequency_bands=frequency_bands,
        min_frequency=min_frequency,
        max_frequency=max_frequency,
        margin_bottom=margin_bottom,
    )


def _build_cues(raw: Any, path: pathlib.Path) -> dict[str, str | None]:
    if not isinstance(raw, dict):
        raise ConfigError(path, "feedback.cues", f"must be a table, got {type(raw).__name__}")
    cues: dict[str, str | None] = {}
    for name, value in raw.items():
        if name not in CUE_NAMES:
            raise ConfigError(
                path,
                f"feedback.cues.{name}",
                f"unknown cue name; must be one of {', '.join(CUE_NAMES)}",
            )
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
    renamed = _RENAMED_INJECTION_METHODS.get(injection_method)
    if renamed is not None:
        # Both values were renamed in 0.9.2. Rejecting them would hard-fail
        # every config written before that release -- including the shipped
        # default -- at daemon startup, so warn and accept the old spelling.
        logger.warning(
            'output.injection_method = "%s" is deprecated; use "%s"', injection_method, renamed
        )
        injection_method = renamed
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


def _build_incremental(table: dict[str, Any], path: pathlib.Path) -> IncrementalConfig:
    min_chunk_seconds = _expect_number(
        table, "min_chunk_seconds", "incremental.min_chunk_seconds", path
    )
    if not (0.25 <= min_chunk_seconds <= 5):
        raise ConfigError(path, "incremental.min_chunk_seconds", "must satisfy 0.25 <= x <= 5")
    agreement_n = _expect_int(table, "agreement_n", "incremental.agreement_n", path)
    if not (2 <= agreement_n <= 4):
        raise ConfigError(path, "incremental.agreement_n", "must satisfy 2 <= x <= 4")
    beam_size = _expect_optional_int(table, "beam_size", "incremental.beam_size", path)
    if beam_size is not None and not (1 <= beam_size <= 10):
        raise ConfigError(path, "incremental.beam_size", "must be null or satisfy 1 <= x <= 10")
    max_buffer_seconds = _expect_number(
        table, "max_buffer_seconds", "incremental.max_buffer_seconds", path
    )
    if not (5 <= max_buffer_seconds <= 120):
        raise ConfigError(path, "incremental.max_buffer_seconds", "must satisfy 5 <= x <= 120")
    return IncrementalConfig(
        min_chunk_seconds=min_chunk_seconds,
        agreement_n=agreement_n,
        beam_size=beam_size,
        max_buffer_seconds=max_buffer_seconds,
    )


def _build_formatting(table: dict[str, Any], path: pathlib.Path) -> FormattingConfig:
    paragraph_pause_seconds = _expect_number(
        table, "paragraph_pause_seconds", "formatting.paragraph_pause_seconds", path
    )
    if not (0 <= paragraph_pause_seconds <= 10):
        raise ConfigError(path, "formatting.paragraph_pause_seconds", "must satisfy 0 <= x <= 10")
    capitalize_sentences = _expect_bool(
        table, "capitalize_sentences", "formatting.capitalize_sentences", path
    )
    normalize_spacing = _expect_bool(
        table, "normalize_spacing", "formatting.normalize_spacing", path
    )
    return FormattingConfig(
        paragraph_pause_seconds=paragraph_pause_seconds,
        capitalize_sentences=capitalize_sentences,
        normalize_spacing=normalize_spacing,
    )


def _build_update(table: dict[str, Any], path: pathlib.Path) -> UpdateConfig:
    check_on_startup = _expect_bool(table, "check_on_startup", "update.check_on_startup", path)
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
        check_on_startup=check_on_startup,
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


def _expect_optional_int(table: dict, key: str, dotted: str, path: pathlib.Path) -> int | None:
    value = table.get(key)
    if value is None or value == "":  # `key = null` is rewritten to "" at load
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(
            path,
            dotted,
            f"expected int or null, got {type(value).__name__}: {value!r}",
        )
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
    v = cfg.visualizer
    o = cfg.output
    c = cfg.clipboard
    i = cfg.incremental
    fm = cfg.formatting
    u = cfg.update
    lines: list[str] = [
        "# stenographer configuration",
        "",
        "[stenographer]",
        "",
        "# Hotkey",
        f"hotkey.binding = {_toml_str(h.binding)}",
        f"hotkey.toggle_threshold_seconds = {h.toggle_threshold_seconds}",
        f"hotkey.double_tap_window_seconds = {h.double_tap_window_seconds}",
        f"hotkey.cancel_binding = {_toml_str(h.cancel_binding)}",
        f"hotkey.device = {_toml_optional(h.device)}",
        f"hotkey.trigger_mode = {_toml_str(h.trigger_mode)}",
        "",
        "# Audio capture",
        f"audio.sample_rate = {a.sample_rate}",
        f"audio.frames_per_buffer = {a.frames_per_buffer}",
        f"audio.input_device = {_toml_optional(a.input_device)}",
        f"audio.max_recording_seconds = {a.max_recording_seconds}",
        "# 0 disables the pre-decode energy gate",
        f"audio.min_speech_rms = {a.min_speech_rms}",
        "",
        "# ASR",
        f"asr.model = {_toml_str(r.model)}",
        f"asr.language = {_toml_str(r.language)}",
        f"asr.beam_size = {r.beam_size}",
        f"asr.compute_type = {_toml_str(r.compute_type)}",
        f"asr.silence_threshold = {r.silence_threshold}",
        f"asr.vad_filter = {_toml_bool(r.vad_filter)}",
        f"asr.max_new_tokens = {r.max_new_tokens}",
        f"asr.mode = {_toml_str(r.mode)}",
        f"asr.idle_unload_seconds = {r.idle_unload_seconds}",
        '# hotwords: proper nouns / jargon to bias recognition toward, e.g. "wtype, Wayland"',
        f"asr.hotwords = {_toml_optional(r.hotwords)}",
        "# initial_prompt: free-text context prepended to decoding (style/domain hints)",
        f"asr.initial_prompt = {_toml_optional(r.initial_prompt)}",
        "",
        "# Audio feedback",
        f"feedback.volume = {f.volume}",
        f"feedback.mute = {_toml_bool(f.mute)}",
        "",
        "# Bottom-center Wayland spectrum overlay",
        f"visualizer.enabled = {_toml_bool(v.enabled)}",
        f"visualizer.frequency_bands = {v.frequency_bands}",
        f"visualizer.min_frequency = {v.min_frequency}",
        f"visualizer.max_frequency = {v.max_frequency}",
        f"visualizer.margin_bottom = {v.margin_bottom}",
        "",
        "# Text output",
        f"output.injection_method = {_toml_str(o.injection_method)}",
        f"output.append_trailing_space = {_toml_bool(o.append_trailing_space)}",
        f"output.max_chars = {o.max_chars}",
        "",
        "# Clipboard",
        f"clipboard.enabled = {_toml_bool(c.enabled)}",
        "",
        "# Incremental word-level decoding (always enabled).",
        "# min_chunk_seconds / beam_size are the CPU knobs if re-decodes lag.",
        f"incremental.min_chunk_seconds = {i.min_chunk_seconds}",
        f"incremental.agreement_n = {i.agreement_n}",
        "incremental.beam_size = null"
        if i.beam_size is None
        else f"incremental.beam_size = {i.beam_size}",
        f"incremental.max_buffer_seconds = {i.max_buffer_seconds}",
        "",
        "# Formatting heuristics (applies to all output modes)",
        f"formatting.paragraph_pause_seconds = {fm.paragraph_pause_seconds}",
        f"formatting.capitalize_sentences = {_toml_bool(fm.capitalize_sentences)}",
        f"formatting.normalize_spacing = {_toml_bool(fm.normalize_spacing)}",
        "",
        "# Update",
        f"update.check_on_startup = {_toml_bool(u.check_on_startup)}",
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
