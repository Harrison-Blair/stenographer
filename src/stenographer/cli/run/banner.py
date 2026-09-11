# SPDX-License-Identifier: GPL-3.0-or-later
"""Privacy-preserving startup configuration and backend reporting."""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

from stenographer.lib.logging.pipeline import fmt_event

if TYPE_CHECKING:
    from pathlib import Path

    from stenographer.cli.shared.capabilities import Capabilities
    from stenographer.lib.config.models import Config
    from stenographer.lib.platform.provider import Platform
    from stenographer.overlay.capabilities.models import OverlayCapability

log = logging.getLogger("stenographer.lib.daemon")


def _overlay_backend_name(overlay: OverlayCapability) -> str:
    """Name the overlay backend the daemon will actually get. PURE."""
    if not overlay.enabled:
        return "disabled"
    if overlay.backend is not None:
        return overlay.backend.value
    if overlay.reason is not None:
        return f"unavailable_{overlay.reason.value}"
    return "unknown"


def _shown(value: object) -> object:
    """Render an unset optional visibly: a banner key must never go missing."""
    if value is None:
        return "<unset>"
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, tuple):
        return ",".join(f"{item:g}" for item in value)
    return value


def _log_banner(cfg: Config, plat: Platform, caps: Capabilities, config_path: Path) -> None:
    """Record the whole effective configuration once, at INFO.

    A report that does not say what the daemon was actually configured with
    forces every question back to the reporter, so this is written before the
    startup gate can refuse — a refused start is exactly when it is wanted.

    ``asr.hotwords`` and ``asr.initial_prompt`` are the only config values that
    hold arbitrary user prose; they are reported as sizes. Everything else is
    the user's own settings, which rule 6 does not restrict.
    """
    from stenographer._version import __version__
    from stenographer.lib.transcribe.decode import resolve_cpu_threads

    version = sys.version_info
    log.info(
        fmt_event(
            "banner",
            "build",
            version=__version__,
            python=f"{version.major}.{version.minor}.{version.micro}",
            platform=plat.name,
            config=config_path,
        )
    )
    log.info(
        fmt_event(
            "banner",
            "backends",
            clipboard=_shown(caps.clipboard_backend),
            overlay=_overlay_backend_name(caps.overlay),
            cue_player=_shown(caps.cue_player),
        )
    )
    log.info(
        fmt_event(
            "banner",
            "config_hotkey",
            binding=cfg.hotkey.binding,
            cancel_binding=_shown(cfg.hotkey.cancel_binding),
            device=_shown(cfg.hotkey.device),
            mode=cfg.hotkey.mode,
            hybrid_threshold_seconds=cfg.hotkey.hybrid_threshold_seconds,
        )
    )
    log.info(
        fmt_event(
            "banner",
            "config_audio",
            input_device=_shown(cfg.audio.input_device),
            min_speech_rms=cfg.audio.min_speech_rms,
            max_recording_seconds=cfg.audio.max_recording_seconds,
        )
    )
    asr = cfg.asr
    log.info(
        fmt_event(
            "banner",
            "config_asr",
            model=asr.model,
            compute_type=asr.compute_type,
            beam_size=asr.beam_size,
            hotwords_words=len((asr.hotwords or "").split()),
            initial_prompt_chars=len(asr.initial_prompt or ""),
            vad_filter=_shown(asr.vad_filter),
            silence_threshold=asr.silence_threshold,
            idle_unload_seconds=asr.idle_unload_seconds,
            cpu_threads=asr.cpu_threads,
            resolved_cpu_threads=resolve_cpu_threads(asr.cpu_threads, plat.physical_core_count()),
        )
    )
    feedback = cfg.feedback
    log.info(
        fmt_event(
            "banner",
            "config_feedback",
            volume=feedback.volume,
            mute=_shown(feedback.mute),
            overlay=_shown(feedback.overlay),
            update_check=_shown(feedback.update_check),
            spectrum_floor_dbfs=_shown(feedback.spectrum_floor_dbfs),
            sound_pack=feedback.sound_pack,
            log_level=feedback.log_level,
        )
    )
    log.info(
        fmt_event(
            "banner",
            "config_analytics",
            enabled=int(cfg.analytics.enabled),
            resource_profiling=int(cfg.analytics.resource_profiling),
        )
    )
