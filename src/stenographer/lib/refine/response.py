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
from itertools import pairwise

from stenographer.lib.refine.errors import RefineRejectedError, RefineResponseError
from stenographer.lib.refine.profiles import RefineProfile
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

_PROTECTED_TOKEN = re.compile(
    r"(?<!\w)(?:--?[A-Za-z0-9][\w.-]*|(?:\.{0,2}/|~?/)[^\s,;!?]+|"
    r"[A-Za-z]:\\[^\s,;!?]+|[A-Za-z][\w-]*(?:[._:/][\w.-]+)+|"
    r"[A-Za-z]+[A-Z][A-Za-z0-9]*)"
)
_QUOTED = re.compile(r'(["\u201c]).*?(["\u201d])|(?<!\w)\'[^\'\n]+\'(?!\w)')
_LEXICAL_TOKEN = re.compile(r"[A-Za-z0-9]+(?:['\u2019][A-Za-z0-9]+)?")
_SAFE_FILLERS = frozenset({"um", "uh", "er", "ah"})
_AGENT_CORRECTION_MARKERS = _CORRECTION_MARKERS - {"no", "rather"}

#: A protected token counts as taken back only when a correction marker
#: follows it within this many words *and* another protected token follows the
#: marker within the reach: "use qwen3:8b no wait gemma4:e2b" replaces a
#: choice, while "the bug is in OllamaRefiner actually" replaces nothing.
_REPLACEMENT_REACH = 8
#: Words after a correction marker searched for the replacement choice.
_CORRECTION_REACH = 6
#: Longest head phrase a correction may repeat ("the old retry logic sorry the
#: new retry logic" repeats two).
_HEAD_WORDS = 3
_AGENT_MARKER_WORDS = tuple(tuple(marker.split()) for marker in _AGENT_CORRECTION_MARKERS)
_AGENT_MARKERS = "|".join(
    r"\s+".join(marker.split()) for marker in sorted(_AGENT_CORRECTION_MARKERS)
)
_AGENT_MARKER_AFTER = re.compile(
    rf"(?:\W+\w+){{0,{_MARKER_WINDOW - 1}}}?\W+(?:{_AGENT_MARKERS})\b", re.IGNORECASE
)

#: A capitalized word inside a sentence: the name of a tool, model, or product
#: ("use Codex", "ask Claude"). Lowercase names are not reliably detected by this heuristic.
_NAME = re.compile(r"(?<![.!?:\n] )(?<!- )(?<![.!?:\n\"])(?<!^)\b[A-Z][a-z]+\b")

#: Spoken contractions of "not", expanded before any word is compared so that
#: "don't" and "do not" are the same edit.
_CONTRACTIONS = (
    (re.compile(r"\bcan't\b"), "can not"),
    (re.compile(r"\bwon't\b"), "will not"),
    (re.compile(r"\bshan't\b"), "shall not"),
    (re.compile(r"\bcannot\b"), "can not"),
    (re.compile(r"n't\b"), " not"),
)

#: Boundary negations compare by presence, without asserting their scope.
_NEGATIONS = frozenset(
    {"not", "no", "never", "nothing", "none", "nor", "neither", "without", "nobody", "nowhere"}
)
#: An action verb this many words after a negation is forbidden, not asked for.
_NEGATION_SCOPE = 3
_SENTENCE_BREAK = re.compile(r"[.?!;:]+(?=\s|$)|\n")
#: A "no" that only answers or hedges ("No, that's fine", "yeah no so ...")
#: negates nothing; "No retries." still does.
_DISCOURSE_NO = re.compile(
    r"(^|[.!?\n]\s*|\byeah,?\s+)no\b(?=\s*,|\s+(?:that's|it's|so|yeah|okay|ok|i)[\s,])"
)
#: "no" that opens a correction ("10 no wait 12") negates nothing.
_CORRECTING_NO = re.compile(
    r"\bno\s+(?=(?:wait|actually|sorry|i\s+mean|scratch\s+that|make\s+that|rather|correction)\b)"
)

