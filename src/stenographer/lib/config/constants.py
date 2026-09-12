# SPDX-License-Identifier: GPL-3.0-or-later
"""Configuration vocabulary and validation bounds."""

from __future__ import annotations

import re

ALLOWED_COMPUTE_TYPES: frozenset[str] = frozenset(
    {"int8", "int8_float16", "float16", "float32", "default"}
)


ALLOWED_HOTKEY_MODES: frozenset[str] = frozenset({"hold", "toggle", "hybrid"})


ALLOWED_LOG_LEVELS: frozenset[str] = frozenset({"debug", "info", "warning", "error"})


MIN_SPECTRUM_FLOOR_DBFS = -96.0


MAX_SPECTRUM_FLOOR_DBFS = -13.0


SOUND_PACK_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


DEFAULT_SOUND_PACK = "minimal-ui"


#: The refine stage accepts an HTTP(S) Ollama host and nothing else.
ALLOWED_REFINE_SCHEMES: frozenset[str] = frozenset({"http", "https"})


MIN_REFINE_WORDS = 1


MAX_REFINE_WORDS = 10000


SpectrumFloor = float | tuple[float, ...]
