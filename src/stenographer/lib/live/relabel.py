# SPDX-License-Identifier: GPL-3.0-or-later
"""Batch-cluster live phrases of one source and preserve renamed labels."""

from __future__ import annotations

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


def _best_active_pair(
    active: np.ndarray,
    best_scores: np.ndarray,
    best_neighbors: np.ndarray,
    cluster_ids: np.ndarray,
) -> tuple[int, int, float]:
    """Return the highest-scoring pair with the heap's logical-id tie order."""
    rows = np.flatnonzero(active)
    maximum = np.max(best_scores[rows])
    candidates = rows[best_scores[rows] == maximum]
    neighbors = best_neighbors[candidates]
    left_ids = np.minimum(cluster_ids[candidates], cluster_ids[neighbors])
    right_ids = np.maximum(cluster_ids[candidates], cluster_ids[neighbors])
    order = np.lexsort((right_ids, left_ids))
    left_slot = int(candidates[order[0]])
    right_slot = int(best_neighbors[left_slot])
    if cluster_ids[left_slot] > cluster_ids[right_slot]:
        left_slot, right_slot = right_slot, left_slot
    return left_slot, right_slot, float(maximum)


def relabel_work_units(
    lines: Iterable[TranscriptLine],
    *,
    minimum_duration: float = MINIMUM_SPEECH_DURATION_SECONDS,
) -> int:
    """Return the progress total that ``relabel_system_lines`` reports for *lines*.

    A caller learns it before the pass starts. It holds for the default pass
    without a fixed speaker count.
    """
    original = tuple(lines)
    anchors = sum(1 for line in original if max(0.0, line.end - line.start) >= minimum_duration)
    return 2 * anchors + len(original)


