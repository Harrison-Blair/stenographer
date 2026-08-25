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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from stenographer.platform.base import ClipboardWriter, KeyInjector

log = logging.getLogger(__name__)


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
        if not self._copy(text):
            return False
        if self._wait_released is not None and not self._wait_released():
            log.warning(
                "deliver: binding_still_held action=proceed "
                "reason=clipboard_already_holds_transcript"
            )
        self._keyboard.send_chord()
        return True

    def close(self) -> None:
        self._keyboard.close()
