# SPDX-License-Identifier: GPL-3.0-or-later
"""Ask the Refine model for a one-line session title.

The request goes through :func:`stenographer.lib.refine.client.post_chat`, the
only code that talks to Ollama. Its body sets no context size: a ``num_ctx``
that differs from the one the model was loaded with makes Ollama load the
model again. Nothing here logs; a failure raises a :class:`RefineError` with a
fixed reason, never the transcript or the reply.
"""

from __future__ import annotations

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
    whole lines from the start, around the middle, and from the end, each until it
    holds at least :data:`SAMPLE_WORDS` words. An empty transcript gives ``""``.
    """

    lines = [line for line in lines if line.split()]
    counts = [len(line.split()) for line in lines]
    if sum(counts) <= 3 * SAMPLE_WORDS:
        return "\n".join(lines)
    count = len(lines)
    middle = count // 2
    around = [middle]
    for step in range(1, count):
        around += [index for index in (middle + step, middle - step) if 0 <= index < count]
    samples = []
    for order in (range(count), around, range(count - 1, -1, -1)):
        picked: list[int] = []
        words = 0
        for index in order:
            if words >= SAMPLE_WORDS:
                break
            picked.append(index)
            words += counts[index]
        samples.append("\n".join(lines[index] for index in sorted(picked)))
    return SAMPLE_GAP.join(samples)


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
