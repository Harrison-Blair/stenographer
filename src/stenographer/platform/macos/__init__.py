# SPDX-License-Identifier: GPL-3.0-or-later
"""macOS desktop/setup provider; native dictation remains unavailable.

Directory and settings access work independently of the daemon. A native
hotkey/injection provider and signed interactive acceptance remain pending.
"""

from __future__ import annotations

import shlex
import signal
from pathlib import Path
from typing import TYPE_CHECKING

from stenographer.keycodes import StaticKeyTable
from stenographer.platform.base import (
    HostGuidance,
    HostProbe,
    NullNotifier,
    UnsupportedPlatformError,
)
from stenographer.platform.desktop import DesktopHostMixin

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable, Mapping, Sequence
    from typing import TextIO

    from stenographer.platform.base import (
        CuePlayer,
        HelperTransport,
        HotkeyListener,
        KeyInjector,
        KeyTable,
        Notifier,
        OverlayBackendSpec,
        SingleInstanceLock,
    )

_APP = "stenographer"


def _run_with_config(path: str) -> str:
    return f"STENOGRAPHER_CONFIG={shlex.quote(path)} stenographer run"


def signal_reason(signum: int) -> str:
    """Name a stop signal without risking failure in stop context."""

    try:
        return signal.Signals(signum).name
    except Exception:
        return f"signal {signum}"


class MacOSPlatform(DesktopHostMixin):
    name = "macos"

    def config_path(self, env: Mapping[str, str], home: Path) -> Path:
        base = (
            Path(env["XDG_CONFIG_HOME"])
            if env.get("XDG_CONFIG_HOME")
            else (home / "Library" / "Application Support")
        )
        return base / _APP / "config.toml"

    def state_dir(self, env: Mapping[str, str], home: Path) -> Path:
        base = (
            Path(env["XDG_STATE_HOME"])
            if env.get("XDG_STATE_HOME")
            else (home / "Library" / "Application Support")
        )
        return base / _APP

    def runtime_dir(self, env: Mapping[str, str]) -> Path:
        return self.state_dir(env, Path.home()) / "runtime"

    def keys(self) -> KeyTable:
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
        raise UnsupportedPlatformError("hotkey listener is not available on macOS yet")

    def hotkey_devices(self) -> list[tuple[str, str]]:
        return []

    def capture_binding(self, stdin: TextIO, device: str | None, *, timeout: float) -> str:
        from stenographer.binding_capture import BindingCaptureError

        raise BindingCaptureError("binding capture is not available on macOS yet")

    def key_injector(self) -> KeyInjector:
        raise UnsupportedPlatformError("paste injection is not available on macOS yet")

    def clipboard_writer(self, backend: str) -> Callable[[str], bool]:
        raise UnsupportedPlatformError("clipboard delivery is not available on macOS yet")

    def notifier(self) -> Notifier:
        return NullNotifier()

    def cue_player(self) -> CuePlayer | None:
        from stenographer.platform.preview_audio import PortAudioCuePlayer

        return PortAudioCuePlayer()

    def helper_transport(self) -> HelperTransport:
        raise UnsupportedPlatformError("the overlay helper is not available on macOS yet")

    def single_instance_lock(self) -> SingleInstanceLock:
        raise UnsupportedPlatformError("single-instance lock is not available on macOS yet")

    def install_stop_handlers(self, handler: Callable[[str], None]) -> None:
        def _on_signal(signum: int, frame: object) -> None:
            handler(signal_reason(signum))

        signal.signal(signal.SIGINT, _on_signal)
        signal.signal(signal.SIGTERM, _on_signal)

    def physical_core_count(self) -> int | None:
        return None

    def journal_attached(self, env: Mapping[str, str]) -> bool:
        return False

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

    def guidance(self) -> HostGuidance:
        return HostGuidance(
            capability_labels={
                "key_injector_ok": "paste injection",
                "hotkey_access_ok": "global hotkey hook",
                "has_mic": "microphone",
                "model_cached": "ASR model cached",
                "clipboard_ok": "clipboard",
            },
            capability_fix_hints={
                "key_injector_ok": "no macOS paste-injection backend exists yet",
                "hotkey_access_ok": "no macOS hotkey backend exists yet",
                "has_mic": "no audio input device found; check the microphone / PortAudio",
                "model_cached": "run: stenographer model download",
            },
            clipboard_fix_hints={},
            clipboard_fix_hint_default="no macOS clipboard backend exists yet",
            overlay_backend_labels={},
            overlay_fix_hints={},
            overlay_fix_hint_default="the overlay is not available on macOS yet",
            service_noun="background service (not available on macOS yet)",
            service_name="the stenographer service",
            service_installer="the macOS service installer (not available yet)",
            service_unknown_detail="macOS has no service integration yet",
            service_start_command="stenographer run",
            service_restart_command="stenographer run",
            service_log_command="stenographer run",
            hotkey_device_comment='reserved for a future device selector; "" = auto-detect',
            run_with_config=_run_with_config,
        )

    def restart_service(self) -> tuple[bool, str]:
        return (False, "no service manager integration on macOS")

    def overlay_backends(self) -> Sequence[OverlayBackendSpec]:
        return ()
