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
    """Desktop notifications; must never raise and never block the daemon."""

    def error(self, message: str) -> None: ...

    def info(self, message: str) -> None:
        """Show *message* as a normal-urgency notice, with ``error``'s guarantees."""
        ...


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


class HelperProcess(Protocol):
    """One live overlay-helper child process, with its two pipes.

    The supervisor owns every policy above this line (mailbox, NDJSON framing,
    readiness deadline, restart budget); the host owns pipe creation, the
    blocking wait for helper output, and process termination — none of which
    survives a move between OSes unchanged (``selectors.SelectSelector``
    accepts only sockets on Windows; POSIX signal escalation has no analogue
    there).
    """

    def write(self, data: bytes) -> None:
        """Write *data* to the helper's stdin and flush; raises ``OSError``."""
        ...

    def close_input(self) -> None:
        """Close the helper's stdin so it sees EOF. Never raises."""
        ...

    def wait_readable(self, timeout: float) -> bool:
        """Block up to *timeout* seconds; ``True`` when stdout has bytes or EOF."""
        ...

    def read(self, size: int) -> bytes:
        """Read at most *size* bytes; ``b""`` at EOF *and* on any read error."""
        ...

    def is_running(self) -> bool:
        """``True`` while the child has not exited (no blocking, no reaping)."""
        ...

    def wait(self, timeout: float) -> None:
        """Wait up to *timeout* seconds for a voluntary exit. Never raises."""
        ...

    def terminate(self, grace_seconds: float) -> None:
        """Stop the child with the host's escalation, then reap it. Never raises.

        Called after the supervisor has already granted an expected exit its
        own grace period, so an implementation escalates immediately; *grace*
        bounds each step of that escalation.
        """
        ...

    def close(self) -> None:
        """Release the pipes and any polling resources. Never raises."""
        ...


class HelperTransport(Protocol):
    """Spawns overlay helper processes with the pipe layout the supervisor needs."""

    def spawn(self, command: Sequence[str]) -> HelperProcess:
        """Start *command*; raises ``OSError``/``ValueError`` when it cannot start."""
        ...


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
class HostGuidance:
    """The host's user-facing prose: what the core prints but cannot phrase.

    Everything the CLI shows a user that is true only of one OS lives here —
    capability labels and fix hints, the words for the background service and
    the commands that control it, the config template's hotkey-device comment,
    and the shell syntax for running against an explicit config path. The core
    supplies the sentence frames; the host supplies the clauses.

    ``capability_labels`` and ``capability_fix_hints`` are keyed by the
    semantic ``HostProbe`` / ``capabilities.Capabilities`` field names, so no
    core dict needs a per-OS branch; ``clipboard_fix_hints`` is keyed by the
    backend name the probe reported, with ``clipboard_fix_hint_default`` for a
    backend the host did not anticipate. Commands are printed verbatim.
    """

    capability_labels: Mapping[str, str]
    capability_fix_hints: Mapping[str, str]
    clipboard_fix_hints: Mapping[str, str]
    clipboard_fix_hint_default: str
    overlay_backend_labels: Mapping[str, str]
    """Display name per ``status.Backend`` value in the doctor report."""
    overlay_fix_hints: Mapping[UnavailableReason, str]
    """Why an overlay backend is unusable, keyed by the probe's fixed reason."""
    overlay_fix_hint_default: str
    service_noun: str
    """What the user-visible background service is called (``doctor``'s row label)."""
    service_name: str
    """The service instance's name, embedded verbatim in core sentence frames."""
    service_installer: str
    """What installs the service; printed after "run" and inside backticks."""
    service_unknown_detail: str
    """Why the service state could not be determined, as a parenthetical clause."""
    service_start_command: str
    service_restart_command: str
    service_log_command: str
    hotkey_device_comment: str
    """The ``hotkey.device`` comment written into the annotated default config."""
    run_with_config: Callable[[str], str]
    """Build the shell line that runs the daemon against an explicit config path."""


@dataclass(frozen=True, slots=True)
class HostProbe:
    """The platform-owned half of ``capabilities.Capabilities`` (read-only, no writes).

    Field names are shared verbatim with the core dataclass and its
    ``REQUIRED`` gate — no per-OS renaming anywhere in the chain.
    """

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
    def helper_transport(self) -> HelperTransport:
        """Transport for the overlay helper child; raises when the host has none."""
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

    def overlay_backends(self) -> Sequence[OverlayBackendSpec]: ...


class NullNotifier:
    """Notifier that does nothing (mirrors ``status.NullStatusSink``)."""

    def error(self, message: str) -> None:
        return None

    def info(self, message: str) -> None:
        return None
