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
        HostProbe,
        HotkeyListener,
        KeyInjector,
        KeyTable,
        Notifier,
        OverlayBackendSpec,
        SingleInstanceLock,
    )


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
    def helper_spawn_kwargs(self) -> dict[str, object]:
        from stenographer.platform.linux.process import helper_spawn_kwargs

        return helper_spawn_kwargs()

    def single_instance_lock(self) -> SingleInstanceLock:
        from stenographer.platform.linux.lock import FlockSingleInstanceLock

        return FlockSingleInstanceLock()

    def install_stop_signal_handlers(self, handler: Callable[[int, object], None]) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, handler)

    # --- probes ---
    def probe_host(self) -> HostProbe:
        from stenographer.platform.linux.probe import probe_host

        return probe_host()

    def restart_service(self) -> tuple[bool, str]:
        from stenographer.platform.linux.probe import restart_service

        return restart_service()

    def overlay_backends(self) -> Sequence[OverlayBackendSpec]:
        from stenographer.platform.linux.overlay import overlay_backends

        return overlay_backends()
