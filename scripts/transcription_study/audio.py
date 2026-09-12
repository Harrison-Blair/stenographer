# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic synthetic controls; digital gain does not model hardware gain."""

import numpy as np


def transform(
    samples: np.ndarray,
    sample_rate: int = 16000,
    *,
    gain_db: float = 0.0,
    normalize_rms_dbfs: float | None = None,
    max_gain_db: float = 12.0,
    channel: str = "first",
    leading_ms: float = 0,
    trailing_ms: float = 0,
    trim_leading_ms: float = 0,
    trim_trailing_ms: float = 0,
) -> np.ndarray:
    """Select a channel, trim, amplify without clipping, and pad with silence.

    Normalization uses samples above one tenth of peak to avoid counting long
    silence as speech energy. Its amplification is independently bounded.
    """
    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim not in (1, 2) or not np.isfinite(audio).all():
        raise ValueError("Audio must be finite and have one or two dimensions")
    if sample_rate <= 0 or min(leading_ms, trailing_ms, trim_leading_ms, trim_trailing_ms) < 0:
        raise ValueError("Sample rate must be positive and boundary durations nonnegative")
    if channel not in {"first", "last", "mean", "strongest"}:
        raise ValueError("Unknown channel selection")
    if audio.ndim == 2:
        if audio.shape[1] == 0:
            raise ValueError("Audio must contain a channel")
        match channel:
            case "first":
                audio = audio[:, 0]
            case "last":
                audio = audio[:, -1]
            case "mean":
                audio = audio.mean(axis=1)
            case "strongest":
                index = int(np.argmax(np.sum(audio * audio, axis=0)))
                audio = audio[:, index]
    start = round(trim_leading_ms * sample_rate / 1000)
    end = max(start, len(audio) - round(trim_trailing_ms * sample_rate / 1000))
    audio = audio[start:end].copy()
    if len(audio):
        peak = float(np.max(np.abs(audio)))
        factor = 10 ** (gain_db / 20)
        if normalize_rms_dbfs is not None and peak > 0:
            speech = audio[np.abs(audio) >= peak * 0.1]
            rms = float(np.sqrt(np.mean(speech * speech)))
            factor *= min(10 ** (max_gain_db / 20), 10 ** (normalize_rms_dbfs / 20) / rms)
        if peak > 0 and (gain_db != 0 or normalize_rms_dbfs is not None):
            factor = min(factor, 0.9989999 / peak)
        audio *= factor
    return np.pad(
        audio,
        (round(leading_ms * sample_rate / 1000), round(trailing_ms * sample_rate / 1000)),
    ).astype(np.float32)
