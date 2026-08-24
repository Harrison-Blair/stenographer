# SPDX-License-Identifier: GPL-3.0-or-later
"""Desktop notifications, errors only.

``notify-send`` is fired non-blocking and no-ops when absent. Only short,
caller-supplied error strings are ever passed — never audio or transcript text
(the log-privacy rule). The one pure unit target is ``build_notify_command``
(mirroring cues.build_play_command); the Popen call is never mock-tested.
"""

from __future__ import annotations

import logging
import shutil
import subprocess

from stenographer.platform.linux.process import child_env

log = logging.getLogger(__name__)


def build_notify_command(message: str) -> list[str]:
    """The ``notify-send`` argv for an error notification. PURE."""
    return ["notify-send", "-a", "Stenographer", "-u", "critical", "Stenographer", message]


class NotifySendNotifier:
    """Fires error notifications, degrading to a no-op when notify-send is absent."""

    def __init__(self) -> None:
        self._available = self.probe()

    @staticmethod
    def probe() -> bool:
        """True if ``notify-send`` is on PATH (shared with the M6 doctor probe)."""
        return shutil.which("notify-send") is not None

    def error(self, message: str) -> None:
        """Show *message* as a critical notification, non-blocking. No-op when
        unavailable; failures are swallowed to log.debug (a broken notifier must
        never take the daemon down)."""
        if not self._available:
            return
        try:
            subprocess.Popen(
                build_notify_command(message),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=child_env(),
            )
        except OSError as exc:
            log.debug("notify: send failed: %s", exc)
