# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import dataclasses

from stenographer.lib.diagnostics.capability_result import Capabilities
from stenographer.lib.platform import current_platform

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


def probe() -> Capabilities:
    """Read-only environment probe: no writes, no network, no device opens."""
    from stenographer.lib.transcribe import bark_download

    host = current_platform().probe_host()
    return Capabilities(
        **dataclasses.asdict(host),
        has_mic=_has_mic(),
        model_cached=bark_download.is_model_cached(),
    )


def missing_required(caps: Capabilities) -> list[str]:
    """Pure: names of REQUIRED capabilities that are absent."""
    return [name for name in REQUIRED if not getattr(caps, name)]
