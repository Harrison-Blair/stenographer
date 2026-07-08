# SPDX-License-Identifier: GPL-3.0-or-later
"""Streaming (intra-utterance) transcription via LocalAgreement-N.

The daemon today transcribes each utterance in one batch pass. This module
prototypes an alternative: re-decode a rolling audio buffer every chunk, and
only *commit* the word-prefix that has agreed across the last ``N`` decodes.
The still-unstable tail is re-decoded (with the committed text supplied as
``initial_prompt`` for context) on the next chunk, so earlier provisional words
can be revised backwards as more audio arrives.

It is decoupled from audio I/O: the offline benchmark drives it with
:meth:`push`; a future live path can drive it from the recorder callback.

Reference: Macháček et al., "Turning Whisper into Real-Time Transcription
System" (whisper_streaming), the LocalAgreement-n policy.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np

from stenographer.asr.model import Model, WordInfo


def _norm(word: str) -> str:
    """Normalise a word token for agreement comparison (not for output)."""
    return word.strip().lower().strip(".,!?;:\"'“”‘’…-")  # noqa: RUF001


def longest_common_prefix(hyps: list[list[str]]) -> int:
    """Length of the longest common prefix across all token lists in *hyps*.

    Comparison is case/punctuation-insensitive via :func:`_norm`.
    """
    if not hyps or any(not h for h in hyps):
        return 0
    shortest = min(len(h) for h in hyps)
    n = 0
    while n < shortest:
        token = _norm(hyps[0][n])
        if token == "" or any(_norm(h[n]) != token for h in hyps):
            break
        n += 1
    return n


@dataclass
class StepResult:
    """Outcome of one :meth:`StreamingTranscriber.push`."""

    newly_committed: list[WordInfo] = field(default_factory=list)
    # Absolute audio end-time (s from utterance start) of each newly committed word.
    committed_audio_ends: list[float] = field(default_factory=list)
    provisional: str = ""
    # True when the provisional tail changed vs the previous step (a revision).
    revised: bool = False


class StreamingTranscriber:
    """LocalAgreement-N streaming transcriber with backward revision.

    Feed audio with :meth:`push` (any chunk size); call :meth:`finish` once the
    utterance ends to flush the remaining tail. ``committed_text`` holds the
    stabilised transcript at any point.
    """

    def __init__(
        self,
        model: Model,
        *,
        sample_rate: int,
        agree: int = 2,
        use_context: bool = True,
        beam_size: int | None = None,
    ) -> None:
        if agree < 1:
            raise ValueError("agree must be >= 1")
        self._model = model
        self._sample_rate = sample_rate
        self._agree = agree
        self._use_context = use_context
        self._beam_size = beam_size
        # Rolling window of not-yet-committed audio (mono float32).
        self._buffer = np.empty((0,), dtype=np.float32)
        # Audio-time (s) at the start of the buffer = total audio trimmed off.
        self._buffer_offset = 0.0
        # Total audio pushed so far (s) — "now" in the simulated stream.
        self._audio_pushed = 0.0
        self._committed: list[WordInfo] = []
        # Recent uncommitted-tail hypotheses (token lists), for agreement.
        self._history: deque[list[str]] = deque(maxlen=agree)
        self._prev_provisional = ""

    @property
    def committed_text(self) -> str:
        return "".join(w.word for w in self._committed).strip()

    @property
    def committed_words(self) -> list[WordInfo]:
        return list(self._committed)

    def push(self, samples: np.ndarray) -> StepResult:
        """Append audio, re-decode the buffer, and commit any stable prefix."""
        chunk = self._flatten(samples)
        self._audio_pushed += chunk.shape[0] / self._sample_rate
        self._buffer = np.concatenate([self._buffer, chunk])

        prompt = self.committed_text if self._use_context else None
        words = self._model.transcribe_words(
            self._buffer, beam_size=self._beam_size, initial_prompt=prompt or None
        )

        tokens = [w.word for w in words]
        self._history.append(tokens)

        commit_n = (
            longest_common_prefix(list(self._history)) if len(self._history) >= self._agree else 0
        )

        result = StepResult()
        if commit_n > 0:
            committed = words[:commit_n]
            cut_time = committed[-1].end  # buffer-local seconds
            for w in committed:
                self._committed.append(w)
                result.committed_audio_ends.append(self._buffer_offset + w.end)
            result.newly_committed = committed
            self._trim(cut_time)
            # Re-align stored hypotheses to the trimmed buffer.
            for h in self._history:
                del h[:commit_n]
            # Recompute the provisional tail from the leftover of this decode.
            words = words[commit_n:]

        provisional = "".join(w.word for w in words).strip()
        result.provisional = provisional
        result.revised = provisional != self._prev_provisional
        self._prev_provisional = provisional
        return result

    def finish(self) -> str:
        """Flush the remaining buffer: decode it once more and commit all words."""
        if self._buffer.shape[0] > 0:
            prompt = self.committed_text if self._use_context else None
            words = self._model.transcribe_words(
                self._buffer, beam_size=self._beam_size, initial_prompt=prompt or None
            )
            self._committed.extend(words)
            self._trim(self._buffer.shape[0] / self._sample_rate)
        self._history.clear()
        self._prev_provisional = ""
        return self.committed_text

    # -- internal ------------------------------------------------------------

    def _flatten(self, samples: np.ndarray) -> np.ndarray:
        arr = np.asarray(samples, dtype=np.float32)
        if arr.ndim == 2:
            arr = arr[:, 0]
        return arr

    def _trim(self, cut_time: float) -> None:
        """Drop the first *cut_time* seconds of the rolling buffer."""
        cut = round(cut_time * self._sample_rate)
        cut = max(0, min(cut, self._buffer.shape[0]))
        self._buffer = self._buffer[cut:]
        self._buffer_offset += cut / self._sample_rate
