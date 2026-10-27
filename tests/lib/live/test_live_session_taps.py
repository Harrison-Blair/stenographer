# SPDX-License-Identifier: GPL-3.0-or-later
"""Speech flags and block listeners of a live session, without audio hardware."""

from __future__ import annotations

import logging
import threading
import time

import numpy as np

from tests.lib.live.test_live_session import _make_session


def _speech(session):
    return session.speech_detected


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def test_speech_flag_follows_the_source_segmenter_after_each_block(monkeypatch, tmp_path):
    session, _writer, _worker, _system, recorder, segmenters = _make_session(monkeypatch, tmp_path)
    mic_segmenter = next(s for s in segmenters if s.source == "mic")

    assert _speech(session) == {"mic": False, "system": False}
    mic_segmenter.speech_detected = True
    assert _speech(session)["mic"] is False
    recorder.emit(3)
    assert _speech(session) == {"mic": True, "system": False}
    mic_segmenter.speech_detected = False
    recorder.emit(3)
    assert _speech(session)["mic"] is False
    session.stop()


def test_speech_flag_is_false_when_the_source_is_off_paused_or_stopped(monkeypatch, tmp_path):
    session, _writer, _worker, system, recorder, segmenters = _make_session(monkeypatch, tmp_path)
    for segmenter in segmenters:
        segmenter.speech_detected = True
    recorder.emit(3)
    system.emit(3)
    assert _speech(session) == {"mic": True, "system": True}

    session.toggle("mic")
    assert _speech(session) == {"mic": False, "system": True}

    session.pause()
    assert _speech(session) == {"mic": False, "system": False}

    session.resume()
    assert _speech(session) == {"mic": False, "system": False}
    session.stop()
    assert _speech(session) == {"mic": False, "system": False}


def test_block_listener_gets_read_only_copies_after_the_write(monkeypatch, tmp_path):
    session, writer, _worker, system, recorder, _segmenters = _make_session(monkeypatch, tmp_path)
    received = []
    written_before = []

    def listener(source, samples):
        written_before.append(
            any(name == source and np.array_equal(audio, samples) for name, audio in writer.audio)
        )
        received.append((source, samples))

    mutated = threading.Event()
    session.add_block_listener(lambda _source, _samples: mutated.wait(2))
    session.add_block_listener(listener)
    block = np.asarray([3.0, 0.5], dtype=np.float32)
    recorder.on_block(block, 16000, 1)
    block[:] = 9.0
    mutated.set()
    system.emit(4)

    assert _wait_until(lambda: len(received) == 2)
    assert received[0][0] == "mic"
    assert received[0][1].tolist() == [3.0, 0.5]
    assert not received[0][1].flags.writeable
    assert received[1][0] == "system"
    assert written_before == [True, True]
    session.stop()


def test_removing_a_block_listener_stops_delivery(monkeypatch, tmp_path):
    session, _writer, _worker, _system, recorder, _segmenters = _make_session(monkeypatch, tmp_path)
    kept, removed = [], []
    session.add_block_listener(lambda source, samples: kept.append(source))
    remove = session.add_block_listener(lambda source, samples: removed.append(source))
    recorder.emit(3)
    assert _wait_until(lambda: len(kept) == 1 and len(removed) == 1)

    remove()
    recorder.emit(3)
    assert _wait_until(lambda: len(kept) == 2)
    time.sleep(0.05)
    assert removed == ["mic"]
    session.stop()


def test_a_slow_listener_does_not_delay_accept_or_pause(monkeypatch, tmp_path):
    session, _writer, _worker, _system, recorder, _segmenters = _make_session(monkeypatch, tmp_path)
    calls = []

    def slow(source, _samples):
        calls.append(source)
        time.sleep(0.4)

    session.add_block_listener(slow)
    started = time.monotonic()
    for _ in range(5):
        recorder.emit(3)
    assert time.monotonic() - started < 0.1
    assert _wait_until(lambda: calls)
    started = time.monotonic()
    session.pause()
    assert time.monotonic() - started < 0.1
    session.stop()


def test_stop_waits_at_most_half_a_second_for_a_held_listener(monkeypatch, tmp_path):
    session, _writer, _worker, _system, recorder, _segmenters = _make_session(monkeypatch, tmp_path)
    release = threading.Event()
    entered = threading.Event()
    calls = []

    def held(source, _samples):
        calls.append(source)
        entered.set()
        release.wait(5)

    session.add_block_listener(held)
    for _ in range(3):
        recorder.emit(3)
    assert entered.wait(2)

    started = time.monotonic()
    session.stop()
    assert time.monotonic() - started < 0.6
    thread = session._block_thread
    assert thread.daemon
    assert thread.is_alive()

    release.set()
    thread.join(2)
    assert not thread.is_alive()
    assert calls == ["mic"]


def test_each_session_has_its_own_delivery_thread(monkeypatch, tmp_path):
    first, *_ = _make_session(monkeypatch, tmp_path / "a")
    second, *_ = _make_session(monkeypatch, tmp_path / "b")
    first.add_block_listener(lambda *_args: None)
    second.add_block_listener(lambda *_args: None)

    assert first._block_thread is not second._block_thread
    first.stop()
    second.stop()
    assert not first._block_thread.is_alive()
    assert not second._block_thread.is_alive()


def test_a_full_queue_drops_new_blocks_and_counts_them(monkeypatch, tmp_path):
    session, _writer, _worker, _system, recorder, _segmenters = _make_session(monkeypatch, tmp_path)
    release = threading.Event()
    entered = threading.Event()
    received = []

    def held(_source, samples):
        entered.set()
        release.wait(5)
        received.append(float(samples[0]))

    session.add_block_listener(held)
    recorder.emit(1)
    assert entered.wait(2)
    for value in range(2, 2 + 32 + 3):
        recorder.emit(value)

    assert session.dropped_blocks == 3
    release.set()
    assert _wait_until(lambda: len(received) == 33)
    assert received == [float(value) for value in range(1, 34)]
    session.stop()


def test_a_raising_listener_is_logged_without_its_message(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    session, _writer, _worker, _system, recorder, _segmenters = _make_session(monkeypatch, tmp_path)
    marker = "MARKER-7f3a-audio-detail"
    received = []

    def raising(_source, _samples):
        raise RuntimeError(marker)

    session.add_block_listener(raising)
    session.add_block_listener(lambda source, _samples: received.append(source))
    recorder.emit(3)
    recorder.emit(3)

    assert _wait_until(lambda: len(received) == 2)
    assert recorder.running
    assert any("block_listener_failed" in record.getMessage() for record in caplog.records)
    for record in caplog.records:
        assert marker not in record.getMessage()
        assert record.exc_info is None or marker not in str(record.exc_info[1])
    assert marker not in caplog.text
    session.stop()
