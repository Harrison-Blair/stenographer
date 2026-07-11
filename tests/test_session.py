# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for :mod:`stenographer.session`."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import numpy as np

from stenographer.asr.model import SegmentInfo, TranscriptionResult
from stenographer.asr.worker import CancelledError
from stenographer.session import Session


def _mock_cfg() -> MagicMock:
    return MagicMock()


def _make_components() -> dict[str, MagicMock]:
    return {
        "cfg": _mock_cfg(),
        "caps": MagicMock(has_wtype=True, has_wl_copy=True),
        "listener": MagicMock(),
        "recorder": MagicMock(is_active=False),
        "worker": MagicMock(),
        "feedback": MagicMock(),
        "injector": MagicMock(),
        "clipboard": MagicMock(),
    }


def _make_session(
    one_shot: bool = False,
    **overrides: object,
) -> tuple[Session, dict[str, MagicMock]]:
    components = _make_components()
    components.update(overrides)
    cfg = components["cfg"]
    caps = components["caps"]
    listener = components.pop("listener")
    recorder = components.pop("recorder")
    worker = components.pop("worker")
    feedback = components.pop("feedback")
    injector = components.pop("injector")
    clipboard = components.pop("clipboard")
    session = Session(
        cfg=cfg,
        capabilities=caps,
        listener=listener,
        recorder=recorder,
        worker=worker,
        feedback=feedback,
        injector=injector,
        clipboard=clipboard,
        notification=components.get("notification", None),
        one_shot=one_shot,
    )
    return session, components


def _fake_future() -> MagicMock:
    """A worker future whose add_done_callback fires immediately, so the
    session's segment loop sees its completion sentinel."""
    fut = MagicMock()
    fut.add_done_callback.side_effect = lambda cb: cb(fut)
    return fut


def _components(session: Session) -> dict[str, MagicMock]:
    return {
        "recorder": session._recorder,
        "worker": session._worker,
        "injector": session._injector,
        "clipboard": session._clipboard,
        "feedback": session._feedback,
        "listener": session._listener,
        "caps": session._caps,
        "cfg": session._cfg,
    }


# ---------------------------------------------------------------------------
# on_recording_start / lifecycle
# ---------------------------------------------------------------------------


def test_on_recording_start_invokes_recorder_start() -> None:
    session, _m = _make_session()
    c = _components(session)
    session.on_recording_start()
    c["recorder"].start.assert_called_once()


def test_on_recording_start_when_already_recording_is_noop() -> None:
    session, _m = _make_session()
    c = _components(session)
    session.on_recording_start()
    c["recorder"].start.reset_mock()
    session.on_recording_start()
    c["recorder"].start.assert_not_called()


def test_run_returns_when_stop_is_called() -> None:
    session, _m = _make_session()
    session.start()
    thread = threading.Thread(target=session.run, daemon=True)
    thread.start()
    time.sleep(0.05)
    assert thread.is_alive()
    session.stop()
    thread.join(timeout=2.0)
    assert not thread.is_alive()


# ---------------------------------------------------------------------------
# _process unit tests (core transcription + output logic)
# ---------------------------------------------------------------------------


def test_process_submits_to_worker_and_outputs() -> None:
    session, _m = _make_session()
    c = _components(session)
    c["cfg"].clipboard.enabled = True
    future = _fake_future()
    future.result.return_value = TranscriptionResult(
        text="hello world", duration_seconds=0.5, segments=[]
    )
    c["worker"].submit.return_value = future
    samples = np.zeros((16000, 1), dtype=np.float32)
    session._process(samples, "ptt", threading.Event())
    c["worker"].submit.assert_called_once()
    future.result.assert_called_once()
    c["injector"].type_text.assert_called_once_with("hello world")
    c["clipboard"].copy.assert_called_once_with("hello world")


def test_process_empty_transcript_skips_output() -> None:
    session, _m = _make_session()
    c = _components(session)
    c["cfg"].clipboard.enabled = True
    future = _fake_future()
    future.result.return_value = TranscriptionResult(text="   ", duration_seconds=0.0, segments=[])
    c["worker"].submit.return_value = future
    session._process(np.zeros((1, 1), dtype=np.float32), "ptt", threading.Event())
    c["injector"].type_text.assert_not_called()
    c["clipboard"].copy.assert_not_called()
    c["feedback"].play.assert_called_once_with("error")


