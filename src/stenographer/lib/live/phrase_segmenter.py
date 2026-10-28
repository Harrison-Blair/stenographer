# SPDX-License-Identifier: GPL-3.0-or-later
"""Cut 16 kHz audio blocks into Silero VAD speech phrases."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from stenographer.lib.live.phrase import Phrase

_RATE = 16000
_VAD_WINDOW = 512


class PhraseSegmenter:
    """Turn 16 kHz mono blocks into timestamped phrases for one source."""

    def __init__(
        self,
        source: str,
        vad_model_path: Path | str,
        *,
        max_phrase_seconds: float = 25,
    ) -> None:
        if max_phrase_seconds <= 0:
            raise ValueError("maximum phrase length must be greater than zero")
        import sherpa_onnx

        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = str(vad_model_path)
        config.silero_vad.threshold = 0.5
        config.silero_vad.min_speech_duration = 0.25
        config.silero_vad.min_silence_duration = 0.6
        config.silero_vad.max_speech_duration = max_phrase_seconds
        config.sample_rate = _RATE
        config.num_threads = 1
        config.provider = "cpu"
        if not config.validate():
            raise ValueError(f"Invalid Silero VAD model: {vad_model_path}")
        self._source = source
        self._max_phrase_frames = round(max_phrase_seconds * _RATE)
        self._vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=120)
        self._flushed = False

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
        for offset in range(0, samples.size, _VAD_WINDOW):
            self._vad.accept_waveform(samples[offset : offset + _VAD_WINDOW])
        return self._drain()

    def flush(self) -> list[Phrase]:
        """Flush and return any speech phrase that remains open."""
        if self._flushed:
            return []
        self._flushed = True
        self._vad.flush()
        return self._drain()

    def _drain(self) -> list[Phrase]:
        phrases: list[Phrase] = []
        while not self._vad.empty():
            segment = self._vad.front
            samples = np.asarray(segment.samples, dtype=np.float32).reshape(-1)
            start_frame = int(segment.start)
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
