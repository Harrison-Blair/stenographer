# SPDX-License-Identifier: GPL-3.0-or-later
"""The capability gate: what the daemon and `doctor` both require to run.

This is *core* — the daemon's startup gate must not reach into `cli/`. The
environment probing lives in :func:`probe` (host half from the current
platform's ``probe_host``/``overlay_backends``, plus the microphone and model
cache); the exit-78 decision (:func:`missing_required`) is pure, so it is
unit-testable without mocking the environment.

Field and ``REQUIRED`` names are semantic and match
:class:`~stenographer.platform.base.HostProbe` exactly — injector available,
listener permitted, clipboard available, mic, model — so no name needs
renaming per OS. Only the labels and fix hints differ per platform, and those
are host data: they come from ``platform.base.HostGuidance``, keyed by these
same names, and ``cli/doctor.py`` only lays them out.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from stenographer.platform import current_platform
from stenographer.status import Backend, UnavailableReason

if TYPE_CHECKING:
    from stenographer.config import Config


@dataclasses.dataclass(frozen=True, slots=True)
class OverlayCapability:
    """Informational result of the optional display-backend probe."""

    enabled: bool
    backend: Backend | None = None
    reason: UnavailableReason | None = None

    @classmethod
    def disabled(cls) -> OverlayCapability:
        return cls(False)

    @classmethod
    def available(cls, backend: Backend) -> OverlayCapability:
        return cls(True, backend=backend)

    @classmethod
    def unavailable(cls, reason: UnavailableReason) -> OverlayCapability:
        return cls(True, reason=reason)


@dataclasses.dataclass(frozen=True)
class Capabilities:
    key_injector_ok: bool
    hotkey_access_ok: bool
    has_mic: bool
    model_cached: bool
    clipboard_ok: bool
    clipboard_backend: str
    cue_player: str | None
    service_enabled: str | None
    service_active: str | None
    overlay: OverlayCapability = dataclasses.field(default_factory=OverlayCapability.disabled)


REQUIRED: tuple[str, ...] = (
    "key_injector_ok",
    "hotkey_access_ok",
    "has_mic",
    "model_cached",
    "clipboard_ok",
)


def _has_mic() -> bool:
    from stenographer.audio_probe import has_input_device, query_devices

    return has_input_device(query_devices().devices)


def probe_overlay(enabled: bool) -> OverlayCapability:
    """Probe optional backends in runtime preference order without creating a surface."""
    if not enabled:
        return OverlayCapability.disabled()

    reason: UnavailableReason | None = None
    for spec in current_platform().overlay_backends():
        reason = spec.probe()
        if reason is None:
            return OverlayCapability.available(spec.backend)
    return OverlayCapability.unavailable(reason or UnavailableReason.BACKENDS_UNAVAILABLE)


def probe(cfg: Config) -> Capabilities:
    """Read-only environment probe: no writes, no network, no device opens."""
    from stenographer.transcribe import model

    host = current_platform().probe_host()
    return Capabilities(
        key_injector_ok=host.key_injector_ok,
        hotkey_access_ok=host.hotkey_access_ok,
        has_mic=_has_mic(),
        model_cached=model.is_model_cached(cfg.asr.model),
        clipboard_ok=host.clipboard_ok,
        clipboard_backend=host.clipboard_backend,
        cue_player=host.cue_player,
        service_enabled=host.service_enabled,
        service_active=host.service_active,
        overlay=probe_overlay(cfg.feedback.overlay),
    )


def missing_required(caps: Capabilities) -> list[str]:
    """Pure: names of REQUIRED capabilities that are absent."""
    return [name for name in REQUIRED if not getattr(caps, name)]
