# SPDX-License-Identifier: GPL-3.0-or-later
"""Read one Ollama reply and decide whether it may be delivered. PURE: no I/O.

This is the half of the stage that assumes the model is untrustworthy. A local
model that answered the utterance instead of editing it, echoed its reasoning,
wrapped the answer in a code fence, or returned nothing at all must not reach
the user's cursor — and none of those are transport errors, so only a content
guard can catch them.

Every rejection raises :class:`RefineRejectedError` with a fixed reason. The
text that was rejected is never part of the message: the caller logs the
reason, and the caller's log is the user's log.
"""

from __future__ import annotations

import json

from stenographer.lib.refine.errors import RefineRejectedError, RefineResponseError
from stenographer.lib.refine.prompt import RESPONSE_KEY

#: Accepted length of the output relative to the input. Cleanup removes fillers
#: and adds punctuation, so it stays close to the original; a reply far outside
#: this band answered, summarized, or repeated itself.
#:
#: The floor is 0.30 rather than 0.40 because the benchmark found a *correct*
#: answer below the tighter bound: collapsing an enumeration whose last item the
#: speaker retracted legitimately drops about a third of the words, and measured
#: 0.37-0.40 for every model tested. A guard that rejects the right answer is
#: worse than one that occasionally lets a short one through.
MIN_LENGTH_RATIO = 0.30
MAX_LENGTH_RATIO = 1.6

#: One wrapping pair is stripped before the checks; a second one is a refusal.
_QUOTE_PAIRS = (
    ('"', '"'),
    ("'", "'"),
    ("\u201c", "\u201d"),  # curly double quotes
    ("\u2018", "\u2019"),  # curly single quotes
)
_FENCE = "```"

#: Ollama's own word for "I stopped because num_predict ran out".
_TRUNCATED_REASON = "length"


def message_content(payload: str | bytes) -> str:
    """The assistant's text from a non-streaming ``/api/chat`` reply.

    A reply cut off at ``num_predict`` is refused here rather than passed on.
    Truncation is the one failure the length guard cannot be trusted to catch:
    the prefix of a correct answer is well-formed, unquoted, and usually still
    inside the length band, so it would sail through and paste half a sentence
    at the user's cursor. Ollama says so itself in ``done_reason``; an older
    build that omits the field is taken at its word rather than assumed bad.
    """

    try:
        data = json.loads(payload)
    except ValueError as exc:
        raise RefineResponseError("reply was not JSON") from exc
    if not isinstance(data, dict):
        raise RefineResponseError("reply was not an object")
    if data.get("done_reason") == _TRUNCATED_REASON:
        raise RefineRejectedError("output was truncated")
    message = data.get("message")
    if not isinstance(message, dict):
        raise RefineResponseError("reply carried no message")
    content = message.get("content")
    if not isinstance(content, str):
        raise RefineResponseError("reply carried no content")
    return content


def unwrap_structured(content: str, *, structured_output: bool) -> str:
    """Take the schema's field out of a structured reply, or pass text through."""

    if not structured_output:
        return content
    try:
        data = json.loads(content)
    except ValueError as exc:
        raise RefineResponseError("structured reply was not JSON") from exc
    if not isinstance(data, dict):
        raise RefineResponseError("structured reply was not an object")
    value = data.get(RESPONSE_KEY)
    if not isinstance(value, str):
        raise RefineResponseError("structured reply had no text field")
    return value


def _wraps(value: str, opening: str, closing: str) -> bool:
    """Whether *opening*/*closing* really enclose *value*. PURE.

    Starting and ending with a quote is not the same as being quoted. Dictated
    dialogue does it constantly — ``"We are done," he said, and then, "let's go
    home."`` — and stripping those two characters corrupts the paste silently,
    which is the worst way for this stage to fail.

    So a quote counts as a wrapper only when the text contains no other
    candidate for it: exactly two of a symmetric mark, exactly one each of an
    asymmetric pair. An apostrophe anywhere inside therefore disqualifies the
    single-quote reading, which is what makes ``'tis ... the dog's bowl'`` safe.
    """

    if len(value) < 2 or not value.startswith(opening) or not value.endswith(closing):
        return False
    if opening == closing:
        return value.count(opening) == 2
    return value.count(opening) == 1 and value.count(closing) == 1


def _strip_one_wrapper(text: str) -> tuple[str, bool]:
    """Remove a single wrapping fence or quote pair. PURE.

    Returns the inner text and whether a pair was actually removed, so the
    caller can tell "was never wrapped" from "was wrapped once".
    """

    value = text.strip()
    if len(value) >= 2 * len(_FENCE) and value.startswith(_FENCE) and value.endswith(_FENCE):
        inner = value[len(_FENCE) : -len(_FENCE)]
        # ```json\n...\n``` — the opening fence may carry a language tag.
        head, newline, rest = inner.partition("\n")
        if newline and head.strip().isalpha():
            inner = rest
        return inner.strip(), True
    for opening, closing in _QUOTE_PAIRS:
        if _wraps(value, opening, closing):
            return value[1:-1].strip(), True
    return value, False


def guard(original: str, candidate: str) -> str:
    """Return the deliverable form of *candidate*, or refuse it.

    One wrapping pair is forgiven — models quote an edited sentence back
    routinely — but a reply still wrapped after that was formatted rather than
    edited, and the length band catches the rest.
    """

    stripped, _ = _strip_one_wrapper(candidate)
    _, still_wrapped = _strip_one_wrapper(stripped)
    if still_wrapped:
        raise RefineRejectedError("output was wrapped")
    if not stripped.strip():
        raise RefineRejectedError("output was empty")
    reference = original.strip()
    if not reference:
        raise RefineRejectedError("input was empty")
    ratio = len(stripped) / len(reference)
    if not MIN_LENGTH_RATIO <= ratio <= MAX_LENGTH_RATIO:
        raise RefineRejectedError("output length was out of range")
    return stripped


def refined_text(payload: str | bytes, original: str, *, structured_output: bool) -> str:
    """Parse a reply and hand back text that passed the guard."""

    content = unwrap_structured(
        message_content(payload),
        structured_output=structured_output,
    )
    return guard(original, content)


def restore_trailing_space(original: str, refined: str) -> str:
    """Keep the formatter's dictation spacing across the refine stage.

    ``transcript_text`` appends the trailing space that stops consecutive
    pastes from running together; a model has no reason to preserve it.
    """

    if original.endswith(" ") and not refined.endswith(" "):
        return refined + " "
    return refined
