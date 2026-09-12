# SPDX-License-Identifier: GPL-3.0-or-later
"""The refine stage inside the real utterance pipeline.

The whole daemon runs: gate, worker, formatter, delivery, summary, analytics
projection. Only the refiner is a double, and it honours the same contract the
shipping one does — so what is proved here is the *pipeline's* behaviour around
an optional stage, not a mock's.
"""

from __future__ import annotations

import threading
import time

from stenographer.lib.analytics.metrics import METRICS, PHASES, clean_metrics
from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.lib.refine.cancellation import never_cancelled
from stenographer.lib.refine.results import (
    OUTCOME_APPLIED,
    OUTCOME_CANCELLED,
    OUTCOME_FAILED,
    RefineResult,
)
from stenographer.lib.transcribe.pipeline import analytics_metrics
from stenographer.lib.transcribe.results import TranscriptionResult

from .support import _daemon, _daemon_with_status, _Refiner, _run_utterance, _summary

#: Eleven words: over the ten-word default threshold.
LONG = "um i think we should ship it on thursday no wait friday"
#: Four words: under it.
SHORT = "ship it on friday"
CLEANED = "I think we should ship it on Friday. "
#: What the local formatter alone produces from ``LONG``: capitalized first
#: word, single spacing, and the dictation trailing space. Nothing else.
FORMATTED = "Um I think we should ship it on thursday no wait friday "


#: A stand-in for the worst case a real refiner can impose on the pipeline:
#: ``COLD_LOAD_TIMEOUT_SECONDS`` plus a probe plus the reply budget, which is
#: a little over two minutes. Scaled down to something a test may really wait
#: out, so that waiting it out is visible rather than fatal.
_MODEL_BUDGET = 2.0
#: Everything here should happen in milliseconds; this only bounds a hang.
_DEADLINE = 10.0


def _raise(*args, **kwargs):
    raise RuntimeError("a refiner that broke its contract")


class _SlowRefiner:
    """A refiner that takes a model's worth of time and can be told to stop.

    Honours the same contract the shipping one does, including the optional
    ``cancelled`` predicate: it polls between the steps it would otherwise be
    blocked in, exactly as ``OllamaRefiner`` checks between its requests.
    """

    def __init__(self, *, budget: float = _MODEL_BUDGET) -> None:
        self._budget = budget
        self._last_result: RefineResult | None = None
        self.started = threading.Event()
        self.observed_cancel = False
        self.elapsed: float | None = None

    @property
    def last_result(self) -> RefineResult | None:
        return self._last_result

    def will_refine(self, text: str) -> bool:
        return True

    def refine(self, text: str, *, cancelled=never_cancelled) -> str:
        self.started.set()
        started_at = time.perf_counter()
        while time.perf_counter() - started_at < self._budget:
            if cancelled():
                self.observed_cancel = True
                break
            time.sleep(0.005)
        self.elapsed = time.perf_counter() - started_at
        self._last_result = RefineResult(
            OUTCOME_CANCELLED if self.observed_cancel else OUTCOME_APPLIED,
            chars_in=len(text),
            duration_ms=self.elapsed * 1000,
        )
        return text


def _result(text: str) -> TranscriptionResult:
    return TranscriptionResult(text=text, duration_seconds=1.0, vad_seconds=1.0)


def test_a_long_utterance_is_refined_and_the_refined_text_is_what_is_pasted():
    refiner = _Refiner(refined=CLEANED)
    daemon = _daemon(result=_result(LONG), refiner=refiner)
    try:
        _run_utterance(daemon)
    finally:
        daemon.stop()

    assert len(refiner.calls) == 1
    assert daemon._deliverer.delivered == [CLEANED]


def test_a_short_utterance_never_reaches_the_model():
    refiner = _Refiner(refined=CLEANED)
    daemon = _daemon(result=_result(SHORT), refiner=refiner)
    try:
        _run_utterance(daemon)
    finally:
        daemon.stop()

    assert refiner.calls == []
    assert daemon._deliverer.delivered == ["Ship it on friday "]


