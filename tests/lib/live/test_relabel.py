# SPDX-License-Identifier: GPL-3.0-or-later
"""Batch speaker relabeling tests with synthetic embeddings."""

from __future__ import annotations

import numpy as np

from stenographer.lib.live.relabel import relabel_system_lines
from stenographer.lib.live.transcript_line import TranscriptLine


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
        "Speaker 4",
        "Speaker 4",
    ]


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
