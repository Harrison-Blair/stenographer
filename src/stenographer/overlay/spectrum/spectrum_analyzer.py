# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import numpy as np

from stenographer.lib.contracts.constants import SPECTRUM_BANDS
from stenographer.overlay.spectrum.analysis import (
    DEFAULT_SPECTRUM_FLOOR_DBFS,
    SPECTRUM_FPS,
    WINDOW_SECONDS,
    _band_dbfs,
    _validate_sample_rate,
    _validated_floor_dbfs,
    display_levels,
    quantize_spectrum,
    smooth_spectrum,
)


class SpectrumAnalyzer:
    """Fixed-range monitor with per-recording sample and motion state."""

    def __init__(self, floor_dbfs: object = DEFAULT_SPECTRUM_FLOOR_DBFS) -> None:
        validated = _validated_floor_dbfs(floor_dbfs)
        self._floor_dbfs = (
            tuple(float(value) for value in validated)
            if isinstance(validated, np.ndarray)
            else validated
        )
        self._stream_epoch: int | None = None
        self._sample_rate = 0
        self._window = np.empty(0, dtype=np.float32)
        self._smoothed = np.zeros(SPECTRUM_BANDS, dtype=np.float64)

    @property
    def floor_dbfs(self) -> float | tuple[float, ...]:
        """Return the fixed display floor configured for this analyzer."""
        return self._floor_dbfs

    def begin_recording(self) -> None:
        """Clear samples and motion at the start of every recording."""
        if self._window.size:
            self._window.fill(0.0)
        self._smoothed.fill(0.0)

    def reset(self) -> None:
        """Forget the stream and all sample and motion state."""
        self._stream_epoch = None
        self._sample_rate = 0
        self._window = np.empty(0, dtype=np.float32)
        self._smoothed.fill(0.0)

    def _configure_stream(self, sample_rate: int, stream_epoch: int) -> None:
        self._stream_epoch = stream_epoch
        self._sample_rate = sample_rate
        size = max(2, round(sample_rate * WINDOW_SECONDS))
        self._window = np.zeros(size, dtype=np.float32)
        self._smoothed.fill(0.0)

    def update(
        self,
        samples: object,
        sample_rate: int,
        *,
        stream_epoch: int,
        elapsed: float = 1.0 / SPECTRUM_FPS,
    ) -> tuple[int, ...]:
        """Append a latest block and return one fixed-range, smoothed protocol frame."""
        _validate_sample_rate(sample_rate)  # validates the negotiated rate
        if isinstance(stream_epoch, bool) or not isinstance(stream_epoch, int) or stream_epoch < 0:
            raise ValueError("stream epoch must be a non-negative integer")
        if sample_rate != self._sample_rate or stream_epoch != self._stream_epoch:
            self._configure_stream(sample_rate, stream_epoch)
        try:
            block = np.asarray(samples, dtype=np.float32).reshape(-1)
        except (TypeError, ValueError):
            block = np.empty(0, dtype=np.float32)
        if block.size:
            block = np.nan_to_num(block, nan=0.0, posinf=0.0, neginf=0.0)
            if block.size >= self._window.size:
                self._window[:] = block[-self._window.size :]
            else:
                self._window[: -block.size] = self._window[block.size :]
                self._window[-block.size :] = block

        target = display_levels(_band_dbfs(self._window, sample_rate), self._floor_dbfs)
        self._smoothed = smooth_spectrum(self._smoothed, target, elapsed)
        return quantize_spectrum(self._smoothed)
