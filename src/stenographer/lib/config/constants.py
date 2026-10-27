# SPDX-License-Identifier: GPL-3.0-or-later
"""Configuration vocabulary and validation bounds."""

from __future__ import annotations

import re

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


#: Refine vocabulary bounds: one term is a word or a short name, and the list
#: rides in every refine request, so its total size stays small.
MAX_VOCABULARY_TERM_CHARS = 64


MAX_VOCABULARY_TERMS = 200


#: A minute bounds the busy window after each paste and stays far inside
#: what ``time.sleep`` accepts.
MAX_RESTORE_DELAY_MS = 60000


SpectrumFloor = float | tuple[float, ...]