#: Phase, scope, and authorization words; every one the speaker said must
#: survive. "just" is kept unconditionally: the guard cannot tell "just
#: investigate" (a scope limit) from filler, and losing a limit is the worse
#: mistake.
_INVESTIGATIVE_WORDS = tuple(
    re.compile(rf"\b{stem}\b")
    for stem in (
        r"investigat\w*",
        r"plan(?:s|ned|ning)?",
        r"review\w*",
        r"explain\w*",
        r"validat\w*",
    )
)
_PHASE_WORDS = _INVESTIGATIVE_WORDS + tuple(
    re.compile(rf"\b{stem}\b") for stem in (r"wait\w*", "yet", "only", "just", "for now")
)
#: Words that make a request conditional; none may be lost ("if it's green
#: you can merge" must not become "merge").
_CONDITIONS = frozenset(("if", "unless", "until", "once", "otherwise"))
_HEDGES = tuple(
    re.compile(rf"\b{hedge}\b") for hedge in ("maybe", "might", "probably", "possibly", "perhaps")
)
#: "I think" and "I guess" hedge a claim unless another hedge word right after
#: them already does ("I think probably keep it"), or they open the filler
#: "I think the thing is".
_SPEAKER_HEDGE = re.compile(r"\bi (?:think|guess)\b(?! the thing is\b)")
_SPEAKER_HEDGE_REACH = 3

#: Verbs that authorize work. The reply may not introduce one the speaker never
#: said. A form right after a determiner is a noun ("pushed a fix") and does
#: not count.
_ACTION_VERBS = {
    verb: re.compile(forms)
    for verb, forms in (
        ("implement", r"implement\w*"),
        ("fix", r"fix(?:es|ed|ing)?|repair(?:s|ed|ing)?"),
        ("change", r"chang(?:e|es|ed|ing)|modif(?:y|ies|ied|ying)|alter(?:s|ed|ing)?"),
        ("apply", r"appl(?:y|ies|ied|ying)"),
        ("commit", r"commit(?:s|ted|ting)?"),
        ("merge", r"merg(?:e|es|ed|ing)"),
        ("delete", r"delet(?:e|es|ed|ing)"),
        ("write", r"writ(?:e|es|ing|ten)|wrote"),
        ("build", r"buil(?:d|ds|ding|t)"),
        ("push", r"push(?:es|ed|ing)?"),
        ("add", r"add(?:s|ed|ing)?"),
        ("update", r"updat(?:e|es|ed|ing)"),
        ("remove", r"remov(?:e|es|ed|ing)|eras(?:e|es|ed|ing)"),
        ("rename", r"renam(?:e|es|ed|ing)"),
        ("refactor", r"refactor(?:s|ed|ing)?"),
        ("touch", r"touch(?:es|ed|ing)?"),
        ("install", r"install(?:s|ed|ing)?"),
        ("run", r"r(?:un|uns|an|unning)"),
        ("edit", r"edit(?:s|ed|ing)?"),
        ("create", r"creat(?:e|es|ed|ing)"),
        ("bump", r"bump(?:s|ed|ing)?"),
        ("replace", r"replac(?:e|es|ed|ing)"),
        ("deploy", r"deploy(?:s|ed|ing)?"),
    )
}
_DETERMINERS = frozenset(
    {
        "a",
        "an",
        "the",
        "this",
        "that",
        "these",
        "those",
        "my",
        "your",
        "our",
        "their",
        "its",
        "his",
        "her",
        "any",
        "some",
        "each",
        "every",
        "another",
    }
)

#: A question stays a question: a sentence ending in "?" or opened by one of
#: these, after any spoken warm-up. A polite request ("can you look at ...")
#: is not one; the reply may make it an imperative.
_INTERROGATIVES = frozenset(
    {
        "can",
        "could",
        "would",
        "why",
        "how",
        "what",
        "when",
        "where",
        "which",
        "who",
        "is",
        "are",
        "does",
        "did",
        "should",
    }
)
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]*")
_WARM_UP = re.compile(
    r"[\s\"'(\-]*(?:(?:um|uh|er|ah|okay|ok|so|alright|well|like|and|but|then)[\s,]+)*",
    re.IGNORECASE,
)
#: "you" only: "can we merge it?" asks permission. An opinion verb ("would you
#: say ...") still asks a question.
_POLITE_REQUEST = re.compile(
    r"(?:can|could|would|will)\s+you\s+(?!(?:please\s+)?(?:say|think|know|agree|mind|reckon|feel)\b)",
    re.IGNORECASE,
)

