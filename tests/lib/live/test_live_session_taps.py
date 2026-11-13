# SPDX-License-Identifier: GPL-3.0-or-later
"""Speech flags and block listeners of a live session, without audio hardware."""

from __future__ import annotations

import logging
import threading
import time

import numpy as np

from tests.lib.live.test_live_session import _make_session
from tests.support import wait_until as _wait


def wait_until(predicate, timeout=2.0):
    return _wait(predicate, timeout)


def test_speech_flag_follows_the_source_segmenter_after_each_block(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path)
    mic_segmenter = next(s for s in rig.segmenters if s.source == "mic")

    assert rig.session.speech_detected == {"mic": False, "system": False}
    mic_segmenter.speech_detected = True
    assert rig.session.speech_detected["mic"] is False
    rig.recorder.emit(3)
    assert rig.session.speech_detected == {"mic": True, "system": False}
    mic_segmenter.speech_detected = False
    rig.recorder.emit(3)
    assert rig.session.speech_detected["mic"] is False
    rig.session.stop()


def test_speech_flag_is_false_when_the_source_is_off_paused_or_stopped(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path)
    for segmenter in rig.segmenters:
        segmenter.speech_detected = True
    rig.recorder.emit(3)
    rig.system.emit(3)
    assert rig.session.speech_detected == {"mic": True, "system": True}

    rig.session.toggle("mic")
    assert rig.session.speech_detected == {"mic": False, "system": True}

    rig.session.pause()
    assert rig.session.speech_detected == {"mic": False, "system": False}

    rig.session.resume()
    assert rig.session.speech_detected == {"mic": False, "system": False}
    rig.session.stop()
    assert rig.session.speech_detected == {"mic": False, "system": False}


def test_block_listener_gets_read_only_copies_after_the_write(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path)
    received = []
    written_before = []

    def listener(source, samples):
        written_before.append(
            any(
                name == source and np.array_equal(audio, samples)
                for name, audio in rig.writer.audio
            )
        )
        received.append((source, samples))

    mutated = threading.Event()
    rig.session.add_block_listener(lambda _source, _samples: mutated.wait(2))
    rig.session.add_block_listener(listener)
    block = np.asarray([3.0, 0.5], dtype=np.float32)
    rig.recorder.on_block(block)
    block[:] = 9.0
    mutated.set()
    rig.system.emit(4)

    assert wait_until(lambda: len(received) == 2)
    assert received[0][0] == "mic"
    assert received[0][1].tolist() == [3.0, 0.5]
    assert not received[0][1].flags.writeable
    assert received[1][0] == "system"
    assert written_before == [True, True]
    rig.session.stop()


def test_removing_a_block_listener_stops_delivery(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path)
    kept, removed = [], []
    rig.session.add_block_listener(lambda source, samples: kept.append(source))
    remove = rig.session.add_block_listener(lambda source, samples: removed.append(source))
    rig.recorder.emit(3)
    assert wait_until(lambda: len(kept) == 1 and len(removed) == 1)

    remove()
    rig.recorder.emit(3)
    assert wait_until(lambda: len(kept) == 2)
    time.sleep(0.05)
    assert removed == ["mic"]
    rig.session.stop()


def test_a_slow_listener_does_not_delay_accept_or_pause(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path)
    calls = []

    def slow(source, _samples):
        calls.append(source)
        time.sleep(2.0)

    rig.session.add_block_listener(slow)
    started = time.monotonic()
    for _ in range(5):
        rig.recorder.emit(3)
    assert time.monotonic() - started < 1.0
    assert wait_until(lambda: calls)
    started = time.monotonic()
    rig.session.pause()
    assert time.monotonic() - started < 1.0
    rig.session.stop()


def test_stop_waits_at_most_half_a_second_for_a_held_listener(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path)
    release = threading.Event()
    entered = threading.Event()
    calls = []

    def held(source, _samples):
        calls.append(source)
        entered.set()
        release.wait(5)

    rig.session.add_block_listener(held)
    for _ in range(3):
        rig.recorder.emit(3)
    assert entered.wait(2)

    started = time.monotonic()
    rig.session.stop()
    assert time.monotonic() - started < 2.0
    thread = rig.session._block_thread
    assert thread.daemon
    assert thread.is_alive()

    release.set()
    thread.join(2)
    assert not thread.is_alive()
    assert calls == ["mic"]


def test_each_session_has_its_own_delivery_thread(monkeypatch, tmp_path):
    first = _make_session(monkeypatch, tmp_path / "a").session
    second = _make_session(monkeypatch, tmp_path / "b").session
    first.add_block_listener(lambda *_args: None)
    second.add_block_listener(lambda *_args: None)

    assert first._block_thread is not second._block_thread
    first.stop()
    second.stop()
    assert not first._block_thread.is_alive()
    assert not second._block_thread.is_alive()


def test_a_full_queue_drops_new_blocks_and_counts_them(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path)
    release = threading.Event()
    entered = threading.Event()
    received = []

    def held(_source, samples):
        entered.set()
        release.wait(5)
        received.append(float(samples[0]))

    rig.session.add_block_listener(held)
    rig.recorder.emit(1)
    assert entered.wait(2)
    for value in range(2, 2 + 32 + 3):
        rig.recorder.emit(value)

    assert rig.session.dropped_blocks == 3
    release.set()
    assert wait_until(lambda: len(received) == 33)
    assert received == [float(value) for value in range(1, 34)]
    rig.session.stop()


def test_a_raising_listener_is_logged_without_its_message(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    rig = _make_session(monkeypatch, tmp_path)
    marker = "MARKER-7f3a-audio-detail"
    received = []

    def raising(_source, _samples):
        raise RuntimeError(marker)

    rig.session.add_block_listener(raising)
    rig.session.add_block_listener(lambda source, _samples: received.append(source))
    rig.recorder.emit(3)
    rig.recorder.emit(3)

    assert wait_until(lambda: len(received) == 2)
    assert rig.recorder.running
    assert any("block_listener_failed" in record.getMessage() for record in caplog.records)
    for record in caplog.records:
        assert marker not in record.getMessage()
        assert record.exc_info is None or marker not in str(record.exc_info[1])
    assert marker not in caplog.text
    rig.session.stop()
