# SPDX-License-Identifier: GPL-3.0-or-later
"""Batch speaker relabeling tests with synthetic embeddings."""

from __future__ import annotations

import numpy as np

from stenographer.lib.live.relabel import _best_active_pair, relabel_system_lines
from stenographer.lib.live.transcript_line import TranscriptLine


def test_best_active_pair_preserves_global_heap_tie_order():
    active = np.array([True, True, True, True])
    best_scores = np.array([0.9, 0.9, 0.9, 0.9], dtype=np.float32)
    best_neighbors = np.array([1, 0, 3, 2])
    cluster_ids = np.array([10, 2, 8, 9])

    left, right, score = _best_active_pair(active, best_scores, best_neighbors, cluster_ids)

    assert (left, right) == (1, 0)
    assert score == float(np.float32(0.9))


def _line(start: float, duration: float, speaker_id: str, label: str) -> TranscriptLine:
    return TranscriptLine(
        start=start,
        end=start + duration,
        wall="wall",
        source="system",
        speaker_id=speaker_id,
        label=label,
        text="placeholder",
    )


def test_default_relabel_does_not_merge_when_float64_score_is_below_threshold():
    lines = (
        _line(0.0, 3.0, "speaker-1", "L0"),
        _line(4.0, 3.0, "speaker-2", "L1"),
        _line(8.0, 6.0, "speaker-3", "L2"),
    )
    embeddings = (
        np.array([0.4999999403953552, 0.8660253882408142, 0.0], dtype=np.float32),
        np.array([0.5, 0.8659821152687073, 0.008660109713673592], dtype=np.float32),
        np.array([1.0, 0.0, 0.0], dtype=np.float32),
    )

    relabeled = relabel_system_lines(lines, embeddings)

    assert [line.speaker_id for line in relabeled] == ["speaker-1", "speaker-1", "speaker-2"]
    assert [line.label for line in relabeled] == ["L0", "L0", "L2"]


def test_batch_relabel_merges_split_voices_and_keeps_the_dominant_renamed_label():
    lines = (
        _line(0.0, 1.0, "speaker-1", "Speaker 1"),
        _line(2.0, 5.0, "speaker-2", "Renamed voice"),
        _line(10.0, 1.0, "speaker-3", "Speaker 3"),
        _line(12.0, 4.0, "speaker-4", "Speaker 4"),
    )
    embeddings = (
        np.array([1.0, 0.0], dtype=np.float32),
        np.array([0.99, 0.1], dtype=np.float32),
        np.array([0.0, 1.0], dtype=np.float32),
        np.array([0.1, 0.99], dtype=np.float32),
    )

    relabeled = relabel_system_lines(lines, embeddings, threshold=0.8)

    assert [line.speaker_id for line in relabeled] == [
        "speaker-1",
        "speaker-1",
        "speaker-2",
        "speaker-2",
    ]
    assert [line.label for line in relabeled] == [
        "Renamed voice",
        "Renamed voice",
        "Speaker 1",
        "Speaker 1",
    ]


def test_batch_relabel_assigns_renames_once_and_numbers_unnamed_clusters_by_appearance():
    lines = (
        _line(0.0, 4.0, "speaker-1", "Renamed voice"),
        _line(10.0, 6.0, "speaker-2", "Renamed voice"),
        _line(20.0, 3.0, "speaker-172", "Speaker 172"),
    )
    embeddings = (
        np.array([1.0, 0.0, 0.0], dtype=np.float32),
        np.array([0.0, 1.0, 0.0], dtype=np.float32),
        np.array([0.0, 0.0, 1.0], dtype=np.float32),
    )

    relabeled = relabel_system_lines(lines, embeddings, threshold=0.8)

    assert relabeled[0].speaker_id != relabeled[1].speaker_id
    assert [line.label for line in relabeled] == ["Speaker 1", "Renamed voice", "Speaker 2"]
    assert sum(line.label == "Renamed voice" for line in relabeled) == 1


def test_batch_relabel_keeps_sustained_minor_voice_at_realistic_similarity():
    lines = (
        _line(0.0, 100.0, "speaker-1", "Speaker 1"),
        *(
            _line(101.0 + index * 4.0, 3.0, f"speaker-{index + 2}", "Speaker 2")
            for index in range(5)
        ),
    )
    voice_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    voice_b = np.array([0.3, np.sqrt(0.91), 0.0], dtype=np.float32)
    embeddings = (voice_a,) + (voice_b,) * 5

    relabeled = relabel_system_lines(lines, embeddings, threshold=0.5)

    assert len({line.speaker_id for line in relabeled}) == 2
    assert [line.label for line in relabeled] == ["Speaker 1"] + ["Speaker 2"] * 5


