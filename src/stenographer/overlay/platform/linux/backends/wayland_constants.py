# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


REQUIRED_GLOBALS = ("wl_compositor", "wl_shm", "zwlr_layer_shell_v1")


_OPTIONAL_GLOBALS = ("wp_fractional_scale_manager_v1", "wp_viewporter")


_REQUIRED_VERSIONS = {"wl_compositor": 3, "wl_shm": 1, "zwlr_layer_shell_v1": 1}


_MAX_IN_FLIGHT_BUFFERS = 3


_OUTPUT_INTERFACE = "wl_output"
