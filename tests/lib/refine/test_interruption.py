# SPDX-License-Identifier: GPL-3.0-or-later
"""Stopping a refine that has already started.

Two callers need it. Shutdown must leave the model out of video memory however
long the last request takes — an unload that a request already in flight
overtakes re-establishes ``keep_alive`` and pins gigabytes until Ollama's own
timer expires, which on ``idle_unload_seconds = 0`` is never. And a user who
cancels the utterance must get the hotkey back, rather than waiting out a
budget of up to two minutes for a reply nobody will read.

Only the transport is replaced — the same seam ``test_refiner`` uses. Nothing
here opens a socket and nothing sleeps for a fixed duration.
"""

from __future__ import annotations

import json
import threading

import pytest

from stenographer.lib.refine import client, ollama_refiner
from stenographer.lib.refine.ollama_refiner import OllamaRefiner
from stenographer.lib.refine.prompt import RESPONSE_KEY
from stenographer.lib.refine.results import OUTCOME_APPLIED, OUTCOME_CANCELLED

SPOKEN = "um i think we should ship it on thursday no wait friday okay "
CLEANED = "I think we should ship it on Friday. "

#: Long enough that a wait which really elapses is unmistakable in the output,
#: short enough that such a test still finishes.
_DEADLINE = 10.0


class _HarnessFailure(BaseException):
    """A handshake in the stub below broke, which is never a verdict.

    Deliberately not an ``Exception``: every stub method runs inside the
    refiner's blanket fail-open handler, so an ``assert`` here would be caught,
    classified as a failed attempt, and quietly degrade a broken harness into a
    passing test. A ``BaseException`` goes straight past that handler and out
    through pytest's unraisable-thread hook instead.
    """


class _Transport:
    """Every call that can pin or release the model, in the order it landed.

    The journal is the whole point: a chat or a warm that returns *after* an
    unload has re-established ``keep_alive`` on the server, so a run whose last
    residency event is not an unload has leaked the model. The read-only
    ``/api/ps`` probe is journalled too — it pins nothing, but a stage that was
    told to stop should not be issuing it either.
    """

    def __init__(self) -> None:
        self.journal: list[str] = []
        self.loaded = True
        self.block_chat = False
        self.block_warm = False
        self.chat_entered = threading.Event()
        self.chat_release = threading.Event()
        self.warm_entered = threading.Event()
        self.warm_release = threading.Event()
        # One count per warm that has actually reached the stub, so a test
        # with two warm threads can wait for *both* to be inside it rather
        # than for the first — the flag above cannot tell them apart.
        self.warms_entered = threading.Semaphore(0)
        self._lock = threading.Lock()

    def _note(self, event: str) -> None:
        with self._lock:
            self.journal.append(event)

    def post_chat(self, host, body, *, timeout):
        self.chat_entered.set()
        if self.block_chat and not self.chat_release.wait(timeout=_DEADLINE):
            raise _HarnessFailure("the chat request was never released")
        self._note("chat")
        content = json.dumps({RESPONSE_KEY: CLEANED})
        return json.dumps({"message": {"content": content}}).encode()

    def is_model_loaded(self, host, model):
        self._note("probe")
        return self.loaded

    def warm_model(self, host, model, *, keep_alive, timeout=None):
        self.warm_entered.set()
        self.warms_entered.release()
        if self.block_warm and not self.warm_release.wait(timeout=_DEADLINE):
            raise _HarnessFailure("the warm request was never released")
        self._note("warm")

    def unload_model(self, host, model):
        self._note("unload")

    @property
    def residency(self) -> list[str]:
        """The journal without the read-only ``/api/ps`` probe."""

        with self._lock:
            return [event for event in self.journal if event != "probe"]


@pytest.fixture
def transport(monkeypatch) -> _Transport:
    stub = _Transport()
    monkeypatch.setattr(ollama_refiner, "post_chat", stub.post_chat)
    monkeypatch.setattr(ollama_refiner, "is_model_loaded", stub.is_model_loaded)
    monkeypatch.setattr(ollama_refiner, "warm_model", stub.warm_model)
    monkeypatch.setattr(client, "unload_model", stub.unload_model)
    return stub


