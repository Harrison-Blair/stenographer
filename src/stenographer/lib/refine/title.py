# SPDX-License-Identifier: GPL-3.0-or-later
"""Ask the Refine model for a one-line session title.

The request goes through :func:`stenographer.lib.refine.client.post_chat`, the
only code that talks to Ollama. Its body sets no context size: a ``num_ctx``
that differs from the one the model was loaded with makes Ollama load the
model again. Nothing here logs; a failure raises a :class:`RefineError` with a
fixed reason, never the transcript or the reply.
"""

from __future__ import annotations

import itertools
from typing import TYPE_CHECKING

from stenographer.lib.refine.client import post_chat
from stenographer.lib.refine.errors import RefineRejectedError
from stenographer.lib.refine.response import message_content

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

#: Words in each of the three samples of a long transcript.
SAMPLE_WORDS = 600
#: A reply longer than this, after the removal of outer white space, is discarded.
MAX_TITLE_CHARS = 80
#: A title is a few words; the limit only stops a model that does not end.
NUM_PREDICT = 40
#: The reply budget includes a cold load of the model.
TIMEOUT_SECONDS = 150.0
#: Separates the three samples in the request.
SAMPLE_GAP = "\n[…]\n"

#: Tuned on 2026-11-12 with gemma4:e2b against six synthetic transcripts.
SYSTEM_PROMPT = (
    "Write a title for this transcript of a recording. Name the specific subjects that were "
    "discussed, not the kind of recording; avoid generic words such as meeting, call, "
    "discussion, updates or notes. Start with a capital letter and use at most eight words; "
    "separate up to three subjects with commas. Reply with only the title on one line, with "
    "no quotes and no final period."
)


def transcript_samples(lines: Sequence[str]) -> str:
    """Return the text to send: the whole transcript, or three samples of it. PURE.

    A transcript of at most three samples of words is sent whole. A longer one gives
    :data:`SAMPLE_WORDS` words each from the start, around the middle word, and from
    the end, by word position: no word is in two samples, and a sample may start or end
    inside a line. A sample keeps the line breaks between its words. An empty
    transcript gives ``""``.
    """

    lines = [line for line in lines if line.split()]
    words = [(number, word) for number, line in enumerate(lines) for word in line.split()]
    if len(words) <= 3 * SAMPLE_WORDS:
        return "\n".join(lines)
    middle = len(words) // 2 - SAMPLE_WORDS // 2
    starts = (0, middle, len(words) - SAMPLE_WORDS)
    return SAMPLE_GAP.join(_join(words[start : start + SAMPLE_WORDS]) for start in starts)


def _join(words: list[tuple[int, str]]) -> str:
    """Join ``(line number, word)`` pairs: a space inside a line, a line break between lines."""
    text = words[0][1]
    for (line, _), (next_line, word) in itertools.pairwise(words):
        text += ("\n" if next_line != line else " ") + word
    return text


def build_title_body(text: str, *, model: str, keep_alive: int) -> dict[str, object]:
    """The complete ``/api/chat`` body of one title request. PURE."""

    return {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "stream": False,
        "think": False,
        "keep_alive": keep_alive,
        "options": {"temperature": 0, "num_predict": NUM_PREDICT},
    }


def title_from_reply(payload: str | bytes) -> str:
    """Return the title of a reply, or raise :class:`RefineRejectedError`. PURE.

    The title is the reply without outer white space. It must be one line of
    1 to :data:`MAX_TITLE_CHARS` characters.
    """

    title = message_content(payload).strip()
    if not title:
        raise RefineRejectedError("the model gave no title")
    if "\n" in title or "\r" in title:
        raise RefineRejectedError("the title was not one line")
    if len(title) > MAX_TITLE_CHARS:
        raise RefineRejectedError(f"the title was longer than {MAX_TITLE_CHARS} characters")
    return title


def request_title(
    host: str,
    model: str,
    text: str,
    *,
    keep_alive: int,
    post: Callable[..., bytes] = post_chat,
) -> str:
    """Send one title request for *text* and return the checked title.

    Raises only :class:`RefineError`.
    """

    body = build_title_body(text, model=model, keep_alive=keep_alive)
    return title_from_reply(post(host, body, timeout=TIMEOUT_SECONDS))
