# SPDX-License-Identifier: GPL-3.0-or-later
"""Integration smoke + manual acceptance procedure for the daemon.

Real dictation end-to-end on both compositor families is the acceptance test
and is inherently MANUAL: it needs a microphone, real speech, and a focused
window. It cannot be asserted programmatically.

    MANUAL ACCEPTANCE PROCEDURE
    1. Ensure the model is cached (`stenographer model download`) and you are
       in the `input` group with write access to /dev/uinput.
    2. Set hotkey.mode = "hold". On THREE consecutive cold service starts,
       focus a text field, press and hold KEY_RIGHTCTRL, and say "Opening words
       must remain in this transcription" immediately when the start cue
       sounds. Release the key; each pasted result must retain at least
       "Opening words must remain".
    3. Repeat the cold-start check once with feedback.mute=true.
    4. Set a short asr.idle_unload_seconds, complete one dictation, wait for the
       worker to unload, and repeat the immediate-speech check.
    5. Disconnect/reconnect the microphone or restart PipeWire, then confirm a
       later press starts a new capture and succeeds. A failed capture must play
       the error cue/notification and must NEVER paste partial text.
    6. Run `test_dictation_log_reports_metrics_without_the_transcript` below
       immediately after step 2's dictations (it reads the same
       stenographer.log): it asserts the `pipeline: utterance` summary line is
       there and the canary phrase is not. Then eyeball the journal and the
       rotated logs for the same property, and confirm the startup banner named
       your configuration and the summary's timings look sane.
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
       and confirm the paste. Then start a recording and keep talking past the
       600-second cap: the stop cue
       must fire at the cap and the transcript up to it must be delivered. A
       press during transcription must do nothing.
    10. Set hotkey.mode = "hybrid" (the default). Tap KEY_RIGHTCTRL well inside
       the 0.5-second hybrid threshold: the pill must stay up with the key
       released. Speak, tap again, and confirm the paste. Then press and hold
       past the threshold, speak, and release — it must stop on release exactly
       like hold mode. Confirm a latched recording stops 600 seconds after the
       PRESS (not after the
       release), while a hold longer than the cap ends only on release and
       reports capped=1 in its summary.
    11. Run the complete opt-in integration suite. All of these checks are the
       real-machine merge gate; the sandbox-safe unit suite is not a substitute.

The automated tests below use the real default microphone through pw-record
and the actual lock path. They are collected only with STENOGRAPHER_INTEGRATION=1.
"""

from __future__ import annotations

import os
import pathlib
import time

import numpy as np
import pytest

from stenographer.lib.audio.recorder import Recorder
from stenographer.lib.platform import current_platform
from stenographer.lib.platform.linux.lock import (
    LOCK_PATH,
    acquire_single_instance_lock,
)

pytestmark = pytest.mark.integration

#: The phrase step 2 of the manual procedure dictates, lowercased for matching.
_CANARY = "opening words must remain"


def _recorder() -> Recorder:
    return Recorder(capture_factory=current_platform().mic_capture, device=None, max_seconds=2)


def test_two_real_capture_cycles_deliver_16_khz_audio():
    recorder = _recorder()
    try:
        captures = []
        for _ in range(2):
            recorder.start()
            started_at = time.perf_counter()
            time.sleep(0.75)
            capture_seconds = time.perf_counter() - started_at
            captures.append((recorder.stop(), capture_seconds))
            assert not recorder.capturing
        for samples, capture_seconds in captures:
            assert samples.dtype == np.float32
            assert samples.ndim == 1
            assert samples.size > 0
            expected_frames = round(capture_seconds * 16000)
            # Allow the child start and the pipe, while remaining tight enough
            # that a wrong rate fails.
            tolerance = max(4096, round(expected_frames * 0.30))
            assert abs(samples.size - expected_frames) <= tolerance
    finally:
        recorder.close()


def test_recorder_close_is_idempotent():
    recorder = _recorder()
    recorder.close()
    recorder.close()
    assert not recorder.capturing


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


def test_dictation_log_reports_metrics_without_the_transcript():
    """Step 6, automated: the log after a real dictation carries no transcript.

    Reads the daemon's actual ``stenographer.log`` rather than a captured
    logger, because rule 6 is a property of the file that gets attached to a
    report — not of the call sites in isolation. Run it right after step 2.
    """
    log_path = current_platform().state_dir(os.environ, pathlib.Path.home()) / "stenographer.log"
    if not log_path.exists():
        pytest.skip(f"no daemon log yet: {log_path}")
    text = log_path.read_text(encoding="utf-8", errors="replace")

    summaries = [line for line in text.splitlines() if "pipeline: utterance " in line]
    if not summaries:
        pytest.skip("no dictation recorded in the current log; run step 2 first")

    assert _CANARY not in text.lower()
    last = summaries[-1]
    for field in ("utt=", "outcome=", "peak_rms=", "vad_frames=", "total_ms="):
        assert field in last, last