def _refiner(**overrides) -> OllamaRefiner:
    kwargs = {
        "host": "http://127.0.0.1:11434",
        "model": "test-model",
        "min_words": 10,
        "structured_output": True,
        "keep_alive": -1,
    }
    kwargs.update(overrides)
    return OllamaRefiner(**kwargs)


def _in_thread(target) -> threading.Thread:
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread


def test_a_chat_in_flight_when_shutdown_begins_cannot_leave_the_model_resident(transport):
    """The defect exactly: ``unload`` lands, the in-flight reply returns after
    it and re-establishes ``keep_alive``, and the model stays in video memory.
    No join timeout can fix it — a join that expires stops waiting, it does not
    stop the thread — so the unload has to outlive the request instead."""
    refiner = _refiner()
    transport.block_chat = True
    worker = _in_thread(lambda: refiner.refine(SPOKEN))
    assert transport.chat_entered.wait(timeout=_DEADLINE)

    refiner.unload()
    transport.chat_release.set()
    worker.join(timeout=_DEADLINE)

    assert not worker.is_alive()
    assert transport.residency[-1] == "unload", transport.residency


def test_a_warm_and_a_chat_both_in_flight_still_end_with_the_model_released(transport):
    """Both threads that can reach a ``keep_alive``-setting request are out at
    once: the background warm-up and an utterance's own reply. Whichever
    returns last is the one that decides whether the model is resident."""
    refiner = _refiner()
    transport.loaded = False
    transport.block_chat = True
    transport.block_warm = True
    warming = _in_thread(refiner.warm)
    refining = _in_thread(lambda: refiner.refine(SPOKEN))
    assert transport.warms_entered.acquire(timeout=_DEADLINE)
    assert transport.warms_entered.acquire(timeout=_DEADLINE)

    refiner.unload()
    transport.warm_release.set()
    warming.join(timeout=_DEADLINE)
    transport.chat_release.set()
    refining.join(timeout=_DEADLINE)

    assert not warming.is_alive() and not refining.is_alive()
    assert transport.residency[-1] == "unload", transport.residency


def test_nothing_new_is_sent_once_shutdown_has_begun(transport):
    """A request that has not started yet must simply not start: the daemon is
    going away, and an utterance begun after the unload would pin the model
    again from scratch."""
    refiner = _refiner()
    refiner.unload()
    transport.journal.clear()

    assert refiner.refine(SPOKEN) == SPOKEN
    assert refiner.warm() is False

    assert transport.residency == []
    assert refiner.last_result.outcome == OUTCOME_CANCELLED
    assert refiner.last_result.attempted is False
    assert refiner.last_result.failed is False


def test_shutdown_stops_a_refine_that_is_already_past_its_claim(transport):
    """Shutdown is a cancellation the caller never has to mention. An utterance
    that claimed its slot before ``unload`` ran is past the gate, so the only
    thing that keeps its *remaining* requests from re-pinning the model is the
    stage reading the shutdown flag at its own checkpoints. Seen to FAIL
    against a ``_check_stopped`` that consulted only the caller's predicate:
    the chat request went out after the model had been released."""
    refiner = _refiner()
    transport.loaded = False
    transport.block_warm = True
    delivered: list[str] = []
    worker = _in_thread(lambda: delivered.append(refiner.refine(SPOKEN)))
    assert transport.warm_entered.wait(timeout=_DEADLINE)

    refiner.unload()
    transport.warm_release.set()
    worker.join(timeout=_DEADLINE)

    assert not worker.is_alive()
    assert delivered == [SPOKEN]
    assert "chat" not in transport.journal, transport.journal
    assert refiner.last_result.outcome == OUTCOME_CANCELLED


