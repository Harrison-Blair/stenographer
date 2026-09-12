# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

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
from stenographer.lib.platform.types import ClipboardWriter


@runtime_checkable
class Platform(Protocol):
    """Everything the core needs from the host, in one provider."""

    name: str

    def resource_probe(self) -> Callable[..., dict]: ...

    def process_identity(self) -> tuple[int, float]: ...

    def process_alive(self, pid: int, started_epoch: float) -> bool | None: ...

    def runtime_context(self) -> dict[str, str]: ...

    # --- user directories (STENOGRAPHER_CONFIG override stays in config.py) ---
    def config_path(self, env: Mapping[str, str], home: Path) -> Path: ...

    def state_dir(self, env: Mapping[str, str], home: Path) -> Path: ...

    def runtime_dir(self, env: Mapping[str, str]) -> Path: ...

    # --- hotkey / input ---
    def keys(self) -> KeyTable: ...

    def default_hotkey_binding(self) -> str:
        """The ``KEY_*`` name a fresh config binds dictation to on this host.

        Which key is free to hold down is a property of the host's desktop, not
        of the core, so the provider names it and ``Config.defaults()`` asks
        rather than branching on ``sys.platform``.
        """
        ...

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
    def asr_transport(self) -> AsrTransport:
        """The shared native ASR transport, resolved lazily by each provider."""
        ...

    def single_instance_lock(self) -> SingleInstanceLock: ...

    def install_stop_handlers(self, handler: Callable[[str], None]) -> None:
        """Ask the host to call ``handler(reason)`` when the user stops the daemon.

        ``reason`` is a short human-readable label for the log line only
        (``"SIGTERM"``, ``"SIGINT"``, later ``"CTRL_CLOSE"``): naming the stop
        is host vocabulary, so the provider — not the core — formats it. The
        core's handler runs in whatever context the host delivers (a POSIX
        signal handler, a Windows console-control thread), so a provider must
        keep its own formatting allocation-light and exception-safe: the stop
        must fire even when the reason cannot be named.
        """
        ...

    # --- probes ---
    def physical_core_count(self) -> int | None:
        """Affinity-visible physical cores, or ``None`` when the host cannot tell.

        Hyperthread siblings count once; a host that cannot see its own
        topology says so rather than guessing, so the core can apply its
        documented fallback instead of an inflated logical-CPU number.
        """
        ...

    def journal_attached(self, env: Mapping[str, str]) -> bool:
        """True when stderr is already a system log that stamps its own timestamps.

        Purely an output-formatting question — the core asks so it can drop the
        ``asctime`` column from the stderr formatter rather than print a second
        timestamp beside the host's.
        """
        ...

    def probe_host(self) -> HostProbe: ...

    def guidance(self) -> HostGuidance:
        """Host-specific user-facing prose for the CLI's reports and hints."""
        ...

    def restart_service(self) -> tuple[bool, str]:
        """Restart the user service; ``(ok, detail)`` where detail explains a failure."""
        ...
