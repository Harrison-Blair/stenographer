# SPDX-License-Identifier: GPL-3.0-or-later
"""``doctor`` rendering: the human half of the capability gate.

The gate itself — :class:`~stenographer.capabilities.Capabilities`,
``REQUIRED``, :func:`~stenographer.capabilities.probe` and
:func:`~stenographer.capabilities.missing_required` — is core
(``stenographer.capabilities``) because the daemon's startup gate shares it.
What lives here is the report layout: the sentence frames and the pure
:func:`render`, plus :func:`run` for the subcommand. Every host-specific
word in it — capability labels, fix hints, the service noun and its installer
— comes from the platform's :class:`~stenographer.platform.base.HostGuidance`,
so this module carries no Linux prose.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from stenographer.capabilities import (
    REQUIRED,
    Capabilities,
    OverlayCapability,
    missing_required,
    probe,
)
from stenographer.status import UnavailableReason

if TYPE_CHECKING:
    import pathlib

    from stenographer.config import Config
    from stenographer.platform.base import HostGuidance


def format_service_status(enabled: str | None, active: str | None, guidance: HostGuidance) -> str:
    """Pure: one-line summary of the host service's state, in the host's words."""
    if enabled is None and active is None:
        return f"unknown ({guidance.service_unknown_detail})"
    if enabled is None:
        return f"not installed — run {guidance.service_installer}"
    return f"{enabled}, {active or 'unknown'}"


def format_overlay_status(capability: OverlayCapability, guidance: HostGuidance) -> str:
    """Pure one-line status for an optional overlay capability."""
    if not capability.enabled:
        return "disabled"
    if capability.backend is not None:
        return guidance.overlay_backend_labels.get(
            capability.backend.value, capability.backend.value
        )
    reason = capability.reason or UnavailableReason.BACKENDS_UNAVAILABLE
    hint = guidance.overlay_fix_hints.get(reason, guidance.overlay_fix_hint_default)
    return f"unavailable — {hint}"


def render(
    caps: Capabilities,
    cfg: Config,
    config_path: pathlib.Path,
    guidance: HostGuidance,
) -> str:
    """Pure: the doctor report, with an exact fix hint per missing capability."""
    lines = [
        f"config: {config_path}",
        f"model: {cfg.asr.model}",
        f"hotkey binding: {cfg.hotkey.binding}",
        "",
    ]
    for name in REQUIRED:
        ok = bool(getattr(caps, name))
        label = guidance.capability_labels[name]
        if name == "clipboard_ok":
            label = f"{label} ({caps.clipboard_backend})"
        line = f"  {label}: {'ok' if ok else 'MISSING'}"
        if not ok:
            hint = (
                guidance.clipboard_fix_hints.get(
                    caps.clipboard_backend, guidance.clipboard_fix_hint_default
                )
                if name == "clipboard_ok"
                else guidance.capability_fix_hints[name]
            )
            line += f" — {hint}"
        lines.append(line)
    player = caps.cue_player or "none (sound cues disabled)"
    lines.append(f"  audio player: {player}")
    service = format_service_status(caps.service_enabled, caps.service_active, guidance)
    lines.append(f"  {guidance.service_noun}: {service}")
    lines.append(f"  overlay: {format_overlay_status(caps.overlay, guidance)}")
    lines.append("")
    missing = missing_required(caps)
    labels = [guidance.capability_labels.get(name, name) for name in missing]
    if missing:
        lines.append(f"missing required capabilities: {', '.join(labels)}")
    else:
        lines.append("all required capabilities present")
    return "\n".join(lines)


def run(cfg: Config, config_path: pathlib.Path) -> int:
    from stenographer.platform import current_platform

    caps = probe(cfg)
    print(render(caps, cfg, config_path, current_platform().guidance()))
    return 78 if missing_required(caps) else 0
