# SPDX-License-Identifier: GPL-3.0-or-later
"""Frozen configuration sections and their validated aggregate."""

from __future__ import annotations

import pathlib
import tomllib
from dataclasses import asdict, dataclass

from stenographer.lib.config.constants import DEFAULT_SOUND_PACK, SpectrumFloor
from stenographer.lib.config.defaults import default_toml
from stenographer.lib.config.errors import ConfigError
from stenographer.lib.config.reader import _Reader
from stenographer.lib.refine.prompt import DEFAULT_MODEL, DEFAULT_STRUCTURED_OUTPUT


@dataclass(frozen=True)
class HotkeyConfig:
    binding: str
    device: str | None
    cancel_binding: str | None = "KEY_ESC"
    mode: str = "hybrid"
    hybrid_threshold_seconds: float = 0.5


@dataclass(frozen=True)
class AudioConfig:
    input_device: str | None
    min_speech_rms: float
    max_recording_seconds: int


@dataclass(frozen=True)
class AsrConfig:
    model: str
    compute_type: str
    beam_size: int
    hotwords: str | None
    initial_prompt: str | None
    vad_filter: bool
    silence_threshold: float
    idle_unload_seconds: int
    cpu_threads: int


@dataclass(frozen=True)
class FeedbackConfig:
    volume: float
    mute: bool
    overlay: bool = True
    update_check: bool = True
    spectrum_floor_dbfs: SpectrumFloor = -45.0
    sound_pack: str = DEFAULT_SOUND_PACK
    log_level: str = "info"


@dataclass(frozen=True)
class RefineConfig:
    """The optional local-model cleanup pass. Off, and loopback, by default."""

    enabled: bool = False
    host: str = "http://127.0.0.1:11434"
    model: str = DEFAULT_MODEL
    min_words: int = 10
    structured_output: bool = DEFAULT_STRUCTURED_OUTPUT


@dataclass(frozen=True)
class AnalyticsConfig:
    enabled: bool = True
    resource_profiling: bool = True


@dataclass(frozen=True)
class Config:
    hotkey: HotkeyConfig
    audio: AudioConfig
    asr: AsrConfig
    feedback: FeedbackConfig
    refine: RefineConfig = RefineConfig()
    analytics: AnalyticsConfig = AnalyticsConfig()

    @classmethod
    def defaults(cls) -> Config:
        return cls(
            hotkey=HotkeyConfig(
                binding="KEY_RIGHTCTRL",
                device=None,
                cancel_binding="KEY_ESC",
                mode="hybrid",
                hybrid_threshold_seconds=0.5,
            ),
            audio=AudioConfig(input_device=None, min_speech_rms=0.0005, max_recording_seconds=600),
            asr=AsrConfig(
                model="Systran/faster-whisper-medium.en",
                compute_type="int8",
                beam_size=1,
                hotwords=None,
                initial_prompt=None,
                vad_filter=True,
                silence_threshold=0.6,
                idle_unload_seconds=900,
                cpu_threads=0,
            ),
            feedback=FeedbackConfig(
                volume=0.6,
                mute=False,
                overlay=True,
                update_check=True,
                spectrum_floor_dbfs=-45.0,
                sound_pack=DEFAULT_SOUND_PACK,
                log_level="info",
            ),
        )

    @classmethod
    def load(cls, path: pathlib.Path) -> Config:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as e:
            raise ConfigError(path, "<file>", f"cannot read: {e}") from e

        return cls.loads(content, path)

    @classmethod
    def loads(cls, content: str, path: pathlib.Path = pathlib.Path("<memory>")) -> Config:
        """Load and validate TOML already held in memory."""

        from stenographer.lib.config.validation import (
            _build_asr,
            _build_audio,
            _build_feedback,
            _build_hotkey,
            _build_refine,
            _merge,
        )

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
        for name in ("hotkey", "audio", "asr", "feedback", "refine", "analytics"):
            if not isinstance(merged[name], dict):
                raise ConfigError(path, name, f"must be a table, got {type(merged[name]).__name__}")
        return cls(
            hotkey=_build_hotkey(merged["hotkey"], path),
            audio=_build_audio(merged["audio"], path),
            asr=_build_asr(merged["asr"], path),
            feedback=_build_feedback(merged["feedback"], path),
            refine=_build_refine(merged["refine"], path),
            analytics=AnalyticsConfig(
                enabled=_Reader(merged["analytics"], path, "analytics").bool("enabled"),
                resource_profiling=_Reader(merged["analytics"], path, "analytics").bool(
                    "resource_profiling"
                ),
            ),
        )

    @classmethod
    def write_default(cls, path: pathlib.Path) -> None:
        # Bytes, not text mode: setup writes LF bytes, and a CRLF default on
        # Windows would make the first setup save always rewrite the file.
        path.write_bytes(default_toml().encode("utf-8"))
