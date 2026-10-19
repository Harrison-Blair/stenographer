# SPDX-License-Identifier: GPL-3.0-or-later
"""Speaker embedding extraction and display labels."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from stenographer.lib.live.speaker import SpeakerClustering


class SpeakerTracker:
    """Extract phrase embeddings, assign IDs, and manage speaker labels."""

    def __init__(self, model_path: str | Path, threshold: float = 0.50, num_threads: int = 2):
        import sherpa_onnx

        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(model_path), num_threads=num_threads, debug=False, provider="cpu"
        )
        self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        self._clustering = SpeakerClustering(threshold)
        self._names: dict[str, str] = {}

    def assign(self, samples: np.ndarray) -> str:
        """Return the speaker ID for an audio phrase."""
        stream = self._extractor.create_stream()
        waveform = np.ascontiguousarray(samples, dtype=np.float32)
        stream.accept_waveform(sample_rate=16000, waveform=waveform)
        stream.input_finished()
        if not self._extractor.is_ready(stream):
            seconds = len(waveform) / 16000
            raise ValueError(f"Speaker embedding model rejected a {seconds:.1f}s phrase")
        embedding = np.asarray(self._extractor.compute(stream), dtype=np.float32)
        return self._clustering.assign(embedding)

    def label(self, speaker_id: str) -> str:
        """Return the display label for a speaker ID."""
        if speaker_id == "you":
            return "You"
        return self._names.get(speaker_id, f"Speaker {speaker_id.removeprefix('speaker-')}")

    def rename(self, speaker_id: str, name: str) -> None:
        """Set a display label for a speaker ID."""
        if speaker_id == "you":
            raise ValueError("The microphone source cannot be renamed")
        label = name.strip()
        if not label:
            raise ValueError("Speaker name cannot be empty")
        if not any(speaker.speaker_id == speaker_id for speaker in self._clustering.speakers):
            raise ValueError(f"Unknown speaker ID: {speaker_id}")
        self._names[speaker_id] = label
