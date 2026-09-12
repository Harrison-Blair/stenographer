# SPDX-License-Identifier: GPL-3.0-or-later
"""The refine stage against a local Ollama server."""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from stenographer.lib.logging.pipeline import fmt_event, log_failure
from stenographer.lib.refine.cancellation import never_cancelled
from stenographer.lib.refine.client import is_model_loaded, post_chat, warm_model
from stenographer.lib.refine.errors import (
    RefineCancelledError,
    RefineError,
    RefineRejectedError,
    RefineTimeoutError,
)
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
    OUTCOME_CANCELLED,
    OUTCOME_FAILED,
    OUTCOME_REJECTED,
    OUTCOME_SKIPPED,
    OUTCOME_TIMEOUT,
    RefineResult,
)

if TYPE_CHECKING:
    from collections.abc import Callable

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

    Interruptible in both directions. :meth:`unload` is the shutdown gate: it
    stops any further request from being issued and guarantees the model ends
    up released even if a request already in flight re-pins it afterwards.
    :meth:`refine` takes a ``cancelled`` predicate it honours between requests,
    so an utterance the user withdrew stops costing the pipeline the rest of
    its budget. Neither can abort a request already open — ``urllib`` has no
    such affordance without a thread of its own — so the granularity of both
    is one request, and the bookkeeping is built around that rather than
    pretending otherwise.
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
        # Guards the two fields below only; never held across a request.
        self._lock = threading.Lock()
        self._shutdown = False
        self._in_flight = 0

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
        """Resident the model ahead of the first utterance. Never raises.

        Declines outright once :meth:`unload` has run: a warm-up that started
        after the shutdown gate closed would page the model straight back in.
        """

        if not self._claim():
            return False
        try:
            warm_model(self._host, self._model, keep_alive=self._keep_alive)
        except Exception as exc:
            log_failure(log, logging.WARNING, "refine: warm_failed", exc, safe=True)
            return False
        finally:
            self._release()
        log.info(fmt_event("refine", "warm", model=self._model, keep_alive=self._keep_alive))
        return True

    def unload(self) -> None:
        """Release the model, and keep it released. Never raises.

        Also the stage's shutdown gate, which is what makes it safe to call
        while the daemon is still winding down. Two things can re-establish
        ``keep_alive`` after an unload — the background warm-up and an
        utterance's own chat request — and a bounded join on either does not
        help: a join whose timeout expires stops *waiting*, it does not stop
        the thread, so the request lands afterwards and the model stays
        resident. Closing that needs a gate the request itself respects:

        * nothing new is issued once this has run (:meth:`_claim` refuses, and
          :meth:`refine` treats the flag as a cancellation at its next check),
          so the leak cannot be re-opened by a later utterance; and
        * whichever request was already in flight re-issues the unload as it
          returns (:meth:`_release`), so the last word about residency always
          belongs to the unload, for any wait budget the caller had — a
          bounded one, an expired one, or none at all.

        The alternative shape — wait here for the in-flight request, then
        unload once — buys ordering only while the wait lasts, and has to pick
        a budget; with both the warm-up and a chat out at once it has to
        outlast the slower of the two or reopen the same race. This one needs
        no budget, and with several requests out only the last to return
        unloads, so the extra traffic is one request however many were in
        flight.

        A stuck model is not a dictation bug: every failure here is swallowed.
        """

        with self._lock:
            self._shutdown = True
        self._unload_now()

    def refine(self, text: str, *, cancelled: Callable[[], bool] = never_cancelled) -> str:
        """Return the cleaned text, or *text* unchanged on any failure at all.

        *cancelled* is asked between requests — before the load, after it, and
        once more before the reply is parsed. It cannot interrupt a request
        that is already open, so the promise is bounded by one request, not by
        the caller's patience: a cancel during a cold load waits out that load,
        a cancel during the reply waits out the reply, and in both cases the
        stage then stops rather than going on to the next request. The default
        never cancels, so a caller that has nothing to say is unaffected.
        """

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
        if not self._claim():
            self._last_result = RefineResult(OUTCOME_CANCELLED, chars_in=len(text))
            return text
        try:
            self._check_stopped(cancelled)
            self._ensure_loaded(cancelled)
            self._check_stopped(cancelled)
            payload = post_chat(self._host, body, timeout=timeout_seconds(words))
            self._check_stopped(cancelled)
            candidate = refined_text(payload, text, structured_output=self._structured_output)
        except Exception as exc:
            outcome = self._outcome_for(exc)
            self._last_result = RefineResult(
                outcome,
                chars_in=len(text),
                # A cancelled attempt is timed by how long the user took to
                # give up, not by the model, and it is charged as no attempt
                # at all. Reporting a duration anyway would put a two-minute
                # abandoned cold load into any aggregate over ``refine_ms``
                # that did not also filter on ``attempted``. Left unset, as
                # ``skipped`` already is.
                duration_ms=(
                    None
                    if outcome == OUTCOME_CANCELLED
                    else (time.perf_counter() - started_at) * 1000
                ),
            )
            # A ``RefineError`` is built from one of this package's fixed
            # reason strings and can be rendered. Anything else escaped the
            # parser and may quote the model's reply, which is derived from
            # the transcript: class and frames only.
            log_failure(
                log,
                # A withdrawn utterance is a thing the user did, not a fault
                # to warn about; it is still logged so a stage that stopped
                # can be told from one that never ran.
                logging.DEBUG if outcome == OUTCOME_CANCELLED else logging.WARNING,
                "refine: not_applied",
                exc,
                safe=isinstance(exc, RefineError),
                outcome=outcome,
            )
            return text
        finally:
            self._release()
        result = restore_trailing_space(text, candidate)
        self._last_result = RefineResult(
            OUTCOME_APPLIED,
            chars_in=len(text),
            chars_out=len(result),
            duration_ms=(time.perf_counter() - started_at) * 1000,
        )
        return result

    def _claim(self) -> bool:
        """Take a slot for one outbound request, unless shutdown already ran.

        False means "do not send anything": the gate is closed and the model
        has been released, so issuing this request would only pin it again.
        """

        with self._lock:
            if self._shutdown:
                return False
            self._in_flight += 1
            return True

    def _release(self) -> None:
        """Give the slot back, releasing the model if shutdown overtook it.

        Only the last request out unloads. While anything else is still open
        it may re-establish ``keep_alive`` after this one, so an unload here
        would be the one that gets overtaken — exactly the defect this guards.
        """

        with self._lock:
            self._in_flight -= 1
            overtaken = self._shutdown and self._in_flight == 0
        if overtaken:
            self._unload_now()

    def _unload_now(self) -> None:
        """Ask Ollama to release the model, swallowing whatever comes back."""

        from stenographer.lib.refine.client import unload_model

        try:
            unload_model(self._host, self._model)
        except Exception as exc:
            log_failure(log, logging.DEBUG, "refine: unload_failed", exc, safe=True)

    def _check_stopped(self, cancelled: Callable[[], bool]) -> None:
        """Abandon the attempt if nobody is waiting for the reply any more.

        Shutdown counts as a cancellation: the daemon is going away, and every
        request still to be issued would re-pin a model that has just been
        released. The caller's predicate is asked second and may raise — it is
        third-party-shaped code like the rest of the collaborator — which the
        one fail-open handler in :meth:`refine` treats as any other failure.

        The read of ``_shutdown`` is deliberately unlocked, and must stay that
        way: it is an early exit, not the gate. All the gate's correctness
        lives in :meth:`_claim` and :meth:`_release`, which do take the lock.
        Reading it under the lock here would buy nothing, and holding a lock
        across the request that follows would deadlock shutdown outright.
        """

        if self._shutdown:
            raise RefineCancelledError("the refine stage is shutting down")
        if cancelled():
            raise RefineCancelledError("the utterance was cancelled")

    def _ensure_loaded(self, cancelled: Callable[[], bool] = never_cancelled) -> None:
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
        it would a failed reply. The probe answers in seconds and the load can
        take minutes, so a cancellation that arrived during the probe is worth
        catching before committing to the load.
        """

        if is_model_loaded(self._host, self._model):
            return
        self._check_stopped(cancelled)
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

        if isinstance(exc, RefineCancelledError):
            return OUTCOME_CANCELLED
        if isinstance(exc, RefineTimeoutError):
            return OUTCOME_TIMEOUT
        if isinstance(exc, RefineRejectedError):
            return OUTCOME_REJECTED
        return OUTCOME_FAILED
