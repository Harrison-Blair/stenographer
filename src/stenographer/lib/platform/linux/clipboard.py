# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
import os
import selectors
import shutil
import subprocess
import time
from typing import TYPE_CHECKING

from stenographer.lib.logging.pipeline import fmt_event, log_failure
from stenographer.lib.platform.clipboard_snapshot import ClipboardSnapshot
from stenographer.lib.platform.linux.process import child_env

if TYPE_CHECKING:
    from collections.abc import Callable

    from stenographer.lib.platform.types import ClipboardReader, ClipboardRestorer

from stenographer.lib.platform.linux.clipboard_backend import ClipboardBackend

log = logging.getLogger(__name__)


_COPY_TIMEOUT_SECONDS = 10.0


_COPY_ERRORS = (
    subprocess.CalledProcessError,
    subprocess.TimeoutExpired,
    FileNotFoundError,
)


#: The whole snapshot (type listing plus read) shares one budget: the clipboard
#: owner is another application that may never answer, and the user is
#: waiting for the paste.
_SNAPSHOT_BUDGET_SECONDS = 1.0


#: Bounds the memory one snapshot may hold.
_SNAPSHOT_MAX_BYTES = 64 * 1024 * 1024


#: X selection bookkeeping atoms: offered on every X11 selection, never content.
_X_ATOMS = frozenset({"TARGETS", "TIMESTAMP", "MULTIPLE", "SAVE_TARGETS"})


#: Plain text, most specific first.
_PREFERRED_TYPES = ("text/plain;charset=utf-8", "text/plain")


#: X text atoms: kept only when nothing better is offered.
_TEXT_FALLBACK_TYPES = ("UTF8_STRING", "STRING", "TEXT")


#: Set by password managers (KeePassXC and others) on a secret they copied.
_SENSITIVE_TYPE = "x-kde-passwordManagerHint"


_DATA_CONTROL_GLOBALS = frozenset({"ext_data_control_manager_v1", "zwlr_data_control_manager_v1"})


def pick_backend(globals_seen: set[str] | None, *, have_display: bool) -> ClipboardBackend:
    """Choose the clipboard backend from the compositor's registry globals. PURE.

    Data-control present → wl-copy works from a background process. Absent
    (GNOME <= 46) → the xclip/XWayland bridge, provided an X display exists;
    an unavailable registry probe follows the same fallback policy. With no X
    display alternative, keep wl-copy (status quo, and its failure is already
    the safe no-chord path).
    """
    if globals_seen is not None and globals_seen & _DATA_CONTROL_GLOBALS:
        return ClipboardBackend.WL_COPY
    return ClipboardBackend.X11 if have_display else ClipboardBackend.WL_COPY


def _wayland_global_interfaces() -> set[str]:
    """One registry roundtrip against the session compositor; raises on failure."""
    from pywayland.client import Display

    seen: set[str] = set()
    display = Display()
    display.connect()
    try:
        registry = display.get_registry()
        registry.dispatcher["global"] = lambda _registry, _name, interface, _version: seen.add(
            interface
        )
        if display.roundtrip() < 0:
            raise RuntimeError("Wayland registry roundtrip failed")
        registry.destroy()
    finally:
        display.disconnect()
    return seen


def detect_clipboard_backend() -> ClipboardBackend:
    """Probe the compositor once (daemon startup, never under the state lock)."""
    have_display = bool(os.environ.get("DISPLAY"))
    try:
        globals_seen = _wayland_global_interfaces()
    except Exception as exc:
        backend = pick_backend(None, have_display=have_display)
        log_failure(
            log,
            logging.WARNING,
            "deliver: wayland_probe_failed",
            exc,
            safe=True,
            backend=backend.value,
        )
        return backend
    return pick_backend(globals_seen, have_display=have_display)


def copy_both_selections(text: str) -> bool:
    """Copy *text* to the regular clipboard and the primary selection.

    Both selections because Shift+Insert reads the primary selection in some
    clients (e.g. kitty) and the regular clipboard in others. Returns True only
    if BOTH ``wl-copy`` invocations succeed; False on any failure.

    stdout/stderr go to DEVNULL rather than being captured: wl-copy forks and
    serves the selection in the background, and the forked child inherits any
    pipes, so capturing blocks until the timeout even though the clipboard is
    already set. The return code is still collected, so check=True is unchanged.
    """
    payload = text.encode("utf-8")
    for argv in (["wl-copy"], ["wl-copy", "--primary"]):
        try:
            subprocess.run(
                argv,
                input=payload,
                check=True,
                timeout=_COPY_TIMEOUT_SECONDS,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=child_env(),
            )
        except _COPY_ERRORS as exc:
            # WARNING, not DEBUG: a failed copy is why nothing was pasted, and
            # ``wl-copy``'s own complaint is host vocabulary, never transcript.
            log_failure(
                log,
                logging.WARNING,
                "deliver: copy_failed",
                exc,
                safe=True,
                argv=" ".join(argv),
            )
            return False
    return True


