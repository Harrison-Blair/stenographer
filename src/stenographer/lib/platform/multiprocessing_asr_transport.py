# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from stenographer.lib.config.models import AsrConfig

from stenographer.lib.platform.multiprocessing_asr_process import MultiprocessingAsrProcess


class MultiprocessingAsrTransport:
    def spawn(
        self, config: AsrConfig, *, on_log: Callable[[logging.LogRecord], None]
    ) -> MultiprocessingAsrProcess:
        return MultiprocessingAsrProcess(config, on_log=on_log)
