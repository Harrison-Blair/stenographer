# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic and OS-level tests for daemon.py.

Covered here: the pipeline outcome policy (``classify_pipeline``), the
one-at-a-time admission rule (``can_start``), the toggle-mode press mapping
(``toggle_action``, seen to fail against a stub returning "start"
unconditionally), the stale-timer guard (``max_duration_applies``, seen to
fail against a stub that ignores the generation), the overlay publish policy as
bound by ``_publish_state`` (``should_publish_state``, seen to fail against a
dedup-only stub), the mode-to-edge mapping (``edge_handlers``), and that
``Daemon.build`` wires all collaborators lazily (no uinput device, stream, or
model opened) with a safe pre-start ``stop``, per ``hotkey.mode``. The two
full-build tests need a host that actually provides a hotkey listener and key
injector, so they skip on a provider that raises ``UnsupportedPlatformError``
(the mapping itself is covered purely, and runs everywhere).

The last group drives a REAL ``Daemon`` through a whole utterance with injected
stand-ins for its four collaborators. That is dependency wiring, not mocking a
call away: nothing asserts that a subprocess/UInput/wl-copy call would have
happened, and every line of pipeline policy, utterance-id allocation, record
filling and summary rendering under test is the shipping one. It is the unit
half of the privacy gate — the log must never carry the transcript — whose
other half is the real dictation acceptance procedure.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time

import numpy as np
import pytest

from stenographer.audio import CaptureStats
from stenographer.capabilities import REQUIRED, Capabilities, OverlayCapability
from stenographer.config import Config
from stenographer.daemon import (
    Daemon,
    Outcome,
    can_start,
    classify_pipeline,
    edge_handlers,
    ignored_edge_reason,
    max_duration_applies,
    should_publish_state,
    startup_clipboard_backend,
    toggle_action,
)
from stenographer.delivery.deliver import DeliveryTimings
from stenographer.platform.base import UnsupportedPlatformError
from stenographer.status import OverlayState
from stenographer.transcribe.model import TranscriptionResult
from stenographer.transcribe.pipeline import transcript_text
from stenographer.transcribe.worker import (
    WorkerError,
    WorkerPathologicalError,
    WorkerTimings,
)
from stenographer.utils.logging_setup import UtteranceFilter, set_utterance

#: Never a substring of any field name, level, subsystem or path in the log.
CANARY = "supercalifragilisticexpialidocious"


def _startup_caps(**overrides) -> Capabilities:
    fields = {
        "key_injector_ok": True,
        "hotkey_access_ok": True,
        "has_mic": True,
        "model_cached": True,
        "clipboard_ok": True,
        "clipboard_backend": "wl-copy",
        "cue_player": "pw-play",
        "service_enabled": "enabled",
        "service_active": "active",
        "overlay": OverlayCapability.disabled(),
    }
    fields.update(overrides)
    return Capabilities(**fields)


def test_gate_failure_is_silent():
    assert classify_pipeline(gate_passed=False, transcript_nonempty=False, deliver_result=None) == (
        Outcome.SILENT,
        None,
    )


def test_empty_transcript_is_silent():
    # Gate passed but the decode was empty/all-gated: success-shaped, no error.
    assert classify_pipeline(gate_passed=True, transcript_nonempty=False, deliver_result=None) == (
        Outcome.SILENT,
        None,
    )


def test_delivered_transcript():
    assert classify_pipeline(gate_passed=True, transcript_nonempty=True, deliver_result=True) == (
        Outcome.DELIVERED,
        None,
    )


def test_failed_delivery_is_error_with_message():
    outcome, message = classify_pipeline(
        gate_passed=True, transcript_nonempty=True, deliver_result=False
    )
    # A False deliver on non-empty text is never silent: the copy failed,
    # so the chord was withheld and the user must be told.
    assert outcome is Outcome.ERROR
    assert message


