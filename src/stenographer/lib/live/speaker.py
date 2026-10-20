# SPDX-License-Identifier: GPL-3.0-or-later
"""Speaker embedding state and pure online clustering."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# In the consented recording, 335 VAD phrases were shorter than 1.2 seconds.
MINIMUM_SPEECH_DURATION_SECONDS = 1.2
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
                        speaker,
                    )
                self.previous_speaker_id = speaker.speaker_id
                return speaker.speaker_id
            if scores[best_index] >= self.threshold:
                speaker.include(embedding)
                self.previous_speaker_id = speaker.speaker_id
                return speaker.speaker_id

        speaker_id = f"speaker-{self.next_number}"
        self.next_number += 1
        self.speakers.append(Speaker(speaker_id, embedding.copy()))
        self.previous_speaker_id = speaker_id
        return speaker_id