_STOPWORDS = frozenset(
    word
    for group in (
        "a an the and or but if then so as of to in on at by for with from into onto about",
        "over under up down out off than too very just only yet also again still even ever",
        "is are was were be been being am do does did doing done have has had having",
        "will would shall should can could may might must",
        "i me my we us our you your he him his she her it its they them their",
        "this that these those there here what which who whom whose when where why how",
        "all any anything some something each every both either more most other such own",
        "same few much many",
        "it's i'm i've i'd i'll we're we've we'd we'll you're you've you'd you'll they're",
        "there's that's what's let's he's she's",
        "okay ok yeah yep alright well like know mean kind sort thing things really",
        "basically literally actually quite pretty please right now",
        "one ones first second third fourth fifth next last",
    )
    for word in group.split()
)


def _value(pattern: re.Pattern[str], match: re.Match[str]) -> str:
    value = match.group(0)
    if pattern is _PROTECTED_TOKEN:
        value = value.rstrip(".,;!?\"')]}>")
    if pattern is _QUOTED:
        # A comma or period moved just inside the closing quote is house style.
        value = re.sub(r"[,.](?=[\"\u201d']$)", "", value)
    return value


def _agent_words(text: str) -> list[str]:
    """Lowercased words with "n't" spelled out, fillers and a discourse "no" gone,
    stammers collapsed."""

    folded = text.casefold().replace("\u2019", "'")
    for pattern, replacement in _CONTRACTIONS:
        folded = pattern.sub(replacement, folded)
    folded = _DISCOURSE_NO.sub(r"\1", folded)
    words = [word for word in _LEXICAL_TOKEN.findall(folded) if word not in _SAFE_FILLERS]
    for size in range(4, 0, -1):
        index = 0
        while index + 2 * size <= len(words):
            if words[index : index + size] == words[index + size : index + 2 * size]:
                del words[index + size : index + 2 * size]
            else:
                index += 1
    return words


def _anchored_values(pattern: re.Pattern[str], text: str) -> tuple[set[str], set[str]]:
    """Values the reply must keep, and values the speaker replaced with another."""

    kept: set[str] = set()
    replaced: set[str] = set()
    for match in pattern.finditer(text):
        value = _value(pattern, match)
        marker = _AGENT_MARKER_AFTER.match(text, match.end())
        replacement = marker and pattern.search(
            " ".join(text[marker.end() :].split()[:_REPLACEMENT_REACH])
        )
        (replaced if replacement else kept).add(value)
    return kept, replaced - kept


def _changes_anchored_values(pattern: re.Pattern[str], original: str, candidate: str) -> bool:
    """Whether the reply lost a kept value, or wrote one that is new or replaced.

    Values compare as sets, so a repeated value may be written once. A replaced
    value may still appear when the reply keeps the correction that replaced
    it, marker and all.
    """

    kept, replaced = _anchored_values(pattern, original)
    produced_kept, produced_replaced = _anchored_values(pattern, candidate)
    return produced_kept != kept or not produced_replaced <= replaced


def _speaker_hedged(text: str) -> bool:
    for match in _SPEAKER_HEDGE.finditer(text):
        reach = " ".join(text[match.end() :].split()[:_SPEAKER_HEDGE_REACH])
        if not any(hedge.search(reach) for hedge in _HEDGES):
            return True
    return False


def _authorized_actions(text: str) -> set[str]:
    """Recognized action verbs, excluding nouns and nearby negated verbs.

    Finite glossary aliases compare symmetrically. This heuristic does not
    establish who acts, which object changes, or which condition governs it.
    """

    asked: set[str] = set()
    for sentence in _SENTENCE_BREAK.split(text):
        words = _agent_words(sentence)
        for index, word in enumerate(words):
            if index and words[index - 1] in _DETERMINERS:
                continue
            if _NEGATIONS.intersection(words[max(0, index - _NEGATION_SCOPE) : index]):
                continue
            asked |= {verb for verb, forms in _ACTION_VERBS.items() if forms.fullmatch(word)}
    return asked


