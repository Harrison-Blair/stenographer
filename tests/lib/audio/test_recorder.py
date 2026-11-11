# SPDX-License-Identifier: GPL-3.0-or-later
"""The dictation ``Recorder`` against a stand-in platform microphone capture.

The stand-in implements the ``MicCapture`` contract: it hands blocks or an
error to the callback the way the reader thread does. No OS call is patched;
the real ``pw-record`` child is covered by the platform tests.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from stenographer.lib.audio.recorder import Recorder
from stenographer.lib.platform.errors import MicCaptureError

_LOGGER = "stenographer.lib.audio.recorder"


class FakeCapture:
    def __init__(self, *, start_error: Exception | None = None) -> None:
        self.start_error = start_error
        self.on_block = None
        self.targets: list[str | None] = []
        self.running = False
        self.stops = 0
        # Blocks the reader thread delivers before stop returns.
        self.pending: list[np.ndarray | MicCaptureError] = []

    def start(self, target, on_block):
        if self.start_error is not None:
            raise self.start_error
        self.targets.append(target)
        self.on_block = on_block
        self.running = True

    def stop(self):
        self.stops += 1
        if self.running:
            for item in self.pending:
                self.on_block(item)
            self.pending.clear()
        self.running = False

    def emit(self, *values: float) -> None:
        self.on_block(np.asarray(values, dtype=np.float32))


def _recorder(capture: FakeCapture, **kwargs) -> Recorder:
    options = {"device": None, "max_seconds": 10, **kwargs}
    return Recorder(capture=capture, **options)


@pytest.mark.parametrize(
    ("device", "target"),
    [
        (None, None),
        ("", None),
        ("pipewire", None),
        ("10", None),
        ("alsa_input.usb", "alsa_input.usb"),
    ],
)
def test_start_targets_the_source_the_setting_names(device, target):
    capture = FakeCapture()
    recorder = _recorder(capture, device=device)

    recorder.start()

    assert capture.targets == [target]


def test_nothing_captures_before_start_or_after_stop():
    capture = FakeCapture()
    recorder = _recorder(capture)
    assert not capture.running

    recorder.start()
    assert capture.running
    recorder.stop()

    assert not capture.running


def test_stop_returns_every_block_including_those_delivered_while_stopping():
    capture = FakeCapture()
    recorder = _recorder(capture)
    recorder.start()
    capture.emit(0.1, 0.2)
    capture.pending.append(np.asarray([0.3], dtype=np.float32))

    samples = recorder.stop()

    np.testing.assert_array_equal(samples, np.asarray([0.1, 0.2, 0.3], dtype=np.float32))
    stats = recorder.last_capture
    assert stats is not None
    assert stats.input_frames == stats.output_frames == 3
    assert stats.input_rate == 16000
    assert stats.callback_count == 2
    assert stats.first_callback_at is not None
    assert stats.activation_to_callback_ms is not None


def test_each_capture_starts_empty_and_gets_a_new_stream_epoch():
    capture = FakeCapture()
    seen = []
    recorder = _recorder(capture, on_block=lambda block, rate, epoch: seen.append((rate, epoch)))
    recorder.start()
    capture.emit(0.5)
    recorder.stop()
    recorder.start()
    capture.emit(0.25)

    np.testing.assert_array_equal(recorder.stop(), np.asarray([0.25], dtype=np.float32))
    assert seen == [(16000, 1), (16000, 2)]


def test_a_capture_that_cannot_start_raises_and_is_not_capturing():
    recorder = _recorder(FakeCapture(start_error=MicCaptureError("pw-record is not installed")))

    with pytest.raises(MicCaptureError, match="pw-record is not installed"):
        recorder.start()

    assert not recorder.capturing
    assert recorder.stop().size == 0


def test_a_capture_that_stops_by_itself_calls_on_failure_and_stop_raises(caplog):
    capture = FakeCapture()
    failures = []
    recorder = _recorder(capture, on_failure=lambda: failures.append(True))
    recorder.start()
    capture.emit(0.1)

    capture.on_block(MicCaptureError("pw-record exited unexpectedly with status 1"))

    assert failures == [True]
    with caplog.at_level(logging.WARNING, logger=_LOGGER), pytest.raises(MicCaptureError):
        recorder.stop()
    assert "recorder: capture_failed" in caplog.text
    assert recorder.last_capture is None
    # The next dictation starts clean.
    recorder.start()
    capture.emit(0.2)
    np.testing.assert_array_equal(recorder.stop(), np.asarray([0.2], dtype=np.float32))


def test_the_sample_cap_keeps_max_seconds_of_audio_and_warns(caplog):
    capture = FakeCapture()
    recorder = _recorder(capture, max_seconds=1)
    recorder.start()
    block = np.zeros(10_000, dtype=np.float32)
    capture.on_block(block)
    capture.on_block(block)
    capture.on_block(block)

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        samples = recorder.stop()

    assert samples.size == 20_000
    assert recorder.last_capture.capped is True
    assert "recorder: capture_capped" in caplog.text


def test_close_stops_a_running_capture_and_is_repeatable():
    capture = FakeCapture()
    recorder = _recorder(capture)
    recorder.start()

    recorder.close()
    recorder.close()

    assert not capture.running
    assert not recorder.capturing


def test_start_while_capturing_is_refused():
    recorder = _recorder(FakeCapture())
    recorder.start()

    with pytest.raises(RuntimeError, match="already capturing"):
        recorder.start()
