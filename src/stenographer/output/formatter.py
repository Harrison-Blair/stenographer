# SPDX-License-Identifier: GPL-3.0-or-later
"""Heuristic text formatting: spacing, capitalisation, pause-based paragraphs.

Sits between the transcriber and the output sink. In the live streaming path
each committed word passes through :meth:`HeuristicFormatter.feed` exactly
once and the result is typed immediately, so every decision may depend only
on already-emitted left context plus the incoming token's start timestamp —
the formatter is append-only by construction. Batch paths (paste mode,
``transcribe FILE``) use :meth:`format_batch` over whole segments.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from stenographer.config import FormattingConfig

_NO_SPACE_BEFORE = ",.?!;:"
_SENTENCE_TERMINALS = ".?!"


class _Token(Protocol):
    """Anything with a text payload and absolute start/end times.

    Satisfied by both :class:`~stenographer.asr.model.WordInfo` (via its
    ``word`` field, see :func:`_token_text`) and
    :class:`~stenographer.asr.model.SegmentInfo`.
    """

    start: float
    end: float


def _token_text(item: object) -> str:
    text = getattr(item, "word", None)
    if text is None:
        text = item.text  # type: ignore[attr-defined]
    return text


class HeuristicFormatter:
    """Stateful, append-only formatter for committed transcript tokens."""

    def __init__(self, cfg: FormattingConfig, *, append_trailing_space: bool) -> None:
        self._cfg = cfg
        self._append_trailing_space = append_trailing_space
        self._started = False
        self._prev_end = 0.0
        self._capitalize_next = True

    def feed(self, tokens: Sequence[_Token]) -> str:
        """Format newly committed *tokens*; returns the exact string to emit."""
        return "".join(self._feed_token(_token_text(t), t.start, t.end) for t in tokens)

    def finalize(self) -> str:
        """End of utterance: the trailing space (if configured), then reset."""
        emit = " " if self._started and self._append_trailing_space else ""
        self.reset()
        return emit

    def reset(self) -> None:
        self._started = False
        self._prev_end = 0.0
        self._capitalize_next = True

    def format_batch(self, tokens: Sequence[_Token]) -> str:
        """One-shot formatting for batch paths (paste mode, transcribe FILE)."""
        self.reset()
        out = self.feed(tokens) + self.finalize()
        return out

    # -- internal ------------------------------------------------------------

    def _feed_token(self, text: str, start: float, end: float) -> str:
        if not self._cfg.normalize_spacing:
            self._started = True
            self._prev_end = end
            return text

        # Strip the token's own leading/trailing space and collapse any
        # internal runs; the separator below is the single source of spacing.
        core = " ".join(text.split())
        if not core:
            return ""

        pause = self._cfg.paragraph_pause_seconds
        paragraph = self._started and pause > 0 and (start - self._prev_end) >= pause

        if not self._started:
            sep = ""
        elif paragraph:
            sep = "\n\n"
        elif core[0] in _NO_SPACE_BEFORE:
            sep = ""
        else:
            sep = " "

        if self._cfg.capitalize_sentences:
            if core == "i":
                core = "I"
            if paragraph or self._capitalize_next:
                core = self._capitalize(core)
            self._capitalize_next = core[-1] in _SENTENCE_TERMINALS

        self._started = True
        self._prev_end = end
        return sep + core

    @staticmethod
    def _capitalize(token: str) -> str:
        for i, ch in enumerate(token):
            if ch.isalpha():
                return token[:i] + ch.upper() + token[i + 1 :]
        return token