def _asks(text: str, *, requests: bool) -> bool:
    """Whether *text* asks a question; polite requests count only if *requests*."""

    for sentence in _SENTENCE.findall(text):
        body = sentence[_WARM_UP.match(sentence).end() :]
        opener = re.match(r"[A-Za-z]+", body)
        asked = sentence.rstrip().endswith("?") or bool(
            opener and opener.group().casefold() in _INTERROGATIVES
        )
        if asked and (requests or not _POLITE_REQUEST.match(body)):
            return True
    return False


def _stem(word: str) -> str:
    """A rough lemma: "settings", "setting" -> "set"; "failing", "fails" -> "fail".

    A stem that would collide with a function word or negation is not used
    ("noted" must not match "not").
    """

    stem = word
    if stem.endswith("s") and not stem.endswith("ss") and len(stem) > 3:
        stem = stem[:-1]
    for suffix in ("ing", "ed", "e"):
        if stem.endswith(suffix) and len(stem) - len(suffix) >= 3:
            stem = stem[: -len(suffix)]
            break
    if len(stem) > 3 and stem[-1] == stem[-2]:
        stem = stem[:-1]
    return word if stem in _STOPWORDS or stem in _NEGATIONS else stem


def _is_content(word: str) -> bool:
    return (
        word not in _STOPWORDS
        and word not in _NEGATIONS
        and not any(character.isdigit() for character in word)
    )


def _revives_a_correction(source: list[str], produced: list[str]) -> bool:
    """Whether the reply kept a word the speaker replaced ("use grep no wait use ripgrep").

    A word counts as replaced when it is said once, right before a correction
    marker, and the correction repeats the word before it with a new word
    ("use grep" ... "use ripgrep"); or when it is said once before up to
    :data:`_HEAD_WORDS` head words that the correction repeats after a new
    word ("the old retry logic" ... "the new retry logic"). A reply that keeps
    a marker shows the correction instead of reversing it.
    """

    def marker_at(words: list[str], index: int) -> tuple[str, ...] | None:
        return next(
            (
                marker
                for marker in _AGENT_MARKER_WORDS
                if tuple(words[index : index + len(marker)]) == marker
            ),
            None,
        )

    if any(marker_at(produced, index) for index in range(len(produced))):
        return False
    written = {_stem(word) for word in produced}
    for index in range(2, len(source)):
        marker = marker_at(source, index)
        if marker is None:
            continue
        after = source[index + len(marker) : index + len(marker) + _CORRECTION_REACH]
        before, last = source[index - 2], source[index - 1]
        # "use grep no wait use ripgrep": the word before the choice repeats.
        if any(
            previous == before and word != last and _is_content(word)
            for previous, word in pairwise(after)
        ) and _replaced(source, last, written):
            return True
        # "the old retry logic sorry the new retry logic": the head words
        # repeat after a new modifier; the modifier before them was replaced.
        for size in range(1, min(_HEAD_WORDS, index - 1) + 1):
            head = source[index - size : index]
            replaced = source[index - size - 1]
            if not all(map(_is_content, head)):
                break
            if any(
                after[start : start + size] == head
                and _is_content(after[start - 1])
                and after[start - 1] != replaced
                for start in range(1, len(after) - size + 1)
            ) and _replaced(source, replaced, written):
                return True
    return False


def _replaced(source: list[str], word: str, written: set[str]) -> bool:
    """Whether a once-said content word the speaker corrected made it into the reply."""

    return _is_content(word) and source.count(word) == 1 and _stem(word) in written


