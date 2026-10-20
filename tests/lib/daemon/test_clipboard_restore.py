# SPDX-License-Identifier: GPL-3.0-or-later
"""The pipeline's half of the clipboard history copy and the clipboard restore.

The deliverer owns the snapshot and the writes; the pipeline decides when an
original transcript is worth keeping in the history, and asks for the restore
from one point after every delivery attempt, whatever ended it.
"""

from __future__ import annotations

import time

from stenographer.lib.analytics.metrics import METRICS, clean_metrics
from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.lib.daemon.pipeline import UtterancePipeline
from stenographer.lib.delivery.timings import DeliveryTimings
from stenographer.lib.refine.profiles import RefineProfile
from stenographer.lib.transcribe.pipeline import analytics_metrics, apply_restore
from stenographer.lib.transcribe.results import TranscriptionResult
from stenographer.lib.transcribe.utterance_record import UtteranceRecord

from .support import _SPEECH, _daemon, _daemon_with_status, _Refiner, _summary

#: Eleven words: over the ten-word refine threshold.
LONG = "um i think we should ship it on thursday no wait friday"
CLEANED = "I think we should ship it on Friday. "
#: What the local formatter alone produces from ``LONG``.
FORMATTED = "Um I think we should ship it on thursday no wait friday "


class _Deliverer:
    """Delivery double that records what the pipeline asked for, in order."""

    def __init__(self, events: list[str], *, result=True, error=None, copy_first=True) -> None:
        self._events = events
        self._result = result
        self._error = error
        self._copy_first = copy_first
        self.originals: list[str | None] = []
        self.restores = 0
        self.last_timings: DeliveryTimings | None = None

    def deliver(self, text, *, original=None, on_copied=None, cancelled=None):
        self._events.append("deliver")
        self.originals.append(original)
        if self._copy_first:
            self.last_timings = DeliveryTimings(
                copy_ms=8.0, release_wait_ms=None, release_timeout=None, copied=True
            )
        if self._error is not None:
            raise self._error
        self.last_timings = DeliveryTimings(
            copy_ms=8.0,
            release_wait_ms=30.0,
            release_timeout=False,
            copied=True,
            chord_sent=bool(self._result),
            snapshot_ms=2.0,
            original_copied=original is not None or None,
            original_copy_ms=3.0 if original is not None else None,
        )
        return self._result

    def restore_clipboard(self) -> bool:
        self._events.append("restore")
        self.restores += 1
        if self.last_timings is not None:
            self.last_timings = DeliveryTimings(
                **{**self.last_timings.__dict__, "restore_ms": 4.0, "restored": True}
            )
        return True

    def close(self) -> None: ...


def _pipeline(
    *,
    events: list[str],
    deliverer: _Deliverer,
    refined: str | None = CLEANED,
    text: str = LONG,
    copy_original: bool = True,
    cancelled=None,
    play_cue=None,
):
    daemon = _daemon(result=TranscriptionResult(text=text, duration_seconds=1.0))
    failures: list[str] = []

    def cue(name: str) -> None:
        events.append(f"cue:{name}")
        if play_cue is not None:
            play_cue(name)

    pipeline = UtterancePipeline(
        min_speech_rms=daemon._cfg.audio.min_speech_rms,
        worker=daemon._worker,
        deliverer=deliverer,
        refiner=_Refiner(refined=refined),
        telemetry=daemon._telemetry,
        publish_state=lambda _state: None,
        fail=failures.append,
        play_cue=cue,
        cancelled=(lambda: False) if cancelled is None else cancelled,
        cancel_state=lambda: OverlayState.CANCELLED,
        copy_original=copy_original,
    )
    return pipeline, failures


def _record() -> UtteranceRecord:
    now = time.perf_counter()
    return UtteranceRecord(utt=1, started_at=now, stopped_at=now, source="hotkey", mode="hold")


def test_an_agent_refine_that_changed_the_text_hands_over_the_original():
    events: list[str] = []
    deliverer = _Deliverer(events)
    pipeline, _failures = _pipeline(events=events, deliverer=deliverer)

    assert pipeline.run(_SPEECH, utterance=1, record=_record(), profile=RefineProfile.AGENT) == (
        "DELIVERED"
    )
    assert deliverer.originals == [FORMATTED]


