# SPDX-License-Identifier: GPL-3.0-or-later
"""TOML config schema and loading for stenographer.

The package splits by lifecycle -- :mod:`schema` (what a config is),
:mod:`sections` (reading one table), :mod:`builders` (validating sections),
and :mod:`serialize` (writing defaults) -- while this module owns the
:class:`Config` lifecycle (defaults/load/write) and re-exports the public API.
"""

from __future__ import annotations

import os
import pathlib
import tomllib
from dataclasses import asdict, dataclass
from typing import Any

from stenographer.config.builders import (
    _build_asr,
    _build_audio,
    _build_clipboard,
    _build_feedback,
    _build_formatting,
    _build_hotkey,
    _build_incremental,
    _build_output,
    _build_update,
    _build_visualizer,
    _migrate_streaming_table,
    _validate_cross_section,
)
from stenographer.config.schema import (
    ALLOWED_ASR_MODES,
    ALLOWED_COMPUTE_TYPES,
    ALLOWED_INJECTION_METHODS,
    ALLOWED_SAMPLE_RATES,
    ALLOWED_TRIGGER_MODES,
    ALLOWED_UPDATE_CHANNELS,
    CUE_NAMES,
    AsrConfig,
    AudioConfig,
    ClipboardConfig,
    ConfigError,
    FeedbackConfig,
    FormattingConfig,
    HotkeyConfig,
    IncrementalConfig,
    OutputConfig,
    UpdateConfig,
    VisualizerConfig,
)
from stenographer.config.sections import _NULL_VALUE_RE, _merge
from stenographer.config.serialize import _format_default_toml

__all__ = [
    "ALLOWED_ASR_MODES",
    "ALLOWED_COMPUTE_TYPES",
    "ALLOWED_INJECTION_METHODS",
    "ALLOWED_SAMPLE_RATES",
    "ALLOWED_TRIGGER_MODES",
    "ALLOWED_UPDATE_CHANNELS",
    "CUE_NAMES",
    "AsrConfig",
    "AudioConfig",
    "ClipboardConfig",
    "Config",
    "ConfigError",
    "FeedbackConfig",
    "FormattingConfig",
    "HotkeyConfig",
    "IncrementalConfig",
    "OutputConfig",
    "UpdateConfig",
    "VisualizerConfig",
    "load_or_default",
    "resolve_config_path",
]


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
                beam_size=1,
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
                interim_timeout_seconds=5.0,
                release_timeout_seconds=8.0,
            ),
            formatting=FormattingConfig(
                paragraph_pause_seconds=0.0,
                capitalize_sentences=True,
                normalize_spacing=True,
            ),
            update=UpdateConfig(
                check_on_startup=False,
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
