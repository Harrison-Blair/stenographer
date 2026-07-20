# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for session orchestration and the final-output boundary."""

from __future__ import annotations

import dataclasses
import threading
from unittest.mock import MagicMock

import numpy as np

from stenographer.asr.model import SegmentInfo, TranscriptionResult
from stenographer.config import Config
from stenographer.session import Session, _LiveItem


def _cfg(*, mode: str = "type", clipboard: bool = True) -> Config:
    cfg = Config.defaults()
    return dataclasses.replace(
        cfg,
        asr=dataclasses.replace(cfg.asr, mode="eager"),
        output=dataclasses.replace(cfg.output, injection_method=mode),
        clipboard=dataclasses.replace(cfg.clipboard, enabled=clipboard),
    )


def _make_session(
    *,
    cfg: Config | None = None,
    notification: MagicMock | None = None,
) -> tuple[Session, dict[str, MagicMock]]:
    components = {
        "caps": MagicMock(has_paste_trigger=True, has_clipboard=True),
        "listener": MagicMock(),
        "recorder": MagicMock(is_active=False),
        "worker": MagicMock(),
        "feedback": MagicMock(),
        "injector": MagicMock(),
        "clipboard": MagicMock(),
    }
    components["clipboard"].copy.return_value = True
    components["injector"].type_text.return_value = True
    components["injector"].paste.return_value = True
    components["worker"].is_model_loaded.return_value = True
    session = Session(
        cfg=cfg or _cfg(),
        capabilities=components["caps"],
        listener=components["listener"],
        recorder=components["recorder"],
        worker=components["worker"],
        feedback=components["feedback"],
        injector=components["injector"],
        clipboard=components["clipboard"],
        notification=notification,
    )
    return session, components


def test_recording_always_uses_incremental_partial_callback_in_type_mode() -> None:
    session, components = _make_session(cfg=_cfg(mode="type"))
    session.on_recording_start()

    kwargs = components["recorder"].start.call_args.kwargs
    assert callable(kwargs["on_partial"])
    assert kwargs["min_partial_seconds"] == session._cfg.incremental.min_chunk_seconds
    assert "on_segment" not in kwargs
    item = session._utterance_queue.get_nowait()
    assert isinstance(item, _LiveItem)


def test_recording_always_uses_incremental_partial_callback_in_clipboard_paste_mode() -> None:
    session, components = _make_session(cfg=_cfg(mode="clipboard_paste"))
    session.on_recording_start()
    assert callable(components["recorder"].start.call_args.kwargs["on_partial"])
    assert isinstance(session._utterance_queue.get_nowait(), _LiveItem)


def test_recording_stop_signals_final_without_queuing_batch_item() -> None:
    session, components = _make_session()
    samples = np.ones((16000, 1), dtype=np.float32)
    components["recorder"].stop.return_value = samples
    session.on_recording_start()
    driver = session._recording_streamer
    assert driver is not None

    session.on_recording_stop("ptt")

    assert session._utterance_queue.qsize() == 1
    kind, final_samples = driver._signals.get_nowait()
    assert kind == "final"
    assert np.array_equal(final_samples, samples)


def test_type_mode_delivers_once_and_optionally_copies() -> None:
    session, components = _make_session(cfg=_cfg(mode="type", clipboard=True))
    driver = MagicMock()
    driver.abort = threading.Event()
    driver.run.return_value = "Hello world "

    session._run_incremental(driver, session._preview_generation)

    components["injector"].type_text.assert_called_once_with("Hello world ", raw=True)
    components["injector"].paste.assert_not_called()
    components["clipboard"].copy.assert_called_once_with("Hello world ", primary=True)
    components["feedback"].play.assert_called_once_with("transcribe_done")


def test_type_mode_respects_disabled_clipboard() -> None:
    session, components = _make_session(cfg=_cfg(mode="type", clipboard=False))
    assert session._deliver_final("Hello ")
    components["injector"].type_text.assert_called_once_with("Hello ", raw=True)
    components["clipboard"].copy.assert_not_called()


