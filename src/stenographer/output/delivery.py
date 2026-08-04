# SPDX-License-Identifier: GPL-3.0-or-later
"""Final-output delivery boundary: type/paste the transcript and copy to clipboard."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from stenographer.errors import notify_failure

if TYPE_CHECKING:
    from collections.abc import Callable

    from stenographer.capabilities import Capabilities
    from stenographer.config import ClipboardConfig, OutputConfig
    from stenographer.output.clipboard import ClipboardManager
    from stenographer.output.inject import Injector

log = logging.getLogger(__name__)


class TranscriptDelivery:
    """Performs one focused-app delivery of a final transcript."""

    def __init__(
        self,
        *,
        output: OutputConfig,
        clipboard_cfg: ClipboardConfig,
        capabilities: Capabilities,
        injector: Injector,
        clipboard: ClipboardManager,
        wait_hotkey_released: Callable[[], bool] | None = None,
    ) -> None:
        self._output = output
        self._clipboard_cfg = clipboard_cfg
        self._caps = capabilities
        self._injector = injector
        self._clipboard = clipboard
        self._wait_hotkey_released = wait_hotkey_released

    def _await_hotkey_release(self) -> None:
        """Wait for the hotkey binding to be physically released.

        A modifier binding (e.g. RCtrl) still held when we inject merges
        into the seat state: the paste chord becomes Ctrl+Shift+Insert and
        typed text fires Ctrl+<letter> shortcuts. On timeout we proceed
        anyway — the clipboard already holds the transcript as recovery.
        """
        if self._wait_hotkey_released is None:
            return
        if not self._wait_hotkey_released():
            log.warning(
                "delivery: hotkey still held after wait; proceeding "
                "(clipboard already holds the transcript)"
            )

    def deliver_final(self, text: str) -> bool:
        """Apply the output cap once, then perform one focused-app delivery."""
        if not text:
            return False
        if self._output.injection_method == "clipboard_paste":
            # Uncapped on purpose: the cap bounds per-character wtype
            # synthesis, which pasting does not do. Here the clipboard is the
            # transport rather than a recovery copy, so capping before the copy
            # would drop the tail somewhere the user cannot reach it at all.
            return self._deliver_paste(text)

        max_chars = self._output.max_chars
        injected = text
        if len(text) > max_chars:
            log.warning("delivery: truncating transcript from %d to %d chars", len(text), max_chars)
            injected = text[:max_chars]

        delivered = False
        if self._caps.has_paste_trigger:
            self._await_hotkey_release()
            try:
                # Incremental/batch formatters already applied whitespace and
                # trailing-space policy; raw avoids preparing it a second time.
                delivered = bool(self._injector.type_text(injected, raw=True))
            except Exception as exc:
                log.error("delivery: injector.type_text raised: %s", exc)
        if self._clipboard_cfg.enabled and self._caps.has_wl_copy:
            copied = False
            try:
                # The full transcript, not the capped one: the clipboard is the
                # recovery path for whatever the cap kept from being typed.
                # primary=True: this copy exists to be pasted by hand, and the
                # paste chord reads the primary selection in some clients --
                # populating only the regular clipboard would make Shift+Insert
                # paste the user's old mouse selection instead.
                copied = bool(self._clipboard.copy(text, primary=True))
            except Exception as exc:
                log.error("delivery: clipboard.copy raised: %s", exc)
            # Without a paste trigger the clipboard is the only transport left.
            # A successful copy still put the transcript within reach, so it is
            # a delivery -- otherwise every dictation on a machine without
            # wtype ends on the error cue.
            delivered = delivered or copied
        return delivered

    def _deliver_paste(self, text: str) -> bool:
        """Copy *text*, then fire the paste chord to deliver it at the cursor.

        The chord pastes whatever the clipboard currently holds, so it is
        fired only after a confirmed copy: on a failed copy it would paste
        the user's previous clipboard content into their document. Config
        validation guarantees clipboard.enabled in clipboard_paste mode, so
        there is no flag to honour here -- the clipboard is the transport.

        Returns True when the text reached the cursor. Callers must not play
        the success cue on a False: the clipboard is the only transport, so a
        failed copy means the utterance reached neither the cursor nor the
        clipboard and the user has nothing to recover.
        """
        if not self._caps.has_wl_copy:
            notify_failure("clipboard_paste mode requires wl-copy; nothing delivered")
            return False
        copied = False
        try:
            copied = self._clipboard.copy(text, primary=True)
        except Exception as exc:
            log.error("delivery: clipboard.copy raised: %s", exc)
        if not copied:
            notify_failure("clipboard copy failed; skipping paste to avoid pasting stale text")
            return False
        if not self._caps.has_paste_trigger:
            # The text is on the clipboard, so it is recoverable by hand, but
            # nothing reached the cursor -- not a success.
            log.error("delivery: no paste trigger available; transcript left on the clipboard")
            return False
        self._await_hotkey_release()
        try:
            return bool(self._injector.paste())
        except Exception as exc:
            log.error("delivery: injector.paste raised: %s", exc)
            return False
