# SPDX-License-Identifier: GPL-3.0-or-later
"""Validating sections: the per-table `_build_*` functions, the cross-section
check, and the deprecated-`[streaming]` migration."""

from __future__ import annotations

import logging
import os
import pathlib
from typing import TYPE_CHECKING, Any

from stenographer.config.schema import (
    _RENAMED_INJECTION_METHODS,
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
from stenographer.config.sections import _Section
from stenographer.errors import ConfigError as _BaseConfigError

if TYPE_CHECKING:
    from stenographer.config import Config

logger = logging.getLogger(__name__)


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


def _build_hotkey(
    table: dict[str, Any], path: pathlib.Path, *, cancel_explicit: bool = False
) -> HotkeyConfig:
    section = _Section(table, "hotkey", path)
    binding = section.str("binding")
    if not binding:
        raise ConfigError(path, "hotkey.binding", "must be a non-empty string")
    threshold = section.number("toggle_threshold_seconds")
    if not (0 < threshold <= 5):
        raise ConfigError(path, "hotkey.toggle_threshold_seconds", "must satisfy 0 < x <= 5")
    window = section.number("double_tap_window_seconds")
    if not (0 < window <= 2):
        raise ConfigError(path, "hotkey.double_tap_window_seconds", "must satisfy 0 < x <= 2")
    cancel_binding = section.str("cancel_binding")
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
    device = section.optional_path("device")
    trigger_mode = section.str("trigger_mode")
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
    section = _Section(table, "audio", path)
    sample_rate = section.int("sample_rate")
    if sample_rate not in ALLOWED_SAMPLE_RATES:
        raise ConfigError(
            path,
            "audio.sample_rate",
            f"must be one of {sorted(ALLOWED_SAMPLE_RATES)}",
        )
    frames_per_buffer = section.int("frames_per_buffer")
    if not (64 <= frames_per_buffer <= 8192):
        raise ConfigError(path, "audio.frames_per_buffer", "must satisfy 64 <= x <= 8192")
    input_device = section.optional_str("input_device")
    max_recording_seconds = section.int("max_recording_seconds")
    if not (0 <= max_recording_seconds <= 86400):
        raise ConfigError(path, "audio.max_recording_seconds", "must satisfy 0 <= x <= 86400")
    min_speech_rms = section.number("min_speech_rms")
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
    section = _Section(table, "asr", path)
    model = section.str("model")
    language = section.str("language")
    beam_size = section.int("beam_size")
    if not (1 <= beam_size <= 10):
        raise ConfigError(path, "asr.beam_size", "must satisfy 1 <= x <= 10")
    compute_type = section.str("compute_type")
    if compute_type not in ALLOWED_COMPUTE_TYPES:
        raise ConfigError(
            path,
            "asr.compute_type",
            f"must be one of {sorted(ALLOWED_COMPUTE_TYPES)}",
        )
    silence_threshold = section.number("silence_threshold")
    if not (0.0 <= silence_threshold <= 1.0):
        raise ConfigError(path, "asr.silence_threshold", "must satisfy 0.0 <= x <= 1.0")
    vad_filter = section.bool("vad_filter")
    max_new_tokens = section.int("max_new_tokens")
    if not (1 <= max_new_tokens <= 448):
        raise ConfigError(path, "asr.max_new_tokens", "must satisfy 1 <= x <= 448")
    cpu_threads = section.int("cpu_threads")
    if not (0 <= cpu_threads <= 64):
        raise ConfigError(path, "asr.cpu_threads", "must satisfy 0 <= x <= 64")
    mode = section.str("mode")
    if mode not in ALLOWED_ASR_MODES:
        raise ConfigError(path, "asr.mode", f"must be one of {sorted(ALLOWED_ASR_MODES)}")
    idle_unload_seconds = section.int("idle_unload_seconds")
    if not (0 <= idle_unload_seconds <= 86400):
        raise ConfigError(path, "asr.idle_unload_seconds", "must satisfy 0 <= x <= 86400")
    hotwords = section.optional_str("hotwords")
    initial_prompt = section.optional_str("initial_prompt")
    return AsrConfig(
        model=model,
        language=language,
        beam_size=beam_size,
        compute_type=compute_type,
        silence_threshold=silence_threshold,
        vad_filter=vad_filter,
        max_new_tokens=max_new_tokens,
        cpu_threads=cpu_threads,
        mode=mode,
        idle_unload_seconds=idle_unload_seconds,
        hotwords=hotwords,
        initial_prompt=initial_prompt,
    )


def _build_feedback(table: dict[str, Any], path: pathlib.Path) -> FeedbackConfig:
    section = _Section(table, "feedback", path)
    volume = section.number("volume")
    if not (0.0 <= volume <= 1.0):
        raise ConfigError(path, "feedback.volume", "must satisfy 0.0 <= x <= 1.0")
    cues = _build_cues(table.get("cues", {}), path)
    mute = section.bool("mute")
    return FeedbackConfig(volume=volume, cues=cues, mute=mute)


def _build_visualizer(table: dict[str, Any], path: pathlib.Path) -> VisualizerConfig:
    section = _Section(table, "visualizer", path)
    enabled = section.bool("enabled")
    frequency_bands = section.int("frequency_bands")
    if not (6 <= frequency_bands <= 32):
        raise ConfigError(path, "visualizer.frequency_bands", "must satisfy 6 <= x <= 32")
    min_frequency = section.number("min_frequency")
    if not (20 <= min_frequency <= 2000):
        raise ConfigError(path, "visualizer.min_frequency", "must satisfy 20 <= x <= 2000")
    max_frequency = section.number("max_frequency")
    if not (1000 <= max_frequency <= 24000):
        raise ConfigError(path, "visualizer.max_frequency", "must satisfy 1000 <= x <= 24000")
    if max_frequency <= min_frequency:
        raise ConfigError(
            path,
            "visualizer.max_frequency",
            "must be greater than visualizer.min_frequency",
        )
    margin_bottom = section.int("margin_bottom")
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
    section = _Section(table, "output", path)
    injection_method = section.str("injection_method")
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
    append_trailing_space = section.bool("append_trailing_space")
    max_chars = section.int("max_chars")
    if not (1 <= max_chars <= 100000):
        raise ConfigError(path, "output.max_chars", "must satisfy 1 <= x <= 100000")
    return OutputConfig(
        injection_method=injection_method,
        append_trailing_space=append_trailing_space,
        max_chars=max_chars,
    )


def _build_clipboard(table: dict[str, Any], path: pathlib.Path) -> ClipboardConfig:
    enabled = _Section(table, "clipboard", path).bool("enabled")
    return ClipboardConfig(enabled=enabled)


def _build_incremental(table: dict[str, Any], path: pathlib.Path) -> IncrementalConfig:
    section = _Section(table, "incremental", path)
    min_chunk_seconds = section.number("min_chunk_seconds")
    if not (0.25 <= min_chunk_seconds <= 5):
        raise ConfigError(path, "incremental.min_chunk_seconds", "must satisfy 0.25 <= x <= 5")
    agreement_n = section.int("agreement_n")
    if not (2 <= agreement_n <= 4):
        raise ConfigError(path, "incremental.agreement_n", "must satisfy 2 <= x <= 4")
    beam_size = section.optional_int("beam_size")
    if beam_size is not None and not (1 <= beam_size <= 10):
        raise ConfigError(path, "incremental.beam_size", "must be null or satisfy 1 <= x <= 10")
    max_buffer_seconds = section.number("max_buffer_seconds")
    if not (5 <= max_buffer_seconds <= 120):
        raise ConfigError(path, "incremental.max_buffer_seconds", "must satisfy 5 <= x <= 120")
    interim_timeout_seconds = section.number("interim_timeout_seconds")
    if not (1 <= interim_timeout_seconds <= 60):
        raise ConfigError(path, "incremental.interim_timeout_seconds", "must satisfy 1 <= x <= 60")
    release_timeout_seconds = section.number("release_timeout_seconds")
    if not (1 <= release_timeout_seconds <= 60):
        raise ConfigError(path, "incremental.release_timeout_seconds", "must satisfy 1 <= x <= 60")
    return IncrementalConfig(
        min_chunk_seconds=min_chunk_seconds,
        agreement_n=agreement_n,
        beam_size=beam_size,
        max_buffer_seconds=max_buffer_seconds,
        interim_timeout_seconds=interim_timeout_seconds,
        release_timeout_seconds=release_timeout_seconds,
    )


def _build_formatting(table: dict[str, Any], path: pathlib.Path) -> FormattingConfig:
    section = _Section(table, "formatting", path)
    paragraph_pause_seconds = section.number("paragraph_pause_seconds")
    if not (0 <= paragraph_pause_seconds <= 10):
        raise ConfigError(path, "formatting.paragraph_pause_seconds", "must satisfy 0 <= x <= 10")
    capitalize_sentences = section.bool("capitalize_sentences")
    normalize_spacing = section.bool("normalize_spacing")
    return FormattingConfig(
        paragraph_pause_seconds=paragraph_pause_seconds,
        capitalize_sentences=capitalize_sentences,
        normalize_spacing=normalize_spacing,
    )


def _build_update(table: dict[str, Any], path: pathlib.Path) -> UpdateConfig:
    section = _Section(table, "update", path)
    check_on_startup = section.bool("check_on_startup")
    repo = section.str("repo")
    if "/" not in repo:
        raise ConfigError(path, "update.repo", f"must be OWNER/REPO, got {repo!r}")
    channel = section.str("channel")
    if channel not in ALLOWED_UPDATE_CHANNELS:
        raise ConfigError(
            path,
            "update.channel",
            f"must be one of {sorted(ALLOWED_UPDATE_CHANNELS)}",
        )
    base_url = section.str("base_url")
    if not base_url.startswith(("http://", "https://")):
        raise ConfigError(
            path,
            "update.base_url",
            f"must be an http(s) URL, got {base_url!r}",
        )
    asset_pattern = section.str("asset_pattern")
    if "{version}" not in asset_pattern:
        raise ConfigError(
            path,
            "update.asset_pattern",
            "must contain the literal '{version}'",
        )
    timeout_seconds = section.int("timeout_seconds")
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
