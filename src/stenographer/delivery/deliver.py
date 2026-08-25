# SPDX-License-Identifier: GPL-3.0-or-later
"""Final-output boundary: copy → confirm → release-guard → paste chord.

The clipboard writer and the key injector come from the current platform
(``stenographer.platform``); this module holds only the delivery policy, which
is platform-neutral: empty text is not delivered, a failed copy never fires the
chord, and a release-wait timeout proceeds because the clipboard already holds
the transcript as recovery.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from stenographer.utils.logging_setup import fmt_event

if TYPE_CHECKING:
    from collections.abc import Callable

    from stenographer.platform.base import ClipboardWriter, KeyInjector

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeliveryTimings:
    """What one delivery attempt cost, for the utterance summary line."""

    copy_ms: float
    release_wait_ms: float | None
    release_timeout: bool | None


class Deliverer:
    """Copy → confirm → release-guard → paste-chord, in that fixed order.

    Collaborators are injected so the daemon (M5) owns the single persistent
    injector (from the current platform) and wires the hotkey listener's
    ``wait_binding_released``. This is dependency wiring, not test mocking.
    """

    def __init__(
        self,
        *,
        keyboard: KeyInjector,
        wait_released: Callable[[], bool] | None = None,
        copy: ClipboardWriter,
    ) -> None:
        self._keyboard = keyboard
        self._wait_released = wait_released
        self._copy = copy
        # One utterance at a time, so the last attempt is the caller's own.
        self.last_timings: DeliveryTimings | None = None

    def deliver(self, text: str) -> bool:
        """Deliver *text* at the cursor. Return True once the chord is sent.

        Empty text is success-shaped upstream: return False, no side effects.
        A failed copy returns False WITHOUT sending the chord (the
        copy-confirmed-before-paste rule) — a chord after a failed copy pastes
        stale clipboard content. On a release-wait timeout, proceed anyway: the
        clipboard already holds the transcript as recovery.
        """
        if not text:
            return False
        copy_started_at = time.perf_counter()
        copied = self._copy(text)
        copy_ms = (time.perf_counter() - copy_started_at) * 1000.0
        if not copied:
            self.last_timings = DeliveryTimings(copy_ms, None, None)
            return False
        release_wait_ms: float | None = None
        released: bool | None = None
        if self._wait_released is not None:
            release_started_at = time.perf_counter()
            released = self._wait_released()
            release_wait_ms = (time.perf_counter() - release_started_at) * 1000.0
            if not released:
                log.warning(
                    fmt_event(
                        "deliver",
                        "binding_still_held",
                        action="proceed",
                        waited_ms=round(release_wait_ms, 1),
                        reason="clipboard_already_holds_transcript",
                    )
                )
        self.last_timings = DeliveryTimings(
            copy_ms, release_wait_ms, None if released is None else not released
        )
        self._keyboard.send_chord()
        return True

    def close(self) -> None:
        self._keyboard.close()
