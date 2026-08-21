# SPDX-License-Identifier: GPL-3.0-or-later
"""Integration smoke + manual acceptance procedure for the daemon (M5 Verify).

The M5 Verify clause — "real dictation end-to-end on both compositor families" —
is the acceptance test and is inherently MANUAL: it needs a microphone, real
speech, and a focused window. It cannot be asserted programmatically.

    MANUAL ACCEPTANCE PROCEDURE
    1. Ensure the model is cached (`stenographer model download`) and you are
       in the `input` group with write access to /dev/uinput.
    2. On THREE consecutive cold service starts, focus a text field, press and
       hold KEY_RIGHTCTRL, and say "Opening words must remain in this
       transcription" immediately when the start cue sounds. Release the key;
       each pasted result must retain at least "Opening words must remain".
    3. Repeat the cold-start check once with feedback.mute=true.
    4. Set a short asr.idle_unload_seconds, complete one dictation, wait for the
       worker to unload, and repeat the immediate-speech check.
    5. Disconnect/reconnect the microphone or restart PipeWire, then confirm a
       later press renegotiates capture and succeeds. A failed capture must play
       the error cue/notification and must NEVER paste partial text.
    6. Inspect the journal, the current stenographer.log, and rotated logs for
       preparation/activation/capture/recovery timing records. The dictated
       canary phrase above must not appear anywhere in those logs.
    7. Confirm the record_start and record_stop cues, paste at the cursor,
       delivered cue, and matching clipboard (`wl-paste`; `xclip -o` where the
       daemon logged clipboard_backend=x11) on both Hyprland (wlroots) and
       GNOME Wayland (Mutter).
    8. On a cold press, confirm the 4 px amber border starts breathing around
       the recording pill while all 18 spectrum bars continue. With only steady
       room or fan noise at or below the configured floor, confirm the bars remain
       at their baselines immediately; quiet speech above the floor must still
       animate them. Release quickly and confirm the same-width
       Transcribing pill appears directly with the border still breathing, then
       loses the border at ready or failure. No Loading model label or amber
       loading dot may appear. If ready arrives during a longer recording, the
       border must disappear there instead. A warm recording has no border;
       repeat after idle unload and confirm it returns. Model loading itself must
       make no sound. Disable or kill the overlay and confirm recording,
       transcription, and delivery still succeed.
    9. Set hotkey.mode = "toggle". Press KEY_RIGHTCTRL once, confirm the pill
       animates and the mic records with the key released, speak, press again,
       and confirm the paste. Then set a short audio.max_recording_seconds
       (e.g. 5), start a recording and keep talking past the cap: the stop cue
       must fire at the cap and the transcript up to it must be delivered. A
       press during transcription must do nothing.
    10. Run the complete opt-in integration suite. All of these checks are the
       real-machine merge gate; the sandbox-safe unit suite is not a substitute.

The automated tests below use the real default PortAudio input and actual lock
path. They self-skip unless STENOGRAPHER_INTEGRATION=1.
"""

from __future__ import annotations

import os
import time

import numpy as np
import pytest

pytestmark = pytest.mark.integration

if os.environ.get("STENOGRAPHER_INTEGRATION") != "1":
    pytest.skip("integration suite requires STENOGRAPHER_INTEGRATION=1", allow_module_level=True)

import sounddevice  # noqa: E402

from stenographer.audio import Recorder  # noqa: E402
from stenographer.daemon import (  # noqa: E402
    LOCK_PATH,
    acquire_single_instance_lock,
)


def _recorder() -> Recorder:
    return Recorder(device=None, max_seconds=2)


def test_prepared_recorder_is_stopped_and_has_no_samples():
    recorder = _recorder()
    try:
        recorder.prepare()
        assert recorder.is_prepared is True
        assert recorder.is_active is False
        assert recorder._stream.active is False
        time.sleep(0.2)
        assert recorder._frames == 0
        assert recorder._blocks == []
        assert recorder.stop().size == 0
        assert recorder.is_prepared is True
    finally:
        recorder.close()


def test_two_real_capture_cycles_reuse_one_stream():
    recorder = _recorder()
    try:
        recorder.prepare()
        stream = recorder._stream
        captures = []
        for _ in range(2):
            recorder.start()
            started_at = time.perf_counter()
            time.sleep(0.75)
            capture_seconds = time.perf_counter() - started_at
            captures.append((recorder.stop(), capture_seconds))
            assert recorder._stream is stream
            assert recorder.is_prepared is True
        for samples, capture_seconds in captures:
            assert samples.dtype == np.float32
            assert samples.ndim == 1
            assert samples.size > 0
            expected_frames = round(capture_seconds * 16000)
            # Allow host callback-block and scheduler timing, while remaining
            # tight enough that unresampled 8/22.05/44.1/48 kHz capture fails.
            tolerance = max(2048, round(expected_frames * 0.20))
            assert abs(samples.size - expected_frames) <= tolerance
    finally:
        recorder.close()


def test_input_overflow_preserves_real_stream_and_buffered_audio(caplog):
    recorder = _recorder()
    try:
        recorder.prepare()
        stream = recorder._stream
        recorder.start()
        time.sleep(0.2)

        # Reliably provoking a host overflow is machine- and scheduler-dependent.
        # Feed PortAudio's real status type through the callback while a real input
        # stream is active, then exercise the real stop/retain boundary.
        status = sounddevice.CallbackFlags()
        status.input_overflow = True
        recorder._on_audio(
            np.zeros((64, recorder._channels), dtype=np.float32),
            64,
            None,
            status,
        )
        samples = recorder.stop()

        assert samples.size > 0
        assert recorder._stream is stream
        assert recorder.is_prepared is True
        assert "recorder: input_overflow" in caplog.text
        assert "recorder: capture_failed" not in caplog.text
    finally:
        recorder.close()


def test_recorder_close_is_idempotent():
    recorder = _recorder()
    recorder.prepare()
    recorder.close()
    recorder.close()
    assert recorder.is_active is False
    assert recorder.is_prepared is False


def test_real_lock_path_mutual_exclusion():
    fd = acquire_single_instance_lock()
    if fd < 0:
        pytest.skip(f"another instance already holds {LOCK_PATH}")
    inode = LOCK_PATH.stat().st_ino
    try:
        # A real, non-mocked second acquire against the daemon's actual runtime
        # lock path fails while the first fd holds it.
        assert acquire_single_instance_lock() == -1
    finally:
        os.close(fd)

    next_fd = acquire_single_instance_lock()
    assert next_fd >= 0
    try:
        assert LOCK_PATH.stat().st_ino == inode
        assert acquire_single_instance_lock() == -1
    finally:
        os.close(next_fd)
