# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import math
from functools import lru_cache
from itertools import pairwise

import numpy as np

from stenographer.lib.contracts.constants import SPECTRUM_BANDS
from stenographer.overlay.spectrum.band_analysis import _BandAnalysis

SPECTRUM_FPS = 60


WINDOW_SECONDS = 0.032


FFT_MIN_SIZE = 4096


LOW_FREQUENCY_HZ = 80.0


HIGH_FREQUENCY_HZ = 8000.0


MIN_SPECTRUM_FLOOR_DBFS = -96.0


MAX_SPECTRUM_FLOOR_DBFS = -13.0


DEFAULT_SPECTRUM_FLOOR_DBFS = -45.0


SPECTRUM_CEILING_DBFS = -12.0


DISPLAY_RANGE_DBFS = 30.0


DISPLAY_GAMMA = 0.7


ATTACK_SECONDS = 0.0025


RELEASE_SECONDS = 0.0225


def _validated_floor_dbfs(floor_dbfs: object) -> float | np.ndarray:
    if isinstance(floor_dbfs, int | float) and not isinstance(floor_dbfs, bool):
        floor = float(floor_dbfs)
        if math.isfinite(floor) and MIN_SPECTRUM_FLOOR_DBFS <= floor <= MAX_SPECTRUM_FLOOR_DBFS:
            return floor
        raise ValueError(
            f"spectrum floor must be in [{MIN_SPECTRUM_FLOOR_DBFS}, {MAX_SPECTRUM_FLOOR_DBFS}] dBFS"
        )
    try:
        floors = np.asarray(floor_dbfs, dtype=np.float64).reshape(-1)
    except (TypeError, ValueError) as exc:
        raise TypeError("spectrum floor must be a number or 18-band sequence") from exc
    if floors.size != SPECTRUM_BANDS:
        raise ValueError(f"spectrum floor profile requires {SPECTRUM_BANDS} bands")
    if (
        not np.all(np.isfinite(floors))
        or np.any(floors < MIN_SPECTRUM_FLOOR_DBFS)
        or np.any(floors > MAX_SPECTRUM_FLOOR_DBFS)
    ):
        raise ValueError(
            f"spectrum floor must be in [{MIN_SPECTRUM_FLOOR_DBFS}, {MAX_SPECTRUM_FLOOR_DBFS}] dBFS"
        )
    return floors


def _validate_sample_rate(sample_rate: int) -> None:
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
        raise ValueError("sample rate must be a positive integer")


def logarithmic_band_edges(sample_rate: int) -> np.ndarray:
    """Return 19 band edges from 80 Hz to clamped 8 kHz/Nyquist."""
    _validate_sample_rate(sample_rate)
    upper = min(HIGH_FREQUENCY_HZ, sample_rate / 2.0)
    if upper <= LOW_FREQUENCY_HZ:
        return np.full(SPECTRUM_BANDS + 1, upper, dtype=np.float64)
    return np.geomspace(LOW_FREQUENCY_HZ, upper, SPECTRUM_BANDS + 1)


def fft_size_for_window(sample_count: int) -> int:
    """Return a power-of-two FFT size at least 4096 and large enough for a window."""
    if isinstance(sample_count, bool) or not isinstance(sample_count, int) or sample_count < 1:
        raise ValueError("FFT sample count must be a positive integer")
    return max(FFT_MIN_SIZE, 1 << (sample_count - 1).bit_length())


@lru_cache(maxsize=8)
def _band_analysis(sample_rate: int, window_size: int) -> _BandAnalysis:
    """Derive the Hann window, FFT size, and per-band rfft bin ranges once."""
    window = np.hanning(window_size)
    window.flags.writeable = False  # the cached array is shared across frames
    coherent_gain = float(np.sum(window))
    fft_size = fft_size_for_window(window_size)
    frequencies = np.fft.rfftfreq(fft_size, d=1.0 / sample_rate)
    edges = logarithmic_band_edges(sample_rate)
    bands: list[tuple[int, int] | None] = []
    for index, (lower, upper) in enumerate(pairwise(edges)):
        if upper <= lower:
            bands.append(None)
            continue
        start = int(np.searchsorted(frequencies, lower, side="left"))
        # The last band is top-inclusive so the Nyquist bin stays counted.
        side = "right" if index == SPECTRUM_BANDS - 1 else "left"
        stop = int(np.searchsorted(frequencies, upper, side=side))
        bands.append((start, stop) if start < stop else None)
    return _BandAnalysis(window, coherent_gain, fft_size, tuple(bands))


