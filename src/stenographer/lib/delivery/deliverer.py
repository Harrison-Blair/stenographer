# SPDX-License-Identifier: GPL-3.0-or-later
"""Final-output boundary: snapshot → copy → confirm → release-guard → paste chord.

The clipboard writer, reader, restorer and the key injector come from the
current platform (``stenographer.lib.platform``); this module holds only the
delivery policy, which is platform-neutral: empty text is not delivered, a
failed copy never fires the chord, and a release-wait timeout proceeds because
the copy is already confirmed. After the chord the caller asks for
:meth:`Deliverer.restore_clipboard`, which puts back the clipboard item the
user had before this delivery wrote over it."""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from typing import TYPE_CHECKING

from stenographer.lib.logging.pipeline import fmt_event, log_failure

if TYPE_CHECKING:
    from collections.abc import Callable

    from stenographer.lib.platform.clipboard_snapshot import ClipboardSnapshot
    from stenographer.lib.platform.key_injector import KeyInjector
    from stenographer.lib.platform.types import (
        ClipboardReader,
        ClipboardRestorer,
        ClipboardWriter,
    )

from stenographer.lib.delivery.timings import DeliveryTimings

log = logging.getLogger(__name__)


class Deliverer:
    """Snapshot → copy → confirm → release-guard → paste-chord, in that fixed order.

    Collaborators are injected so the daemon (M5) owns the single persistent
    injector (from the current platform) and wires the hotkey listener's
    ``wait_binding_released``. This is dependency wiring, not test mocking.
    Without ``read`` and ``restore`` the clipboard keeps the delivered text.
    """

    def __init__(
        self,
        *,
        keyboard: KeyInjector,
        wait_released: Callable[[], bool] | None = None,
        copy: ClipboardWriter,
        read: ClipboardReader | None = None,
        restore: ClipboardRestorer | None = None,
        restore_delay: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._keyboard = keyboard
        self._wait_released = wait_released
        self._copy = copy
        self._read = read
        self._restore = restore
        self._restore_delay = restore_delay
        self._sleep = sleep
        # One utterance at a time, so the last attempt is the caller's own.
        self.last_timings: DeliveryTimings | None = None
        # Held only between a snapshot and the write that follows it at once.
        self._snapshot: ClipboardSnapshot | None = None

    def deliver(
        self,
        text: str,
        *,
        original: str | None = None,
        on_copied: Callable[[], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> bool:
        """Deliver *text* at the cursor. Return True once the chord is sent.

        Empty text is success-shaped upstream: return False, no side effects.
        A non-empty *original* is copied first, best effort, so a clipboard
        history keeps it one entry behind *text*. A failed copy of *text*
        returns False WITHOUT sending the chord (the copy-confirmed-before-paste
        rule) — a chord after a failed copy pastes stale clipboard content. On
        a release-wait timeout, proceed anyway: the copy is already confirmed.
        """
        self.last_timings = None
        self._snapshot = None
        if not text or (cancelled is not None and cancelled()):
            return False
        snapshot_ms: float | None = None
        if self._read is not None:
            snapshot_started_at = time.perf_counter()
            try:
                self._snapshot = self._read()
            except Exception as exc:
                # The reader captures another application's bytes.
                log_failure(log, logging.WARNING, "deliver: snapshot_failed", exc, safe=False)
            snapshot_ms = (time.perf_counter() - snapshot_started_at) * 1000.0
            # A slow snapshot must never lead to a write after a cancel.
            if cancelled is not None and cancelled():
                self._snapshot = None
                return False
        original_copied: bool | None = None
        original_copy_ms: float | None = None
        if original:
            original_started_at = time.perf_counter()
            try:
                original_copied = self._copy(original)
            except Exception as exc:
                original_copied = False
                log_failure(log, logging.WARNING, "deliver: original_copy_failed", exc, safe=False)
            else:
                if not original_copied:
                    log.warning(fmt_event("deliver", "original_copy_failed"))
            original_copy_ms = (time.perf_counter() - original_started_at) * 1000.0
        copy_started_at = time.perf_counter()
        copied = False
        try:
            copied = self._copy(text)
        finally:
            copy_ms = (time.perf_counter() - copy_started_at) * 1000.0
            timings = DeliveryTimings(
                copy_ms,
                None,
                None,
                copied=copied,
                snapshot_ms=snapshot_ms,
                original_copied=original_copied,
                original_copy_ms=original_copy_ms,
            )
            self.last_timings = timings
        if not copied:
            return False
        if on_copied is not None:
            on_copied()
        if self._wait_released is not None:
            release_started_at = time.perf_counter()
            released: bool | None = None
            try:
                released = self._wait_released()
            finally:
                release_wait_ms = (time.perf_counter() - release_started_at) * 1000.0
                timings = replace(
                    timings,
                    release_wait_ms=release_wait_ms,
                    release_timeout=None if released is None else not released,
                )
                self.last_timings = timings
            if not released:
                log.warning(
                    fmt_event(
                        "deliver",
                        "binding_still_held",
                        action="proceed",
                        waited_ms=round(release_wait_ms, 1),
                        reason="copy_already_confirmed",
                    )
                )
        if cancelled is not None and cancelled():
            return False
        self._keyboard.send_chord()
        self.last_timings = replace(timings, chord_sent=True)
        return True

    def restore_clipboard(self) -> bool:
        """Put back the clipboard item the last :meth:`deliver` wrote over.

        A no-op returning False unless that delivery took a snapshot, which it
        keeps only once a write follows. Otherwise wait the settle delay, so the target window
        has read the paste, then write the snapshot back once; it is dropped
        either way. Never raises: a failure is logged and returns False. A
        cancel is deliberately not consulted, because the paste has landed.
        """
        snapshot, self._snapshot = self._snapshot, None
        if snapshot is None or self._restore is None:
            return False
        restored = False
        restore_started_at = time.perf_counter()
        try:
            self._sleep(self._restore_delay)
            restore_started_at = time.perf_counter()
            restored = self._restore(snapshot)
        except Exception as exc:
            log_failure(log, logging.WARNING, "deliver: restore_failed", exc, safe=False)
        else:
            if not restored:
                log.warning(fmt_event("deliver", "restore_failed"))
        if self.last_timings is not None:
            self.last_timings = replace(
                self.last_timings,
                restore_ms=(time.perf_counter() - restore_started_at) * 1000.0,
                restored=restored,
            )
        return restored

    def close(self) -> None:
        self._keyboard.close()
