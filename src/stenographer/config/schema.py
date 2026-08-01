# SPDX-License-Identifier: GPL-3.0-or-later
"""What a config *is*: the frozen dataclasses, the enum-like allow-lists, and
the key-scoped :class:`ConfigError` they are validated against."""

from __future__ import annotations

import pathlib
import typing
from dataclasses import dataclass

from stenographer.audio.feedback import CueName
from stenographer.errors import ConfigError as _BaseConfigError

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
    cpu_threads: int
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
    interim_timeout_seconds: float = 5.0
    release_timeout_seconds: float = 8.0


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