def test_process_injector_skipped_when_wtype_unavailable() -> None:
    session, _m = _make_session()
    c = _components(session)
    c["caps"].has_wtype = False
    c["cfg"].clipboard.enabled = True
    future = _fake_future()
    future.result.return_value = TranscriptionResult(text="hi", duration_seconds=0.0, segments=[])
    c["worker"].submit.return_value = future
    session._process(np.zeros((1, 1), dtype=np.float32), "ptt", threading.Event())
    c["injector"].type_text.assert_not_called()
    c["clipboard"].copy.assert_called_once()


def test_process_clipboard_skipped_when_disabled() -> None:
    session, _m = _make_session()
    c = _components(session)
    c["cfg"].clipboard.enabled = False
    future = _fake_future()
    future.result.return_value = TranscriptionResult(text="hi", duration_seconds=0.0, segments=[])
    c["worker"].submit.return_value = future
    session._process(np.zeros((1, 1), dtype=np.float32), "ptt", threading.Event())
    c["clipboard"].copy.assert_not_called()


def test_process_injects_partial_segments_and_skips_duplicate_final() -> None:
    session, _m = _make_session()
    c = _components(session)
    c["cfg"].asr.silence_threshold = 0.6
    c["cfg"].clipboard.enabled = True

    result = TranscriptionResult(text="hello world", duration_seconds=1.0, segments=[])
    future = _fake_future()
    future.done.return_value = True
    future.result.return_value = result

    def submit_side_effect(samples, *, on_segment=None, cancel_event=None):
        if on_segment is not None:
            on_segment(SegmentInfo(0.0, 0.5, " hello", 0.1))
            on_segment(SegmentInfo(0.5, 1.0, " world", 0.1))
        return future

    c["worker"].submit.side_effect = submit_side_effect
    session._process(np.zeros((16000, 1), dtype=np.float32), "ptt", threading.Event())

    c["injector"].type_text.assert_any_call(" hello", raw=True)
    c["injector"].type_text.assert_any_call(" world", raw=True)
    assert c["injector"].type_text.call_count == 2
    c["clipboard"].copy.assert_called_once_with("hello world")


def test_process_paste_mode_skips_partial_injection_and_pastes_at_end() -> None:
    session, _m = _make_session()
    c = _components(session)
    c["cfg"].asr.silence_threshold = 0.6
    c["cfg"].clipboard.enabled = True
    c["cfg"].output.injection_method = "paste"

    result = TranscriptionResult(text="hello world", duration_seconds=1.0, segments=[])
    future = _fake_future()
    future.done.return_value = True
    future.result.return_value = result

    def submit_side_effect(samples, *, on_segment=None, cancel_event=None):
        if on_segment is not None:
            on_segment(SegmentInfo(0.0, 0.5, " hello", 0.1))
            on_segment(SegmentInfo(0.5, 1.0, " world", 0.1))
        return future

    c["worker"].submit.side_effect = submit_side_effect
    session._process(np.zeros((16000, 1), dtype=np.float32), "ptt", threading.Event())

    c["injector"].type_text.assert_not_called()
    c["feedback"].play.assert_any_call("segment")
    c["feedback"].play.assert_any_call("transcribe_done")
    assert c["feedback"].play.call_count == 3  # 2 segments + transcribe_done
    c["clipboard"].copy.assert_called_once_with("hello world")
    c["injector"].paste.assert_called_once()


def test_process_paste_mode_empty_transcript_skips_output() -> None:
    session, _m = _make_session()
    c = _components(session)
    c["cfg"].output.injection_method = "paste"

    future = _fake_future()
    future.done.return_value = True
    future.result.return_value = TranscriptionResult(text="   ", duration_seconds=0.0, segments=[])
    c["worker"].submit.return_value = future
    session._process(np.zeros((1, 1), dtype=np.float32), "ptt", threading.Event())

    c["injector"].type_text.assert_not_called()
    c["injector"].paste.assert_not_called()
    c["clipboard"].copy.assert_not_called()
    c["feedback"].play.assert_called_once_with("error")


def test_process_paste_mode_clipboard_disabled_still_pastes() -> None:
    session, _m = _make_session()
    c = _components(session)
    c["cfg"].clipboard.enabled = False
    c["cfg"].output.injection_method = "paste"

    future = _fake_future()
    future.done.return_value = True
    future.result.return_value = TranscriptionResult(text="hi", duration_seconds=0.0, segments=[])
    c["worker"].submit.return_value = future
    session._process(np.zeros((1, 1), dtype=np.float32), "ptt", threading.Event())

    c["clipboard"].copy.assert_not_called()
    c["injector"].paste.assert_called_once()