def test_only_the_last_request_out_reissues_the_unload(transport):
    """Whoever returns while something else is still open must leave the
    unload to that one: an unload issued with a request still in flight is
    exactly the unload that gets overtaken. So the cost of the gate is one
    extra unload however many requests were out — here two in total, the one
    ``unload()`` sent and the one the last release sent, not three."""
    refiner = _refiner()
    transport.loaded = False
    transport.block_warm = True
    warming = _in_thread(refiner.warm)
    refining = _in_thread(lambda: refiner.refine(SPOKEN))
    # Both really inside the stub, so both really hold a claim: unloading
    # while only one of them did would prove nothing about the other.
    assert transport.warms_entered.acquire(timeout=_DEADLINE)
    assert transport.warms_entered.acquire(timeout=_DEADLINE)

    refiner.unload()
    transport.warm_release.set()
    warming.join(timeout=_DEADLINE)
    refining.join(timeout=_DEADLINE)

    assert not warming.is_alive() and not refining.is_alive()
    assert transport.journal.count("unload") == 2, transport.journal


def test_a_cancelled_utterance_sends_nothing_at_all_not_even_the_probe(transport):
    """Cancellation before the stage does anything costs the user nothing at
    all: no probe, no load, no reply, and the formatted transcript back.
    Asserted on the whole journal rather than on ``residency``, which hides the
    probe — the earlier form could not see a stage that was told to stop and
    went on to ask ``/api/ps`` anyway."""
    refiner = _refiner()

    assert refiner.refine(SPOKEN, cancelled=lambda: True) == SPOKEN

    assert transport.journal == [], transport.journal
    assert refiner.last_result.outcome == OUTCOME_CANCELLED
    # Nothing was timed, so nothing is reported: a cancelled attempt that
    # carried a duration would average a 120-second cold load it never
    # charged as an attempt into any aggregate over ``refine_ms``.
    assert refiner.last_result.duration_ms is None


def test_a_cancel_during_the_residency_probe_never_commits_to_the_cold_load(transport):
    """The probe answers in seconds and the load it decides on can take two
    minutes, so the gap between them is the single most valuable checkpoint in
    the stage. Seen to FAIL against an ``_ensure_loaded`` that probed and then
    loaded without looking: the utterance was committed to the long budget by
    a decision taken before the user pressed cancel."""
    refiner = _refiner()
    transport.loaded = False

    # False until the probe has run, true immediately after: the cancel lands
    # inside the residency check, before the load would be committed to.
    assert refiner.refine(SPOKEN, cancelled=lambda: "probe" in transport.journal) == SPOKEN

    assert transport.journal == ["probe"], transport.journal
    assert refiner.last_result.outcome == OUTCOME_CANCELLED


def test_a_cancel_between_the_load_and_the_reply_stops_before_the_chat(transport):
    """A cold load is the long half of the worst case. Cancelling during it
    must not then be followed by the reply request anyway."""
    refiner = _refiner()
    transport.loaded = False

    assert refiner.refine(SPOKEN, cancelled=transport.warm_entered.is_set) == SPOKEN

    assert transport.residency == ["warm"], transport.residency
    assert refiner.last_result.outcome == OUTCOME_CANCELLED


def test_a_cancel_that_lands_while_the_reply_is_open_discards_it(transport):
    """An open ``urlopen`` cannot be aborted without a thread of its own, so
    the granularity is one request: the reply is read and then thrown away
    rather than pasted into whatever the user moved on to."""
    refiner = _refiner()
    transport.block_chat = True
    result: list[str] = []
    cancelled = threading.Event()
    worker = _in_thread(lambda: result.append(refiner.refine(SPOKEN, cancelled=cancelled.is_set)))
    assert transport.chat_entered.wait(timeout=_DEADLINE)

    cancelled.set()
    transport.chat_release.set()
    worker.join(timeout=_DEADLINE)

    assert result == [SPOKEN]
    assert refiner.last_result.outcome == OUTCOME_CANCELLED


def test_an_uncancelled_utterance_is_refined_exactly_as_before(transport):
    """The interruption machinery is invisible to the ordinary path."""
    refiner = _refiner()

    assert refiner.refine(SPOKEN) == CLEANED
    assert refiner.last_result.outcome == OUTCOME_APPLIED
    assert transport.residency == ["chat"]


def test_a_refine_after_a_completed_one_still_runs(transport):
    """The in-flight bookkeeping must not leak a claim between utterances."""
    refiner = _refiner()

    assert refiner.refine(SPOKEN) == CLEANED
    assert refiner.refine(SPOKEN) == CLEANED

    assert transport.residency == ["chat", "chat"]
