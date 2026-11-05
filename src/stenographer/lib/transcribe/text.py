# SPDX-License-Identifier: GPL-3.0-or-later
"""Text measurements used by transcription and refinement."""

import re

_WORD = re.compile(r"[^\W_]+(?:['\u2019][^\W_]+)*", re.UNICODE)


def count_words(text: str) -> int:
    return len(_WORD.findall(text))
