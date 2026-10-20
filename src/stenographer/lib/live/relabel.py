# SPDX-License-Identifier: GPL-3.0-or-later
"""Batch-cluster live system phrases and preserve renamed labels."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace

import numpy as np

from stenographer.lib.live.speaker import MINIMUM_SPEECH_DURATION_SECONDS
from stenographer.lib.live.transcript_line import TranscriptLine


def relabel_system_lines(
    lines: Iterable[TranscriptLine],
    embeddings: Iterable[np.ndarray],
    *,
    threshold: float = 0.5,
    minimum_duration: float = MINIMUM_SPEECH_DURATION_SECONDS,
    progress: Callable[[int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[TranscriptLine, ...] | None:
    """Relabel system phrases from the session's full set of embeddings."""
    original = tuple(lines)
    vectors = np.asarray(tuple(embeddings), dtype=np.float32)
    if not original:
        return ()
    if vectors.ndim != 2 or len(vectors) != len(original):
        raise ValueError("each system phrase must have one speaker embedding")
    if not np.all(np.isfinite(vectors)):
        raise ValueError("speaker embeddings must be finite")

    norms = np.linalg.norm(vectors, axis=1)
    if np.any(norms == 0):
        raise ValueError("speaker embeddings must not be empty")
    vectors = vectors / norms[:, np.newaxis]
    durations = np.asarray([max(0.0, line.end - line.start) for line in original])
    anchor_indices = [
        index for index, duration in enumerate(durations) if duration >= minimum_duration
    ]
    if not anchor_indices:
        anchor_indices = list(range(len(original)))

    parents = list(range(len(anchor_indices)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    anchor_vectors = vectors[anchor_indices]
    anchor_count = len(anchor_indices)
    for row in range(anchor_count):
        if should_cancel is not None and should_cancel():
            return None
        similarities = anchor_vectors[row + 1 :] @ anchor_vectors[row]
        for offset in np.flatnonzero(similarities >= threshold):
            union(row, row + 1 + int(offset))
        if progress is not None:
            progress(row + 1, anchor_count)

    clusters: dict[int, list[int]] = {}
    for position, phrase_index in enumerate(anchor_indices):
        root = find(position)
        clusters.setdefault(root, []).append(phrase_index)

    for phrase_index, duration in enumerate(durations):
        if duration >= minimum_duration:
            continue
        if should_cancel is not None and should_cancel():
            return None
        scores = []
        for members in clusters.values():
            members_array = np.asarray(members, dtype=np.intp)
            similarities = vectors[members_array] @ vectors[phrase_index]
            weighted = np.maximum(similarities, 0.0) * durations[members_array]
            scores.append(float(np.sum(weighted)))
        root = next(iter(clusters))
        if scores:
            root = list(clusters)[int(np.argmax(scores))]
        clusters[root].append(phrase_index)

    ranked_clusters = sorted(clusters.values(), key=lambda members: min(members))
    speaker_ids: dict[int, str] = {}
    cluster_labels: dict[str, str] = {}
    for number, members in enumerate(ranked_clusters, 1):
        label_weights: dict[str, float] = {}
        speaker_id = f"speaker-{number}"
        for index in members:
            label = original[index].label
            label_weights[label] = label_weights.get(label, 0.0) + durations[index]
            speaker_ids[index] = speaker_id
        cluster_labels[speaker_id] = max(label_weights, key=label_weights.get)

    return tuple(
        replace(
            line,
            speaker_id=speaker_ids[index],
            label=cluster_labels[speaker_ids[index]],
        )
        for index, line in enumerate(original)
    )
