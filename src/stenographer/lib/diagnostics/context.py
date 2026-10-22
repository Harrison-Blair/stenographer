# SPDX-License-Identifier: GPL-3.0-or-later
"""Privacy-safe configured identifiers for numeric analytics."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from stenographer.lib.transcribe.bark_download import MODEL_DIRNAME

if TYPE_CHECKING:
    from stenographer.lib.config.models import Config


def technical_context(cfg: Config) -> dict[str, str | int]:
    """Retain configured identifiers, substituting fixed labels for path-valued settings."""
    device = cfg.audio.input_device or "default"
    if device.startswith(("/", "\\", ".")) or re.match(r"^[A-Za-z]:[\\/]", device):
        device = "configured_device"
    return {
        "model": MODEL_DIRNAME,
        "device": device[:256],
        "mode": cfg.hotkey.mode,
    }