def test_a_refiner_that_raises_still_delivers_the_formatted_transcript(daemon_logs):
    """The stage is optional; a bug inside it must not cost a dictation.
    Seen to FAIL against a pipeline that called ``refine`` unguarded."""
    refiner = _Refiner(error=RuntimeError("model exploded"))
    daemon = _daemon(result=_result(LONG), refiner=refiner)
    try:
        _run_utterance(daemon)
    finally:
        daemon.stop()

    assert daemon._deliverer.delivered == [FORMATTED]
    assert "pipeline: refine_failed" in daemon_logs.text
    assert "outcome=DELIVERED" in _summary(daemon_logs)


def test_a_refiner_that_returns_nothing_delivers_the_formatted_transcript():
    daemon = _daemon(result=_result(LONG), refiner=_Refiner(refined="   "))
    try:
        _run_utterance(daemon)
    finally:
        daemon.stop()

    assert daemon._deliverer.delivered == [FORMATTED]


def test_a_failed_refine_records_the_fallback_without_losing_the_utterance(daemon_logs):
    """The record is detached when the utterance finalizes, so it has to be
    captured from the summary the daemon actually emitted. Seen to FAIL as a
    tautology: ``record is None or ...`` passed without asserting anything,
    because the daemon had already cleared ``_record``."""
    refiner = _Refiner(refined=None, outcome=OUTCOME_FAILED)
    daemon = _daemon(result=_result(LONG), refiner=refiner)
    try:
        _run_utterance(daemon)
    finally:
        daemon.stop()

    line = _summary(daemon_logs)
    assert refiner.last_result.outcome == OUTCOME_FAILED
    assert "refine=0" in line
    assert "refine_failed=1" in line
    assert daemon._deliverer.delivered == [FORMATTED]


def test_the_refining_pill_is_shown_between_transcribing_and_delivering():
    daemon, status = _daemon_with_status(result=_result(LONG), refiner=_Refiner(refined=CLEANED))
    try:
        _run_utterance(daemon)
    finally:
        daemon.stop()

    assert OverlayState.REFINING in status.states
    order = [s for s in status.states if s in (OverlayState.REFINING, OverlayState.DELIVERING)]
    assert order[:2] == [OverlayState.REFINING, OverlayState.DELIVERING]


def test_a_skipped_refine_never_shows_the_pill():
    daemon, status = _daemon_with_status(result=_result(SHORT), refiner=_Refiner(refined=CLEANED))
    try:
        _run_utterance(daemon)
    finally:
        daemon.stop()

    assert OverlayState.REFINING not in status.states


def test_cancelling_during_a_refine_drops_the_utterance_without_pasting():
    """The global cancel binding covers the whole utterance, not just the
    decode: a refine can take seconds, which is exactly when Escape is pressed.
    Seen to FAIL against a pipeline with no cancellation check after refine."""
    refiner = _Refiner(refined=CLEANED)
    daemon, status = _daemon_with_status(result=_result(LONG), refiner=refiner)
    refiner.on_refine = daemon.on_cancel
    try:
        _run_utterance(daemon)
    finally:
        daemon.stop()

    assert refiner.calls != []
    assert daemon._deliverer.delivered == []
    assert OverlayState.CANCELLED in status.states


def test_cancelling_a_refine_releases_the_pipeline_without_waiting_out_the_budget():
    """Cancel is the user saying "stop, give me my hotkey back". The overlay
    already said CANCELLED, but the daemon stays busy until the pipeline thread
    returns, and a refine can hold it for the cold-load budget plus the reply
    budget — up to about two minutes, during which every press is counted as
    an ignored busy press. The stage has to be told, not just outlived. Seen to
    FAIL against a ``_refine`` that never handed the refiner a cancel
    predicate: ``observed_cancel`` was False and the pipeline waited out the
    whole budget."""
    refiner = _SlowRefiner()
    daemon, status = _daemon_with_status(result=_result(LONG), refiner=refiner)
    daemon.on_key_down()
    daemon.on_key_up()
    assert refiner.started.wait(timeout=_DEADLINE)

    daemon.on_cancel()
    thread = daemon._pipeline_thread
    assert thread is not None
    thread.join(timeout=_DEADLINE)
    daemon.stop()

    assert not thread.is_alive()
    assert refiner.observed_cancel is True
    assert refiner.elapsed is not None and refiner.elapsed < _MODEL_BUDGET / 2
    assert daemon._busy is False
    assert daemon._deliverer.delivered == []
    assert OverlayState.CANCELLED in status.states


