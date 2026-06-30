# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for :mod:`stenographer.session`."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import numpy as np

from stenographer.asr.model import SegmentInfo, TranscriptionResult
from stenographer.session import Session


def _make_components() -> dict[str, MagicMock]:
    return {
        "cfg": MagicMock(),
        "caps": MagicMock(has_wtype=True, has_wl_copy=True),
        "listener": MagicMock(),
        "recorder": MagicMock(),
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
        one_shot=one_shot,
    )
    return session, components


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


def test_on_recording_stop_submits_to_worker_and_outputs() -> None:
    session, _m = _make_session()
    c = _components(session)
    c["cfg"].clipboard.enabled = True
    future = MagicMock()
    future.result.return_value = TranscriptionResult(
        text="hello world", duration_seconds=0.5, segments=[]
    )
    c["worker"].submit.return_value = future
    c["recorder"].stop.return_value = np.zeros((16000, 1), dtype=np.float32)
    session.on_recording_start()
    session.on_recording_stop("ptt")
    c["recorder"].stop.assert_called_once()
    c["worker"].submit.assert_called_once()
    future.result.assert_called_once()
    c["injector"].type_text.assert_called_once_with("hello world")
    c["clipboard"].copy.assert_called_once_with("hello world")


def test_on_recording_stop_empty_transcript_skips_output() -> None:
    session, _m = _make_session()
    c = _components(session)
    c["cfg"].clipboard.enabled = True
    future = MagicMock()
    future.result.return_value = TranscriptionResult(text="   ", duration_seconds=0.0, segments=[])
    c["worker"].submit.return_value = future
    c["recorder"].stop.return_value = np.zeros((1, 1), dtype=np.float32)
    session.on_recording_start()
    session.on_recording_stop("ptt")
    c["injector"].type_text.assert_not_called()
    c["clipboard"].copy.assert_not_called()


def test_on_toggle_off_invokes_recording_stop() -> None:
    session, _m = _make_session()
    c = _components(session)
    future = MagicMock()
    future.result.return_value = TranscriptionResult(text="hi", duration_seconds=0.1, segments=[])
    c["worker"].submit.return_value = future
    c["recorder"].stop.return_value = np.zeros((1, 1), dtype=np.float32)
    session.on_recording_start()
    c["recorder"].start.reset_mock()
    session.on_toggle_off()
    c["recorder"].stop.assert_called_once()
    c["worker"].submit.assert_called_once()


def test_one_shot_stops_after_first_utterance() -> None:
    session, _m = _make_session(one_shot=True)
    c = _components(session)
    future = MagicMock()
    future.result.return_value = TranscriptionResult(text="hi", duration_seconds=0.1, segments=[])
    c["worker"].submit.return_value = future
    c["recorder"].stop.return_value = np.zeros((1, 1), dtype=np.float32)
    session.on_recording_start()
    session.on_recording_stop("ptt")
    assert session.stop_event.is_set()


def test_run_returns_when_stop_is_called() -> None:
    session, _m = _make_session()
    thread = threading.Thread(target=session.run, daemon=True)
    thread.start()
    time.sleep(0.05)
    assert thread.is_alive()
    session.stop()
    thread.join(timeout=2.0)
    assert not thread.is_alive()


def test_stop_drains_in_flight_recording() -> None:
    session, _m = _make_session()
    c = _components(session)
    future = MagicMock()
    future.result.return_value = TranscriptionResult(
        text="drained", duration_seconds=0.0, segments=[]
    )
    c["worker"].submit.return_value = future
    c["recorder"].is_active = True
    c["recorder"].stop.return_value = np.zeros((1, 1), dtype=np.float32)
    c["cfg"].clipboard.enabled = False
    session.on_recording_start()
    session.stop()
    c["worker"].submit.assert_called()
    future.result.assert_called()
    c["recorder"].stop.assert_called()


def test_injector_skipped_when_wtype_unavailable() -> None:
    session, _m = _make_session()
    c = _components(session)
    c["caps"].has_wtype = False
    c["cfg"].clipboard.enabled = True
    future = MagicMock()
    future.result.return_value = TranscriptionResult(text="hi", duration_seconds=0.0, segments=[])
    c["worker"].submit.return_value = future
    c["recorder"].stop.return_value = np.zeros((1, 1), dtype=np.float32)
    session.on_recording_start()
    session.on_recording_stop("ptt")
    c["injector"].type_text.assert_not_called()
    c["clipboard"].copy.assert_called_once()


def test_clipboard_skipped_when_disabled() -> None:
    session, _m = _make_session()
    c = _components(session)
    c["cfg"].clipboard.enabled = False
    future = MagicMock()
    future.result.return_value = TranscriptionResult(text="hi", duration_seconds=0.0, segments=[])
    c["worker"].submit.return_value = future
    c["recorder"].stop.return_value = np.zeros((1, 1), dtype=np.float32)
    session.on_recording_start()
    session.on_recording_stop("ptt")
    c["clipboard"].copy.assert_not_called()


def test_streaming_injects_partial_segments_and_skips_duplicate_final() -> None:
    session, _m = _make_session()
    c = _components(session)
    c["cfg"].clipboard.enabled = True

    result = TranscriptionResult(text="hello world", duration_seconds=1.0, segments=[])
    future = MagicMock()
    future.done.return_value = True
    future.result.return_value = result

    def submit_side_effect(samples, *, on_segment=None):
        if on_segment is not None:
            on_segment(SegmentInfo(0.0, 0.5, " hello", 0.1))
            on_segment(SegmentInfo(0.5, 1.0, " world", 0.1))
        return future

    c["worker"].submit.side_effect = submit_side_effect
    c["recorder"].stop.return_value = np.zeros((16000, 1), dtype=np.float32)

    session.on_recording_start()
    session.on_recording_stop("ptt")

    c["injector"].type_text.assert_any_call(" hello", raw=True)
    c["injector"].type_text.assert_any_call(" world", raw=True)
    assert c["injector"].type_text.call_count == 2
    c["clipboard"].copy.assert_called_once_with("hello world")
