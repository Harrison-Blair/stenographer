# SPDX-License-Identifier: GPL-3.0-or-later
"""Cut 16 kHz audio blocks into Silero VAD speech phrases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from stenographer.lib.live.errors import InvalidVadModelError


@dataclass(frozen=True)
class Phrase:
    """One VAD speech interval with times in the session clock."""

    source: str
    start: float
    end: float
    samples: np.ndarray


_RATE = 16000
_VAD_WINDOW = 512
_MAX_PHRASE_SECONDS = 25
_VAD_BUFFER_SECONDS = 120
_GAIN_TARGET = 0.1
_GAIN_MAX = 50.0
_GAIN_HALF_LIFE_SECONDS = 10.0
#: The lowest peak, so the gain never exceeds ``_GAIN_MAX``.
_GAIN_FLOOR = _GAIN_TARGET / _GAIN_MAX
_GAIN_DECAY = 0.5 ** (_VAD_WINDOW / _RATE / _GAIN_HALF_LIFE_SECONDS)


def detector_gain(window: np.ndarray, peak: float) -> tuple[np.ndarray, float]:
    """Scale one detector window toward the target level. PURE.

    *peak* is the running level from the previous window (``_GAIN_FLOOR`` at the
    start). It follows a louder window at once and decays with a 10 s
    half-life. Return the scaled window, clipped to ±1, and the new peak.
    """
    rms = float(np.sqrt(np.mean(np.square(window, dtype=np.float64)))) if window.size else 0.0
    peak = max(rms, peak * _GAIN_DECAY, _GAIN_FLOOR)
    scaled = np.clip(window * np.float32(_GAIN_TARGET / peak), -1.0, 1.0).astype(np.float32)
    return scaled, peak


class PhraseSegmenter:
    """Turn 16 kHz mono blocks into timestamped phrases for one source.

    The detector hears the audio through :func:`detector_gain`, so a quiet
    microphone is detected like a loud one. Each phrase holds the original
    samples: sherpa-onnx returns the scaled samples it received, so a phrase is
    cut from the original audio by the segment start and length.
    """

    def __init__(
        self,
        source: str,
        vad_model_path: Path | str,
    ) -> None:
        import sherpa_onnx

        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = str(vad_model_path)
        config.silero_vad.threshold = 0.3
        config.silero_vad.min_speech_duration = 0.25
        config.silero_vad.min_silence_duration = 0.6
        config.silero_vad.max_speech_duration = _MAX_PHRASE_SECONDS
        config.sample_rate = _RATE
        config.num_threads = 1
        config.provider = "cpu"
        if not config.validate():
            raise InvalidVadModelError(f"Invalid Silero VAD model: {vad_model_path}")
        self._source = source
        self._max_phrase_frames = round(_MAX_PHRASE_SECONDS * _RATE)
        self._vad = sherpa_onnx.VoiceActivityDetector(
            config, buffer_size_in_seconds=_VAD_BUFFER_SECONDS
        )
        self._flushed = False
        self._peak = _GAIN_FLOOR
        self._pending = np.empty(0, dtype=np.float32)
        # The original audio the detector may still return a segment of: at
        # most its own buffer, so a recording of hours keeps a bounded tail.
        self._kept: list[np.ndarray] = []
        self._kept_start = 0
        self._fed = 0

    @property
    def speech_detected(self) -> bool:
        """Return whether the voice detector hears speech in the latest audio."""
        return bool(self._vad.is_speech_detected())

    def accept(self, block: np.ndarray) -> list[Phrase]:
        """Accept one mono block and return all phrases now available."""
        if self._flushed:
            raise RuntimeError("cannot accept audio after flush")
        samples = np.asarray(block, dtype=np.float32)
        if samples.ndim != 1:
            raise ValueError("audio block must be one-dimensional mono float32")
        pending = np.concatenate((self._pending, samples))
        whole = pending.size - pending.size % _VAD_WINDOW
        for offset in range(0, whole, _VAD_WINDOW):
            self._feed(pending[offset : offset + _VAD_WINDOW])
        self._pending = pending[whole:].copy()
        return self._drain()

    def flush(self) -> list[Phrase]:
        """Flush and return any speech phrase that remains open."""
        if self._flushed:
            return []
        self._flushed = True
        if self._pending.size:
            self._feed(self._pending)
            self._pending = np.empty(0, dtype=np.float32)
        self._vad.flush()
        return self._drain()

    def _feed(self, window: np.ndarray) -> None:
        scaled, self._peak = detector_gain(window, self._peak)
        self._vad.accept_waveform(scaled)
        self._kept.append(window.copy())
        self._fed += window.size
        oldest = self._fed - _VAD_BUFFER_SECONDS * _RATE
        while self._kept and self._kept_start + self._kept[0].size <= oldest:
            self._kept_start += self._kept.pop(0).size

    def _original(self, start: int, frames: int) -> np.ndarray:
        """Cut ``frames`` original samples from session frame ``start``."""
        if start < self._kept_start or start + frames > self._fed:
            raise RuntimeError(
                f"VAD segment {start}+{frames} is outside the kept audio "
                f"{self._kept_start}..{self._fed}"
            )
        offset = start - self._kept_start
        return np.concatenate(self._kept)[offset : offset + frames]

    def _drain(self) -> list[Phrase]:
        phrases: list[Phrase] = []
        while not self._vad.empty():
            segment = self._vad.front
            start_frame = int(segment.start)
            samples = self._original(start_frame, len(segment.samples))
            for offset in range(0, samples.size, self._max_phrase_frames):
                phrase_samples = np.ascontiguousarray(
                    samples[offset : offset + self._max_phrase_frames]
                ).copy()
                start = (start_frame + offset) / _RATE
                phrases.append(
                    Phrase(
                        source=self._source,
                        start=start,
                        end=start + phrase_samples.size / _RATE,
                        samples=phrase_samples,
                    )
                )
            self._vad.pop()
        return phrases