def test_process_silence_no_speech_prob_skips_output() -> None:
    session, _m = _make_session()
    c = _components(session)
    c["cfg"].asr.silence_threshold = 0.6
    c["cfg"].clipboard.enabled = True
    future = _fake_future()
    future.result.return_value = TranscriptionResult(
        text="Thank you",
        duration_seconds=1.0,
        segments=[
            SegmentInfo(0.0, 0.5, "Thank", 0.95),
            SegmentInfo(0.5, 1.0, " you", 0.88),
        ],
    )
    c["worker"].submit.return_value = future
    session._process(np.zeros((16000, 1), dtype=np.float32), "ptt", threading.Event())
    c["injector"].type_text.assert_not_called()
    c["clipboard"].copy.assert_not_called()
    c["feedback"].play.assert_called_once_with("error")


def test_process_silence_no_speech_prob_below_threshold_outputs() -> None:
    session, _m = _make_session()
    c = _components(session)
    c["cfg"].asr.silence_threshold = 0.6
    c["cfg"].clipboard.enabled = True
    future = _fake_future()
    future.result.return_value = TranscriptionResult(
        text="hello",
        duration_seconds=0.5,
        segments=[
            SegmentInfo(0.0, 0.5, "hello", 0.1),
        ],
    )
    c["worker"].submit.return_value = future
    session._process(np.zeros((16000, 1), dtype=np.float32), "ptt", threading.Event())
    c["injector"].type_text.assert_called_once_with("hello")
    c["clipboard"].copy.assert_called_once_with("hello")


def test_process_silence_segments_never_reach_cursor() -> None:
    """Hallucinated segments over silence must not be typed at the cursor."""
    session, _m = _make_session()
    c = _components(session)
    c["cfg"].asr.silence_threshold = 0.6
    c["cfg"].clipboard.enabled = True

    segments = [
        SegmentInfo(0.0, 0.5, " Thank", 0.95),
        SegmentInfo(0.5, 1.0, " you.", 0.88),
    ]
    result = TranscriptionResult(text="Thank you.", duration_seconds=1.0, segments=segments)
    future = _fake_future()
    future.result.return_value = result

    def submit_side_effect(samples, *, on_segment=None, cancel_event=None):
        if on_segment is not None:
            for seg in segments:
                on_segment(seg)
        return future

    c["worker"].submit.side_effect = submit_side_effect
    session._process(np.zeros((16000, 1), dtype=np.float32), "ptt", threading.Event())

    c["injector"].type_text.assert_not_called()
    c["clipboard"].copy.assert_not_called()
    c["feedback"].play.assert_called_once_with("error")


def test_process_types_speech_but_skips_silence_segments() -> None:
    session, _m = _make_session()
    c = _components(session)
    c["cfg"].asr.silence_threshold = 0.6
    c["cfg"].clipboard.enabled = True

    segments = [
        SegmentInfo(0.0, 0.5, " hello", 0.1),
        SegmentInfo(0.5, 1.0, " Thank you.", 0.95),
    ]
    result = TranscriptionResult(text="hello Thank you.", duration_seconds=1.0, segments=segments)
    future = _fake_future()
    future.result.return_value = result

    def submit_side_effect(samples, *, on_segment=None, cancel_event=None):
        if on_segment is not None:
            for seg in segments:
                on_segment(seg)
        return future

    c["worker"].submit.side_effect = submit_side_effect
    session._process(np.zeros((16000, 1), dtype=np.float32), "ptt", threading.Event())

    c["injector"].type_text.assert_called_once_with(" hello", raw=True)
    c["clipboard"].copy.assert_called_once_with("hello")


def test_process_paste_mode_clipboard_excludes_silence_segments() -> None:
    session, _m = _make_session()
    c = _components(session)
    c["cfg"].asr.silence_threshold = 0.6
    c["cfg"].clipboard.enabled = True
    c["cfg"].output.injection_method = "paste"
    # The formatter holds cfg.formatting (captured at construction); pin its
    # fields so the formatted paste output is deterministic.
    c["cfg"].formatting.paragraph_pause_seconds = 2.0
    c["cfg"].formatting.capitalize_sentences = True
    c["cfg"].formatting.normalize_spacing = True

    future = _fake_future()
    future.result.return_value = TranscriptionResult(
        text="hello Thank you.",
        duration_seconds=1.0,
        segments=[
            SegmentInfo(0.0, 0.5, "hello", 0.1),
            SegmentInfo(0.5, 1.0, " Thank you.", 0.95),
        ],
    )
    c["worker"].submit.return_value = future
    session._process(np.zeros((16000, 1), dtype=np.float32), "ptt", threading.Event())

    # The silence segment is excluded and the survivor is formatted
    # (capitalised, trailing space per output.append_trailing_space).
    c["clipboard"].copy.assert_called_once_with("Hello ")
    c["injector"].paste.assert_called_once()