def test_ignored_edge_reason_names_the_state_that_refused_the_press():
    # Seen to FAIL against the single "recording_or_busy" reason this replaced,
    # which was true of every refusal and so explained none of them.
    assert ignored_edge_reason(recording=True, busy=True, stopping=True) == "recording"
    assert ignored_edge_reason(recording=False, busy=True, stopping=True) == "busy"
    assert ignored_edge_reason(recording=False, busy=False, stopping=True) == "stopping"
    assert ignored_edge_reason(recording=False, busy=False, stopping=False) == "none"


def test_can_start_only_when_fully_idle():
    assert can_start(recording=False, busy=False, stopping=False) is True
    assert can_start(recording=True, busy=False, stopping=False) is False
    assert can_start(recording=False, busy=True, stopping=False) is False
    assert can_start(recording=False, busy=False, stopping=True) is False


def test_toggle_action_maps_press_edges():
    # Idle press starts; a press while recording always stops, even during
    # shutdown, so a live capture is never stranded. A press during
    # transcription (busy) neither starts nor queues — one utterance at a time.
    assert toggle_action(recording=False, busy=False, stopping=False) == "start"
    assert toggle_action(recording=True, busy=False, stopping=False) == "stop"
    assert toggle_action(recording=False, busy=True, stopping=False) is None
    assert toggle_action(recording=False, busy=False, stopping=True) is None
    assert toggle_action(recording=True, busy=False, stopping=True) == "stop"


def test_max_duration_applies_guards_stale_generation():
    # A fired timer can be blocked on the state lock while a manual stop and an
    # immediate restart advance the generation; the stale timer must not stop
    # the newer recording, and a matching timer applies only while live.
    assert max_duration_applies(3, 3, recording=True) is True
    assert max_duration_applies(2, 3, recording=True) is False
    assert max_duration_applies(3, 3, recording=False) is False


def test_publish_policy_always_represents_error():
    # The helper auto-hides ERROR after a fixed timeout without notifying the
    # daemon, so the producer cache can be stale: a repeated ERROR (e.g. mic
    # failing twice in a row) must re-present rather than dedup away. Tested
    # against the name daemon.py binds in _publish_state. Seen to fail against
    # a dedup-only stub shadowing the helper.
    assert should_publish_state(OverlayState.ERROR, OverlayState.ERROR) is True


def test_publish_policy_dedups_stable_states():
    # Every non-ERROR state coalesces when repeated; any actual change passes.
    for state in OverlayState:
        if state is OverlayState.ERROR:
            continue
        assert should_publish_state(state, state) is False
    assert should_publish_state(OverlayState.HIDDEN, OverlayState.RECORDING) is True
    assert should_publish_state(OverlayState.RECORDING, OverlayState.TRANSCRIBING) is True
    assert should_publish_state(OverlayState.ERROR, OverlayState.HIDDEN) is True


def test_startup_gate_tracks_every_current_doctor_requirement():
    assert startup_clipboard_backend(_startup_caps()) == "wl-copy"
    for name in REQUIRED:
        caps = dataclasses.replace(_startup_caps(), **{name: False})
        assert startup_clipboard_backend(caps) is None, name


def test_startup_gate_ignores_optional_capabilities_and_reuses_backend():
    caps = _startup_caps(
        clipboard_backend="x11",
        cue_player=None,
        service_enabled=None,
        service_active=None,
        overlay=OverlayCapability.disabled(),
    )
    assert startup_clipboard_backend(caps) == "x11"


def _build_or_skip(cfg):
    """Build for real, or skip where the host provides no hotkey/paste backend.

    Expressed as a capability rather than an OS name so a provider that grows
    a real backend starts running these checks without touching the test.
    """
    from stenographer.daemon import Daemon

    try:
        return Daemon.build(cfg, clipboard_backend="wl-copy")
    except UnsupportedPlatformError as exc:
        pytest.skip(f"no hotkey/injection backend on this host: {exc}")