def copy_both_selections_x11(text: str) -> bool:
    """Copy *text* to CLIPBOARD and PRIMARY via xclip under XWayland.

    xclip forks a child that serves the selection, and that child inherits any
    pipes — stdout/stderr go to DEVNULL for the same reason as wl-copy above.
    Unlike wl-copy's exit status, taking X11 selection ownership is
    fire-and-forget, so each write is confirmed by reading the selection back
    (``xclip -o`` exits without forking) and comparing bytes: True only when
    both selections verifiably hold *text*.
    """
    payload = text.encode("utf-8")
    for selection in ("clipboard", "primary"):
        argv = ["xclip", "-selection", selection]
        try:
            # The write discards both streams, so nothing it can raise has ever
            # seen the selection: its own complaint is host vocabulary.
            subprocess.run(
                argv,
                input=payload,
                check=True,
                timeout=_COPY_TIMEOUT_SECONDS,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=child_env(),
            )
        except _COPY_ERRORS as exc:
            log_failure(
                log,
                logging.WARNING,
                "deliver: copy_failed",
                exc,
                safe=True,
                argv=" ".join(argv),
                phase="write",
            )
            return False
        try:
            readback = subprocess.run(
                [*argv, "-o"],
                check=True,
                timeout=_COPY_TIMEOUT_SECONDS,
                capture_output=True,
                env=child_env(),
            )
        except _COPY_ERRORS as exc:
            # safe=False, and split from the write above for exactly this
            # reason: the read-back captures the selection, so a raised
            # ``CalledProcessError``/``TimeoutExpired`` carries the clipboard's
            # own bytes on ``.output``/``.stdout``. Only the class name and the
            # traceback frames may ever be rendered from this lineage; the argv
            # is ours, so it is passed as a field rather than read off ``.cmd``.
            log_failure(
                log,
                logging.WARNING,
                "deliver: copy_failed",
                exc,
                safe=False,
                argv=" ".join(argv),
                phase="readback",
            )
            return False
        if readback.stdout != payload:
            log.warning(
                "deliver: xclip_readback_mismatch selection=%s expected_bytes=%d got_bytes=%d",
                selection,
                len(payload),
                len(readback.stdout),
            )
            return False
    return True


def pick_snapshot_type(offered: list[str]) -> str | None:
    """The one offered type a snapshot keeps. PURE.

    Plain text first; otherwise the first offered type, so an image stays an
    image; X text atoms last; X bookkeeping atoms never.
    """
    types = [mime for mime in offered if mime and mime not in _X_ATOMS]
    for mime in _PREFERRED_TYPES:
        if mime in types:
            return mime
    for mime in types:
        if mime not in _TEXT_FALLBACK_TYPES:
            return mime
    for mime in _TEXT_FALLBACK_TYPES:
        if mime in types:
            return mime
    return None