def relabel_system_lines(
    lines: Iterable[TranscriptLine],
    embeddings: Iterable[np.ndarray],
    *,
    threshold: float = 0.5,
    minimum_duration: float = MINIMUM_SPEECH_DURATION_SECONDS,
    progress: Callable[[int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    speaker_count: int | None = None,
    label_prefix: str = "Speaker",
) -> tuple[TranscriptLine, ...] | None:
    """Relabel one source's phrases from the session's full set of embeddings.

    Clusters get IDs ``<prefix>-N`` and labels ``<Prefix> N`` from *label_prefix*:
    ``Speaker`` for system audio, ``Room`` for a diarized microphone.
    """
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
            label_prefix=label_prefix,
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
    # Keep exact scores for ordering; round only when a later merge reads them.
    similarities = np.full((anchor_count, anchor_count), -np.inf, dtype=np.float64)
    active = np.ones(anchor_count, dtype=bool)
    sizes = np.ones(anchor_count, dtype=np.float64)
    cluster_ids = np.arange(anchor_count, dtype=np.intp)
    left_children = np.full(capacity, -1, dtype=np.intp)
    right_children = np.full(capacity, -1, dtype=np.intp)
    best_scores = np.full(anchor_count, -np.inf, dtype=np.float64)
    best_neighbors = np.full(anchor_count, -1, dtype=np.intp)
    total = relabel_work_units(original, minimum_duration=minimum_duration)
    if progress is not None:
        progress(0, total)

    for row in range(anchor_count):
        if should_cancel is not None and should_cancel():
            return None
        row_scores = anchor_vectors[row + 1 :] @ anchor_vectors[row]
        similarities[row, row + 1 : anchor_count] = row_scores
        similarities[row + 1 : anchor_count, row] = row_scores
        if row_scores.size:
            maximum = np.max(row_scores)
            if maximum > best_scores[row]:
                offset = int(np.flatnonzero(row_scores == maximum)[0])
                best_scores[row] = maximum
                best_neighbors[row] = row + 1 + offset
        if progress is not None:
            progress(row + 1, total)

    next_cluster = anchor_count
    active_count = anchor_count
    while active_count > 1:
        if should_cancel is not None and should_cancel():
            return None
        left, right, score = _best_active_pair(active, best_scores, best_neighbors, cluster_ids)
        if not score >= threshold:
            break

        merged_size = sizes[left] + sizes[right]
        left_children[next_cluster] = cluster_ids[left]
        right_children[next_cluster] = cluster_ids[right]
        remaining = active.copy()
        remaining[left] = False
        remaining[right] = False
        other_slots = np.flatnonzero(remaining)
        # The previous matrix rounded each completed score to float32 before reuse.
        updated_scores = (
            sizes[left] * similarities[left, other_slots].astype(np.float32)
            + sizes[right] * similarities[right, other_slots].astype(np.float32)
        ) / merged_size
        similarities[left, other_slots] = updated_scores
        similarities[other_slots, left] = updated_scores
        merged_scores = similarities[left, other_slots]
        similarities[left, left] = -np.inf
        similarities[left, right] = -np.inf
        similarities[right, left] = -np.inf
        similarities[right, right] = -np.inf

        active[right] = False
        active_count -= 1
        cluster_ids[left] = next_cluster
        sizes[left] = merged_size
        improved = merged_scores > best_scores[other_slots]
        improved_slots = other_slots[improved]
        best_scores[improved_slots] = merged_scores[improved]
        best_neighbors[improved_slots] = left

        affected_mask = active & ((best_neighbors == left) | (best_neighbors == right))
        affected_mask[left] = True
        affected = np.flatnonzero(affected_mask)
        active_slots = np.flatnonzero(active)
        for row in affected:
            candidates = active_slots[active_slots != row]
            if not candidates.size:
                best_scores[row] = -np.inf
                best_neighbors[row] = -1
                continue
            row_scores = similarities[row, candidates]
            maximum = np.max(row_scores)
            tied = candidates[row_scores == maximum]
            partner = tied[np.argmin(cluster_ids[tied])]
            best_scores[row] = maximum
            best_neighbors[row] = partner

        next_cluster += 1
        if progress is not None:
            progress(next_cluster, total)

    if should_cancel is not None and should_cancel():
        return None

    clusters = {}
    for slot in np.flatnonzero(active):
        root = int(cluster_ids[slot])
        members = []
        pending = [root]
        while pending:
            node = pending.pop()
            if node < anchor_count:
                members.append(anchor_indices[node])
            else:
                pending.append(int(right_children[node]))
                pending.append(int(left_children[node]))
        clusters[root] = members

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
    id_prefix = f"{label_prefix.lower()}-"
    renamed_labels = {
        line.label
        for line in original
        if line.label != f"{label_prefix} {line.speaker_id.removeprefix(id_prefix)}"
    }
    for number, members in enumerate(ranked_clusters, 1):
        label_weights: dict[str, float] = {}
        speaker_id = f"{id_prefix}{number}"
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
        label = f"{label_prefix} {next_number}"
        while label in assigned_labels:
            next_number += 1
            label = f"{label_prefix} {next_number}"
        cluster_labels[cluster_index] = label
        assigned_labels.add(label)
        next_number += 1

    labels_by_speaker = {
        f"{id_prefix}{cluster_index + 1}": label for cluster_index, label in cluster_labels.items()
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
    label_prefix: str,
) -> tuple[TranscriptLine, ...] | None:
    """Agglomerate phrases with a dense matrix, then cut at the target count."""
    phrase_count = len(lines)
    target = min(speaker_count, phrase_count)
    merge_count = phrase_count - target
    total = max(1, phrase_count + (phrase_count - 1 if merge_count else 0))
    if progress is not None:
        progress(0, total)

    merge_events: list[tuple[float, int, int, int]] = []
    children: list[tuple[int, int] | None] = [None] * (2 * phrase_count - 1)
    if merge_count:
        similarities = np.empty((phrase_count, phrase_count), dtype=np.float32)
        np.fill_diagonal(similarities, -np.inf)
        active = np.ones(phrase_count, dtype=bool)
        sizes = np.where(durations > 0, durations, 1.0).astype(np.float64)
        slot_nodes = np.arange(phrase_count, dtype=np.intp)
        for left in range(phrase_count):
            if should_cancel is not None and should_cancel():
                return None
            scores = vectors[left + 1 :] @ vectors[left]
            similarities[left, left + 1 :] = scores
            similarities[left + 1 :, left] = scores
            if progress is not None:
                progress(left + 1, total)

        chain: list[int] = []
        next_node = phrase_count
        active_count = phrase_count
        done = 0
        while active_count > 1:
            if should_cancel is not None and should_cancel():
                return None
            if not chain:
                chain.append(int(np.flatnonzero(active)[0]))
            current = chain[-1]
            candidates = np.where(active, similarities[current], -np.inf)
            candidates[current] = -np.inf
            nearest = int(np.argmax(candidates))
            if len(chain) > 1 and nearest == chain[-2]:
                left = chain[-2]
                right = current
                node = next_node
                next_node += 1
                children[node] = (int(slot_nodes[left]), int(slot_nodes[right]))
                merge_events.append((float(similarities[left, right]), node, *children[node]))

                merged_size = sizes[left] + sizes[right]
                other_mask = active.copy()
                other_mask[left] = False
                other_mask[right] = False
                others = np.flatnonzero(other_mask)
                updated = (
                    sizes[left] * similarities[left, others]
                    + sizes[right] * similarities[right, others]
                ) / merged_size
                similarities[left, others] = updated
                similarities[others, left] = updated
                similarities[left, left] = -np.inf
                sizes[left] = merged_size
                active[right] = False
                slot_nodes[left] = node
                chain.pop()
                chain.pop()
                active_count -= 1
                done += 1
                if progress is not None:
                    progress(phrase_count + done, total)
            else:
                chain.append(nearest)
    else:
        for completed in range(phrase_count):
            if should_cancel is not None and should_cancel():
                return None
            if progress is not None:
                progress(completed + 1, total)

    if should_cancel is not None and should_cancel():
        return None

    selected = np.zeros(2 * phrase_count - 1, dtype=bool)
    selected[:phrase_count] = True
    parents = np.full(2 * phrase_count - 1, -1, dtype=np.intp)
    for _score, node, left, right in sorted(merge_events, key=lambda event: event[0], reverse=True)[
        :merge_count
    ]:
        selected[node] = True
        parents[left] = node
        parents[right] = node
    roots = np.flatnonzero(selected & (parents == -1))
    ranked_clusters = []
    for root in roots:
        members = []
        pending_nodes = [int(root)]
        while pending_nodes:
            node = pending_nodes.pop()
            branch = children[node]
            if branch is None:
                members.append(node)
            else:
                pending_nodes.extend(branch)
        ranked_clusters.append(members)
    ranked_clusters.sort(key=min)
    speaker_ids: dict[int, str] = {}
    label_weights_by_cluster: list[dict[str, float]] = []
    id_prefix = f"{label_prefix.lower()}-"
    renamed_labels = {
        line.label
        for line in lines
        if line.label != f"{label_prefix} {line.speaker_id.removeprefix(id_prefix)}"
    }
    for number, members in enumerate(ranked_clusters, 1):
        label_weights: dict[str, float] = {}
        for index in members:
            speaker_ids[index] = f"{id_prefix}{number}"
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
        label = f"{label_prefix} {next_number}"
        while label in assigned_labels:
            next_number += 1
            label = f"{label_prefix} {next_number}"
        labels_by_cluster[cluster_index] = label
        assigned_labels.add(label)
        next_number += 1

    if progress is not None:
        progress(total, total)
    return tuple(
        replace(
            line,
            speaker_id=speaker_ids[index],
            label=labels_by_cluster[int(speaker_ids[index].removeprefix(id_prefix)) - 1],
        )
        for index, line in enumerate(lines)
    )
