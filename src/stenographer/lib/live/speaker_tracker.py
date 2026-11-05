# SPDX-License-Identifier: GPL-3.0-or-later
"""Speaker embedding extraction and display labels."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# 1.2 seconds separates brief fillers from phrases stable enough for live clustering.
MINIMUM_SPEECH_DURATION_SECONDS = 1.2
# Below this score, continuity is a safer assignment for a short phrase.
_SHORT_PHRASE_FALLBACK_SIMILARITY = 0.25


@dataclass
class Speaker:
    """The mean embedding and count for one known speaker."""

    speaker_id: str
    mean_embedding: np.ndarray
    count: int = 1

    def similarity(self, embedding: np.ndarray) -> float:
        """Return the cosine score against this speaker's mean embedding."""
        return float(
            np.dot(embedding, self.mean_embedding)
            / (np.linalg.norm(embedding) * np.linalg.norm(self.mean_embedding))
        )

    def include(self, embedding: np.ndarray) -> None:
        """Update this speaker's arithmetic mean embedding."""
        self.count += 1
        self.mean_embedding += (embedding - self.mean_embedding) / self.count


@dataclass
class SpeakerClustering:
    """Assign embeddings to speaker IDs without a model dependency."""

    threshold: float
    speakers: list[Speaker] = field(default_factory=list)
    next_number: int = 1
    previous_speaker_id: str | None = None
    id_prefix: str = "speaker"

    def assign(self, embedding: np.ndarray, *, duration: float | None = None) -> str:
        """Return the best matching speaker ID or create a new cluster."""
        if self.speakers:
            scores = [speaker.similarity(embedding) for speaker in self.speakers]
            best_index = int(np.argmax(scores))
            speaker = self.speakers[best_index]
            is_short = duration is not None and duration < MINIMUM_SPEECH_DURATION_SECONDS
            if is_short:
                if scores[best_index] < _SHORT_PHRASE_FALLBACK_SIMILARITY:
                    speaker = next(
                        (
                            known
                            for known in self.speakers
                            if known.speaker_id == self.previous_speaker_id
                        ),
                    )
                self.previous_speaker_id = speaker.speaker_id
                return speaker.speaker_id
            if scores[best_index] >= self.threshold:
                speaker.include(embedding)
                self.previous_speaker_id = speaker.speaker_id
                return speaker.speaker_id

        speaker_id = f"{self.id_prefix}-{self.next_number}"
        self.next_number += 1
        self.speakers.append(Speaker(speaker_id, embedding.copy()))
        self.previous_speaker_id = speaker_id
        return speaker_id


class SpeakerTracker:
    """Extract phrase embeddings, assign IDs, and manage speaker labels."""

    def __init__(
        self,
        model_path: str | Path,
        threshold: float = 0.50,
        num_threads: int = 2,
        *,
        label_prefix: str = "Speaker",
    ):
        import sherpa_onnx

        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(model_path), num_threads=num_threads, debug=False, provider="cpu"
        )
        self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        self._label_prefix = label_prefix
        self._id_prefix = f"{label_prefix.lower()}-"
        self._clustering = SpeakerClustering(threshold, id_prefix=label_prefix.lower())
        self._names: dict[str, str] = {}

    @property
    def speaker_ids(self) -> tuple[str, ...]:
        """Return the known speaker IDs in order of appearance."""
        return tuple(speaker.speaker_id for speaker in self._clustering.speakers)

    def assign(self, samples: np.ndarray, *, duration: float | None = None) -> str:
        """Return the speaker ID for an audio phrase."""
        return self.assign_embedding(self.embed(samples), duration=duration)

    def embed(self, samples: np.ndarray) -> np.ndarray:
        """Return the speaker embedding for an audio phrase."""
        stream = self._extractor.create_stream()
        waveform = np.ascontiguousarray(samples, dtype=np.float32)
        stream.accept_waveform(sample_rate=16000, waveform=waveform)
        stream.input_finished()
        if not self._extractor.is_ready(stream):
            seconds = len(waveform) / 16000
            raise ValueError(f"Speaker embedding model rejected a {seconds:.1f}s phrase")
        return np.asarray(self._extractor.compute(stream), dtype=np.float32)

    def assign_embedding(self, embedding: np.ndarray, *, duration: float | None = None) -> str:
        """Return the speaker ID for a precomputed embedding."""
        return self._clustering.assign(embedding, duration=duration)

    def label(self, speaker_id: str) -> str:
        """Return the display label for a speaker ID."""
        if speaker_id == "you":
            return "You"
        number = speaker_id.removeprefix(self._id_prefix)
        return self._names.get(speaker_id, f"{self._label_prefix} {number}")

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