def test_an_agent_refine_that_kept_the_text_hands_over_no_original():
    events: list[str] = []
    deliverer = _Deliverer(events)
    pipeline, _failures = _pipeline(events=events, deliverer=deliverer, refined=FORMATTED)

    pipeline.run(_SPEECH, utterance=1, record=_record(), profile=RefineProfile.AGENT)
    assert deliverer.originals == [None]


def test_a_general_refine_never_hands_over_the_original():
    events: list[str] = []
    deliverer = _Deliverer(events)
    pipeline, _failures = _pipeline(events=events, deliverer=deliverer)

    pipeline.run(_SPEECH, utterance=1, record=_record(), profile=RefineProfile.GENERAL)
    assert deliverer.originals == [None]


def test_copy_original_off_hands_over_no_original():
    events: list[str] = []
    deliverer = _Deliverer(events)
    pipeline, _failures = _pipeline(events=events, deliverer=deliverer, copy_original=False)

    pipeline.run(_SPEECH, utterance=1, record=_record(), profile=RefineProfile.AGENT)
    assert deliverer.originals == [None]


def test_the_restore_follows_the_delivered_cue_and_lands_on_the_record():
    events: list[str] = []
    deliverer = _Deliverer(events)
    pipeline, _failures = _pipeline(events=events, deliverer=deliverer)
    record = _record()

    pipeline.run(_SPEECH, utterance=1, record=record, profile=RefineProfile.AGENT)

    assert events == ["deliver", "cue:delivered", "restore"]
    assert record.restored is True
    assert record.restore_ms == 4.0
    assert record.snapshot_ms == 2.0
    assert record.original_copied is True
    assert record.original_copy_ms == 3.0


def test_the_restore_runs_after_a_refused_copy():
    events: list[str] = []
    deliverer = _Deliverer(events, result=False)
    pipeline, failures = _pipeline(events=events, deliverer=deliverer)

    assert pipeline.run(_SPEECH, utterance=1, record=_record()) == "ERROR"
    assert failures == ["could not copy transcript to clipboard"]
    assert events == ["deliver", "restore"]


def test_the_restore_runs_after_a_raising_delivery():
    events: list[str] = []
    deliverer = _Deliverer(events, error=RuntimeError("chord refused"))
    pipeline, failures = _pipeline(events=events, deliverer=deliverer)

    assert pipeline.run(_SPEECH, utterance=1, record=_record()) == "ERROR"
    assert failures == ["delivery failed"]
    assert events == ["deliver", "restore"]


def test_the_restore_runs_after_a_cancel_that_withheld_the_chord():
    events: list[str] = []
    deliverer = _Deliverer(events, result=False)
    calls = iter([False, False, False, True])
    pipeline, _failures = _pipeline(
        events=events, deliverer=deliverer, refined=None, cancelled=lambda: next(calls, True)
    )

    assert pipeline.run(_SPEECH, utterance=1, record=_record()) == "CANCELLED"
    assert events == ["deliver", "restore"]


def test_the_restore_runs_when_the_delivered_cue_raises():
    events: list[str] = []
    deliverer = _Deliverer(events)

    def broken_cue(_name: str) -> None:
        raise RuntimeError("player gone")

    pipeline, failures = _pipeline(events=events, deliverer=deliverer, play_cue=broken_cue)

    pipeline.run(_SPEECH, utterance=1, record=_record())
    assert failures == ["transcription pipeline failed"]
    assert events == ["deliver", "cue:delivered", "restore"]


def test_no_restore_is_asked_for_without_a_delivery_attempt():
    events: list[str] = []
    deliverer = _Deliverer(events)
    pipeline, _failures = _pipeline(events=events, deliverer=deliverer, text="   ")

    assert pipeline.run(_SPEECH, utterance=1, record=_record()) == "SILENT"
    assert events == []


def test_a_raising_restore_never_reaches_the_pipeline_outcome(daemon_logs):
    events: list[str] = []
    deliverer = _Deliverer(events)

    def broken() -> bool:
        raise RuntimeError("restore exploded")

    deliverer.restore_clipboard = broken
    pipeline, failures = _pipeline(events=events, deliverer=deliverer)
    record = _record()

    assert pipeline.run(_SPEECH, utterance=1, record=record) == "DELIVERED"
    assert failures == []
    assert "pipeline: restore_failed" in daemon_logs.text


