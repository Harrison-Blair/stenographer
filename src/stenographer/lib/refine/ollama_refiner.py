# SPDX-License-Identifier: GPL-3.0-or-later
"""The refine stage against a local Ollama server."""

from __future__ import annotations

import logging
import time

from stenographer.lib.logging.pipeline import fmt_event, log_failure
from stenographer.lib.refine.client import is_model_loaded, post_chat, warm_model
from stenographer.lib.refine.errors import RefineError, RefineRejectedError, RefineTimeoutError
from stenographer.lib.refine.policy import (
    COLD_LOAD_TIMEOUT_SECONDS,
    should_refine,
    timeout_seconds,
    word_count,
)
from stenographer.lib.refine.request import build_chat_body
from stenographer.lib.refine.response import refined_text, restore_trailing_space
from stenographer.lib.refine.results import (
    OUTCOME_APPLIED,
    OUTCOME_FAILED,
    OUTCOME_REJECTED,
    OUTCOME_SKIPPED,
    OUTCOME_TIMEOUT,
    RefineResult,
)

log = logging.getLogger("stenographer.lib.refine")


class OllamaRefiner:
    """Clean one finished transcript through a local model, or give up quietly.

    Fails open without exception: :meth:`refine` returns the text it was handed
    whenever the server is absent, slow, or unconvincing, and records why on
    :attr:`last_result`. A dictation must never be lost to a cleanup pass that
    is, by construction, optional.

    Privacy is a property of this class, not of its callers. The utterance
    reaches exactly one place — the chat body posted to the configured host —
    and every log line and exception below names an outcome, never content.
    """

    def __init__(
        self,
        *,
        host: str,
        model: str,
        min_words: int,
        structured_output: bool,
        keep_alive: int,
    ) -> None:
        self._host = host
        self._model = model
        self._min_words = min_words
        self._structured_output = structured_output
        self._keep_alive = keep_alive
        self._last_result: RefineResult | None = None

    @property
    def host(self) -> str:
        return self._host

    @property
    def model(self) -> str:
        return self._model

    @property
    def keep_alive(self) -> int:
        return self._keep_alive

    @property
    def last_result(self) -> RefineResult | None:
        return self._last_result

    def will_refine(self, text: str) -> bool:
        """Whether *text* clears the word threshold. PURE.

        A prediction, for a caller that needs to know before it acts — the
        pipeline shows the "Refining" pill only for an utterance that is really
        going to a model. :meth:`refine` asks the same question again rather
        than trusting the answer, so the threshold is enforced in one place
        whether or not anybody looked first.
        """

        return should_refine(text, self._min_words)

    def warm(self) -> bool:
        """Resident the model ahead of the first utterance. Never raises."""

        try:
            warm_model(self._host, self._model, keep_alive=self._keep_alive)
        except Exception as exc:
            log_failure(log, logging.WARNING, "refine: warm_failed", exc, safe=True)
            return False
        log.info(fmt_event("refine", "warm", model=self._model, keep_alive=self._keep_alive))
        return True

    def unload(self) -> None:
        """Release the model. Never raises; a stuck model is not a dictation bug."""

        from stenographer.lib.refine.client import unload_model

        try:
            unload_model(self._host, self._model)
        except Exception as exc:
            log_failure(log, logging.DEBUG, "refine: unload_failed", exc, safe=True)

    def refine(self, text: str) -> str:
        """Return the cleaned text, or *text* unchanged on any failure at all."""

        words = word_count(text)
        if not should_refine(text, self._min_words):
            self._last_result = RefineResult(OUTCOME_SKIPPED, chars_in=len(text))
            return text
        started_at = time.perf_counter()
        body = build_chat_body(
            text,
            model=self._model,
            words=words,
            keep_alive=self._keep_alive,
            structured_output=self._structured_output,
        )
        try:
            self._ensure_loaded()
            payload = post_chat(self._host, body, timeout=timeout_seconds(words))
            candidate = refined_text(payload, text, structured_output=self._structured_output)
        except Exception as exc:
            outcome = self._outcome_for(exc)
            self._last_result = RefineResult(
                outcome,
                chars_in=len(text),
                duration_ms=(time.perf_counter() - started_at) * 1000,
            )
            # A ``RefineError`` is built from one of this package's fixed
            # reason strings and can be rendered. Anything else escaped the
            # parser and may quote the model's reply, which is derived from
            # the transcript: class and frames only.
            log_failure(
                log,
                logging.WARNING,
                "refine: not_applied",
                exc,
                safe=isinstance(exc, RefineError),
                outcome=outcome,
            )
            return text
        result = restore_trailing_space(text, candidate)
        self._last_result = RefineResult(
            OUTCOME_APPLIED,
            chars_in=len(text),
            chars_out=len(result),
            duration_ms=(time.perf_counter() - started_at) * 1000,
        )
        return result

    def _ensure_loaded(self) -> None:
        """Wait for a cold model to load before the reply budget starts.

        The per-utterance budget in :func:`timeout_seconds` prices a reply
        from a resident model. When the model has been evicted — the ASR idle
        window passed, or Ollama made room for something else — the same chat
        request would first page it back in, spend the whole budget doing so,
        and the utterance would be pasted unrefined every time. So a model
        that ``/api/ps`` does not list is loaded here on its own, much longer
        budget, and only then is the ordinary one started. A resident model
        costs one loopback probe and nothing more.

        Raises whatever the load raised; the caller classifies it exactly as
        it would a failed reply.
        """

        if is_model_loaded(self._host, self._model):
            return
        started_at = time.perf_counter()
        warm_model(
            self._host, self._model, keep_alive=self._keep_alive, timeout=COLD_LOAD_TIMEOUT_SECONDS
        )
        log.info(
            fmt_event(
                "refine",
                "cold_load",
                model=self._model,
                load_ms=round((time.perf_counter() - started_at) * 1000),
            )
        )

    @staticmethod
    def _outcome_for(exc: Exception) -> str:
        """Classify a failed attempt without inspecting any message text. PURE."""

        if isinstance(exc, RefineTimeoutError):
            return OUTCOME_TIMEOUT
        if isinstance(exc, RefineRejectedError):
            return OUTCOME_REJECTED
        return OUTCOME_FAILED
