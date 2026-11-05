# SPDX-License-Identifier: GPL-3.0-or-later
"""Stateful polyphase resampling for callback-driven audio."""

from __future__ import annotations

import math

import numpy as np

from stenographer.lib.audio.resample import _polyphase_filter

#: Output samples per filter evaluation; bounds the index matrices on file blocks.
_MAX_BATCH_OUTPUTS = 4096


class StreamingResampler:
    """Resample mono float32 blocks while retaining only filter history."""

    def __init__(self, rate_in: int, rate_out: int) -> None:
        gcd = math.gcd(rate_in, rate_out)
        self._up = rate_out // gcd
        self._down = rate_in // gcd
        self._rate_in = rate_in
        self._rate_out = rate_out
        self._filter = _polyphase_filter(self._up, self._down)
        self._n_taps = self._filter.size
        self._half = self._n_taps // 2
        # Every phase reads the same tap count; a shorter one reads padded zeros.
        self._tap_count = (self._n_taps + self._up - 1) // self._up
        self._padded_filter = np.concatenate(
            (self._filter, np.zeros(self._tap_count * self._up - self._n_taps, np.float32))
        )
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
            return block.copy()

        self._samples = np.concatenate((self._samples, block))
        self._input_frames += block.size
        stop = (self._input_frames * self._up - self._half + self._down - 1) // self._down
        result = self._produce(stop)
        center = self._half + self._next_output * self._down
        keep_from = max(0, (center - self._n_taps + self._up) // self._up)
        discard = min(keep_from - self._buffer_start, self._samples.size)
        if discard > 0:
            self._samples = self._samples[discard:].copy()
            self._buffer_start += discard
        return result

    def flush(self) -> np.ndarray:
        """Return the remaining output samples with zero-padding at end of input."""
        if self._rate_in == self._rate_out:
            return np.empty(0, dtype=np.float32)
        result = self._produce((self._input_frames * self._up + self._down - 1) // self._down)
        self._samples = np.empty(0, dtype=np.float32)
        self._buffer_start = self._input_frames
        return result

    def _produce(self, stop_output: int) -> np.ndarray:
        """Filter outputs ``_next_output`` to ``stop_output``; absent input reads as zero."""
        count = stop_output - self._next_output
        if count <= 0:
            return np.empty(0, dtype=np.float32)
        padding = np.zeros(self._tap_count, dtype=np.float32)
        padded = np.concatenate((padding, self._samples, padding))
        offsets = np.arange(self._tap_count)
        result = np.empty(count, dtype=np.float32)
        for start in range(0, count, _MAX_BATCH_OUTPUTS):
            outputs = self._next_output + np.arange(start, min(start + _MAX_BATCH_OUTPUTS, count))
            centers = self._half + outputs * self._down
            taps = (centers % self._up)[:, None] + offsets * self._up
            inputs = (centers // self._up)[:, None] - offsets - self._buffer_start + self._tap_count
            values = padded[inputs] * self._padded_filter[taps]
            result[outputs - self._next_output] = values.sum(axis=1, dtype=np.float32)
        self._next_output = stop_output
        return result
