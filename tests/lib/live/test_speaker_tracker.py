# SPDX-License-Identifier: GPL-3.0-or-later
"""Speaker clustering tests without sherpa or audio hardware."""

from __future__ import annotations

import numpy as np

from stenographer.lib.live.speaker import SpeakerClustering


def test_clustering_creates_a_speaker_when_no_match_reaches_threshold():
    clustering = SpeakerClustering(threshold=0.5)

    assert clustering.assign(np.array([1.0, 0.0], dtype=np.float32)) == "speaker-1"
    assert clustering.assign(np.array([0.0, 1.0], dtype=np.float32)) == "speaker-2"


def test_clustering_joins_the_best_speaker_above_threshold():
    clustering = SpeakerClustering(threshold=0.9)
    first = np.array([1.0, 0.0], dtype=np.float32)
    close = np.array([0.99, 0.1], dtype=np.float32)

    assert clustering.assign(first) == "speaker-1"
    assert clustering.assign(close) == "speaker-1"


def test_clustering_updates_the_mean_before_a_later_decision():
    clustering = SpeakerClustering(threshold=0.82)
    first = np.array([1.0, 0.0], dtype=np.float32)
    second = np.array([0.9, 0.43589], dtype=np.float32)
    later = np.array([0.8, 0.6], dtype=np.float32)

    assert clustering.assign(first) == "speaker-1"
    assert clustering.assign(second) == "speaker-1"
    assert clustering.assign(later) == "speaker-1"


def test_clustering_never_reuses_speaker_numbers():
    clustering = SpeakerClustering(threshold=0.99)
    vectors = (
        np.array([1.0, 0.0], dtype=np.float32),
        np.array([0.0, 1.0], dtype=np.float32),
        np.array([1.0, 1.0], dtype=np.float32),
        np.array([1.0, -1.0], dtype=np.float32),
    )

    assert [clustering.assign(vector) for vector in vectors] == [
        "speaker-1",
        "speaker-2",
        "speaker-3",
        "speaker-4",
    ]
