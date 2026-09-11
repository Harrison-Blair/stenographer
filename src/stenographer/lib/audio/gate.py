# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure frame-energy speech gating."""

from __future__ import annotations

import numpy as np

from stenographer.lib.audio.records import GateStats

_GATE_FRAME_SECONDS = 0.050


def speech_gate_stats(samples: np.ndarray, sample_rate: int, min_rms: float) -> GateStats:
    """Frame the capture once and return both the verdict and its numbers. PURE.

    The verdict and the reported energy come from a single computation on
    purpose: a log line whose numbers were measured separately from the
    decision it explains can disagree with it, and a quiet-mic false reject is
    exactly the case that has to be diagnosable from the log alone.

    Disabled (always passing) when *min_rms* <= 0. Otherwise the capture passes
    only when two consecutive 50 ms frames both exceed the RMS threshold, so
    isolated clicks and dead air are rejected without eating soft speech
    onsets — the quiet-mic case the owner's setup depends on.
    """
    audio = np.asarray(samples, dtype=np.float32).reshape(-1)
    frame = max(1, int(sample_rate * _GATE_FRAME_SECONDS))
    n_frames = audio.size // frame
    if n_frames == 0:
        return GateStats(0.0, 0.0, 0, 0, min_rms, min_rms <= 0)
    trimmed = audio[: n_frames * frame].reshape(n_frames, frame)
    rms = np.sqrt(np.mean(trimmed * trimmed, axis=1))
    loud = rms > min_rms
    passed = min_rms <= 0 or (n_frames >= 2 and bool(np.any(loud[:-1] & loud[1:])))
    return GateStats(
        peak_rms=float(rms.max()),
        mean_rms=float(rms.mean()),
        frames_total=n_frames,
        frames_above=int(np.count_nonzero(loud)),
        threshold=min_rms,
        passed=passed,
    )