def test_type_mode_without_wtype_counts_clipboard_copy_as_delivery() -> None:
    session, components = _make_session(cfg=_cfg(mode="type", clipboard=True))
    components["caps"].has_paste_trigger = False

    assert session._deliver_final("Hello world ")

    components["injector"].type_text.assert_not_called()
    components["clipboard"].copy.assert_called_once_with("Hello world ", primary=True)


def test_type_mode_without_wtype_plays_success_cue_not_error() -> None:
    session, components = _make_session(cfg=_cfg(mode="type", clipboard=True))
    components["caps"].has_paste_trigger = False
    driver = MagicMock()
    driver.abort = threading.Event()
    driver.run.return_value = "Hello world "

    session._run_incremental(driver, session._preview_generation)

    components["feedback"].play.assert_called_once_with("transcribe_done")


def test_type_mode_reports_failure_when_nothing_reached_the_user() -> None:
    session, components = _make_session(cfg=_cfg(mode="type", clipboard=True))
    components["caps"].has_paste_trigger = False
    components["clipboard"].copy.return_value = False

    assert not session._deliver_final("Hello ")


def test_clipboard_paste_delivers_with_two_selections_then_one_chord() -> None:
    session, components = _make_session(cfg=_cfg(mode="clipboard_paste"))

    assert session._deliver_final("Hello world ")

    components["clipboard"].copy.assert_called_once_with("Hello world ", primary=True)
    components["injector"].type_text.assert_not_called()
    components["injector"].paste.assert_called_once_with()


def test_clipboard_copy_failure_never_fires_paste_chord() -> None:
    session, components = _make_session(cfg=_cfg(mode="clipboard_paste"))
    components["clipboard"].copy.return_value = False

    assert not session._deliver_final("Hello ")

    components["clipboard"].copy.assert_called_once_with("Hello ", primary=True)
    components["injector"].paste.assert_not_called()


def test_output_max_chars_applied_once_before_both_delivery_modes() -> None:
    type_cfg = dataclasses.replace(
        _cfg(mode="type"),
        output=dataclasses.replace(_cfg(mode="type").output, max_chars=5),
    )
    type_session, type_components = _make_session(cfg=type_cfg)
    assert type_session._deliver_final("abcdefgh")
    type_components["injector"].type_text.assert_called_once_with("abcde", raw=True)
    # The cap bounds what is typed, not what is recoverable: the clipboard is
    # the only place the truncated tail still exists.
    type_components["clipboard"].copy.assert_called_once_with("abcdefgh", primary=True)

    paste_cfg = dataclasses.replace(
        _cfg(mode="clipboard_paste"),
        output=dataclasses.replace(_cfg(mode="clipboard_paste").output, max_chars=5),
    )
    paste_session, paste_components = _make_session(cfg=paste_cfg)
    assert paste_session._deliver_final("abcdefgh")
    paste_components["clipboard"].copy.assert_called_once_with("abcde", primary=True)


def test_cancelled_or_failed_incremental_run_has_no_delivery() -> None:
    session, components = _make_session()
    cancelled = MagicMock()
    cancelled.abort = threading.Event()
    cancelled.abort.set()
    cancelled.run.return_value = None
    session._run_incremental(cancelled, 0)

    failed = MagicMock()
    failed.abort = threading.Event()
    failed.run.side_effect = RuntimeError("decode failed")
    session._run_incremental(failed, 0)

    components["injector"].type_text.assert_not_called()
    components["injector"].paste.assert_not_called()
    components["clipboard"].copy.assert_not_called()


def test_empty_incremental_result_plays_error_without_delivery() -> None:
    session, components = _make_session()
    driver = MagicMock()
    driver.abort = threading.Event()
    driver.run.return_value = ""
    session._run_incremental(driver, 0)
    components["injector"].type_text.assert_not_called()
    components["feedback"].play.assert_called_once_with("error")


def test_preview_updates_are_generation_guarded() -> None:
    notification = MagicMock()
    session, _components = _make_session(notification=notification)
    session._preview_generation = 4

    session._publish_preview(3, "old", " tail")
    session._publish_preview(4, "new", " words")

    notification.show_preview.assert_called_once_with("new", " words")