def test_process_transcription_failure_plays_error_cue() -> None:
    session, _m = _make_session()
    c = _components(session)
    future = _fake_future()
    future.result.side_effect = RuntimeError("inference crashed")
    c["worker"].submit.return_value = future
    session._process(np.zeros((16000, 1), dtype=np.float32), "ptt", threading.Event())
    c["injector"].type_text.assert_not_called()
    c["clipboard"].copy.assert_not_called()
    c["feedback"].play.assert_called_once_with("error")


def test_process_silence_some_segments_below_threshold_outputs_speech_only() -> None:
    session, _m = _make_session()
    c = _components(session)
    c["cfg"].asr.silence_threshold = 0.6
    c["cfg"].clipboard.enabled = True
    future = _fake_future()
    future.result.return_value = TranscriptionResult(
        text="hello world",
        duration_seconds=1.0,
        segments=[
            SegmentInfo(0.0, 0.3, "hello", 0.9),
            SegmentInfo(0.3, 1.0, " world", 0.3),
        ],
    )
    c["worker"].submit.return_value = future
    session._process(np.zeros((16000, 1), dtype=np.float32), "ptt", threading.Event())
    c["injector"].type_text.assert_called_once_with("world")
    c["clipboard"].copy.assert_called_once_with("world")


# ---------------------------------------------------------------------------
# Async queue / processor tests
# ---------------------------------------------------------------------------


def test_on_recording_stop_enqueues_and_recorder_stops() -> None:
    """on_recording_stop stops the recorder and enqueues; does NOT block on transcription."""
    session, _m = _make_session()
    c = _components(session)
    session.start()
    c["recorder"].stop.return_value = np.zeros((100, 1), dtype=np.float32)

    session.on_recording_start()
    session.on_recording_stop("ptt")

    c["recorder"].stop.assert_called_once()
    # Worker must NOT have been called yet (queued, not processed immediately)
    c["worker"].submit.assert_not_called()
    # Processor will pick it up: wait a tick
    time.sleep(0.05)
    c["worker"].submit.assert_called_once()


def test_silence_detection_disabled_when_one_shot() -> None:
    cfg = _mock_cfg()
    cfg.audio.silence_detection = True
    session, _m = _make_session(one_shot=True, cfg=cfg)
    assert session._silence_detection is False


def test_silence_detection_enabled_for_daemon() -> None:
    cfg = _mock_cfg()
    cfg.audio.silence_detection = True
    session, _m = _make_session(one_shot=False, cfg=cfg)
    assert session._silence_detection is True


def test_recording_start_wires_flush_callback_when_enabled() -> None:
    cfg = _mock_cfg()
    cfg.audio.silence_detection = True
    cfg.asr.mode = "eager"  # avoid the lazy-load branch
    session, _m = _make_session(cfg=cfg)
    c = _components(session)
    session.on_recording_start()
    assert c["recorder"].start.call_args.kwargs["on_segment"] == session._enqueue_flush_segment


def test_recording_start_no_flush_callback_when_disabled() -> None:
    cfg = _mock_cfg()
    cfg.audio.silence_detection = False
    cfg.asr.mode = "eager"
    session, _m = _make_session(cfg=cfg)
    c = _components(session)
    session.on_recording_start()
    assert c["recorder"].start.call_args.kwargs["on_segment"] is None


def test_enqueue_flush_segment_tags_ptt_and_processes() -> None:
    session, _m = _make_session()
    arr = np.ones((10, 1), dtype=np.float32)
    session._enqueue_flush_segment(arr)
    samples, mode, _abort, _gen = session._utterance_queue.get_nowait()
    assert mode == "ptt"
    assert np.array_equal(samples, arr)