def _changes_names(original: str, candidate: str) -> bool:
    kept, replaced = _anchored_values(_NAME, original)
    produced_kept = _anchored_values(_NAME, candidate)[0]
    written = {word.casefold() for word in _LEXICAL_TOKEN.findall(candidate)}
    said = {word.casefold() for word in _LEXICAL_TOKEN.findall(original)}
    produced_names = {name.casefold() for name in produced_kept}
    return (
        not {name.casefold() for name in kept} <= written
        or bool(produced_names & {name.casefold() for name in replaced})
        or not produced_names <= said
    )


def agent_guard(original: str, candidate: str) -> str:
    """Check mechanical boundaries while permitting substantial Agent rewrites.

    Distinct literal values and boundary words survive; repeated occurrences
    can consolidate. Meaning, associations, and arbitrary detail retention
    remain prompt obligations that these checks cannot prove.
    """

    accepted = _deliverable(original, candidate, minimum_ratio=0)
    source_counts = _numerals(original)
    source_numbers = set(source_counts)
    written_numbers = set(_numerals(accepted))
    if written_numbers - source_numbers:
        raise RefineRejectedError("output changed a number")
    retracted = _retracted_numerals(original)
    if any(retracted[value] < source_counts[value] for value in source_numbers - written_numbers):
        raise RefineRejectedError("output dropped a number")
    for pattern, reason in (
        (_PROTECTED_TOKEN, "output changed a protected token"),
        (_QUOTED, "output changed quoted text"),
    ):
        if _changes_anchored_values(pattern, original, accepted):
            raise RefineRejectedError(reason)
    if _changes_names(original, accepted):
        raise RefineRejectedError("output changed a name")
    source = _agent_words(original)
    produced = _agent_words(accepted)
    source_text = re.sub(r"\bno wait\b", "", " ".join(source))
    produced_text = re.sub(r"\bno wait\b", "", " ".join(produced))
    source_negations = set(_CORRECTING_NO.sub("", source_text).split()) & _NEGATIONS
    written_negations = set(_CORRECTING_NO.sub("", produced_text).split()) & _NEGATIONS
    if source_negations != written_negations:
        raise RefineRejectedError("output changed a negation")
    if any(
        set(word.findall(source_text)) - set(word.findall(produced_text)) for word in _PHASE_WORDS
    ):
        raise RefineRejectedError("output dropped a phase or scope word")
    if (set(source) & _CONDITIONS) - set(produced):
        raise RefineRejectedError("output dropped a condition")
    if any(hedge.search(source_text) and not hedge.search(produced_text) for hedge in _HEDGES):
        raise RefineRejectedError("output dropped a hedge")
    if _speaker_hedged(source_text) and not _SPEAKER_HEDGE.search(produced_text):
        raise RefineRejectedError("output dropped a hedge")
    if _authorized_actions(accepted) - _authorized_actions(original):
        raise RefineRejectedError("output added an action")
    if _asks(original, requests=False) and not _asks(accepted, requests=True):
        raise RefineRejectedError("output answered a question")
    if _revives_a_correction(source, produced):
        raise RefineRejectedError("output kept a corrected word")
    return accepted


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


def _deliverable(original: str, candidate: str, *, minimum_ratio: float) -> str:
    """Shared wrapper, empty-input, and length checks. PURE."""

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
    if not minimum_ratio <= ratio <= MAX_LENGTH_RATIO:
        raise RefineRejectedError("output length was out of range")
    return stripped


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

    stripped = _deliverable(original, candidate, minimum_ratio=MIN_LENGTH_RATIO)
    reference = original.strip()
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


def refined_text(
    payload: str | bytes,
    original: str,
    *,
    structured_output: bool,
    profile: RefineProfile = RefineProfile.GENERAL,
) -> str:
    """Parse a reply and hand back text that passed the guard."""

    content = unwrap_structured(
        message_content(payload),
        structured_output=structured_output,
    )
    if profile is RefineProfile.AGENT:
        return agent_guard(original, content)
    return guard(original, content)


def restore_trailing_space(original: str, refined: str) -> str:
    """Keep the formatter's dictation spacing across the refine stage.

    ``transcript_text`` appends the trailing space that stops consecutive
    pastes from running together; a model has no reason to preserve it.
    """

    if original.endswith(" ") and not refined.endswith(" "):
        return refined + " "
    return refined
