#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import soundfile as sf

SAMPLE_RATE = 44100
SUBTYPE = "PCM_16"
DBFS_BEEP = -12.0
DBFS_SEGMENT = -18.0
DBFS_ERROR = -6.0
ENVELOPE_S = 0.005
GAP_S = 0.060
SEGMENT_S = 0.050
TRANSCRIBE_DONE_S = 0.010


def dbfs_to_amplitude(dbfs: float) -> float:
    return 10.0 ** (dbfs / 20.0)


def apply_envelope(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    n = samples.shape[0]
    attack = round(ENVELOPE_S * sample_rate)
    release = round(ENVELOPE_S * sample_rate)
    if attack + release >= n:
        return samples
    out = samples.copy()
    if attack:
        ramp_up = np.linspace(0.0, 1.0, attack, endpoint=False, dtype=np.float32)
        out[:attack] *= ramp_up
    if release:
        ramp_down = np.linspace(1.0, 0.0, release, endpoint=False, dtype=np.float32)
        out[-release:] *= ramp_down
    return out


def tone(freq_hz: float, duration_s: float, dbfs: float, sample_rate: int) -> np.ndarray:
    n = round(duration_s * sample_rate)
    t = np.arange(n, dtype=np.float32) / sample_rate
    amp = np.float32(dbfs_to_amplitude(dbfs))
    samples = amp * np.sin(np.float32(2.0 * math.pi * freq_hz) * t)
    return apply_envelope(samples, sample_rate).astype(np.float32, copy=False)


def silence(duration_s: float, sample_rate: int) -> np.ndarray:
    n = round(duration_s * sample_rate)
    return np.zeros(n, dtype=np.float32)


def build_cues(sample_rate: int) -> dict[str, np.ndarray]:
    return {
        "ptt_on": tone(880.0, 0.080, DBFS_BEEP, sample_rate),
        "ptt_off": np.concatenate(
            [
                tone(880.0, 0.080, DBFS_BEEP, sample_rate),
                silence(GAP_S, sample_rate),
                tone(880.0, 0.080, DBFS_BEEP, sample_rate),
            ]
        ),
        "toggle_on": tone(440.0, 0.080, DBFS_BEEP, sample_rate),
        "toggle_off": np.concatenate(
            [
                tone(440.0, 0.080, DBFS_BEEP, sample_rate),
                silence(GAP_S, sample_rate),
                tone(440.0, 0.080, DBFS_BEEP, sample_rate),
            ]
        ),
        "cancel": np.concatenate(
            [
                tone(440.0, 0.080, DBFS_BEEP, sample_rate),
                silence(GAP_S, sample_rate),
                tone(220.0, 0.120, DBFS_BEEP, sample_rate),
            ]
        ),
        "discard": tone(330.0, 0.060, DBFS_SEGMENT, sample_rate),
        "error": tone(220.0, 0.250, DBFS_ERROR, sample_rate),
        "segment": tone(660.0, SEGMENT_S, DBFS_SEGMENT, sample_rate),
        "transcribe_done": silence(TRANSCRIBE_DONE_S, sample_rate),
        "model_loading": np.concatenate(
            [
                tone(440.0, 0.080, DBFS_BEEP, sample_rate),
                silence(GAP_S, sample_rate),
                tone(554.0, 0.080, DBFS_BEEP, sample_rate),
                silence(GAP_S, sample_rate),
                tone(660.0, 0.080, DBFS_BEEP, sample_rate),
            ]
        ),
        "model_ready": np.concatenate(
            [
                tone(880.0, 0.060, -10.0, sample_rate),
                silence(0.040, sample_rate),
                tone(880.0, 0.060, -10.0, sample_rate),
            ]
        ),
    }


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    out_dir = repo_root / "src" / "stenographer" / "assets" / "sounds"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, samples in build_cues(SAMPLE_RATE).items():
        sf.write(out_dir / f"{name}.wav", samples, SAMPLE_RATE, subtype=SUBTYPE)


if __name__ == "__main__":
    main()