def test_batch_relabel_keeps_sustained_minor_voice_above_the_merge_threshold():
    # A 100 s core voice and a 15 s minor voice, under the 20% rule of 20 s. The core
    # phrases score 0.6, so they group. Each minor phrase scores about 0.465 against
    # them, so it does not group with them, but it scores 0.52 against their centroid
    # (1, 0, 0), which clears the 0.50 threshold.
    core_a = np.array([np.sqrt(0.8), np.sqrt(0.2), 0.0], dtype=np.float32)
    core_b = np.array([np.sqrt(0.8), -np.sqrt(0.2), 0.0], dtype=np.float32)
    minor = np.array([0.52, 0.0, np.sqrt(1 - 0.52**2)], dtype=np.float32)
    lines = (
        _line(0.0, 50.0, "speaker-1", "Speaker 1"),
        _line(50.0, 50.0, "speaker-1", "Speaker 1"),
        *(
            _line(start, 3.0, "speaker-2", "Speaker 2")
            for start in (101.0, 105.0, 109.0, 113.0, 117.0)
        ),
    )

    relabeled = relabel_system_lines(lines, (core_a, core_b) + (minor,) * 5, threshold=0.5)

    assert [line.speaker_id for line in relabeled] == ["speaker-1"] * 2 + ["speaker-2"] * 5


def test_batch_relabel_merges_sparse_minor_voice_whole_into_its_nearest_core_voice():
    # Axes: voice A's centroid, voice A's spread, voice B's centroid, voice B's spread,
    # and the minor voice's own direction.
    def embedding(a: float, a_spread: float, b: float, b_spread: float) -> np.ndarray:
        own = np.sqrt(1 - a**2 - a_spread**2 - b**2 - b_spread**2)
        return np.array([a, a_spread, b, b_spread, own], dtype=np.float32)

    spread = np.sqrt(0.2)
    centre = np.sqrt(0.8)
    # Three phrases lean to voice A and two lean to voice B, so a phrase-by-phrase vote
    # would split them. As a cluster they score 0.53 against A and 0.512 against B, both
    # at or above 0.50, and A is nearer. They score under 0.50 against every core phrase,
    # so they do not group with a core voice. Sixty-second gaps leave no sustained speech.
    nearer_a = embedding(0.55, 0.0, 0.50, 0.0)
    nearer_b = embedding(0.50, 0.0, 0.53, 0.0)
    lines = (
        _line(0.0, 150.0, "speaker-1", "Speaker 1"),
        _line(150.0, 150.0, "speaker-1", "Speaker 1"),
        _line(300.0, 150.0, "speaker-2", "Speaker 2"),
        _line(450.0, 150.0, "speaker-2", "Speaker 2"),
        *(_line(600.0 + index * 60.0, 3.0, "speaker-3", "Speaker 3") for index in range(5)),
    )
    embeddings = (
        embedding(centre, spread, 0.0, 0.0),
        embedding(centre, -spread, 0.0, 0.0),
        embedding(0.0, 0.0, centre, spread),
        embedding(0.0, 0.0, centre, -spread),
        nearer_a,
        nearer_b,
        nearer_a,
        nearer_b,
        nearer_a,
    )

    relabeled = relabel_system_lines(lines, embeddings, threshold=0.5)

    assert [line.speaker_id for line in relabeled] == ["speaker-1"] * 2 + ["speaker-2"] * 2 + [
        "speaker-1"
    ] * 5


def test_batch_relabel_votes_sparse_minor_voice_by_phrase_when_under_the_merge_threshold():
    # Axes: voice A's centroid, voice A's spread, voice B's centroid, voice B's spread,
    # and the minor voice's own direction. As a cluster the minor phrases score 0.41
    # against A and 0.39 against B, both under 0.50, so each phrase votes for itself.
    # Sixty-second gaps leave no sustained speech.
    def embedding(a: float, a_spread: float, b: float, b_spread: float) -> np.ndarray:
        own = np.sqrt(1 - a**2 - a_spread**2 - b**2 - b_spread**2)
        return np.array([a, a_spread, b, b_spread, own], dtype=np.float32)

    spread = np.sqrt(0.2)
    centre = np.sqrt(0.8)
    nearer_a = embedding(0.45, 0.0, 0.35, 0.0)
    nearer_b = embedding(0.35, 0.0, 0.45, 0.0)
    lines = (
        _line(0.0, 150.0, "speaker-1", "Speaker 1"),
        _line(150.0, 150.0, "speaker-1", "Speaker 1"),
        _line(300.0, 150.0, "speaker-2", "Speaker 2"),
        _line(450.0, 150.0, "speaker-2", "Speaker 2"),
        *(_line(600.0 + index * 60.0, 3.0, "speaker-3", "Speaker 3") for index in range(5)),
    )
    embeddings = (
        embedding(centre, spread, 0.0, 0.0),
        embedding(centre, -spread, 0.0, 0.0),
        embedding(0.0, 0.0, centre, spread),
        embedding(0.0, 0.0, centre, -spread),
        nearer_a,
        nearer_b,
        nearer_a,
        nearer_b,
        nearer_a,
    )

    relabeled = relabel_system_lines(lines, embeddings, threshold=0.5)

    assert [line.speaker_id for line in relabeled] == [
        "speaker-1",
        "speaker-1",
        "speaker-2",
        "speaker-2",
        "speaker-1",
        "speaker-2",
        "speaker-1",
        "speaker-2",
        "speaker-1",
    ]


