# SPDX-License-Identifier: GPL-3.0-or-later
"""Microphone spectrum analysis on a dedicated worker thread."""

from __future__ import annotations

import contextlib
import itertools
import logging
import math
import queue
import threading
from collections.abc import Callable

import numpy as np

from stenographer.visualizer.protocol import _STOP

logger = logging.getLogger(__name__)


def analyze_frequency_bands(
    samples: np.ndarray,
    sample_rate: int,
    band_count: int,
    min_frequency: float,
    max_frequency: float,
) -> np.ndarray:
    """Return logarithmic frequency-band levels normalized to ``0.0..1.0``.

    A Hann-windowed real FFT is mapped from -60 dBFS (empty bar) to 0 dBFS
    (full bar). The highest spectral bin in each logarithmic band drives that
    band, which keeps speech harmonics legible in a compact display.
    """
    mono = np.asarray(samples, dtype=np.float32).reshape(-1)
    if mono.size < 2 or sample_rate <= 0 or band_count <= 0:
        return np.zeros(max(0, band_count), dtype=np.float32)
    mono = np.nan_to_num(mono, copy=False)
    mono = mono - float(np.mean(mono))
    if not np.any(mono):
        return np.zeros(band_count, dtype=np.float32)

    fft_size = max(512, 1 << math.ceil(math.log2(mono.size)))
    window = np.hanning(mono.size).astype(np.float32)
    coherent_gain = max(float(np.sum(window)) / 2.0, np.finfo(np.float32).eps)
    magnitudes = np.abs(np.fft.rfft(mono * window, n=fft_size)) / coherent_gain
    frequencies = np.fft.rfftfreq(fft_size, d=1.0 / sample_rate)

    nyquist = sample_rate / 2.0
    low = max(float(min_frequency), sample_rate / fft_size)
    high = min(float(max_frequency), nyquist)
    if high <= low:
        return np.zeros(band_count, dtype=np.float32)

    edges = np.geomspace(low, high, band_count + 1)
    levels = np.zeros(band_count, dtype=np.float32)
    for index, (edge_low, edge_high) in enumerate(itertools.pairwise(edges)):
        if index == band_count - 1:
            mask = (frequencies >= edge_low) & (frequencies <= edge_high)
        else:
            mask = (frequencies >= edge_low) & (frequencies < edge_high)
        if not np.any(mask):
            continue
        amplitude = float(np.max(magnitudes[mask]))
        dbfs = 20.0 * math.log10(max(amplitude, 1e-6))
        levels[index] = np.clip((dbfs + 60.0) / 60.0, 0.0, 1.0)
    return levels


class SpectrumAnalyzer:
    """Analyze only the newest audio block on a background thread."""

    def __init__(
        self,
        *,
        band_count: int,
        min_frequency: float,
        max_frequency: float,
        on_levels: Callable[[list[float]], None],
    ) -> None:
        self._band_count = band_count
        self._min_frequency = min_frequency
        self._max_frequency = max_frequency
        self._on_levels = on_levels
        self._queue: queue.Queue[tuple[np.ndarray, int] | object] = queue.Queue(maxsize=1)
        self._active = threading.Event()
        self._reset = threading.Event()
        self._mutex = threading.Lock()
        self._closed = False
        # Only the worker thread touches _smoothed; other threads ask for a
        # reset instead, so a zeroing can never be lost inside an update.
        self._smoothed = np.zeros(band_count, dtype=np.float32)
        self._worker = threading.Thread(
            target=self._run,
            name="spectrum-analyzer",
            daemon=True,
        )
        self._worker.start()

    def set_active(self, active: bool) -> None:
        self._reset.set()
        if active:
            self._active.set()
            return
        self._active.clear()
        with self._mutex:
            self._discard_pending()

    def submit(self, samples: np.ndarray, sample_rate: int) -> None:
        """Copy and enqueue a block without waiting for the analyzer."""
        if not self._active.is_set() or self._closed:
            return
        packet = (np.asarray(samples, dtype=np.float32).reshape(-1).copy(), sample_rate)
        # The mutex keeps discard-then-put atomic against close(), which would
        # otherwise see its stop sentinel discarded by a racing submit.
        with self._mutex:
            if self._closed:
                return
            try:
                self._queue.put_nowait(packet)
                return
            except queue.Full:
                pass
            self._discard_pending()
            with contextlib.suppress(queue.Full):
                self._queue.put_nowait(packet)

    def close(self) -> None:
        with self._mutex:
            if self._closed:
                return
            self._closed = True
            self._active.clear()
            self._discard_pending()
            self._queue.put_nowait(_STOP)
        self._worker.join(timeout=2.0)
        if self._worker.is_alive():
            logger.warning("visualizer: spectrum analyzer thread did not exit")

    def _discard_pending(self) -> None:
        with contextlib.suppress(queue.Empty):
            self._queue.get_nowait()

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            if self._reset.is_set():
                self._reset.clear()
                self._smoothed.fill(0.0)
            if not self._active.is_set():
                continue
            samples, sample_rate = item  # type: ignore[misc]
            levels = analyze_frequency_bands(
                samples,
                sample_rate,
                self._band_count,
                self._min_frequency,
                self._max_frequency,
            )
            # A responsive attack and short release make plosives and pauses
            # visually distinct at the target 60 Hz capture cadence.
            coefficient = np.where(levels >= self._smoothed, 0.84, 0.32)
            self._smoothed += coefficient * (levels - self._smoothed)
            smoothed = self._smoothed.tolist()
            if not self._active.is_set():
                # Deactivated while this block was analyzed; publishing now
                # would freeze pre-cancel bars under a "Transcribing" label.
                continue
            try:
                self._on_levels(smoothed)
            except Exception as exc:
                logger.debug("visualizer: level consumer failed: %s", exc)
