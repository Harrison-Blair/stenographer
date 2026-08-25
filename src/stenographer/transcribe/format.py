# SPDX-License-Identifier: GPL-3.0-or-later
"""The fixed transcript formatter: zero knobs, whitespace ownership.

One pure public function. It owns all spacing (single space between tokens,
none before closing punctuation), capitalises sentence starts, and maps a
standalone ``i`` to ``I``. Reference: the old ``output/formatter.py``, minus
paragraph-pause breaks, the normalize/capitalize toggles, and raw passthrough.
"""

from __future__ import annotations

import logging

from stenographer.utils.logging_setup import fmt_event

log = logging.getLogger(__name__)

_NO_SPACE_BEFORE = ",.?!;:"
_SENTENCE_TERMINALS = ".?!"


def _capitalize(token: str) -> str:
    for i, ch in enumerate(token):
        if ch.isalpha():
            return token[:i] + ch.upper() + token[i + 1 :]
    return token


def format_transcript(text: str, *, trailing_space: bool = False) -> str:
    """Format ``text`` into a single spacing-normalised line; ``""`` if blank."""
    out: list[str] = []
    capitalize_next = True
    for token in text.split():
        word = "I" if token == "i" else token
        if capitalize_next:
            word = _capitalize(word)
        sep = "" if not out or word[0] in _NO_SPACE_BEFORE else " "
        out.append(sep + word)
        capitalize_next = word[-1] in _SENTENCE_TERMINALS
    result = "".join(out)
    if trailing_space and result:
        result += " "
    log.debug(fmt_event("format", "applied", in_chars=len(text), out_chars=len(result)))
    return result