def test_batch_relabel_short_residue_does_not_create_speakers():
    lines = tuple(
        _line(index * 2.0, 0.8, f"speaker-{index + 1}", f"Speaker {index + 1}")
        for index in range(4)
    )
    embeddings = tuple(np.eye(4, dtype=np.float32)[index] for index in range(4))

    relabeled = relabel_system_lines(lines, embeddings, threshold=0.5)

    assert len({line.speaker_id for line in relabeled}) == 1
    assert len({line.label for line in relabeled}) == 1


def test_batch_relabel_honors_a_fixed_speaker_count():
    lines = (
        _line(0.0, 4.0, "speaker-1", "Speaker 1"),
        _line(5.0, 4.0, "speaker-2", "Speaker 2"),
        _line(10.0, 4.0, "speaker-3", "Speaker 3"),
    )
    embeddings = (
        np.array([1.0, 0.0], dtype=np.float32),
        np.array([0.99, 0.1], dtype=np.float32),
        np.array([0.0, 1.0], dtype=np.float32),
    )

    two = relabel_system_lines(lines, embeddings, speaker_count=2)
    three = relabel_system_lines(lines, embeddings, speaker_count=3)

    assert len({line.speaker_id for line in two}) == 2
    assert len({line.speaker_id for line in three}) == 3


def test_batch_relabel_uses_speech_time_weighted_votes_for_short_phrases():
    lines = (
        _line(0.0, 100.0, "speaker-1", "Long voice"),
        _line(102.0, 1.2, "speaker-2", "Long voice"),
        _line(104.0, 25.0, "speaker-3", "Brief voice"),
        _line(130.0, 0.5, "speaker-4", "Short live label"),
    )
    toward_a = np.array([0.8, 0.6, 0.0], dtype=np.float32)
    same_cluster = np.array([0.6, 0.8, 0.0], dtype=np.float32)
    toward_b = np.array([0.75, 0.0, np.sqrt(0.4375)], dtype=np.float32)
    embeddings = (toward_a, same_cluster, toward_b, np.array([1.0, 0.0, 0.0]))

    relabeled = relabel_system_lines(lines, embeddings, threshold=0.9)

    assert relabeled[-1].speaker_id == relabeled[0].speaker_id
    assert relabeled[-1].label == "Long voice"


def test_room_prefix_numbers_mic_clusters_as_room_speakers_and_keeps_renames():
    lines = (
        _line(0.0, 3.0, "room-1", "Room 1"),
        _line(4.0, 3.0, "room-2", "Dana"),
        _line(8.0, 3.0, "room-3", "Room 3"),
        _line(12.0, 3.0, "room-4", "Room 4"),
    )
    embeddings = (
        np.array([1.0, 0.0], dtype=np.float32),
        np.array([0.0, 1.0], dtype=np.float32),
        np.array([0.99, 0.1], dtype=np.float32),
        np.array([0.1, 0.99], dtype=np.float32),
    )

    relabeled = relabel_system_lines(lines, embeddings, threshold=0.8, label_prefix="Room")

    assert [line.speaker_id for line in relabeled] == ["room-1", "room-2", "room-1", "room-2"]
    assert [line.label for line in relabeled] == ["Room 1", "Dana", "Room 1", "Dana"]


def test_room_prefix_applies_to_a_fixed_speaker_count():
    lines = (
        _line(0.0, 3.0, "room-1", "Room 1"),
        _line(4.0, 3.0, "room-2", "Room 2"),
        _line(8.0, 3.0, "room-3", "Room 3"),
    )
    embeddings = (
        np.array([1.0, 0.0], dtype=np.float32),
        np.array([0.0, 1.0], dtype=np.float32),
        np.array([0.99, 0.1], dtype=np.float32),
    )

    relabeled = relabel_system_lines(lines, embeddings, speaker_count=2, label_prefix="Room")

    assert [line.speaker_id for line in relabeled] == ["room-1", "room-2", "room-1"]
    assert [line.label for line in relabeled] == ["Room 1", "Room 2", "Room 1"]
