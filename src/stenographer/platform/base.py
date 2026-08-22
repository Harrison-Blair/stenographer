# SPDX-License-Identifier: GPL-3.0-or-later
"""The platform boundary: every host-OS/desktop surface the core consumes.

The core pipeline (hotkey edge → record → gate → ASR worker → format → deliver)
never imports an OS-specific module. Instead it asks the current
:class:`Platform` for collaborators that satisfy the protocols below, exactly
as it already asks for a :class:`~stenographer.status.StatusSink`. Each
protocol is the *minimal* surface the core actually calls — see the call
sites cited on each one — so a new backend implements only what the daemon,
doctor, and setup genuinely use.

This module is stdlib-only (plus the pure ``stenographer.status`` vocabulary)
and must stay importable on every platform.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path
    from typing import BinaryIO, TextIO

    from stenographer.status import Backend, UnavailableReason


class UnsupportedPlatformError(RuntimeError):
    """The host has no platform implementation for the requested surface."""


class SingleInstanceLockError(OSError):
    """Lock I/O failed while acquiring the single-instance lock — not contention."""


class KeyTable(Protocol):
    """The binding key-name vocabulary (evdev ``KEY_*`` names on every platform).

    ``hotkey.binding`` is written with these names regardless of OS; a backend
    maps them onto its own key codes.
    """

    def code(self, name: str) -> int:
        """Key code for *name*; raises ``KeyError`` for an unknown name."""
        ...

    def name(self, code: int) -> str | None:
        """Canonical name for *code*, or ``None`` when it has no name."""
        ...


class HotkeyListener(Protocol):
    """What ``Daemon`` uses of a listener (``daemon.py`` start/stop/release guard)."""

    def start(self) -> None: ...

    def stop(self, timeout: float = 2.0) -> None: ...

    @property
    def is_running(self) -> bool: ...

    def wait_binding_released(self, timeout: float = 1.5, poll_interval: float = 0.01) -> bool:
        """True once no binding key is held (or the listener stopped); False on timeout."""
        ...


class KeyInjector(Protocol):
    """Emits the paste chord at the cursor (``Deliverer``'s keyboard)."""

    def send_chord(self) -> None: ...

    def close(self) -> None: ...


type ClipboardWriter = Callable[[str], bool]
"""Copy text to the clipboard, confirmed: ``False`` means the chord must not fire."""


class Notifier(Protocol):
    """Error notifications; must never raise and never block the daemon."""

    def error(self, message: str) -> None: ...


class CuePlayer(Protocol):
    """Plays cue files; ``Feedback`` owns mute/volume/asset policy."""

    def play(self, path: Path, volume: float) -> None: ...

    def preview(self, path: Path, volume: float) -> None:
        """Play one cue to completion, raising when playback fails."""
        ...


class SingleInstanceLock(Protocol):
    def acquire(self) -> bool:
        """True when held, False on contention; raises SingleInstanceLockError otherwise."""
        ...

    def release(self) -> None: ...


class OverlayBackend(Protocol):
    """Helper-side display backend (see ``overlay.supervisor.run_overlay_helper``)."""

    backend: Backend

    def run(self, input_stream: BinaryIO) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class OverlayBackendSpec:
    """One overlay backend in runtime preference order.

    ``probe`` is read-only (doctor: no surface is created) and returns a fixed
    reason or ``None`` when usable; ``construct`` builds the live backend for
    the helper and raises when unavailable.
    """

    backend: Backend
    probe: Callable[[], UnavailableReason | None]
    construct: Callable[[], OverlayBackend]


@dataclass(frozen=True, slots=True)
class HostProbe:
    """The platform-owned half of ``doctor.Capabilities`` (read-only, no writes)."""

    key_injector_ok: bool
    hotkey_access_ok: bool
    clipboard_ok: bool
    clipboard_backend: str
    cue_player: str | None
    service_enabled: str | None
    service_active: str | None


@runtime_checkable
class Platform(Protocol):
    """Everything the core needs from the host, in one provider."""

    name: str

    # --- user directories (STENOGRAPHER_CONFIG override stays in config.py) ---
    def config_path(self, env: Mapping[str, str], home: Path) -> Path: ...

    def state_dir(self, env: Mapping[str, str], home: Path) -> Path: ...

    def runtime_dir(self, env: Mapping[str, str]) -> Path: ...

    # --- hotkey / input ---
    def keys(self) -> KeyTable: ...

    def hotkey_listener(
        self,
        *,
        chord: frozenset[int],
        device: str | None,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        lock: threading.RLock,
    ) -> HotkeyListener: ...

    def hotkey_devices(self) -> list[tuple[str, str]]:
        """Selectable hotkey devices for setup as ``(value, label)`` pairs."""
        ...

    def capture_binding(self, stdin: TextIO, device: str | None, *, timeout: float) -> str: ...

    # --- output ---
    def key_injector(self) -> KeyInjector: ...

    def clipboard_writer(self, backend: str) -> ClipboardWriter: ...

    def notifier(self) -> Notifier: ...

    def cue_player(self) -> CuePlayer | None: ...

    # --- process / lifecycle ---
    def helper_spawn_kwargs(self) -> dict[str, object]:
        """Extra ``subprocess.Popen`` keyword arguments for the overlay helper."""
        ...

    def single_instance_lock(self) -> SingleInstanceLock: ...

    def install_stop_signal_handlers(self, handler: Callable[[int, object], None]) -> None: ...

    # --- probes ---
    def probe_host(self) -> HostProbe: ...

    def restart_service(self) -> tuple[bool, str]:
        """Restart the user service; ``(ok, detail)`` where detail explains a failure."""
        ...

    def overlay_backends(self) -> Sequence[OverlayBackendSpec]: ...


class NullNotifier:
    """Notifier that does nothing (mirrors ``status.NullStatusSink``)."""

    def error(self, message: str) -> None:
        return None