class _EdgeSpy:
    """Stands in for a Daemon: edge_handlers only reads bound methods."""

    def on_key_down(self) -> None: ...

    def on_key_up(self) -> None: ...

    def on_toggle_press(self) -> None: ...


def test_edge_handlers_map_mode_to_rising_and_falling_callbacks():
    # Seen to FAIL against a mapping that ignores the mode and returns the hold
    # pair for both. Pure: no platform, no listener, no device.
    daemon = _EdgeSpy()

    assert edge_handlers(daemon, "hold") == (daemon.on_key_down, daemon.on_key_up)

    on_start, on_stop = edge_handlers(daemon, "toggle")
    assert on_start == daemon.on_toggle_press
    # Only presses drive the session: the falling edge must be inert.
    assert on_stop not in (daemon.on_key_up, daemon.on_key_down)
    assert on_stop() is None


def test_build_wires_collaborators_lazily():
    # Package A (hotkey.py) is built concurrently against the documented
    # contract; skip this wiring check until it lands, then run it for real.
    pytest.importorskip("stenographer.hotkey")
    from stenographer.config import Config

    daemon = _build_or_skip(Config.defaults())
    try:
        # Built but nothing opened: startup preparation happens only after the
        # single-instance lock is acquired in run().
        assert daemon._recording is False
        assert daemon._busy is False
        assert daemon._listener is not None
        assert daemon._deliverer is not None
        assert daemon._worker.is_alive() is False
        assert daemon._recorder.is_active is False
        assert daemon._recorder.is_prepared is False
    finally:
        # stop() before run() must be a safe no-op.
        daemon.stop()


def test_build_wires_toggle_mode_press_only():
    # Seen to FAIL against a build that ignores hotkey.mode and wires toggle
    # like hold. Same real-build style as the lazy-wiring test above: nothing
    # is opened, no mocks.
    pytest.importorskip("stenographer.hotkey")
    from stenographer.config import Config

    hold = _build_or_skip(Config.defaults())
    try:
        assert hold._listener._on_start == hold.on_key_down
        assert hold._listener._on_stop == hold.on_key_up
    finally:
        hold.stop()

    defaults = Config.defaults()
    toggle_cfg = dataclasses.replace(
        defaults, hotkey=dataclasses.replace(defaults.hotkey, mode="toggle")
    )
    toggle = _build_or_skip(toggle_cfg)
    try:
        # Only presses drive the session; the falling edge must be inert.
        assert toggle._listener._on_start == toggle.on_toggle_press
        assert toggle._listener._on_stop != toggle.on_key_up
        assert toggle._listener._on_stop != toggle.on_key_down
    finally:
        toggle.stop()


# --------------------------------------------------------------------------
# One whole utterance, driven through the real Daemon with injected stand-ins.
# --------------------------------------------------------------------------

_RATE = 16000
_SPEECH = np.full(_RATE, 0.02, dtype=np.float32)
_SILENCE = np.zeros(_RATE, dtype=np.float32)
_CAPTURE = CaptureStats(
    activate_ms=3.0,
    capture_seconds=1.0,
    input_frames=_RATE,
    output_frames=_RATE,
    overflow=False,
    capped=False,
)


class _Feedback:
    def __init__(self) -> None:
        self.cues: list[str] = []

    def play(self, name: str) -> None:
        self.cues.append(name)

    def close(self) -> None: ...


class _Notifier:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def info(self, message: str) -> None: ...


class _Recorder:
    def __init__(self, samples: np.ndarray) -> None:
        self._samples = samples
        self.last_capture: CaptureStats | None = None

    def start(self) -> None:
        self.last_capture = None

    def stop(self) -> np.ndarray:
        self.last_capture = _CAPTURE
        return self._samples

    def prepare(self) -> None: ...

    def close(self) -> None: ...


