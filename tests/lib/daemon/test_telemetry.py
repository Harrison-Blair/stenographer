# SPDX-License-Identifier: GPL-3.0-or-later
"""Daemon telemetry behavior and regression coverage."""

from __future__ import annotations

import threading
import time

from stenographer.lib.transcribe.pipeline import transcript_text
from stenographer.lib.transcribe.results import TranscriptionResult

from .support import (
    CANARY,
    _current_stamp,
    _daemon,
    _run_utterance,
    _summary,
)


def test_delivered_utterance_logs_metrics_and_never_the_transcript(daemon_logs):
    # Verify a whole successful utterance logs metrics without transcript text.
    # Seen to FAIL against a summary line carrying ``text=`` instead of
    # ``chars_out=`` (the canary appeared in caplog.text at INFO).
    result = TranscriptionResult(
        text=f"{CANARY} rides again",
        duration_seconds=1.0,
        segments=[],
        vad_seconds=0.9,
    )
    daemon = _daemon(result=result)
    try:
        _run_utterance(daemon)
    finally:
        daemon.stop()

    expected = transcript_text(result)
    assert daemon._deliverer.delivered == [expected]
    assert CANARY not in daemon_logs.text

    line = _summary(daemon_logs)
    assert "outcome=DELIVERED" in line
    assert f"chars_out={len(expected)}" in line
    assert f"chars_raw={len(result.text)}" in line
    assert "utt=1 source=hotkey mode=hold" in line
    assert "gate=pass" in line
    assert "decode_ms=1500" in line
    assert "copy_ms=8" in line


def test_each_accepted_start_allocates_the_next_utterance_id(daemon_logs):
    # Seen to FAIL against a daemon that allocated the id before the recorder
    # actually started, which numbered refused presses too.
    result = TranscriptionResult(text="one", duration_seconds=1.0)
    daemon = _daemon(result=result)
    try:
        _run_utterance(daemon)
        assert daemon._utterance_id == 1
        _run_utterance(daemon)
        assert daemon._utterance_id == 2
    finally:
        daemon.stop()

    assert daemon._worker.utterances == [1, 2]
    summaries = [m for m in daemon_logs.messages if m.startswith("pipeline: utterance ")]
    assert [line.split()[2] for line in summaries] == ["utt=1", "utt=2"]


def test_the_utterance_stamp_is_cleared_when_the_pipeline_finishes(daemon_logs):
    # ``utt=N`` must not leak onto records emitted between utterances, which
    # would attribute an idle-unload or a hotplug to the last thing dictated.
    # Checked before ``stop()``, whose own teardown clears the stamp too and
    # would otherwise hide a pipeline that never released it.
    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0))
    try:
        daemon.on_key_down()
        assert _current_stamp() == " utt=1"
        daemon.on_key_up()
        thread = daemon._pipeline_thread
        assert thread is not None
        thread.join(timeout=10.0)

        assert _current_stamp() == ""
    finally:
        daemon.stop()


def test_the_summary_is_rendered_before_the_next_press_can_be_accepted(daemon_logs):
    """The summary reads per-utterance state, so nothing may interleave with it.

    ``_emit_summary`` renders ``total_ms`` from the record's own ``started_at``
    and then clears the process-global ``utt`` stamp. Emitting it after the
    state lock was handed on let a fast re-press allocate the next id first:
    utterance N reported ``total_ms`` measured from N+1's start, and N+1's
    records went out unstamped because N's teardown cleared the stamp behind it.

    Asserted directly rather than by winning a race: while the summary is being
    rendered, no other thread may take the state lock. Seen to FAIL against
    ``_emit_summary`` called outside the ``with self._lock:`` block (the probe
    thread acquired it, and the ``total_ms`` check below dropped to ~0).
    """
    import stenographer.lib.daemon.daemon as daemon_module

    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0))
    real = daemon_module.log_summary
    lock_was_free: list[bool] = []

    def spy(record):
        # A foreign thread, because the state lock is reentrant and the
        # emitting thread would re-acquire its own lock happily.
        taken: list[bool] = []

        def probe() -> None:
            taken.append(daemon._lock.acquire(timeout=0.2))
            if taken[0]:
                daemon._lock.release()

        thread = threading.Thread(target=probe, name="lock-probe")
        thread.start()
        thread.join(timeout=5.0)
        lock_was_free.append(bool(taken and taken[0]))
        real(record)

    daemon_module.log_summary = spy
    try:
        daemon.on_key_down()
        time.sleep(0.05)
        daemon.on_key_up()
        thread = daemon._pipeline_thread
        assert thread is not None
        thread.join(timeout=10.0)
    finally:
        daemon_module.log_summary = real
        daemon.stop()

    assert lock_was_free == [False], lock_was_free

    line = next(m for m in daemon_logs.messages if m.startswith("pipeline: utterance utt=1 "))
    total_ms = float(line.split("total_ms=")[1].split()[0])
    # Measured from this utterance's own accepted start, not a shared origin.
    assert total_ms >= 50.0, line
