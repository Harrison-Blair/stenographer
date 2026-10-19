# SPDX-License-Identifier: GPL-3.0-or-later
"""Speaker embedding state and pure online clustering."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


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

    def assign(self, embedding: np.ndarray) -> str | None:
        """Return the best matching speaker ID or create a new cluster."""
        if self.speakers:
            scores = [speaker.similarity(embedding) for speaker in self.speakers]
            best_index = int(np.argmax(scores))
            if scores[best_index] >= self.threshold:
                speaker = self.speakers[best_index]
                speaker.include(embedding)
                return speaker.speaker_id

        speaker_id = f"speaker-{self.next_number}"
        self.next_number += 1
        self.speakers.append(Speaker(speaker_id, embedding.copy()))
        return speaker_id