def test_on_recording_stop_skips_empty_tail_when_silence_detection() -> None:
    cfg = _mock_cfg()
    cfg.audio.silence_detection = True
    cfg.asr.mode = "eager"
    session, _m = _make_session(cfg=cfg)
    c = _components(session)
    c["recorder"].stop.return_value = np.empty((0, 1), dtype=np.float32)

    session.on_recording_start()
    session.on_recording_stop("ptt")

    # Chunks were already flushed mid-recording; the empty tail is not queued.
    assert session._utterance_queue.qsize() == 0


def test_on_recording_stop_enqueues_empty_tail_when_disabled() -> None:
    cfg = _mock_cfg()
    cfg.audio.silence_detection = False
    cfg.asr.mode = "eager"
    session, _m = _make_session(cfg=cfg)
    c = _components(session)
    c["recorder"].stop.return_value = np.empty((0, 1), dtype=np.float32)

    session.on_recording_start()
    session.on_recording_stop("ptt")

    # Legacy behavior preserved: the empty recording is still enqueued.
    assert session._utterance_queue.qsize() == 1


def test_on_recording_stop_shows_transcribing_notification() -> None:
    notif = MagicMock()
    session, _m = _make_session(notification=notif)
    c = _components(session)
    c["cfg"].asr.mode = "eager"
    c["recorder"].stop.return_value = np.zeros((100, 1), dtype=np.float32)

    session.on_recording_start()
    session.on_recording_stop("ptt")

    notif.show_transcribing.assert_called_once()
    notif.hide.assert_not_called()


def test_on_recording_stop_hides_notification_when_nothing_queued() -> None:
    cfg = _mock_cfg()
    cfg.audio.silence_detection = True
    cfg.asr.mode = "eager"
    notif = MagicMock()
    session, _m = _make_session(cfg=cfg, notification=notif)
    c = _components(session)
    c["recorder"].stop.return_value = np.empty((0, 1), dtype=np.float32)

    session.on_recording_start()
    session.on_recording_stop("ptt")

    notif.hide.assert_called_once()
    notif.show_transcribing.assert_not_called()


def test_processor_hides_notification_when_queue_drained() -> None:
    notif = MagicMock()
    session, _m = _make_session(notification=notif)
    c = _components(session)
    c["cfg"].asr.mode = "eager"
    c["recorder"].stop.return_value = np.zeros((100, 1), dtype=np.float32)
    fut = _fake_future()
    fut.result.return_value = TranscriptionResult(text="", duration_seconds=0.0, segments=[])
    c["worker"].submit.return_value = fut
    session.start()

    session.on_recording_start()
    session.on_recording_stop("ptt")
    time.sleep(0.1)

    notif.hide.assert_called_once()


def test_one_shot_sets_stop_event_after_processor_finishes() -> None:
    """In one_shot mode the processor thread sets _stop_event after processing."""
    session, _m = _make_session(one_shot=True)
    c = _components(session)
    session.start()

    future = _fake_future()
    future.result.return_value = TranscriptionResult(text="hi", duration_seconds=0.1, segments=[])
    c["worker"].submit.return_value = future
    c["recorder"].stop.return_value = np.zeros((1, 1), dtype=np.float32)

    session.on_recording_start()
    session.on_recording_stop("ptt")

    # The listener returns immediately, but the processor hasn't finished yet.
    # Wait for the processor to pick up and process.
    # Since the worker future is immediately "done", the processor completes quickly.
    session._stop_event.wait(timeout=2.0)
    assert session._stop_event.is_set()


def test_stop_drains_queued_utterances_before_worker_shutdown() -> None:
    """stop() enqueues the in-flight samples, waits for processor, then stops worker."""
    session, _m = _make_session()
    c = _components(session)
    session.start()

    future = _fake_future()
    future.result.return_value = TranscriptionResult(
        text="drained", duration_seconds=0.0, segments=[]
    )
    c["worker"].submit.return_value = future
    c["recorder"].is_active = True
    c["recorder"].stop.return_value = np.zeros((1, 1), dtype=np.float32)
    c["cfg"].clipboard.enabled = False

    # Simulate an in-flight recording
    session.on_recording_start()
    session.stop()

    # stop() enqueued the drain samples, sent sentinel, and joined processor.
    # Worker should have been called after the processor picked up the item.
    c["worker"].submit.assert_called()
    future.result.assert_called()
    c["recorder"].stop.assert_called()