def test_old_utterance_cannot_clear_new_recordings_preview() -> None:
    notification = MagicMock()
    session, components = _make_session(notification=notification)
    old = MagicMock()
    old.abort = threading.Event()
    old.run.return_value = "Old "
    session._preview_generation = 2

    session._run_incremental(old, preview_generation=1)

    notification.clear_preview.assert_not_called()
    components["injector"].type_text.assert_called_once()


def test_new_recording_clears_replaced_preview_before_listening() -> None:
    notification = MagicMock()
    session, _components = _make_session(notification=notification)
    session.on_recording_start()
    notification.clear_preview.assert_called_once()
    notification.show_listening.assert_called_once()


def test_preview_consumer_failure_does_not_block_final_output() -> None:
    notification = MagicMock()
    notification.show_preview.side_effect = RuntimeError("overlay pipe failed")
    session, components = _make_session(notification=notification)
    session._preview_generation = 1
    session._publish_preview(1, "Hello", " world")

    assert session._deliver_final("Hello world ")
    components["injector"].type_text.assert_called_once()


def test_cancel_invalidates_and_clears_preview() -> None:
    notification = MagicMock()
    session, _components = _make_session(notification=notification)
    session._preview_generation = 3
    session.cancel_all()
    assert session._preview_generation == 4
    notification.clear_preview.assert_called_once()
    notification.hide.assert_called_once()


def test_cancel_hides_indicator_even_if_clearing_preview_raises() -> None:
    notification = MagicMock()
    notification.clear_preview.side_effect = RuntimeError("overlay pipe failed")
    session, _components = _make_session(notification=notification)

    session.cancel_all()

    notification.hide.assert_called_once()


def test_indicator_failure_at_recording_start_strands_nothing() -> None:
    notification = MagicMock()
    notification.show_listening.side_effect = RuntimeError("overlay pipe failed")
    session, components = _make_session(notification=notification)
    components["recorder"].is_active = True

    session.on_recording_start()

    assert not session._recording
    assert session._recording_streamer is None
    components["recorder"].stop.assert_called_once()
    item = session._utterance_queue.get_nowait()
    assert isinstance(item, _LiveItem)
    # The queued driver must be woken, else the processor thread blocks on its
    # signal queue forever and every later utterance is never transcribed.
    assert item.streamer.abort.is_set()
    assert item.streamer._signals.get_nowait()[0] == "abort"


def test_discard_aborts_only_current_recording_and_clears_preview() -> None:
    notification = MagicMock()
    session, components = _make_session(notification=notification)
    components["recorder"].stop.return_value = np.empty((0, 1), dtype=np.float32)
    session.on_recording_start()
    driver = session._recording_streamer
    assert driver is not None

    session.discard_recording()

    assert driver.abort.is_set()
    assert driver._signals.get_nowait()[0] == "abort"
    assert notification.clear_preview.call_count == 2  # replacement clear + discard clear


def test_other_source_cannot_stop_recording() -> None:
    session, components = _make_session()
    session.on_recording_start(source="dictate")
    session.on_recording_stop("ptt", source="prompt")  # type: ignore[arg-type]
    components["recorder"].stop.assert_not_called()


def test_batch_process_performs_no_partial_output_and_one_final_delivery() -> None:
    session, components = _make_session()
    future = MagicMock()
    future.result.return_value = TranscriptionResult(
        text="hello world",
        duration_seconds=1.0,
        segments=[
            SegmentInfo(0.0, 0.5, " hello", 0.1),
            SegmentInfo(0.5, 1.0, " world", 0.1),
        ],
    )
    components["worker"].submit.return_value = future

    session._process(np.ones((16000, 1), dtype=np.float32), "ptt", threading.Event())

    components["worker"].submit.assert_called_once()
    components["injector"].type_text.assert_called_once_with("Hello world ", raw=True)
    components["clipboard"].copy.assert_called_once_with("Hello world ", primary=True)


def test_stop_closes_components_and_indicator() -> None:
    notification = MagicMock()
    session, components = _make_session(notification=notification)
    session.stop()
    components["listener"].stop.assert_called_once()
    components["worker"].cancel.assert_called_once()
    components["worker"].stop.assert_called_once()
    components["feedback"].close.assert_called_once()
    components["injector"].close.assert_called_once()
    components["clipboard"].close.assert_called_once()
    notification.hide.assert_called_once()
    notification.flush.assert_called_once()
