# SPDX-License-Identifier: GPL-3.0-or-later
"""Construct validated configuration sections without altering their schema."""

from __future__ import annotations

import pathlib

from stenographer.lib.config.constants import (
    ALLOWED_COMPUTE_TYPES,
    ALLOWED_HOTKEY_MODES,
    ALLOWED_LOG_LEVELS,
    ALLOWED_REFINE_SCHEMES,
    MAX_REFINE_WORDS,
    MIN_REFINE_WORDS,
    SOUND_PACK_PATTERN,
)
from stenographer.lib.config.errors import ConfigError
from stenographer.lib.config.models import (
    AsrConfig,
    AudioConfig,
    FeedbackConfig,
    HotkeyConfig,
    RefineConfig,
)
from stenographer.lib.config.reader import _Reader
from stenographer.lib.refine.endpoints import host_name, normalize_host, userinfo


def _build_hotkey(table: dict, path: pathlib.Path) -> HotkeyConfig:
    r = _Reader(table, path, "hotkey")
    binding = r.str("binding")
    if not binding:
        raise ConfigError(path, "hotkey.binding", "must be non-empty")
    return HotkeyConfig(
        binding,
        r.optional_str("device"),
        r.optional_str("cancel_binding"),
        r.choice("mode", ALLOWED_HOTKEY_MODES),
        r.ranged_number("hybrid_threshold_seconds", 0.05, 5.0),
    )


def _build_audio(table: dict, path: pathlib.Path) -> AudioConfig:
    r = _Reader(table, path, "audio")
    return AudioConfig(
        r.optional_str("input_device"),
        r.ranged_number("min_speech_rms", 0.0, 1.0),
        r.ranged_int("max_recording_seconds", 1, 86400),
    )


def _build_asr(table: dict, path: pathlib.Path) -> AsrConfig:
    r = _Reader(table, path, "asr")
    return AsrConfig(
        model=r.str("model"),
        compute_type=r.choice("compute_type", ALLOWED_COMPUTE_TYPES),
        beam_size=r.ranged_int("beam_size", 1, 10),
        hotwords=r.optional_str("hotwords"),
        initial_prompt=r.optional_str("initial_prompt"),
        vad_filter=r.bool("vad_filter"),
        silence_threshold=r.ranged_number("silence_threshold", 0.0, 1.0),
        idle_unload_seconds=r.ranged_int("idle_unload_seconds", 0, 86400),
        cpu_threads=r.ranged_int("cpu_threads", 0, 64),
    )


def _build_feedback(table: dict, path: pathlib.Path) -> FeedbackConfig:
    r = _Reader(table, path, "feedback")
    sound_pack = r.str("sound_pack")
    if SOUND_PACK_PATTERN.fullmatch(sound_pack) is None:
        raise ConfigError(
            path,
            "feedback.sound_pack",
            "must match [a-z0-9][a-z0-9-]{0,63}",
        )
    return FeedbackConfig(
        volume=r.ranged_number("volume", 0.0, 1.0),
        mute=r.bool("mute"),
        overlay=r.bool("overlay"),
        update_check=r.bool("update_check"),
        spectrum_floor_dbfs=r.spectrum_floor("spectrum_floor_dbfs"),
        sound_pack=sound_pack,
        log_level=r.folded_choice("log_level", ALLOWED_LOG_LEVELS),
    )


def _build_refine(table: dict, path: pathlib.Path) -> RefineConfig:
    r = _Reader(table, path, "refine")
    host = normalize_host(r.str("host"))
    scheme = host.partition("://")[0]
    if scheme not in ALLOWED_REFINE_SCHEMES:
        raise ConfigError(
            path,
            "refine.host",
            f"must be an http:// or https:// URL, got {r.str('host')!r}",
        )
    if not host_name(host):
        raise ConfigError(path, "refine.host", "must name a host")
    if userinfo(host):
        # Ollama has no authentication to use these for, and the daemon reports
        # its configured host at start; a secret in the URL would be a secret
        # in the log. The message never echoes the value.
        raise ConfigError(path, "refine.host", "must not embed credentials")
    model = r.str("model").strip()
    if not model:
        raise ConfigError(path, "refine.model", "must be non-empty")
    return RefineConfig(
        enabled=r.bool("enabled"),
        host=host,
        model=model,
        min_words=r.ranged_int("min_words", MIN_REFINE_WORDS, MAX_REFINE_WORDS),
        structured_output=r.bool("structured_output"),
    )


def _merge(base: dict, overlay: dict) -> dict:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result
