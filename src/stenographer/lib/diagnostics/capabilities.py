# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from stenographer.lib.platform import current_platform

if TYPE_CHECKING:
    from stenographer.lib.config.models import Config

from stenographer.lib.diagnostics.capability_result import Capabilities

REQUIRED: tuple[str, ...] = (
    "key_injector_ok",
    "hotkey_access_ok",
    "has_mic",
    "model_cached",
    "clipboard_ok",
)


def _has_mic() -> bool:
    from stenographer.lib.audio.probe import has_input_device, query_devices

    return has_input_device(query_devices().devices)


def probe(cfg: Config) -> Capabilities:
    """Read-only environment probe: no writes, no network, no device opens."""
    from stenographer.lib.transcribe.download import is_model_cached

    host = current_platform().probe_host()
    return Capabilities(
        key_injector_ok=host.key_injector_ok,
        hotkey_access_ok=host.hotkey_access_ok,
        has_mic=_has_mic(),
        model_cached=is_model_cached(cfg.asr.model),
        clipboard_ok=host.clipboard_ok,
        clipboard_backend=host.clipboard_backend,
        cue_player=host.cue_player,
        service_enabled=host.service_enabled,
        service_active=host.service_active,
    )


def missing_required(caps: Capabilities) -> list[str]:
    """Pure: names of REQUIRED capabilities that are absent."""
    return [name for name in REQUIRED if not getattr(caps, name)]