def _band_dbfs(samples: object, sample_rate: int) -> np.ndarray:
    """Measure peak Hann-windowed amplitude in each logarithmic band."""
    _validate_sample_rate(sample_rate)
    silence = np.full(SPECTRUM_BANDS, -math.inf, dtype=np.float64)
    try:
        audio = np.asarray(samples, dtype=np.float64).reshape(-1)
    except (TypeError, ValueError):
        return silence
    if audio.size < 2:
        return silence
    audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
    audio = audio - np.mean(audio)
    analysis = _band_analysis(sample_rate, audio.size)
    if analysis.coherent_gain <= 0:
        return silence

    magnitudes = np.abs(np.fft.rfft(audio * analysis.window, n=analysis.fft_size))
    magnitudes /= analysis.coherent_gain
    if magnitudes.size > 1:
        magnitudes[1:] *= 2.0
        magnitudes[-1] *= 0.5  # Nyquist has no negative-frequency partner.

    dbfs = silence.copy()
    for index, band in enumerate(analysis.bands):
        if band is None:
            continue
        magnitude = float(np.max(magnitudes[band[0] : band[1]]))
        if magnitude > 0 and math.isfinite(magnitude):
            dbfs[index] = 20.0 * math.log10(magnitude)
    return dbfs


def display_levels(dbfs: object, floor_dbfs: object = DEFAULT_SPECTRUM_FLOOR_DBFS) -> np.ndarray:
    """Map fixed scalar or per-band floors through a stable 30 dB display range."""
    floor = _validated_floor_dbfs(floor_dbfs)
    values = np.asarray(dbfs, dtype=np.float64).reshape(-1)
    if values.size != SPECTRUM_BANDS:
        raise ValueError(f"spectrum display mapping requires {SPECTRUM_BANDS} levels")
    values = np.nan_to_num(
        values,
        nan=floor,
        posinf=SPECTRUM_CEILING_DBFS,
        neginf=floor,
    )
    ceiling = np.minimum(SPECTRUM_CEILING_DBFS, floor + DISPLAY_RANGE_DBFS)
    normalized = np.clip((values - floor) / (ceiling - floor), 0.0, 1.0)
    return np.power(normalized, DISPLAY_GAMMA)


def smooth_spectrum(
    previous: object,
    target: object,
    elapsed: float,
    *,
    attack: float = ATTACK_SECONDS,
    release: float = RELEASE_SECONDS,
) -> np.ndarray:
    """Apply independent exponential attack/release smoothing to 18 levels."""
    old = np.asarray(previous, dtype=np.float64).reshape(-1)
    new = np.asarray(target, dtype=np.float64).reshape(-1)
    if old.size != SPECTRUM_BANDS or new.size != SPECTRUM_BANDS:
        raise ValueError(f"spectrum smoothing requires {SPECTRUM_BANDS} levels")
    if not math.isfinite(elapsed) or elapsed < 0:
        raise ValueError("smoothing elapsed time must be finite and non-negative")
    if not math.isfinite(attack) or not math.isfinite(release) or min(attack, release) <= 0:
        raise ValueError("smoothing time constants must be finite and positive")
    old = np.clip(np.nan_to_num(old, nan=0.0, posinf=1.0, neginf=0.0), 0.0, 1.0)
    new = np.clip(np.nan_to_num(new, nan=0.0, posinf=1.0, neginf=0.0), 0.0, 1.0)
    attack_weight = 1.0 - math.exp(-elapsed / attack)
    release_weight = 1.0 - math.exp(-elapsed / release)
    weights = np.where(new > old, attack_weight, release_weight)
    return old + weights * (new - old)


def quantize_spectrum(levels: object) -> tuple[int, ...]:
    """Quantize 18 normalized levels to the strict protocol's uint8 range."""
    values = np.asarray(levels, dtype=np.float64).reshape(-1)
    if values.size != SPECTRUM_BANDS:
        raise ValueError(f"spectrum quantization requires {SPECTRUM_BANDS} levels")
    values = np.clip(np.nan_to_num(values, nan=0.0, posinf=1.0, neginf=0.0), 0.0, 1.0)
    return tuple(int(value) for value in np.rint(values * 255.0))
