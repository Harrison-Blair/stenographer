# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging

from stenographer.overlay.spectrum.analysis import SPECTRUM_FPS

log = logging.getLogger(__name__)


_MAILBOX_CAPACITY = 8


_POLL_SECONDS = 0.05


_READY_TIMEOUT_SECONDS = 3.0


_SHUTDOWN_GRACE_SECONDS = 0.75


_THREAD_JOIN_SECONDS = 2.0


_READ_SIZE = 4096


_SPECTRUM_INTERVAL = 1.0 / SPECTRUM_FPS
