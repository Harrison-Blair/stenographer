# SPDX-License-Identifier: GPL-3.0-or-later
"""The Linux/Wayland provider: evdev, uinput, wl-copy/xclip, XDG, flock, systemd.

Every method imports its sibling module lazily so constructing the provider
stays cheap and stdlib-only (``stenographer --help`` never loads evdev).
"""

from __future__ import annotations

import signal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path
    from typing import TextIO

    from stenographer.platform.base import (
        CuePlayer,
        HelperTransport,
        HostGuidance,
        HostProbe,
        HotkeyListener,
        KeyInjector,
        KeyTable,
        Notifier,
        OverlayBackendSpec,
        SingleInstanceLock,
    )


def signal_reason(signum: int) -> str:
    """Name a stop signal for the core's log line. PURE.

    Runs inside a signal handler, so it stays allocation-light (the enum
    lookup returns an interned name) and never raises: an unrecognized number
    — a signal this build's ``signal.Signals`` does not know — degrades to a
    numeric label so ``request_stop`` still fires behind it.
    """

    try:
        return signal.Signals(signum).name
    except Exception:
        return f"signal {signum}"


class LinuxPlatform:
    name = "linux"

    # --- user directories ---
    def config_path(self, env: Mapping[str, str], home: Path) -> Path:
        from stenographer.platform.linux.dirs import config_path

        return config_path(env, home)

    def state_dir(self, env: Mapping[str, str], home: Path) -> Path:
        from stenographer.platform.linux.dirs import state_dir

        return state_dir(env, home)

    def runtime_dir(self, env: Mapping[str, str]) -> Path:
        from stenographer.platform.linux.dirs import runtime_dir

        return runtime_dir(env)

    # --- hotkey / input ---
    def keys(self) -> KeyTable:
        from stenographer.platform.linux.hotkey import EvdevKeyTable

        return EvdevKeyTable()

    def hotkey_listener(
        self,
        *,
        chord: frozenset[int],
        device: str | None,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        lock: threading.RLock,
    ) -> HotkeyListener:
        from stenographer.platform.linux.hotkey import EvdevHotkeyListener

        return EvdevHotkeyListener(
            chord=chord, device_path=device, on_start=on_start, on_stop=on_stop, lock=lock
        )

    def hotkey_devices(self) -> list[tuple[str, str]]:
        from stenographer.platform.linux.hotkey import list_hotkey_devices

        return list_hotkey_devices()

    def capture_binding(self, stdin: TextIO, device: str | None, *, timeout: float) -> str:
        from stenographer.platform.linux.binding_capture import capture_binding

        return capture_binding(stdin, device, timeout=timeout)

    # --- output ---
    def key_injector(self) -> KeyInjector:
        from stenographer.platform.linux.uinput import UinputKeyboard

        return UinputKeyboard()

    def clipboard_writer(self, backend: str) -> Callable[[str], bool]:
        from stenographer.platform.linux.clipboard import ClipboardBackend, copy_for_backend

        return copy_for_backend(ClipboardBackend(backend))

    def notifier(self) -> Notifier:
        from stenographer.platform.linux.notify import NotifySendNotifier

        return NotifySendNotifier()

    def cue_player(self) -> CuePlayer | None:
        from stenographer.platform.linux.cues import LinuxCuePlayer, detect_player

        player = detect_player()
        return LinuxCuePlayer(player) if player is not None else None

    # --- process / lifecycle ---
    def helper_transport(self) -> HelperTransport:
        from stenographer.platform.linux.helper import LinuxHelperTransport

        return LinuxHelperTransport()

    def single_instance_lock(self) -> SingleInstanceLock:
        from stenographer.platform.linux.lock import FlockSingleInstanceLock

        return FlockSingleInstanceLock()

    def install_stop_handlers(self, handler: Callable[[str], None]) -> None:
        def _on_signal(signum: int, frame: object) -> None:
            handler(signal_reason(signum))

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, _on_signal)

    # --- probes ---
    def physical_core_count(self) -> int | None:
        from stenographer.platform.linux.cpu import physical_core_count

        return physical_core_count()

    def probe_host(self) -> HostProbe:
        from stenographer.platform.linux.probe import probe_host

        return probe_host()

    def guidance(self) -> HostGuidance:
        from stenographer.platform.linux.guidance import guidance

        return guidance()

    def restart_service(self) -> tuple[bool, str]:
        from stenographer.platform.linux.probe import restart_service

        return restart_service()

    def overlay_backends(self) -> Sequence[OverlayBackendSpec]:
        from stenographer.platform.linux.overlay import overlay_backends

        return overlay_backends()
