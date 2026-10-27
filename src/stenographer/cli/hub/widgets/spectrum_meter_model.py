# SPDX-License-Identifier: GPL-3.0-or-later
"""Hold the bands, level, peak and state text of one source meter."""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import TYPE_CHECKING

import numpy as np

from stenographer.lib.contracts.constants import SPECTRUM_BANDS
from stenographer.overlay.spectrum.analysis import DEFAULT_SPECTRUM_FLOOR_DBFS
from stenographer.overlay.spectrum.spectrum_analyzer import SpectrumAnalyzer

if TYPE_CHECKING:
    from collections.abc import Callable

ROWS = 8
SCALE = "100  200  400  800 1k6 3k2 6k4"
_RATE = 16000
_PEAK_SECONDS = 3.0
_KEYS = {"mic": "m", "system": "s"}
_STATES = {"on", "idle", "off"}


class SpectrumMeterModel:
    """Turn blocks of one source into 18 bands x 8 rows and the meter text rows."""

    def __init__(
        self,
        source: str,
        device: str,
        *,
        floor_dbfs: object = DEFAULT_SPECTRUM_FLOOR_DBFS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if source not in _KEYS:
            raise ValueError(f"unknown meter source: {source}")
        self.source = source
        self.device = device
        self.speech = False
        self._analyzer = SpectrumAnalyzer(floor_dbfs)
        self._clock = clock if clock is not None else time.monotonic
        self._lock = threading.Lock()
        self._state = "idle"
        self._idle_text = ""
        self._epoch = 0
        self._bands: tuple[int, ...] = (0,) * SPECTRUM_BANDS
        self._level = -math.inf
        self._levels: deque[tuple[float, float]] = deque()

    @property
    def state(self) -> str:
        return self._state

    def set_state(self, state: str, *, idle_text: str = "") -> None:
        """Show *state*; *idle_text* is the level row of the idle state."""
        if state not in _STATES:
            raise ValueError(f"unknown meter state: {state}")
        with self._lock:
            if state == "on" and self._state != "on":
                self._epoch += 1
                self._analyzer.reset()
                self._bands = (0,) * SPECTRUM_BANDS
                self._level = -math.inf
                self._levels.clear()
            self._state = state
            self._idle_text = idle_text

    def feed(self, samples: np.ndarray) -> None:
        """Analyze one 16 kHz mono block; safe to call from any thread."""
        block = np.asarray(samples, dtype=np.float32).reshape(-1)
        rms = float(np.sqrt(np.mean(np.square(block, dtype=np.float64)))) if block.size else 0.0
        level = 20 * math.log10(rms) if rms > 0 else -math.inf
        with self._lock:
            if self._state != "on":
                return
            self._bands = self._analyzer.update(
                block, _RATE, stream_epoch=self._epoch, elapsed=block.size / _RATE
            )
            now = self._clock()
            self._level = level
            self._levels.append((now, level))
            while self._levels and self._levels[0][0] < now - _PEAK_SECONDS:
                self._levels.popleft()

    @property
    def head(self) -> tuple[str, str]:
        """Return the left head text and the right token."""
        key = _KEYS[self.source]
        left = f"[{key}] {self.source.upper()} {self._state} · {self.device}"
        if self._state == "on":
            right = "● speech" if self.speech else "○ quiet"
        elif self._state == "idle" and self.source == "mic":
            right = "[d] device"
        else:
            right = ""
        return left, right

    @property
    def rows(self) -> tuple[str, ...]:
        """Return 8 rows, top first; band *i* is column ``2 * i``."""
        if self._state == "idle":
            return (" ".join("·" * SPECTRUM_BANDS),) * ROWS
        with self._lock:
            bands = self._bands if self._state == "on" else (0,) * SPECTRUM_BANDS
        heights = [round(value * ROWS / 255) for value in bands]
        return tuple(
            " ".join("█" if height >= ROWS - row else " " for height in heights)
            for row in range(ROWS)
        )

    @property
    def scale(self) -> str:
        return SCALE

    @property
    def level_text(self) -> str:
        if self._state == "idle":
            return self._idle_text
        if self._state == "off":
            return f"off · press {_KEYS[self.source]} to enable"
        with self._lock:
            level = self._level
            peak = max((value for _time, value in self._levels), default=-math.inf)
        return f"{self._dbfs(level)} dBFS  peak {self._dbfs(peak)}"

    @staticmethod
    def _dbfs(value: float) -> str:
        return f"{value:.0f}" if math.isfinite(value) else "-inf"
