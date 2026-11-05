# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import enum
import logging
import os
import selectors
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from stenographer.lib.logging.pipeline import fmt_event, log_failure
from stenographer.lib.platform.linux.process import child_env
from stenographer.lib.platform.types import ClipboardSnapshot

if TYPE_CHECKING:
    from collections.abc import Sequence


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


@dataclass(frozen=True)
class ClipboardTools:
    """The tools of one backend and their exact command lines."""

    copy_tool: str
    read_tool: str
    #: ``(selection, argv)`` of each write that delivers a copy.
    copies: tuple[tuple[str, tuple[str, ...]], ...]
    #: Taking X11 selection ownership is fire-and-forget, so xclip's writes are
    #: read back; wl-copy's exit status is already the answer.
    verify_copies: bool
    list_argv: tuple[str, ...]
    read_argv: tuple[str, ...]
    restore_argv: tuple[str, ...]


_XCLIP_READ = ("xclip", "-selection", "clipboard", "-o", "-t")


class ClipboardBackend(enum.Enum):
    WL_COPY = "wl-copy"
    X11 = "x11"

    @property
    def tools(self) -> ClipboardTools:
        return _BACKEND_TOOLS[self]


_BACKEND_TOOLS = {
    ClipboardBackend.WL_COPY: ClipboardTools(
        copy_tool="wl-copy",
        read_tool="wl-paste",
        copies=(("clipboard", ("wl-copy",)), ("primary", ("wl-copy", "--primary"))),
        verify_copies=False,
        list_argv=("wl-paste", "-l"),
        read_argv=("wl-paste", "-n", "-t"),
        restore_argv=("wl-copy",),
    ),
    ClipboardBackend.X11: ClipboardTools(
        copy_tool="xclip",
        read_tool="xclip",
        copies=(
            ("clipboard", ("xclip", "-selection", "clipboard")),
            ("primary", ("xclip", "-selection", "primary")),
        ),
        verify_copies=True,
        list_argv=(*_XCLIP_READ, "TARGETS"),
        read_argv=_XCLIP_READ,
        restore_argv=("xclip", "-selection", "clipboard"),
    ),
}


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


def _write_to_tool(argv: Sequence[str], payload: bytes) -> None:
    """Pipe *payload* to *argv*; raises one of ``_COPY_ERRORS`` on failure.

    stdout/stderr go to DEVNULL rather than being captured: wl-copy and xclip
    fork and serve the selection in the background, and the forked child
    inherits any pipes, so capturing blocks until the timeout even though the
    selection is already set. The return code is still collected, so check=True
    is unchanged. Nothing raised here has seen the payload.
    """
    subprocess.run(
        list(argv),
        input=payload,
        check=True,
        timeout=_COPY_TIMEOUT_SECONDS,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=child_env(),
    )


def copy_both_selections(tools: ClipboardTools, text: str) -> bool:
    """Copy *text* to the regular clipboard and the primary selection.

    Both selections because Shift+Insert reads the primary selection in some
    clients (e.g. kitty) and the regular clipboard in others. Returns True only
    if every write succeeds and, where *tools* asks for it, reads back as *text*.
    """
    payload = text.encode("utf-8")
    for selection, argv in tools.copies:
        try:
            _write_to_tool(argv, payload)
        except _COPY_ERRORS as exc:
            # WARNING, not DEBUG: a failed copy is why nothing was pasted, and
            # the tool's own complaint is host vocabulary, never transcript.
            log_failure(
                log,
                logging.WARNING,
                "deliver: copy_failed",
                exc,
                safe=True,
                argv=" ".join(argv),
                phase="write" if tools.verify_copies else None,
            )
            return False
        if tools.verify_copies and not _selection_holds(selection, argv, payload):
            return False
    return True


def _selection_holds(selection: str, argv: Sequence[str], payload: bytes) -> bool:
    """Whether reading the selection back (``-o`` exits without forking) gives *payload*."""
    try:
        readback = subprocess.run(
            [*argv, "-o"],
            check=True,
            timeout=_COPY_TIMEOUT_SECONDS,
            capture_output=True,
            env=child_env(),
        )
    except _COPY_ERRORS as exc:
        # safe=False, and split from the write for exactly this reason: the
        # read-back captures the selection, so a raised
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


def _capture_bounded(argv: Sequence[str], deadline: float) -> bytes | None:
    """*argv*'s stdout, or None once it fails, overruns the deadline or the cap.

    ``capture_output`` cannot bound memory, so stdout is read in chunks that
    stop at one byte past the cap, and the child is killed on overflow or
    deadline.
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
                chunk = os.read(proc.stdout.fileno(), min(65536, _SNAPSHOT_MAX_BYTES + 1 - size))
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


def read_clipboard(tools: ClipboardTools) -> ClipboardSnapshot | None:
    """Snapshot the regular clipboard, never primary: list, pick, read; one budget."""
    deadline = time.monotonic() + _SNAPSHOT_BUDGET_SECONDS
    listing = _capture_bounded(tools.list_argv, deadline)
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
    data = _capture_bounded([*tools.read_argv, mime], deadline)
    if data is None:
        return None
    if not data:
        log.debug(fmt_event("deliver", "snapshot_skipped", reason="empty"))
        return None
    return ClipboardSnapshot(mime, data)


def restore_clipboard(tools: ClipboardTools, snapshot: ClipboardSnapshot) -> bool:
    """Put *snapshot* back on the regular clipboard only, with its own type."""
    argv = [*tools.restore_argv, "-t", snapshot.mime]
    try:
        _write_to_tool(argv, snapshot.data)
    except _COPY_ERRORS as exc:
        log_failure(log, logging.WARNING, "deliver: restore_failed", exc, safe=True, tool=argv[0])
        return False
    return True


def clipboard_read_available(tools: ClipboardTools) -> bool:
    """Whether the tool that reads this backend's clipboard is installed."""
    return shutil.which(tools.read_tool) is not None


def probe_clipboard() -> tuple[bool, bool, str]:
    """(copy tool present, read tool present, detected backend name) for delivery."""
    backend = detect_clipboard_backend()
    tools = backend.tools
    return shutil.which(tools.copy_tool) is not None, clipboard_read_available(tools), backend.value
