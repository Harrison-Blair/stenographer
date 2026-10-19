# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure clustering checks for the live CPU benchmark."""

from __future__ import annotations

import numpy as np

from scripts.live_bench import _cluster


def test_online_clustering_groups_matching_speakers_without_errors():
    embeddings = [
        ("alice", np.array([1.0, 0.0])),
        ("alice", np.array([0.99, 0.1])),
        ("bob", np.array([0.0, 1.0])),
    ]

    assert _cluster(embeddings, 0.8) == {
        "cluster_count": 2,
        "over_split_count": 0,
        "merge_count": 0,
    }


def test_online_clustering_reports_a_split_and_a_merge():
    split = _cluster(
        [
            ("alice", np.array([1.0, 0.0])),
            ("alice", np.array([0.8, 0.6])),
            ("bob", np.array([0.0, 1.0])),
        ],
        0.9,
    )
    merged = _cluster(
        [
            ("alice", np.array([1.0, 0.0])),
            ("bob", np.array([0.9, 0.4358899])),
        ],
        0.8,
    )

    assert split == {"cluster_count": 3, "over_split_count": 1, "merge_count": 0}
    assert merged == {"cluster_count": 1, "over_split_count": 0, "merge_count": 1}
