# SPDX-License-Identifier: GPL-3.0-or-later
"""Speaker embedding extraction and display labels."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# 1.2 seconds separates brief fillers from phrases stable enough for live clustering.
MINIMUM_SPEECH_DURATION_SECONDS = 1.2
# Below this score, continuity is a safer assignment for a short phrase.
_SHORT_PHRASE_FALLBACK_SIMILARITY = 0.25
_THRESHOLD = 0.50
_NUM_THREADS = 2


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

        speaker = Speaker(self.new_speaker_id(), embedding.copy())
        self.speakers.append(speaker)
        self.previous_speaker_id = speaker.speaker_id
        return speaker.speaker_id

    def assign_nearest(self, embedding: np.ndarray) -> str:
        """Return the nearest speaker ID. Only the first embedding creates a speaker."""
        if not self.speakers:
            speaker = Speaker(self.new_speaker_id(), embedding.copy())
            self.speakers.append(speaker)
            return speaker.speaker_id
        scores = [speaker.similarity(embedding) for speaker in self.speakers]
        return self.speakers[int(np.argmax(scores))].speaker_id

    def new_speaker_id(self) -> str:
        """Return an ID with a number that this clustering has not used."""
        speaker_id = f"{self.id_prefix}-{self.next_number}"
        self.next_number += 1
        return speaker_id


class SpeakerTracker:
    """Extract phrase embeddings, assign IDs, and manage speaker labels."""

    def __init__(
        self,
        model_path: str | Path,
        *,
        label_prefix: str = "Speaker",
    ):
        import sherpa_onnx

        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(model_path), num_threads=_NUM_THREADS, debug=False, provider="cpu"
        )
        self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        self._label_prefix = label_prefix
        self._id_prefix = f"{label_prefix.lower()}-"
        self._clustering = SpeakerClustering(_THRESHOLD, id_prefix=label_prefix.lower())
        self._names: dict[str, str] = {}
        self._merged_into: dict[str, str] = {}
        # Nearest assignment is a guess, so only the first phrase and the phrases
        # that a pass grouped show who a speaker is.
        self._grouped_phrases = 1

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

    def assign_nearest(self, embedding: np.ndarray) -> str:
        """Return the nearest known speaker ID. Only the first embedding creates a speaker."""
        return self._clustering.assign_nearest(embedding)

    def regroup(
        self,
        current_ids: Sequence[str],
        cluster_ids: Sequence[str],
        durations: Sequence[float],
        embeddings: Sequence[np.ndarray],
    ) -> tuple[str, ...]:
        """Adopt a batch grouping of all phrases and return the speaker ID of each phrase.

        Each cluster keeps the known speaker that shares its most grouped speech. A
        renamed speaker chooses first, so its name stays with its speech. A cluster
        with no known speaker gets a new number. A known speaker with no cluster
        stops, and its number is not used again.
        """
        by_speech = self._shared_speech(current_ids, cluster_ids, durations, self._grouped_phrases)
        ids_by_cluster = self._match_clusters(by_speech)
        for cluster in dict.fromkeys(cluster_ids):
            if cluster not in ids_by_cluster:
                ids_by_cluster[cluster] = self._clustering.new_speaker_id()

        kept = set(ids_by_cluster.values())
        for (current, cluster), _speech in by_speech:
            if current not in kept:
                self._merged_into.setdefault(current, ids_by_cluster[cluster])

        speaker_ids = tuple(ids_by_cluster[cluster] for cluster in cluster_ids)
        members: dict[str, list[np.ndarray]] = {}
        for speaker_id, embedding in zip(speaker_ids, embeddings, strict=True):
            members.setdefault(speaker_id, []).append(embedding)
        self._clustering.speakers = [
            Speaker(speaker_id, np.mean(vectors, axis=0), count=len(vectors))
            for speaker_id, vectors in members.items()
        ]
        self._grouped_phrases = len(current_ids)
        return speaker_ids

    def saved_speakers(
        self,
        current_ids: Sequence[str],
        cluster_ids: Sequence[str],
        durations: Sequence[float],
        parents: Sequence[int] | None = None,
    ) -> tuple[tuple[str, str], ...]:
        """Return ``(speaker_id, label)`` of each line for a saved revision.

        Speakers get numbers 1..N in order of first appearance. A given name stays
        with the cluster that its speaker chooses, by the rule of ``regroup``.
        ``parents[i]`` is the recorded phrase that holds line ``i``, if lines were split.
        """
        grouped = self._grouped_phrases
        if parents is not None:
            grouped = sum(parent < grouped for parent in parents)
        matches = self._match_clusters(
            self._shared_speech(current_ids, cluster_ids, durations, grouped)
        )
        speakers = {
            cluster: (
                f"{self._id_prefix}{number}",
                self._names.get(matches.get(cluster), f"{self._label_prefix} {number}"),
            )
            for number, cluster in enumerate(dict.fromkeys(cluster_ids), 1)
        }
        return tuple(speakers[cluster] for cluster in cluster_ids)

    def _shared_speech(
        self,
        current_ids: Sequence[str],
        cluster_ids: Sequence[str],
        durations: Sequence[float],
        grouped: int,
    ) -> list[tuple[tuple[str, str], float]]:
        """Return the grouped speech each speaker shares with each cluster, largest first."""
        shared: dict[tuple[str, str], float] = {}
        for current, cluster, duration in zip(
            current_ids[:grouped], cluster_ids[:grouped], durations[:grouped], strict=True
        ):
            shared[current, cluster] = shared.get((current, cluster), 0.0) + duration
        return sorted(shared.items(), key=lambda item: -item[1])

    def _match_clusters(self, by_speech: list[tuple[tuple[str, str], float]]) -> dict[str, str]:
        """Return the known speaker of each cluster. A renamed speaker chooses first."""
        matches: dict[str, str] = {}
        for (current, cluster), _speech in sorted(
            by_speech, key=lambda item: item[0][0] not in self._names
        ):
            if cluster not in matches and current not in matches.values():
                matches[cluster] = current
        return matches

    def current_id(self, speaker_id: str) -> str:
        """Return the speaker that now holds the phrases of *speaker_id*."""
        while speaker_id in self._merged_into:
            speaker_id = self._merged_into[speaker_id]
        return speaker_id

    def label(self, speaker_id: str) -> str:
        """Return the display label for a speaker ID."""
        number = speaker_id.removeprefix(self._id_prefix)
        return self._names.get(speaker_id, f"{self._label_prefix} {number}")

    def checked_name(self, speaker_id: str, name: str) -> str:
        """Return the display label for *name*, or raise if it cannot be set."""
        label = name.strip()
        if not label:
            raise ValueError("Speaker name cannot be empty")
        if not any(speaker.speaker_id == speaker_id for speaker in self._clustering.speakers):
            raise ValueError(f"Unknown speaker ID: {speaker_id}")
        return label

    def rename(self, speaker_id: str, name: str) -> None:
        """Set a display label for a speaker ID."""
        self._names[speaker_id] = self.checked_name(speaker_id, name)