def test_the_restore_projection_never_recomputes_stop_to_chord():
    record = _record()
    record.stop_to_chord_ms = 123.0
    record.copy_ms = 8.0

    apply_restore(
        record,
        DeliveryTimings(
            copy_ms=99.0,
            release_wait_ms=None,
            release_timeout=None,
            copied=True,
            chord_sent=True,
            restore_ms=4.0,
            restored=False,
        ),
    )

    assert record.stop_to_chord_ms == 123.0
    assert record.copy_ms == 8.0
    assert record.restore_ms == 4.0
    assert record.restored is False


def test_every_clipboard_measurement_is_a_declared_analytics_metric():
    """``clean_metrics`` rejects unknown keys, so a record field added without
    its ``METRICS`` entry would drop the utterance's analytics row."""
    record = UtteranceRecord(
        utt=1,
        snapshot_ms=1.5,
        original_copied=True,
        original_copy_ms=2.5,
        restore_ms=3.5,
        restored=True,
    )
    projected = analytics_metrics(record)

    assert {"snapshot_ms", "original_copied", "original_copy_ms", "restore_ms", "restored"} <= (
        METRICS
    )
    assert clean_metrics(projected) == projected
    assert projected["restored"] is True


def test_the_summary_line_reports_the_restore_with_numbers_only(daemon_logs):
    daemon = _daemon(result=TranscriptionResult(text="one two", duration_seconds=1.0))
    try:
        daemon.on_key_down()
        daemon.on_key_up()
        daemon._pipeline_thread.join(timeout=10.0)
    finally:
        daemon.stop()

    line = _summary(daemon_logs)
    assert "restored=1" in line
    assert "restore_ms=4" in line


def test_a_cancel_during_the_restore_window_is_ignored(daemon_logs):
    """R4: once DELIVERED is chosen the paste has landed; Escape during the
    settle delay must not show a CANCELLED pill or the error cue."""
    daemon, status = _daemon_with_status(
        result=TranscriptionResult(text="one two", duration_seconds=1.0)
    )
    deliverer = daemon._deliverer

    def restore_while_cancelling() -> bool:
        daemon.on_cancel()
        return True

    deliverer.restore_clipboard = restore_while_cancelling
    try:
        daemon.on_key_down()
        daemon.on_key_up()
        daemon._pipeline_thread.join(timeout=10.0)
    finally:
        daemon.stop()

    assert OverlayState.CANCELLED not in status.states
    assert "error" not in daemon._feedback.cues
    assert "outcome=DELIVERED" in _summary(daemon_logs)
    assert "hotkey: cancel_ignored" in daemon_logs.text


# --- Daemon.build: decided once, at startup ---------------------------------


def _build(tmp_path, monkeypatch, *, reader_available=True, **delivery):
    import dataclasses

    from stenographer.lib.daemon.daemon import Daemon

    from .support import _no_network_cfg, _Platform

    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(tmp_path / "config.toml"))
    cfg = _no_network_cfg()
    cfg = dataclasses.replace(cfg, delivery=dataclasses.replace(cfg.delivery, **delivery))
    platform = _Platform()
    platform.reader_available = reader_available
    return Daemon.build(cfg, clipboard_backend="wl-copy", platform=platform), platform


def test_build_enables_the_restore_with_the_configured_delay(tmp_path, monkeypatch, daemon_logs):
    daemon, platform = _build(tmp_path, monkeypatch, restore_delay_ms=250)
    try:
        deliverer = daemon._deliverer
        assert deliverer._read == platform.read_clipboard
        assert deliverer._restore == platform.restore_clipboard
        assert deliverer._restore_delay == 0.25
        assert daemon._pipeline._copy_original is True
    finally:
        daemon.stop()
    assert "deliver: clipboard_restore state=enabled" in daemon_logs.text


def test_build_disables_the_restore_when_the_reader_is_missing(tmp_path, monkeypatch, daemon_logs):
    daemon, _platform = _build(tmp_path, monkeypatch, reader_available=False)
    try:
        assert daemon._deliverer._read is None
        assert daemon._deliverer._restore is None
    finally:
        daemon.stop()
    assert "deliver: clipboard_restore state=disabled reason=reader_missing" in daemon_logs.text


def test_build_disables_the_restore_when_configured_off(tmp_path, monkeypatch, daemon_logs):
    daemon, _platform = _build(tmp_path, monkeypatch, restore_clipboard=False, copy_original=False)
    try:
        assert daemon._deliverer._read is None
        assert daemon._deliverer._restore is None
        assert daemon._pipeline._copy_original is False
    finally:
        daemon.stop()
    assert "deliver: clipboard_restore state=disabled reason=config" in daemon_logs.text