def test_the_summary_line_reports_the_refine_without_any_transcript_text(daemon_logs):
    daemon = _daemon(result=_result(LONG), refiner=_Refiner(refined=CLEANED))
    try:
        _run_utterance(daemon)
    finally:
        daemon.stop()

    line = _summary(daemon_logs)
    assert "refine=1" in line
    assert "refine_ms=12" in line
    assert "friday" not in daemon_logs.text.casefold()


def test_every_refine_measurement_is_a_declared_analytics_metric():
    """``clean_metrics`` rejects unknown keys, so a record field added without
    its ``METRICS`` entry would break analytics at the first refined utterance."""
    from stenographer.lib.transcribe.pipeline import apply_refinement
    from stenographer.lib.transcribe.utterance_record import UtteranceRecord

    record = UtteranceRecord(utt=1)
    apply_refinement(
        record,
        RefineResult("applied", chars_in=60, chars_out=48, duration_ms=1234.5),
        delivered="the delivered text",
    )
    projected = analytics_metrics(record)

    assert {
        "refine_ms",
        "refine_chars_in",
        "refine_chars_out",
        "refine_applied",
        "refine_attempted",
        "refine_failed",
    } <= METRICS
    assert clean_metrics(projected) == projected
    assert projected["refine_applied"] is True
    assert projected["chars_out"] == len("the delivered text")


def test_a_refiner_whose_will_refine_raises_still_delivers_the_transcript(daemon_logs):
    """Every call into the refiner is a call into third-party-shaped code, not
    just ``refine``. Seen to FAIL against a ``_refine`` whose ``will_refine``
    and ``last_result`` calls sat outside the try."""
    refiner = _Refiner(refined=CLEANED)
    refiner.will_refine = _raise

    daemon = _daemon(result=_result(LONG), refiner=refiner)
    try:
        _run_utterance(daemon)
    finally:
        daemon.stop()

    assert daemon._deliverer.delivered == [FORMATTED]
    assert "pipeline: refine_failed" in daemon_logs.text
    assert "outcome=DELIVERED" in _summary(daemon_logs)


def test_a_refiner_whose_last_result_raises_still_delivers_the_refined_text(daemon_logs):
    """The measurement must never be able to cost the text it measured."""
    refiner = _Refiner(refined=CLEANED, measurement_error=RuntimeError("measurement blew up"))
    daemon = _daemon(result=_result(LONG), refiner=refiner)
    try:
        _run_utterance(daemon)
    finally:
        daemon.stop()

    assert daemon._deliverer.delivered == [CLEANED]
    assert "pipeline: refine_failed" in daemon_logs.text


def test_the_refine_checkpoint_sits_between_recognition_and_the_clipboard():
    """Checkpoint phases may not regress, so the new one has to be ordered."""
    assert PHASES.index("accepted_recognition") < PHASES.index("accepted_refinement")
    assert PHASES.index("accepted_refinement") < PHASES.index("clipboard_confirmed")


def test_shutdown_releases_the_refine_model_from_video_memory():
    """The daemon holds the model with a long keep_alive precisely so it is
    resident between utterances; a stop that does not hand it back leaves
    gigabytes of VRAM tied up until Ollama's own timer expires. Seen to FAIL
    against a ``stop`` that never called ``unload``."""
    refiner = _Refiner(refined=CLEANED)
    daemon = _daemon(result=_result(LONG), refiner=refiner)

    daemon.stop()

    assert refiner.unloaded == 1


def test_a_refiner_that_cannot_unload_does_not_break_shutdown():
    refiner = _Refiner(refined=CLEANED, unload_error=RuntimeError("ollama went away"))
    daemon = _daemon(result=_result(LONG), refiner=refiner)

    daemon.stop()

    assert refiner.unloaded == 1


def test_a_refiner_without_an_unload_is_simply_left_alone():
    """``NullRefiner`` is the disabled stage and has nothing to release."""
    from stenographer.lib.refine.null_refiner import NullRefiner

    daemon = _daemon(result=_result(LONG), refiner=NullRefiner())

    daemon.stop()