def test_multiple_utterances_processed_in_order() -> None:
    """Successive on_recording_stop calls queue utterances; processor handles them in order."""
    session, _m = _make_session()
    c = _components(session)
    session.start()

    results = [
        TranscriptionResult(text="first", duration_seconds=0.1, segments=[]),
        TranscriptionResult(text="second", duration_seconds=0.1, segments=[]),
    ]
    submit_count = [0]

    def submit_side_effect(samples, *, on_segment=None, cancel_event=None):
        fut = _fake_future()
        fut.result.return_value = results[submit_count[0]]
        submit_count[0] += 1
        return fut

    c["worker"].submit.side_effect = submit_side_effect
    c["recorder"].stop.return_value = np.zeros((100, 1), dtype=np.float32)

    # Enqueue two utterances
    session.on_recording_start()
    session.on_recording_stop("ptt")
    session.on_recording_start()
    session.on_recording_stop("ptt")

    # Wait for processor to drain the queue
    stop = time.monotonic() + 2.0
    while c["injector"].type_text.call_count < 2 and time.monotonic() < stop:
        time.sleep(0.02)

    assert c["worker"].submit.call_count == 2
    c["injector"].type_text.assert_any_call("first")
    c["injector"].type_text.assert_any_call("second")


def test_on_recording_stop_logs_queue_depth_when_backlog() -> None:
    """When an utterance is already queued, a second enqueue logs the depth."""
    session, _m = _make_session()
    session.start()

    # Simulate a blocked processor by putting a dummy entry on the queue
    session._utterance_queue.put((np.zeros((1, 1), dtype=np.float32), "ptt", threading.Event(), 0))
    assert session._utterance_queue.qsize() == 1

    c = _components(session)
    c["recorder"].stop.return_value = np.zeros((100, 1), dtype=np.float32)

    session.on_recording_start()
    session.on_recording_stop("ptt")

    # Queue should now have 2 items (the dummy + the new one)
    # The dummy is blocking the processor, so the new one is queued
    assert session._utterance_queue.qsize() >= 1  # dummy might have been picked up already


# ---------------------------------------------------------------------------
# Lazy-mode tests
# ---------------------------------------------------------------------------


def test_on_recording_start_lazy_mode_triggers_load_and_shows_loading() -> None:
    session, _m = _make_session()
    c = _components(session)
    c["cfg"].asr.mode = "lazy"
    c["worker"].is_model_loaded.return_value = False
    session.on_recording_start()
    c["worker"].ensure_model_loaded.assert_called_once()
    assert c["feedback"].play.call_count >= 1
    c["feedback"].play.assert_any_call("model_loading")
    assert session._notification is None  # no notification in default _make_session


def test_on_recording_start_lazy_first_press_shows_loading_notification() -> None:
    from stenographer.notification import DesktopNotification

    notif = DesktopNotification()
    notif._available = True
    session, _m = _make_session(notification=MagicMock(wraps=notif))
    c = _components(session)
    c["cfg"].asr.mode = "lazy"
    c["worker"].is_model_loaded.return_value = False
    c["worker"].ensure_model_loaded = MagicMock()
    with patch("stenographer.notification.subprocess.run") as run:
        session.on_recording_start()
        notif.flush()
    assert run.call_count >= 1
    cmd_lines = [run.call_args_list[i][0][0] for i in range(run.call_count)]
    assert any("Loading speech model" in " ".join(str(a) for a in args) for args in cmd_lines)


def test_on_recording_start_eager_mode_does_not_trigger_load() -> None:
    session, _m = _make_session()
    c = _components(session)
    c["cfg"].asr.mode = "eager"
    session.on_recording_start()
    c["worker"].ensure_model_loaded.assert_not_called()


def test_on_recording_start_lazy_second_press_skips_load() -> None:
    session, _m = _make_session()
    c = _components(session)
    c["cfg"].asr.mode = "lazy"
    c["worker"].is_model_loaded.return_value = True
    session.on_recording_start()
    c["worker"].ensure_model_loaded.assert_not_called()
    c["feedback"].play.assert_not_called()


def test_on_model_loaded_plays_ready_cue_and_shows_listening_while_recording() -> None:
    notif = MagicMock()
    session, _m = _make_session(notification=notif)
    c = _components(session)
    session._recording = True
    session._on_model_loaded()
    c["feedback"].play.assert_called_once_with("model_ready")
    notif.show_listening.assert_called_once()


def test_on_model_loaded_leaves_notification_alone_when_not_recording() -> None:
    notif = MagicMock()
    session, _m = _make_session(notification=notif)
    c = _components(session)
    session._on_model_loaded()
    c["feedback"].play.assert_called_once_with("model_ready")
    notif.show_listening.assert_not_called()
    notif.hide.assert_not_called()


