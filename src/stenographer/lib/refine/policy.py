# SPDX-License-Identifier: GPL-3.0-or-later
"""When the refine stage runs, and how long it may take. PURE.

Both decisions are arithmetic over one word count, kept out of the refiner so
the pipeline can ask "will this utterance be refined?" without building a
request, and so the time budget can be asserted in a unit test without a model.
"""

from __future__ import annotations

from stenographer.lib.analytics.metrics import count_words

#: Fixed part of the per-utterance budget: model scheduling plus first token.
TIMEOUT_BASE_SECONDS = 10.0

#: Marginal part: roughly the decode cost of one more spoken word.
TIMEOUT_PER_WORD_SECONDS = 0.06

#: How long one utterance may wait for a model that is not resident to load.
#: The reply budget above assumes a warm model; a cold load is paged in from
#: disk and can take far longer than any reply, so it gets its own budget and
#: the reply budget starts only once the model is up.
COLD_LOAD_TIMEOUT_SECONDS = 120.0

#: The keep_alive Ollama is sent when the ASR worker never unloads either.
#: Negative means "hold the model indefinitely" in Ollama's own vocabulary.
INDEFINITE_KEEP_ALIVE = -1


def word_count(text: str) -> int:
    """Count words exactly as the analytics layer does, so the two agree."""

    return count_words(text)


def should_refine(text: str, min_words: int) -> bool:
    """Whether *text* is long enough to be worth a model round-trip."""

    return bool(text.strip()) and word_count(text) >= min_words


def timeout_seconds(words: int) -> float:
    """The wall-clock budget for one reply from a resident model, in seconds."""

    return TIMEOUT_BASE_SECONDS + TIMEOUT_PER_WORD_SECONDS * max(0, words)


def keep_alive_for(idle_unload_seconds: int) -> int:
    """Tie the model's residency to the ASR worker's own idle-unload window.

    ``idle_unload_seconds = 0`` disables the ASR unload entirely, so the refine
    model is held indefinitely to match rather than being evicted after every
    utterance.
    """

    return INDEFINITE_KEEP_ALIVE if idle_unload_seconds <= 0 else int(idle_unload_seconds)