class _Worker:
    def __init__(self, result: TranscriptionResult | None, error: Exception | None) -> None:
        self._result = result
        self._error = error
        self.last_timings: WorkerTimings | None = None
        self.utterances: list[int | None] = []
        self.is_model_ready = False

    def hold_model(self) -> None: ...

    def release_model(self) -> None: ...

    def warmup(self, utterance: int | None = None) -> None: ...

    def shutdown(self) -> None: ...

    def transcribe(self, samples: np.ndarray, utterance: int | None = None) -> TranscriptionResult:
        self.utterances.append(utterance)
        if self._error is not None:
            raise self._error
        self.last_timings = WorkerTimings(lock_wait_ms=0.5, load_ms=900.0, decode_ms=1500.0)
        self.is_model_ready = True
        return self._result


class _Deliverer:
    def __init__(self) -> None:
        self.delivered: list[str] = []
        self.last_timings: DeliveryTimings | None = None

    def deliver(self, text: str) -> bool:
        self.delivered.append(text)
        self.last_timings = DeliveryTimings(
            copy_ms=8.0, release_wait_ms=30.0, release_timeout=False
        )
        return True

    def close(self) -> None: ...


def _daemon(*, result=None, error=None, samples=_SPEECH, mode="hold") -> Daemon:
    cfg = Config.defaults()
    cfg = dataclasses.replace(cfg, hotkey=dataclasses.replace(cfg.hotkey, mode=mode))
    daemon = Daemon(
        cfg=cfg,
        feedback=_Feedback(),
        notifier=_Notifier(),
        worker=_Worker(result, error),
        recorder=_Recorder(samples),
    )
    daemon._deliverer = _Deliverer()
    return daemon


def _run_utterance(daemon: Daemon) -> None:
    daemon.on_key_down()
    daemon.on_key_up()
    thread = daemon._pipeline_thread
    if thread is not None:
        thread.join(timeout=10.0)
        assert not thread.is_alive()


@pytest.fixture
def daemon_logs(caplog):
    """Capture the daemon's own records regardless of what earlier tests left.

    ``setup_logging`` sets ``propagate = False`` on the package logger and
    ``shutdown_logging`` does not put it back, so caplog's root handler can
    otherwise see nothing at all — and a privacy assertion over an empty log
    passes for the wrong reason.
    """
    logger = logging.getLogger("stenographer")
    saved_propagate, saved_level = logger.propagate, logger.level
    saved_handlers = list(logger.handlers)
    logger.propagate = True
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    try:
        with caplog.at_level(logging.DEBUG, logger="stenographer"):
            yield caplog
    finally:
        logger.propagate, logger.level = saved_propagate, saved_level
        logger.handlers[:] = saved_handlers
        set_utterance(None)


def _summary(caplog) -> str:
    lines = [m for m in caplog.messages if m.startswith("pipeline: utterance ")]
    assert len(lines) == 1, caplog.messages
    return lines[0]


def test_delivered_utterance_logs_metrics_and_never_the_transcript(daemon_logs):
    # The unit half of AGENTS.md rule 6, over a whole successful utterance.
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
    assert "utt=1 mode=hold" in line
    assert "gate=pass" in line
    assert "decode_ms=1500" in line
    assert "copy_ms=8" in line


def test_transcription_failure_never_renders_the_worker_message(daemon_logs):
    # A ``WorkerError`` round-trips the ASR child's own detail string, whose
    # inference branch can quote decoder output derived from the audio: the
    # safe=False tier must keep it out of the log at every level, DEBUG
    # included. Seen to FAIL against ``log_failure(..., safe=True)``.
    daemon = _daemon(error=WorkerError(f"inference blew up on {CANARY}"))
    try:
        _run_utterance(daemon)
    finally:
        daemon.stop()

    assert CANARY not in daemon_logs.text
    assert "pipeline: transcription_failed" in daemon_logs.text
    assert "error=WorkerError" in daemon_logs.text
    assert "outcome=ERROR" in _summary(daemon_logs)