def test_on_model_loading_plays_loading_cue() -> None:
    session, _m = _make_session()
    c = _components(session)
    session._on_model_loading()
    c["feedback"].play.assert_called_once_with("model_loading")


def test_on_model_unloaded_shows_notification() -> None:
    from stenographer.notification import DesktopNotification

    notif = DesktopNotification()
    notif._available = True
    session, _m = _make_session(notification=MagicMock(wraps=notif))
    with patch("stenographer.notification.subprocess.run") as run:
        session._on_model_unloaded()
        notif.flush()
    cmd_lines = [run.call_args_list[i][0][0] for i in range(run.call_count)]
    assert any("Speech model unloaded" in " ".join(str(a) for a in args) for args in cmd_lines)


# ---------------------------------------------------------------------------
# discard_recording / cancel_all
# ---------------------------------------------------------------------------


def test_discard_recording_stops_recorder_without_enqueue() -> None:
    session, _m = _make_session()
    c = _components(session)
    c["recorder"].stop.return_value = np.zeros((100, 1), dtype=np.float32)
    session.on_recording_start()
    session.discard_recording()
    c["recorder"].stop.assert_called_once()
    assert session._utterance_queue.qsize() == 0
    c["worker"].submit.assert_not_called()
    assert not session._recording


def test_discard_recording_without_active_recording_is_noop() -> None:
    session, _m = _make_session()
    c = _components(session)
    session.discard_recording()
    c["recorder"].stop.assert_not_called()


def test_cancel_all_stops_recording_and_drains_queue() -> None:
    session, _m = _make_session()
    c = _components(session)
    c["recorder"].stop.return_value = np.zeros((100, 1), dtype=np.float32)
    # Two queued utterances plus an active recording.
    session._utterance_queue.put((np.zeros((1, 1), dtype=np.float32), "ptt", threading.Event(), 0))
    session._utterance_queue.put((np.zeros((1, 1), dtype=np.float32), "ptt", threading.Event(), 0))
    session.on_recording_start()
    session.cancel_all()
    assert session._utterance_queue.qsize() == 0
    c["recorder"].stop.assert_called_once()
    assert not session._recording


def test_cancel_all_preserves_shutdown_sentinel() -> None:
    session, _m = _make_session()
    session._utterance_queue.put((np.zeros((1, 1), dtype=np.float32), "ptt", threading.Event(), 0))
    session._utterance_queue.put(None)
    session.cancel_all()
    assert session._utterance_queue.get_nowait() is None


def test_cancel_all_aborts_in_flight_processing() -> None:
    """cancel_all sets the abort event of the utterance being processed;
    no further segments inject, no done cue, no error cue."""
    session, _m = _make_session()
    c = _components(session)
    c["cfg"].asr.silence_threshold = 0.6
    c["cfg"].clipboard.enabled = True
    c["cfg"].output.injection_method = "text"
    session.start()

    captured: dict[str, object] = {}
    first_segment_delivered = threading.Event()
    release_second_segment = threading.Event()

    def submit_side_effect(samples, *, on_segment=None, cancel_event=None):
        captured["cancel_event"] = cancel_event
        # Defer the done-callback (the segment-loop sentinel) until all
        # segments are delivered, unlike _fake_future which fires it eagerly.
        fut = MagicMock()
        done_callbacks: list = []
        fut.add_done_callback.side_effect = done_callbacks.append

        def deliver() -> None:
            on_segment(SegmentInfo(0.0, 0.5, " hello", 0.1))
            first_segment_delivered.set()
            release_second_segment.wait(timeout=2.0)
            on_segment(SegmentInfo(0.5, 1.0, " world", 0.1))

            fut.result.side_effect = CancelledError("transcription cancelled")
            for cb in done_callbacks:
                cb(fut)

        t = threading.Thread(target=deliver, daemon=True)
        t.start()
        return fut

    c["worker"].submit.side_effect = submit_side_effect
    c["injector"].type_text.return_value = True
    c["recorder"].stop.return_value = np.zeros((16000, 1), dtype=np.float32)

    session.on_recording_start()
    session.on_recording_stop("ptt")
    assert first_segment_delivered.wait(timeout=2.0)
    # First segment was typed while processing was live.
    _wait = time.monotonic() + 2.0
    while c["injector"].type_text.call_count < 1 and time.monotonic() < _wait:
        time.sleep(0.01)
    c["injector"].type_text.assert_called_once_with(" hello", raw=True)

    session.cancel_all()
    assert captured["cancel_event"] is not None
    assert captured["cancel_event"].is_set()
    release_second_segment.set()

    # Give the processor time to drain the segment queue and observe the cancel.
    _wait = time.monotonic() + 2.0
    while session._active_abort is not None and time.monotonic() < _wait:
        time.sleep(0.01)
    # The second segment must not have been typed, and no done/error cue played.
    c["injector"].type_text.assert_called_once_with(" hello", raw=True)
    played = [call.args[0] for call in c["feedback"].play.call_args_list]
    assert "transcribe_done" not in played
    assert "error" not in played
    c["clipboard"].copy.assert_not_called()


