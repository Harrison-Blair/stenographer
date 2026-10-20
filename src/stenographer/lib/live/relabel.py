# SPDX-License-Identifier: GPL-3.0-or-later
"""Batch-cluster live system phrases and preserve renamed labels."""

from __future__ import annotations

import heapq
from collections.abc import Callable, Iterable
from dataclasses import replace

import numpy as np

from stenographer.lib.live.speaker import MINIMUM_SPEECH_DURATION_SECONDS
from stenographer.lib.live.transcript_line import TranscriptLine

# A cluster with at least one fifth of the largest cluster's speech is a core voice.
_MINIMUM_CLUSTER_SPEECH_FRACTION = 0.20
# Two-second phrases provide sustained turns rather than brief vocal residue.
_MINIMUM_SUSTAINED_PHRASE_SECONDS = 2.0
# Fifteen seconds of sustained phrases provides meaningful minor-voice support.
_MINIMUM_SUSTAINED_SPEECH_SECONDS = 15.0
# A half-minute window groups nearby turns and rejects sparse residue.
_SUSTAINED_SPEECH_WINDOW_SECONDS = 30.0
# Two-thirds of a cluster's speech must come from sustained phrases.
_MINIMUM_SUSTAINED_SPEECH_FRACTION = 2 / 3


def relabel_system_lines(
    lines: Iterable[TranscriptLine],
    embeddings: Iterable[np.ndarray],
    *,
    threshold: float = 0.5,
    minimum_duration: float = MINIMUM_SPEECH_DURATION_SECONDS,
    progress: Callable[[int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    speaker_count: int | None = None,
) -> tuple[TranscriptLine, ...] | None:
    """Relabel system phrases from the session's full set of embeddings."""
    if speaker_count is not None and (
        isinstance(speaker_count, bool) or not isinstance(speaker_count, int) or speaker_count < 1
    ):
        raise ValueError("speaker_count must be a positive integer")
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
    if speaker_count is not None:
        return _relabel_fixed(
            original,
            vectors,
            durations,
            speaker_count,
            progress=progress,
            should_cancel=should_cancel,
        )
    anchor_indices = [
        index for index, duration in enumerate(durations) if duration >= minimum_duration
    ]
    if not anchor_indices:
        if progress is not None:
            progress(0, len(original))
        representative = int(np.argmax(durations))
        speaker_id = original[representative].speaker_id
        label = original[representative].label
        result = tuple(replace(line, speaker_id=speaker_id, label=label) for line in original)
        if progress is not None:
            progress(len(original), len(original))
        return result

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
    unassigned_indices: list[int] = []
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
        sustained_phrases = sorted(
            (original[member].start, durations[member])
            for member in members
            if durations[member] >= _MINIMUM_SUSTAINED_PHRASE_SECONDS
        )
        sustained_window_speech = 0.0
        right = 0
        has_sustained_speech = False
        for window_start, phrase_duration in sustained_phrases:
            while (
                right < len(sustained_phrases)
                and sustained_phrases[right][0] < window_start + _SUSTAINED_SPEECH_WINDOW_SECONDS
            ):
                sustained_window_speech += sustained_phrases[right][1]
                right += 1
            if sustained_window_speech >= _MINIMUM_SUSTAINED_SPEECH_SECONDS:
                has_sustained_speech = True
                break
            sustained_window_speech -= phrase_duration
        # Merge a minor cluster as a whole only when it clears the live threshold.
        if scores[best_candidate] >= threshold:
            core_clusters[candidate_indices[best_candidate]].extend(members)
        elif has_sustained_speech:
            core_clusters[index] = list(members)
            core_vectors[index] = centroid(members)
        else:
            # Unsupported phrases vote individually and cannot seed a speaker label.
            unassigned_indices.extend(members)
        progress_done += 1
        if progress is not None:
            progress(progress_done, total)
    clusters = core_clusters

    def assign_to_best_cluster(phrase_index: int) -> None:
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

    unassigned_indices.extend(
        index for index, duration in enumerate(durations) if duration < minimum_duration
    )
    for phrase_index in unassigned_indices:
        if should_cancel is not None and should_cancel():
            return None
        assign_to_best_cluster(phrase_index)
        progress_done += 1
        if progress is not None:
            progress(progress_done, total)

    pruned_indices: list[int] = []
    for cluster_index in tuple(clusters):
        if cluster_index in core_indices:
            continue
        if should_cancel is not None and should_cancel():
            return None
        members = clusters[cluster_index]
        speech = sum(durations[member] for member in members)
        sustained_speech = sum(
            durations[member]
            for member in members
            if durations[member] >= _MINIMUM_SUSTAINED_PHRASE_SECONDS
        )
        if (
            sustained_speech >= _MINIMUM_SUSTAINED_SPEECH_SECONDS
            and sustained_speech / speech >= _MINIMUM_SUSTAINED_SPEECH_FRACTION
        ):
            continue
        pruned_indices.extend(members)
        del clusters[cluster_index]

    for phrase_index in pruned_indices:
        if should_cancel is not None and should_cancel():
            return None
        assign_to_best_cluster(phrase_index)

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


def _relabel_fixed(
    lines: tuple[TranscriptLine, ...],
    vectors: np.ndarray,
    durations: np.ndarray,
    speaker_count: int,
    *,
    progress: Callable[[int, int], None] | None,
    should_cancel: Callable[[], bool] | None,
) -> tuple[TranscriptLine, ...] | None:
    """Agglomerate all phrases until the requested cluster count remains."""
    phrase_count = len(lines)
    target = min(speaker_count, phrase_count)
    merge_count = phrase_count - target
    total = max(1, phrase_count + merge_count)
    if progress is not None:
        progress(0, total)
    capacity = 2 * phrase_count - 1
    similarities = np.full((capacity, capacity), -np.inf, dtype=np.float32)
    active = np.zeros(capacity, dtype=bool)
    active[:phrase_count] = True
    sizes = np.zeros(capacity, dtype=np.float64)
    sizes[:phrase_count] = np.where(durations > 0, durations, 1.0)
    clusters = {index: [index] for index in range(phrase_count)}
    pending: list[tuple[float, int, int]] = []
    for left in range(phrase_count):
        if should_cancel is not None and should_cancel():
            return None
        scores = vectors[left + 1 :] @ vectors[left]
        similarities[left, left + 1 : phrase_count] = scores
        similarities[left + 1 : phrase_count, left] = scores
        for offset, score in enumerate(scores, start=left + 1):
            heapq.heappush(pending, (-float(score), left, offset))
        if progress is not None:
            progress(left + 1, total)

    next_cluster = phrase_count
    active_count = phrase_count
    done = 0
    while active_count > target:
        if should_cancel is not None and should_cancel():
            return None
        _negative_score, left, right = heapq.heappop(pending)
        if not active[left] or not active[right]:
            continue
        merged_size = sizes[left] + sizes[right]
        clusters[next_cluster] = sorted(clusters.pop(left) + clusters.pop(right))
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
            heapq.heappush(pending, (-float(score), int(other), next_cluster))
        next_cluster += 1
        active_count -= 1
        done += 1
        if progress is not None:
            progress(phrase_count + done, total)

    if should_cancel is not None and should_cancel():
        return None
    ranked_clusters = sorted(clusters.values(), key=min)
    speaker_ids: dict[int, str] = {}
    label_weights_by_cluster: list[dict[str, float]] = []
    renamed_labels = {
        line.label
        for line in lines
        if line.label != f"Speaker {line.speaker_id.removeprefix('speaker-')}"
    }
    for number, members in enumerate(ranked_clusters, 1):
        label_weights: dict[str, float] = {}
        for index in members:
            speaker_ids[index] = f"speaker-{number}"
            label = lines[index].label
            label_weights[label] = label_weights.get(label, 0.0) + durations[index]
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
    labels_by_cluster: dict[int, str] = {}
    assigned_labels: set[str] = set()
    for _negative_speech_time, cluster_index, label in label_matches:
        if cluster_index in labels_by_cluster or label in assigned_labels:
            continue
        labels_by_cluster[cluster_index] = label
        assigned_labels.add(label)

    next_number = 1
    for cluster_index in range(len(ranked_clusters)):
        if cluster_index in labels_by_cluster:
            continue
        label = f"Speaker {next_number}"
        while label in assigned_labels:
            next_number += 1
            label = f"Speaker {next_number}"
        labels_by_cluster[cluster_index] = label
        assigned_labels.add(label)
        next_number += 1

    if progress is not None:
        progress(total, total)
    return tuple(
        replace(
            line,
            speaker_id=speaker_ids[index],
            label=labels_by_cluster[int(speaker_ids[index].removeprefix("speaker-")) - 1],
        )
        for index, line in enumerate(lines)
    )