def test_gate_rejection_is_silent_and_reports_only_the_phases_it_reached(daemon_logs):
    daemon = _daemon(samples=_SILENCE)
    try:
        _run_utterance(daemon)
    finally:
        daemon.stop()

    assert daemon._deliverer.delivered == []
    line = _summary(daemon_logs)
    assert "outcome=SILENT" in line
    assert "gate=fail" in line
    assert "decode_ms=" not in line
    assert "chars_out=" not in line
    assert "audio: speech_gate verdict=fail" in daemon_logs.text


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


def test_a_stale_max_duration_timer_cannot_stop_the_next_utterance():
    # The id doubles as the stale-timer generation. A timer armed for utterance
    # 1 that reaches the lock only after utterance 2 has started must do
    # nothing. Seen to FAIL against ``_on_max_duration`` ignoring its argument.
    result = TranscriptionResult(text="one", duration_seconds=1.0)
    daemon = _daemon(result=result, mode="toggle")
    try:
        _run_utterance(daemon)
        daemon.on_key_down()
        assert daemon._utterance_id == 2
        assert daemon._recording is True

        daemon._on_max_duration(1)
        assert daemon._recording is True

        daemon._on_max_duration(2)
        assert daemon._recording is False
        thread = daemon._pipeline_thread
        assert thread is not None
        thread.join(timeout=10.0)
    finally:
        daemon.stop()


def _current_stamp() -> str:
    """What ``UtteranceFilter`` would stamp on a record emitted right now."""
    record = logging.getLogger("stenographer.daemon").makeRecord(
        "stenographer.daemon", logging.INFO, __file__, 0, "probe: stamp", (), None
    )
    UtteranceFilter().filter(record)
    return record.utt_suffix


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


def test_a_recorder_stop_failure_still_closes_the_utterance(daemon_logs):
    class _BrokenRecorder(_Recorder):
        def stop(self) -> np.ndarray:
            raise OSError("stream vanished")

    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0))
    daemon._recorder = _BrokenRecorder(_SPEECH)
    try:
        daemon.on_key_down()
        daemon.on_key_up()
    finally:
        daemon.stop()

    assert daemon._pipeline_thread is None
    assert "recorder: failed" in daemon_logs.text
    assert "outcome=ERROR" in _summary(daemon_logs)
    assert not [t for t in threading.enumerate() if t.name == "stenographer-pipeline"]


def test_a_pathological_decode_keeps_its_counts_only_reason(daemon_logs):
    # PathologicalOutputError's message is audited to carry counts only, and it
    # is the only thing that explains a decode the daemon silently discarded.
    # Seen to FAIL against a handler that caught WorkerPathologicalError under
    # the plain WorkerError arm at safe=False: detail= disappeared entirely.
    reason = "decoder word density exceeded limit (312 > 40)"
    daemon = _daemon(error=WorkerPathologicalError(reason))
    try:
        _run_utterance(daemon)
    finally:
        daemon.stop()

    assert f'detail="{reason}"' in daemon_logs.text
    assert "error=WorkerPathologicalError" in daemon_logs.text
    assert "outcome=ERROR" in _summary(daemon_logs)


def test_an_inference_failure_beside_it_still_renders_nothing(daemon_logs):
    # The sibling of the test above: same handler, opposite tier. Seen to FAIL
    # against collapsing both arms to safe=True.
    daemon = _daemon(error=WorkerError(f"inference blew up on {CANARY}"))
    try:
        _run_utterance(daemon)
    finally:
        daemon.stop()

    assert CANARY not in daemon_logs.text
    assert "error=WorkerError" in daemon_logs.text


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
    import stenographer.daemon as daemon_module

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


def test_stop_closes_an_in_flight_recording_as_cancelled(daemon_logs):
    # A press then a shutdown must not leave an utterance unaccounted for.
    # Seen to FAIL against a stop() that cleared _recording without taking the
    # record: no pipeline: utterance line was written at all.
    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0))
    daemon.on_key_down()
    daemon.stop()

    assert "outcome=CANCELLED" in _summary(daemon_logs)
    assert _current_stamp() == ""