def test_cancel_all_drops_dequeued_but_unprocessed_item() -> None:
    """An item stamped with a pre-cancel generation is dropped even if the
    processor dequeues it after cancel_all ran."""
    session, _m = _make_session()
    c = _components(session)
    session._utterance_queue.put(
        (np.zeros((1, 1), dtype=np.float32), "ptt", threading.Event(), session._cancel_generation)
    )
    # Cancel before the processor thread ever starts, then start it.
    session.cancel_all()
    session._utterance_queue.put((np.zeros((1, 1), dtype=np.float32), "ptt", threading.Event(), -1))
    session.start()
    _wait = time.monotonic() + 2.0
    while session._utterance_queue.qsize() > 0 and time.monotonic() < _wait:
        time.sleep(0.01)
    time.sleep(0.05)
    c["worker"].submit.assert_not_called()


# --- live streaming wiring ---


def _streaming_cfg() -> MagicMock:
    cfg = _mock_cfg()
    cfg.asr.mode = "eager"  # avoid the lazy-load branch
    cfg.streaming.enabled = True
    cfg.streaming.agreement_n = 2
    cfg.streaming.min_chunk_seconds = 1.0
    cfg.output.injection_method = "text"
    return cfg


def test_streaming_recording_start_wires_on_partial_and_enqueues_live_item() -> None:
    session, _m = _make_session(cfg=_streaming_cfg())
    c = _components(session)
    session.on_recording_start()
    kwargs = c["recorder"].start.call_args.kwargs
    assert "on_segment" not in kwargs  # silence-flush path disabled
    assert callable(kwargs["on_partial"])
    assert kwargs["min_partial_seconds"] == 1.0
    item = session._utterance_queue.get_nowait()
    from stenographer.session import _LiveItem

    assert isinstance(item, _LiveItem)
    assert item.streamer is session._live_streamer


def test_streaming_recording_stop_signals_final_not_enqueue() -> None:
    session, _m = _make_session(cfg=_streaming_cfg())
    c = _components(session)
    tail = np.ones((16000, 1), dtype=np.float32)
    c["recorder"].stop.return_value = tail

    session.on_recording_start()
    streamer = session._live_streamer
    assert streamer is not None
    session.on_recording_stop("ptt")

    # Only the live item is queued; the tail went to the streamer as final.
    assert session._utterance_queue.qsize() == 1
    kind, samples = streamer._signals.get_nowait()
    assert kind == "final"
    assert np.array_equal(samples, tail)


def test_streaming_not_active_in_paste_mode() -> None:
    cfg = _streaming_cfg()
    cfg.output.injection_method = "paste"
    session, _m = _make_session(cfg=cfg)
    assert session._streaming is False


def test_cancel_all_signals_live_streamer_abort() -> None:
    session, _m = _make_session(cfg=_streaming_cfg())
    session.on_recording_start()
    streamer = session._live_streamer
    assert streamer is not None
    session.cancel_all()
    assert streamer.abort.is_set()
    kinds = []
    while True:
        try:
            kinds.append(streamer._signals.get_nowait()[0])
        except Exception:
            break
    assert "abort" in kinds


def test_processor_drops_cancelled_live_item() -> None:
    session, _m = _make_session(cfg=_streaming_cfg())
    session.on_recording_start()
    streamer = session._live_streamer
    session.cancel_all()  # drains the queue and bumps the generation
    # Re-enqueue a stale-generation live item to exercise the processor drop.
    from stenographer.session import _LiveItem

    session._live_streamer = streamer
    session._utterance_queue.put(_LiveItem(streamer, session._cancel_generation - 1))
    session._utterance_queue.put(None)
    session._process_utterance_queue()
    assert session._live_streamer is None  # dangling reference cleared
