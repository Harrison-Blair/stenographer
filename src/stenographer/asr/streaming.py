# SPDX-License-Identifier: GPL-3.0-or-later
"""Word-level commit policy for live streaming via LocalAgreement-N.

The live path re-decodes a growing audio window while recording and types
each word the moment it is *committed*. ``wtype`` cannot un-type, so a word
is committed only once the last ``N`` consecutive re-decodes agree on it —
committed text is immutable and every intermediate typed state is a prefix
of the final transcript.

This class is a pure committer: the driver owns audio capture and decoding
and feeds each full hypothesis (word list for the current window) into
:meth:`insert`.

Reference: Macháček et al., "Turning Whisper into Real-Time Transcription
System" (whisper_streaming), the LocalAgreement-n policy.
"""

from __future__ import annotations

import dataclasses
from collections import deque

from stenographer.asr.model import WordInfo

# Tolerance (s) when matching re-decoded words against the committed prefix.
_EPSILON = 0.05


def _agreement_key(word: str) -> str:
    """Normalise a word token for agreement comparison (not for output).

    Case-insensitive but punctuation-SENSITIVE: ``"world."`` and ``"world"``
    do not agree, so typed punctuation never needs revision. Casing is owned
    by the formatter downstream, so ``"The"`` and ``"the"`` do agree.
    """
    return word.strip().lower()


def longest_common_prefix(hyps: list[list[str]]) -> int:
    """Length of the longest common prefix across all token lists in *hyps*.

    Comparison is case-insensitive (punctuation-sensitive) via
    :func:`_agreement_key`.
    """
    if not hyps or any(not h for h in hyps):
        return 0
    shortest = min(len(h) for h in hyps)
    n = 0
    while n < shortest:
        token = _agreement_key(hyps[0][n])
        if token == "" or any(_agreement_key(h[n]) != token for h in hyps):
            break
        n += 1
    return n


class StreamingTranscriber:
    """LocalAgreement-N committer over successive window re-decodes.

    Feed the full word list of each re-decode with :meth:`insert`; it returns
    only the words newly confirmed since the last call, with timestamps
    converted to absolute utterance time. Call :meth:`flush` at end of
    utterance to commit the residual tail, and :meth:`rebase` after the
    driver trims the audio window.

    The committed prefix is append-only: it is never revised, matching the
    irreversibility of typed output.
    """

    def __init__(self, *, agreement_n: int = 2) -> None:
        if agreement_n < 1:
            raise ValueError("agreement_n must be >= 1")
        self._agreement_n = agreement_n
        # Seconds of audio the driver has trimmed off the window start.
        self._offset = 0.0
        self._committed: list[WordInfo] = []
        # Recent uncommitted-tail hypotheses (agreement-key lists).
        self._history: deque[list[str]] = deque(maxlen=agreement_n)
        # The uncommitted tail of the most recent hypothesis (window-local).
        self._last_tail: list[WordInfo] = []

    @property
    def committed_text(self) -> str:
        return "".join(w.word for w in self._committed).strip()

    @property
    def committed_words(self) -> list[WordInfo]:
        return list(self._committed)

    def insert(self, hypothesis: list[WordInfo]) -> list[WordInfo]:
        """Feed the latest re-decode of the current window; return new commits.

        *hypothesis* carries window-local timestamps and still contains the
        committed words that remain in the untrimmed window; they are skipped
        by time (re-decodes may retokenise the committed region, so index
        alignment cannot be trusted).
        """
        tail = self._skip_committed(hypothesis)
        self._last_tail = tail
        self._history.append([_agreement_key(w.word) for w in tail])

        if len(self._history) < self._agreement_n:
            return []
        commit_n = longest_common_prefix(list(self._history))
        if commit_n == 0:
            return []
        newly = [self._to_absolute(w) for w in tail[:commit_n]]
        self._committed.extend(newly)
        self._last_tail = tail[commit_n:]
        for h in self._history:
            del h[:commit_n]
        return newly

    def flush(self) -> list[WordInfo]:
        """End of utterance: commit the residual tail of the last hypothesis."""
        newly = [self._to_absolute(w) for w in self._last_tail]
        self._committed.extend(newly)
        self._history.clear()
        self._last_tail = []
        return newly

    def rebase(self, dropped_seconds: float) -> None:
        """Record that the driver trimmed *dropped_seconds* off the window.

        Subsequent hypotheses are window-local to the new start; committed
        words are already stored in absolute time and are untouched.
        """
        self._offset += dropped_seconds

    def reset(self) -> None:
        self._offset = 0.0
        self._committed = []
        self._history.clear()
        self._last_tail = []

    # -- internal ------------------------------------------------------------

    def _skip_committed(self, hypothesis: list[WordInfo]) -> list[WordInfo]:
        """Drop the hypothesis prefix that re-decodes already-committed audio."""
        if not self._committed:
            return list(hypothesis)
        cutoff = self._committed[-1].end - self._offset
        for i, w in enumerate(hypothesis):
            if (w.start + w.end) / 2 >= cutoff - _EPSILON:
                return list(hypothesis[i:])
        return []

    def _to_absolute(self, w: WordInfo) -> WordInfo:
        return dataclasses.replace(w, start=w.start + self._offset, end=w.end + self._offset)
