# SPDX-License-Identifier: GPL-3.0-or-later
"""Privacy-preserving startup configuration and backend reporting."""

from __future__ import annotations

import dataclasses
import logging
import sys
from typing import TYPE_CHECKING

from stenographer.lib.logging.pipeline import fmt_event
from stenographer.lib.refine.endpoints import authority, is_loopback

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
    return f"unavailable_{overlay.reason.value}"


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

    Every value is the user's own settings, which rule 6 does not restrict.
    """
    from stenographer._version import __version__
    from stenographer.lib.transcribe.bark_download import MODEL_DIRNAME
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
    hotkey = {
        ("agent_binding" if field.name == "binding" else field.name): _shown(
            getattr(cfg.hotkey, field.name)
        )
        for field in dataclasses.fields(cfg.hotkey)
    }
    log.info(fmt_event("banner", "config_hotkey", **hotkey))
    log.info(
        fmt_event(
            "banner",
            "config_audio",
            **{
                field.name: _shown(getattr(cfg.audio, field.name))
                for field in dataclasses.fields(cfg.audio)
            },
        )
    )
    asr = cfg.asr
    log.info(
        fmt_event(
            "banner",
            "config_asr",
            model=MODEL_DIRNAME,
            idle_unload_seconds=asr.idle_unload_seconds,
            cpu_threads=resolve_cpu_threads(plat.physical_core_count()),
        )
    )
    log.info(
        fmt_event(
            "banner",
            "config_feedback",
            **{
                field.name: _shown(getattr(cfg.feedback, field.name))
                for field in dataclasses.fields(cfg.feedback)
            },
        )
    )
    refine = cfg.refine
    # The authority, not the configured string: a URL can carry userinfo, and
    # while validation now rejects that, the banner is written before anything
    # else can go wrong and must not be the place a credential first appears.
    refine_host = authority(refine.host)
    log.info(
        fmt_event(
            "banner",
            "config_refine",
            enabled=int(refine.enabled),
            host=refine_host,
            model=refine.model,
            loopback=int(is_loopback(refine.host)),
        )
    )
    if refine.enabled and not is_loopback(refine.host):
        # The one configuration that makes a transcript leave the machine. It
        # is the user's own choice, so this warns rather than refuses — but it
        # is never silent.
        log.warning(fmt_event("refine", "remote_host", host=refine_host, leaves_machine=1))
    log.info(
        fmt_event(
            "banner",
            "config_analytics",
            enabled=int(cfg.analytics.enabled),
        )
    )
