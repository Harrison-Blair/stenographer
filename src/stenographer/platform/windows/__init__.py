# SPDX-License-Identifier: GPL-3.0-or-later
"""Windows provider stub: imports everywhere, provides nothing yet.

Stdlib-only on purpose — the Linux bundle's ``collect_submodules`` also
imports it. It lets ``stenographer doctor`` run on Windows (and exit 78) and
keeps the core importable there; every surface that would need a real backend
(hotkey hook, SendInput paste, Win32 clipboard, cues, lock) is reported
unavailable or raises :class:`UnsupportedPlatformError`. Directory defaults are
provisional (``%APPDATA%`` / ``%LOCALAPPDATA%``, honouring ``XDG_*`` when set).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from stenographer.keycodes import StaticKeyTable
from stenographer.platform.base import HostProbe, NullNotifier, UnsupportedPlatformError

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable, Mapping, Sequence
    from typing import TextIO

    from stenographer.platform.base import (
        CuePlayer,
        HotkeyListener,
        KeyInjector,
        KeyTable,
        Notifier,
        OverlayBackendSpec,
        SingleInstanceLock,
    )

_APP = "stenographer"


class WindowsPlatform:
    name = "windows"

    # --- user directories ---
    def config_path(self, env: Mapping[str, str], home: Path) -> Path:
        xdg = env.get("XDG_CONFIG_HOME")
        if xdg:
            return Path(xdg) / _APP / "config.toml"
        appdata = env.get("APPDATA")
        base = Path(appdata) if appdata else home / "AppData" / "Roaming"
        return base / _APP / "config.toml"

    def state_dir(self, env: Mapping[str, str], home: Path) -> Path:
        xdg = env.get("XDG_STATE_HOME")
        if xdg:
            return Path(xdg) / _APP
        local = env.get("LOCALAPPDATA")
        base = Path(local) if local else home / "AppData" / "Local"
        return base / _APP

    def runtime_dir(self, env: Mapping[str, str]) -> Path:
        local = env.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / _APP

    # --- hotkey / input ---
    def keys(self) -> KeyTable:
        # The KEY_* vocabulary is core data, not a host capability: a binding
        # must still parse and render where no hotkey backend exists.
        return StaticKeyTable()

    def hotkey_listener(
        self,
        *,
        chord: frozenset[int],
        device: str | None,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        lock: threading.RLock,
    ) -> HotkeyListener:
        raise UnsupportedPlatformError("hotkey listener is not available on Windows yet")

    def hotkey_devices(self) -> list[tuple[str, str]]:
        return []

    def capture_binding(self, stdin: TextIO, device: str | None, *, timeout: float) -> str:
        from stenographer.cli.binding_capture import BindingCaptureError

        raise BindingCaptureError("binding capture is not available on Windows yet")

    # --- output ---
    def key_injector(self) -> KeyInjector:
        raise UnsupportedPlatformError("paste injection is not available on Windows yet")

    def clipboard_writer(self, backend: str) -> Callable[[str], bool]:
        raise UnsupportedPlatformError("clipboard delivery is not available on Windows yet")

    def notifier(self) -> Notifier:
        return NullNotifier()

    def cue_player(self) -> CuePlayer | None:
        return None

    # --- process / lifecycle ---
    def helper_spawn_kwargs(self) -> dict[str, object]:
        return {}

    def single_instance_lock(self) -> SingleInstanceLock:
        raise UnsupportedPlatformError("single-instance lock is not available on Windows yet")

    def install_stop_signal_handlers(self, handler: Callable[[int, object], None]) -> None:
        import signal

        signal.signal(signal.SIGINT, handler)

    # --- probes ---
    def probe_host(self) -> HostProbe:
        return HostProbe(
            key_injector_ok=False,
            hotkey_access_ok=False,
            clipboard_ok=False,
            clipboard_backend="unavailable",
            cue_player=None,
            service_enabled=None,
            service_active=None,
        )

    def restart_service(self) -> tuple[bool, str]:
        return (False, "no service manager integration on Windows")

    def overlay_backends(self) -> Sequence[OverlayBackendSpec]:
        return ()
