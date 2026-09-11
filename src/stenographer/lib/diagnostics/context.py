# SPDX-License-Identifier: GPL-3.0-or-later
"""Privacy-safe configured identifiers for numeric analytics."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stenographer.lib.config.models import Config


def technical_context(cfg: Config) -> dict[str, str | int]:
    """Retain configured identifiers, substituting fixed labels for path-valued settings."""
    model = cfg.asr.model
    if re.fullmatch(r"[\w.-]+(?:/[\w.-]+)?", model) is None or model.startswith("."):
        model = "local_model"
    device = cfg.audio.input_device or "default"
    if device.startswith(("/", "\\", ".")) or re.match(r"^[A-Za-z]:[\\/]", device):
        device = "configured_device"
    return {
        "model": model,
        "device": device[:256],
        "compute_type": cfg.asr.compute_type,
        "mode": cfg.hotkey.mode,
    }
