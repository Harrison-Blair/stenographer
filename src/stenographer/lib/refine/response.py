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
import re
from collections import Counter

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

#: A numeral as dictation produces it: a digit run, optionally joined by the
#: separators a time, version, decimal or thousands group uses. ``4:15``,
#: ``0.12.3`` and ``1,204`` are each one numeral, so a reply that reformats
#: one is seen to have changed it rather than to have kept its digits.
_NUMERAL = re.compile(r"\d+(?:[.,:]\d+)*")

#: What a speaker says right after a number they are taking back. A numeral
#: may vanish from the reply only when one of these follows it in the input.
#: "not" and "wait" are deliberately absent: they fire on "3 items, not
#: counting the 4 spares" and "wait until 6", which are not corrections.
_CORRECTION_MARKERS = frozenset(
    {
        "no",
        "no wait",
        "actually",
        "sorry",
        "i mean",
        "scratch that",
        "make that",
        "rather",
        "correction",
    }
)

#: How many words after a numeral a correction marker may start. Measured:
#: real retractions needed up to six ("at 6 in the main hall no wait 7");
#: nothing in the corpus changed past six.
_MARKER_WINDOW = 6

_EDGE_PUNCTUATION = ".,;:!?\"'()[]"


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


def _numerals(text: str) -> Counter[str]:
    """Every numeral in *text*, with multiplicity and without position. PURE."""

    return Counter(_NUMERAL.findall(text))


def _words(text: str) -> list[str]:
    """Whitespace tokens, lowercased, without edge punctuation. PURE."""

    return [token.strip(_EDGE_PUNCTUATION).lower() for token in text.split()]


def _marker_follows(words: list[str], index: int) -> bool:
    """Whether a correction marker starts within the window after *index*. PURE."""

    for start in range(index + 1, min(index + 1 + _MARKER_WINDOW, len(words))):
        if words[start] in _CORRECTION_MARKERS:
            return True
        if " ".join(words[start : start + 2]) in _CORRECTION_MARKERS:
            return True
    return False


def _retracted_numerals(original: str) -> Counter[str]:
    """How many times each numeral in *original* is followed by a correction. PURE.

    This is permission, not prediction: a numeral counted here *may* be absent
    from the reply. The model still decides whether it goes.
    """

    words = _words(original)
    allowed: Counter[str] = Counter()
    for index, word in enumerate(words):
        found = _NUMERAL.search(word)
        if found and _marker_follows(words, index):
            allowed[found.group()] += 1
    return allowed


def guard(original: str, candidate: str) -> str:
    """Return the deliverable form of *candidate*, or refuse it.

    One wrapping pair is forgiven — models quote an edited sentence back
    routinely — but a reply still wrapped after that was formatted rather than
    edited, and the length band catches the rest.

    Numerals are held to a stricter standard than words. Prompting cannot
    promise they survive — the benchmark saw a model write ``8`` as ``eight``,
    another inject a colon into ``3080``, and a rule against both made every
    model tested *worse* — so the promise is made here instead. The reply may
    not add, repeat or reformat a numeral, and it may drop one only when the
    speaker took it back: a correction marker follows it in the input. A
    respelled digit has no marker after it, so it is caught as a drop. On
    every real model output measured, this refused nothing correct and
    delivered nothing wrong; strict equality had refused four good cleanups.
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
    source = _numerals(reference)
    produced = _numerals(stripped)
    if produced - source:
        raise RefineRejectedError("output changed a number")
    dropped = source - produced
    if dropped:
        allowed = _retracted_numerals(reference)
        if any(allowed[value] < count for value, count in dropped.items()):
            raise RefineRejectedError("output dropped a number")
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
