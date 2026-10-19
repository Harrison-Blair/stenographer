# SPDX-License-Identifier: GPL-3.0-or-later
"""Stateful polyphase resampling for callback-driven audio."""

from __future__ import annotations

import math

import numpy as np


class StreamingResampler:
    """Resample mono float32 blocks while retaining only filter history."""

    def __init__(self, rate_in: int, rate_out: int) -> None:
        gcd = math.gcd(rate_in, rate_out)
        self._up = rate_out // gcd
        self._down = rate_in // gcd
        self._rate_in = rate_in
        self._rate_out = rate_out
        self._n_taps = 2 * 10 * max(self._up, self._down) + 1
        self._half = self._n_taps // 2
        cutoff = 1.0 / max(self._up, self._down)
        offsets = np.arange(self._n_taps, dtype=np.float64) - self._half
        self._filter = (
            np.sinc(cutoff * offsets) * cutoff * np.hanning(self._n_taps) * self._up
        ).astype(np.float32)
        self._samples = np.empty(0, dtype=np.float32)
        self._buffer_start = 0
        self._input_frames = 0
        self._next_output = 0

    def process(self, samples: np.ndarray) -> np.ndarray:
        """Return output samples that have enough input for stable filtering."""
        block = np.asarray(samples, dtype=np.float32).reshape(-1)
        if block.size == 0:
            return block.copy()
        if self._rate_in == self._rate_out:
            self._input_frames += block.size
            self._next_output += block.size
            return block.copy()

        self._samples = np.concatenate((self._samples, block))
        self._input_frames += block.size
        return self._produce(final=False, output_count=None)

    def flush(self) -> np.ndarray:
        """Return the remaining output samples with zero-padding at end of input."""
        if self._rate_in == self._rate_out:
            return np.empty(0, dtype=np.float32)
        count = (self._input_frames * self._up + self._down - 1) // self._down
        return self._produce(final=True, output_count=count)

    def _produce(self, *, final: bool, output_count: int | None) -> np.ndarray:
        output: list[np.float32] = []
        while output_count is None or self._next_output < output_count:
            center = self._half + self._next_output * self._down
            right = center // self._up
            if not final and right >= self._input_frames:
                break
            left = max(0, (center - self._n_taps + self._up) // self._up)
            right = min(right, self._input_frames - 1)
            left = max(left, self._buffer_start)
            if left <= right:
                indices = np.arange(left, right + 1)
                taps = center - indices * self._up
                values = self._samples[indices - self._buffer_start]
                output.append(np.dot(values, self._filter[taps]))
            else:
                output.append(np.float32(0.0))
            self._next_output += 1

        result = np.asarray(output, dtype=np.float32) if output else np.empty(0, dtype=np.float32)

        if not final:
            center = self._half + self._next_output * self._down
            keep_from = max(0, (center - self._n_taps + self._up) // self._up)
            discard = min(keep_from - self._buffer_start, self._samples.size)
            if discard > 0:
                self._samples = self._samples[discard:].copy()
                self._buffer_start += discard
        else:
            self._samples = np.empty(0, dtype=np.float32)
            self._buffer_start = self._input_frames
        return result