def _capture_bounded(argv: list[str], deadline: float) -> bytes | None:
    """*argv*'s stdout, or None once it fails, overruns the deadline or the cap.

    ``capture_output`` cannot bound memory, so stdout is read in chunks up to
    one byte past the cap and the child is killed on overflow or deadline.
    The output is another application's clipboard: no exception carrying it
    is ever raised or logged here, only the reason and the tool's name.
    """
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=child_env(),
        )
    except OSError as exc:
        log_failure(log, logging.WARNING, "deliver: snapshot_failed", exc, safe=True, tool=argv[0])
        return None
    chunks: list[bytes] = []
    size = 0
    reason: str | None = None
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    reason = "timeout"
                    break
                chunk = os.read(proc.stdout.fileno(), 65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > _SNAPSHOT_MAX_BYTES:
                    reason = "too_large"
                    break
                chunks.append(chunk)
        if reason is None:
            try:
                if proc.wait(timeout=max(0.0, deadline - time.monotonic())) != 0:
                    reason = "exit_status"
            except subprocess.TimeoutExpired:
                reason = "timeout"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        proc.stdout.close()
    if reason is not None:
        # An owner with nothing to offer exits non-zero on every paste; only a
        # stalled or oversized owner is worth a WARNING.
        level = logging.DEBUG if reason == "exit_status" else logging.WARNING
        log.log(level, fmt_event("deliver", "snapshot_failed", reason=reason, tool=argv[0]))
        return None
    return b"".join(chunks)


def _snapshot(list_argv: list[str], read_argv: list[str]) -> ClipboardSnapshot | None:
    """List the clipboard's types, pick one, read it; all within one budget."""
    deadline = time.monotonic() + _SNAPSHOT_BUDGET_SECONDS
    listing = _capture_bounded(list_argv, deadline)
    if listing is None:
        return None
    offered = [line.strip() for line in listing.decode("utf-8", errors="replace").splitlines()]
    if _SENSITIVE_TYPE in offered:
        log.debug(fmt_event("deliver", "snapshot_skipped", reason="sensitive"))
        return None
    mime = pick_snapshot_type(offered)
    if mime is None:
        log.debug(fmt_event("deliver", "snapshot_skipped", reason="no_type"))
        return None
    data = _capture_bounded([*read_argv, mime], deadline)
    if data is None:
        return None
    if not data:
        log.debug(fmt_event("deliver", "snapshot_skipped", reason="empty"))
        return None
    return ClipboardSnapshot(mime, data)


def read_clipboard() -> ClipboardSnapshot | None:
    """Snapshot the regular clipboard (never primary) through ``wl-paste``."""
    return _snapshot(["wl-paste", "-l"], ["wl-paste", "-n", "-t"])


def read_clipboard_x11() -> ClipboardSnapshot | None:
    """Snapshot CLIPBOARD (never PRIMARY) through ``xclip`` under XWayland."""
    argv = ["xclip", "-selection", "clipboard", "-o", "-t"]
    return _snapshot([*argv, "TARGETS"], argv)


def _restore(argv: list[str], snapshot: ClipboardSnapshot) -> bool:
    """Write *snapshot* back with *argv*; True when the tool accepted it.

    Both streams go to DEVNULL for the same fork reason as the copies above,
    so nothing raised here has seen the bytes.
    """
    try:
        subprocess.run(
            argv,
            input=snapshot.data,
            check=True,
            timeout=_COPY_TIMEOUT_SECONDS,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=child_env(),
        )
    except _COPY_ERRORS as exc:
        log_failure(log, logging.WARNING, "deliver: restore_failed", exc, safe=True, tool=argv[0])
        return False
    return True


def restore_clipboard(snapshot: ClipboardSnapshot) -> bool:
    """Put *snapshot* back on the regular clipboard only, with its own type."""
    return _restore(["wl-copy", "-t", snapshot.mime], snapshot)


def restore_clipboard_x11(snapshot: ClipboardSnapshot) -> bool:
    """Put *snapshot* back on CLIPBOARD only, with its own type."""
    return _restore(["xclip", "-selection", "clipboard", "-t", snapshot.mime], snapshot)


def copy_for_backend(backend: ClipboardBackend) -> Callable[[str], bool]:
    """The copy callable for a detected backend. PURE mapping."""
    if backend is ClipboardBackend.X11:
        return copy_both_selections_x11
    return copy_both_selections


def clipboard_read_available(backend: ClipboardBackend) -> bool:
    """Whether the tool that reads *backend*'s clipboard is installed."""
    return shutil.which("xclip" if backend is ClipboardBackend.X11 else "wl-paste") is not None


def reader_for_backend(backend: ClipboardBackend) -> ClipboardReader | None:
    """The snapshot reader for a backend, or None when its tool is missing."""
    if not clipboard_read_available(backend):
        return None
    return read_clipboard_x11 if backend is ClipboardBackend.X11 else read_clipboard


def restorer_for_backend(backend: ClipboardBackend) -> ClipboardRestorer:
    """The snapshot restorer for a backend. PURE mapping."""
    return restore_clipboard_x11 if backend is ClipboardBackend.X11 else restore_clipboard


def probe_clipboard() -> tuple[bool, str]:
    """(needed binary present, detected backend name) for the delivery copy path."""
    backend = detect_clipboard_backend()
    binary = "xclip" if backend is ClipboardBackend.X11 else "wl-copy"
    return shutil.which(binary) is not None, backend.value
