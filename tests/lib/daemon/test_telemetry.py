# SPDX-License-Identifier: GPL-3.0-or-later
"""Daemon telemetry behavior and regression coverage."""

from __future__ import annotations

import dataclasses
import threading
import time

from stenographer.lib.analytics.store import Store
from stenographer.lib.config.models import Config
from stenographer.lib.daemon.telemetry import UtteranceTelemetry
from stenographer.lib.transcribe.pipeline import transcript_text
from stenographer.lib.transcribe.results import TranscriptionResult
from stenographer.lib.transcribe.utterance_record import UtteranceRecord

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


class _Collection:
    """Diagnostics double at the daemon's own seam: real calls, chosen failures."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error
        self.started: list[int] = []
        self.checkpoints: list[tuple[str, str, dict]] = []
        self.finished: list[tuple[str, str]] = []
        self.closed = 0

    def start(self, utterance_id):
        self.started.append(utterance_id)
        if self._error is not None:
            raise self._error
        return f"run:{utterance_id}"

    def checkpoint(self, identity, phase, *, metrics, context):
        self.checkpoints.append((identity, phase, context))
        if self._error is not None:
            raise self._error

    def finish(self, identity, outcome, *, metrics):
        self.finished.append((identity, outcome))
        if self._error is not None:
            raise self._error

    def close(self):
        self.closed += 1


class _AnalyticsHost:
    """Host double for ``create_session``: a real state directory under tmp."""

    name = "test"

    def __init__(self, state_dir) -> None:
        self._state_dir = state_dir

    def state_dir(self, env, home):
        return self._state_dir

    def runtime_context(self):
        return {"os": "test", "architecture": "test64"}

    def physical_core_count(self):
        return 2

    def resource_probe(self):
        return lambda pids: {"cpu_seconds": 0.5, "resident_bytes": 1024}

    def process_identity(self):
        return (4242, 1000.0)

    def process_alive(self, pid, started_epoch):
        return None


def _record(utt: int = 1) -> UtteranceRecord:
    return UtteranceRecord(
        utt=utt,
        started_at=time.perf_counter(),
        source="hotkey",
        mode="hold",
        input_rate=48000,
        channels=1,
        capture_s=1.5,
    )


def test_telemetry_without_a_platform_collects_nothing():
    telemetry = UtteranceTelemetry()
    record = _record()

    telemetry.open(Config.defaults(), None, pids=tuple)
    telemetry.start(record)
    telemetry.checkpoint(record, "secured_capture")
    telemetry.finish(record)
    telemetry.close()

    assert record.analytics_id is None


def test_a_fresh_telemetry_collects_nothing_until_it_is_opened(tmp_path):
    # The daemon constructs telemetry long before it starts its listener; the
    # presses that cannot happen yet must still find nothing to write to.
    telemetry = UtteranceTelemetry()
    before = _record(utt=1)
    telemetry.start(before)
    telemetry.checkpoint(before, "secured_capture")
    before.outcome = "DELIVERED"
    telemetry.finish(before)

    assert before.analytics_id is None
    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []

    after = _record(utt=2)
    try:
        telemetry.open(Config.defaults(), _AnalyticsHost(tmp_path), pids=tuple)
        telemetry.start(after)
        after.outcome = "DELIVERED"
        telemetry.finish(after)
    finally:
        telemetry.close()

    assert after.analytics_id is not None
    assert [record["id"] for record in Store(tmp_path / "analytics.sqlite3").records()] == [
        after.analytics_id
    ]


def test_disabled_analytics_leaves_the_record_unidentified(tmp_path):
    cfg = dataclasses.replace(
        Config.defaults(), analytics=dataclasses.replace(Config.defaults().analytics, enabled=False)
    )
    telemetry = UtteranceTelemetry()
    record = _record()
    try:
        telemetry.open(cfg, _AnalyticsHost(tmp_path), pids=tuple)
        telemetry.start(record)

        record.outcome = "DELIVERED"
        telemetry.checkpoint(record, "secured_capture")
        telemetry.finish(record)

        assert record.analytics_id is None
    finally:
        telemetry.close()

    assert list(tmp_path.iterdir()) == []


def test_a_whole_utterance_reaches_the_real_analytics_database(tmp_path):
    telemetry = UtteranceTelemetry()
    record = _record()
    record.device_name = "USB microphone"
    try:
        telemetry.open(Config.defaults(), _AnalyticsHost(tmp_path), pids=tuple)
        telemetry.start(record)
        assert record.analytics_id is not None

        telemetry.checkpoint(record, "secured_capture")
        record.outcome = "DELIVERED"
        record.total_ms = 1234.0
        telemetry.finish(record)
    finally:
        telemetry.close()

    (stored,) = Store(tmp_path / "analytics.sqlite3").records()
    assert stored["outcome"] == "delivered"
    assert stored["phase"] == "terminal"
    assert stored["context"]["device"] == "USB microphone"
    assert stored["context"]["sample_rate"] == 48000
    assert stored["metrics"]["total_ms"] == 1234.0

    # The collection was released at close: later work finds nowhere to go.
    after_close = _record(utt=2)
    telemetry.start(after_close)
    assert after_close.analytics_id is None
    assert [record["id"] for record in Store(tmp_path / "analytics.sqlite3").records()] == [
        record.analytics_id
    ]


def test_a_control_character_device_name_never_reaches_the_database(tmp_path):
    telemetry = UtteranceTelemetry()
    record = _record()
    record.device_name = "USB\x07microphone"
    try:
        telemetry.open(Config.defaults(), _AnalyticsHost(tmp_path), pids=tuple)
        telemetry.start(record)
        telemetry.checkpoint(record, "secured_capture")
        record.outcome = "CANCELLED"
        telemetry.finish(record)
    finally:
        telemetry.close()

    (stored,) = Store(tmp_path / "analytics.sqlite3").records()
    # The configured-device label survives; the rejected name never replaces it.
    assert stored["context"]["device"] == "default"
    assert "\x07" not in Store(tmp_path / "analytics.sqlite3").export_json()
    assert stored["context"]["sample_rate"] == 48000


def test_a_failing_collection_never_interrupts_the_utterance(daemon_logs):
    collection = _Collection(error=RuntimeError(f"collection exploded on {CANARY}"))
    telemetry = UtteranceTelemetry(collection=collection)
    record = _record()

    telemetry.start(record)
    assert record.analytics_id is None
    assert collection.started == [1]

    # A checkpoint without an identity is skipped before the collection is asked.
    telemetry.checkpoint(record, "secured_capture")
    assert collection.checkpoints == []

    record.analytics_id = "run:1"
    telemetry.checkpoint(record, "secured_capture")
    record.outcome = "ERROR"
    telemetry.finish(record)
    telemetry.close()

    assert [phase for _, phase, _ in collection.checkpoints] == ["secured_capture"]
    assert collection.finished == [("run:1", "error")]
    assert collection.closed == 1
    assert "analytics: start_failed error=RuntimeError" in daemon_logs.text
    assert "analytics: checkpoint_failed error=RuntimeError" in daemon_logs.text
    assert "analytics: finish_failed error=RuntimeError" in daemon_logs.text
    # Collection failures can quote persisted payloads; they stay unrendered.
    assert CANARY not in daemon_logs.text


def test_a_healthy_collection_receives_the_daemon_supplied_phases():
    collection = _Collection()
    telemetry = UtteranceTelemetry(collection=collection)
    record = _record(utt=7)
    record.device_name = "USB microphone"

    telemetry.start(record)
    assert record.analytics_id == "run:7"

    telemetry.checkpoint(record, "secured_capture")
    telemetry.checkpoint(record, "accepted_recognition")
    telemetry.checkpoint(None, "accepted_recognition")
    record.failure = "copy_failed"
    record.outcome = "ERROR"
    telemetry.finish(record)
    telemetry.close()

    identity, phase, context = collection.checkpoints[0]
    assert (identity, phase) == ("run:7", "secured_capture")
    assert context == {"sample_rate": 48000, "channels": 1, "device": "USB microphone"}
    assert collection.checkpoints[1] == ("run:7", "accepted_recognition", {})
    assert len(collection.checkpoints) == 2
    assert collection.finished == [("run:7", "copy_failed")]
    assert collection.closed == 1

    # Closing releases the collection; nothing reaches it afterwards.
    telemetry.start(_record(utt=8))
    assert collection.started == [7]
