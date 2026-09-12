# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import signal
from typing import TYPE_CHECKING

from stenographer.lib.platform.diagnostics_host_mixin import DiagnosticsHostMixin

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable, Mapping
    from pathlib import Path
    from typing import TextIO

    from stenographer.lib.platform.asr_transport import AsrTransport
    from stenographer.lib.platform.cue_player import CuePlayer
    from stenographer.lib.platform.host_guidance import HostGuidance
    from stenographer.lib.platform.host_probe import HostProbe
    from stenographer.lib.platform.hotkey_listener import HotkeyListener
    from stenographer.lib.platform.key_injector import KeyInjector
    from stenographer.lib.platform.key_table import KeyTable
    from stenographer.lib.platform.notifier import Notifier
    from stenographer.lib.platform.single_instance_lock import SingleInstanceLock

from stenographer.lib.platform.linux.support import signal_reason


class LinuxPlatform(DiagnosticsHostMixin):
    name = "linux"

    # --- user directories ---
    def config_path(self, env: Mapping[str, str], home: Path) -> Path:
        from stenographer.lib.platform.linux.dirs import config_path

        return config_path(env, home)

    def state_dir(self, env: Mapping[str, str], home: Path) -> Path:
        from stenographer.lib.platform.linux.dirs import state_dir

        return state_dir(env, home)

    def runtime_dir(self, env: Mapping[str, str]) -> Path:
        from stenographer.lib.platform.linux.dirs import runtime_dir

        return runtime_dir(env)

    # --- hotkey / input ---
    def keys(self) -> KeyTable:
        from stenographer.lib.platform.linux.evdev_key_table import EvdevKeyTable

        return EvdevKeyTable()

    def default_hotkey_binding(self) -> str:
        return "KEY_RIGHTCTRL"

    def hotkey_listener(
        self,
        *,
        chord: frozenset[int],
        device: str | None,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        lock: threading.RLock,
        cancel: frozenset[int] = frozenset(),
        on_cancel: Callable[[], None] | None = None,
    ) -> HotkeyListener:
        from stenographer.lib.platform.linux.evdev_hotkey_listener import EvdevHotkeyListener

        return EvdevHotkeyListener(
            chord=chord,
            device_path=device,
            on_start=on_start,
            on_stop=on_stop,
            lock=lock,
            cancel=cancel,
            on_cancel=on_cancel,
        )

    def hotkey_devices(self) -> list[tuple[str, str]]:
        from stenographer.lib.platform.linux.hotkey import list_hotkey_devices

        return list_hotkey_devices()

    def capture_binding(self, stdin: TextIO, device: str | None, *, timeout: float) -> str:
        from stenographer.lib.platform.linux.binding_capture import capture_binding

        return capture_binding(stdin, device, timeout=timeout)

    # --- output ---
    def key_injector(self) -> KeyInjector:
        from stenographer.lib.platform.linux.uinput_keyboard import UinputKeyboard

        return UinputKeyboard()

    def clipboard_writer(self, backend: str) -> Callable[[str], bool]:
        from stenographer.lib.platform.linux.clipboard import copy_for_backend
        from stenographer.lib.platform.linux.clipboard_backend import ClipboardBackend

        return copy_for_backend(ClipboardBackend(backend))

    def notifier(self) -> Notifier:
        from stenographer.lib.platform.linux.notify_send_notifier import NotifySendNotifier

        return NotifySendNotifier()

    def cue_player(self) -> CuePlayer | None:
        from stenographer.lib.platform.linux.cues import detect_player
        from stenographer.lib.platform.linux.linux_cue_player import LinuxCuePlayer

        player = detect_player()
        return LinuxCuePlayer(player) if player is not None else None

    # --- process / lifecycle ---
    def asr_transport(self) -> AsrTransport:
        from stenographer.lib.platform.multiprocessing_asr_transport import (
            MultiprocessingAsrTransport,
        )

        return MultiprocessingAsrTransport()

    def single_instance_lock(self) -> SingleInstanceLock:
        from stenographer.lib.platform.linux.flock_single_instance_lock import (
            FlockSingleInstanceLock,
        )

        return FlockSingleInstanceLock()

    def install_stop_handlers(self, handler: Callable[[str], None]) -> None:
        def _on_signal(signum: int, frame: object) -> None:
            handler(signal_reason(signum))

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, _on_signal)

    # --- probes ---
    def physical_core_count(self) -> int | None:
        from stenographer.lib.platform.linux.cpu import physical_core_count

        return physical_core_count()

    def journal_attached(self, env: Mapping[str, str]) -> bool:
        from stenographer.lib.platform.linux.dirs import journal_attached

        return journal_attached(env)

    def probe_host(self) -> HostProbe:
        from stenographer.lib.platform.linux.probe import probe_host

        return probe_host()

    def guidance(self) -> HostGuidance:
        from stenographer.lib.platform.linux.guidance import guidance

        return guidance()

    def restart_service(self) -> tuple[bool, str]:
        from stenographer.lib.platform.linux.probe import restart_service

        return restart_service()
