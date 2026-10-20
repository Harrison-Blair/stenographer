# SPDX-License-Identifier: GPL-3.0-or-later
"""Batch-cluster live system phrases and preserve renamed labels."""

from __future__ import annotations

import heapq
from collections.abc import Callable, Iterable
from dataclasses import replace

import numpy as np

from stenographer.lib.live.speaker import MINIMUM_SPEECH_DURATION_SECONDS
from stenographer.lib.live.transcript_line import TranscriptLine

_MINIMUM_CLUSTER_SPEECH_FRACTION = 0.20
# Positive cosine evidence allows weak duplicates but keeps orthogonal voices separate.
_MINIMUM_SMALL_CLUSTER_SIMILARITY = 0.05


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

    anchor_vectors = vectors[anchor_indices]
    anchor_count = len(anchor_indices)
    capacity = 2 * anchor_count - 1
    similarities = np.full((capacity, capacity), -np.inf, dtype=np.float32)
    active = np.zeros(capacity, dtype=bool)
    active[:anchor_count] = True
    sizes = np.zeros(capacity, dtype=np.float64)
    sizes[:anchor_count] = 1.0
    clusters = {index: [phrase_index] for index, phrase_index in enumerate(anchor_indices)}
    queue: list[tuple[float, int, int]] = []
    total = 2 * anchor_count + len(original)
    if progress is not None:
        progress(0, total)

    for row in range(anchor_count):
        if should_cancel is not None and should_cancel():
            return None
        row_scores = anchor_vectors[row + 1 :] @ anchor_vectors[row]
        similarities[row, row + 1 : anchor_count] = row_scores
        similarities[row + 1 : anchor_count, row] = row_scores
        for offset in np.flatnonzero(row_scores >= threshold):
            column = row + 1 + int(offset)
            heapq.heappush(queue, (-float(row_scores[offset]), row, column))
        if progress is not None:
            progress(row + 1, total)

    next_cluster = anchor_count
    while queue:
        if should_cancel is not None and should_cancel():
            return None
        negative_score, left, right = heapq.heappop(queue)
        if not active[left] or not active[right] or -negative_score < threshold:
            continue

        merged_size = sizes[left] + sizes[right]
        members = clusters.pop(left) + clusters.pop(right)
        clusters[next_cluster] = members
        active[left] = False
        active[right] = False
        active[next_cluster] = True
        sizes[next_cluster] = merged_size
        for other in np.flatnonzero(active[:next_cluster]):
            score = (
                sizes[left] * similarities[left, other] + sizes[right] * similarities[right, other]
            ) / merged_size
            similarities[next_cluster, other] = score
            similarities[other, next_cluster] = score
            if score >= threshold:
                heapq.heappush(queue, (-float(score), int(other), next_cluster))
        next_cluster += 1
        if progress is not None:
            progress(next_cluster, total)

    if should_cancel is not None and should_cancel():
        return None

    ordered_clusters = sorted(clusters.values(), key=min)
    cluster_times = [sum(durations[index] for index in members) for members in ordered_clusters]
    minimum_cluster_time = max(cluster_times) * _MINIMUM_CLUSTER_SPEECH_FRACTION
    core_indices = [
        index for index, duration in enumerate(cluster_times) if duration >= minimum_cluster_time
    ]
    if not core_indices:
        core_indices = [int(np.argmax(cluster_times))]

    def centroid(members: list[int]) -> np.ndarray:
        member_vectors = vectors[members]
        weights = durations[members]
        mean = (
            np.average(member_vectors, axis=0, weights=weights)
            if np.sum(weights) > 0
            else np.mean(member_vectors, axis=0)
        )
        norm = np.linalg.norm(mean)
        return mean / norm if norm > 0 else member_vectors[0]

    core_vectors = {index: centroid(ordered_clusters[index]) for index in core_indices}
    core_clusters = {index: list(ordered_clusters[index]) for index in core_indices}
    progress_done = next_cluster
    for index, members in enumerate(ordered_clusters):
        if index in core_clusters:
            continue
        if should_cancel is not None and should_cancel():
            return None
        member_vectors = vectors[members]
        weights = durations[members]
        candidate_indices = list(core_clusters)
        scores = []
        for core_index in candidate_indices:
            similarities = member_vectors @ core_vectors[core_index]
            score = (
                np.average(similarities, weights=weights)
                if np.sum(weights) > 0
                else np.mean(similarities)
            )
            scores.append(float(score))
        best_candidate = int(np.argmax(scores))
        if scores[best_candidate] >= _MINIMUM_SMALL_CLUSTER_SIMILARITY:
            chosen = candidate_indices[best_candidate]
            core_clusters[chosen].extend(members)
        else:
            core_clusters[index] = list(members)
            core_vectors[index] = centroid(members)
        progress_done += 1
        if progress is not None:
            progress(progress_done, total)
    clusters = core_clusters

    for phrase_index, duration in enumerate(durations):
        if duration >= minimum_duration:
            continue
        if should_cancel is not None and should_cancel():
            return None
        scores = []
        for members in clusters.values():
            members_array = np.asarray(members, dtype=np.intp)
            similarities = vectors[members_array] @ vectors[phrase_index]
            weights = durations[members_array]
            if np.sum(weights) > 0:
                scores.append(float(np.average(similarities, weights=weights)))
            else:
                scores.append(float(np.mean(similarities)))
        root = next(iter(clusters))
        if scores:
            root = list(clusters)[int(np.argmax(scores))]
        clusters[root].append(phrase_index)
        progress_done += 1
        if progress is not None:
            progress(progress_done, total)

    if progress is not None:
        progress(total, total)
    ranked_clusters = sorted(clusters.values(), key=lambda members: min(members))
    speaker_ids: dict[int, str] = {}
    label_weights_by_cluster: list[dict[str, float]] = []
    renamed_labels = {
        line.label
        for line in original
        if line.label != f"Speaker {line.speaker_id.removeprefix('speaker-')}"
    }
    for number, members in enumerate(ranked_clusters, 1):
        label_weights: dict[str, float] = {}
        speaker_id = f"speaker-{number}"
        for index in members:
            label = original[index].label
            label_weights[label] = label_weights.get(label, 0.0) + durations[index]
            speaker_ids[index] = speaker_id
        label_weights_by_cluster.append(label_weights)

    label_matches = sorted(
        (
            -speech_time,
            cluster_index,
            label,
        )
        for cluster_index, label_weights in enumerate(label_weights_by_cluster)
        for label, speech_time in label_weights.items()
        if label in renamed_labels
    )
    cluster_labels: dict[int, str] = {}
    assigned_labels: set[str] = set()
    for _negative_speech_time, cluster_index, label in label_matches:
        if cluster_index in cluster_labels or label in assigned_labels:
            continue
        cluster_labels[cluster_index] = label
        assigned_labels.add(label)

    next_number = 1
    for cluster_index in range(len(ranked_clusters)):
        if cluster_index in cluster_labels:
            continue
        label = f"Speaker {next_number}"
        while label in assigned_labels:
            next_number += 1
            label = f"Speaker {next_number}"
        cluster_labels[cluster_index] = label
        assigned_labels.add(label)
        next_number += 1

    labels_by_speaker = {
        f"speaker-{cluster_index + 1}": label for cluster_index, label in cluster_labels.items()
    }
    return tuple(
        replace(
            line,
            speaker_id=speaker_ids[index],
            label=labels_by_speaker[speaker_ids[index]],
        )
        for index, line in enumerate(original)
    )
