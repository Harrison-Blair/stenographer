# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import signal
from pathlib import Path
from typing import TYPE_CHECKING

from stenographer.lib.hotkey.static_key_table import StaticKeyTable
from stenographer.lib.platform.diagnostics_host_mixin import DiagnosticsHostMixin
from stenographer.lib.platform.errors import UnsupportedPlatformError
from stenographer.lib.platform.host_guidance import HostGuidance
from stenographer.lib.platform.host_probe import HostProbe
from stenographer.lib.platform.null_notifier import NullNotifier

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable, Mapping
    from typing import TextIO

    from stenographer.lib.platform.asr_transport import AsrTransport
    from stenographer.lib.platform.cue_player import CuePlayer
    from stenographer.lib.platform.hotkey_listener import HotkeyListener
    from stenographer.lib.platform.key_injector import KeyInjector
    from stenographer.lib.platform.key_table import KeyTable
    from stenographer.lib.platform.notifier import Notifier
    from stenographer.lib.platform.single_instance_lock import SingleInstanceLock

from stenographer.lib.platform.macos.support import _APP, _run_with_config, signal_reason


class MacOSPlatform(DiagnosticsHostMixin):
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
        cancel: frozenset[int] = frozenset(),
        on_cancel: Callable[[], None] | None = None,
    ) -> HotkeyListener:
        raise UnsupportedPlatformError("hotkey listener is not available on macOS yet")

    def hotkey_devices(self) -> list[tuple[str, str]]:
        return []

    def capture_binding(self, stdin: TextIO, device: str | None, *, timeout: float) -> str:
        from stenographer.lib.hotkey.errors import BindingCaptureError

        raise BindingCaptureError("binding capture is not available on macOS yet")

    def key_injector(self) -> KeyInjector:
        raise UnsupportedPlatformError("paste injection is not available on macOS yet")

    def clipboard_writer(self, backend: str) -> Callable[[str], bool]:
        raise UnsupportedPlatformError("clipboard delivery is not available on macOS yet")

    def notifier(self) -> Notifier:
        return NullNotifier()

    def cue_player(self) -> CuePlayer | None:
        from stenographer.lib.platform.preview_audio import PortAudioCuePlayer

        return PortAudioCuePlayer()

    def asr_transport(self) -> AsrTransport:
        from stenographer.lib.platform.multiprocessing_asr_transport import (
            MultiprocessingAsrTransport,
        )

        return MultiprocessingAsrTransport()

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
