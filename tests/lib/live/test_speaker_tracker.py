# SPDX-License-Identifier: GPL-3.0-or-later
"""Speaker clustering tests without sherpa or audio hardware."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile

from stenographer.lib.live.models import LIVE_MODELS
from stenographer.lib.live.speaker_tracker import Speaker, SpeakerClustering, SpeakerTracker
from stenographer.lib.platform import current_platform


def test_clustering_creates_a_speaker_when_no_match_reaches_threshold():
    clustering = SpeakerClustering(threshold=0.5)

    assert clustering.assign(np.array([1.0, 0.0], dtype=np.float32)) == "speaker-1"
    assert clustering.assign(np.array([0.0, 1.0], dtype=np.float32)) == "speaker-2"


def test_short_phrases_reuse_the_first_seed_speaker():
    clustering = SpeakerClustering(threshold=0.9)

    assert clustering.assign(np.array([1.0, 0.0], dtype=np.float32), duration=0.5) == "speaker-1"
    assert clustering.assign(np.array([0.0, 1.0], dtype=np.float32), duration=0.5) == "speaker-1"
    assert len(clustering.speakers) == 1


def test_short_phrase_joins_best_existing_speaker_without_updating_its_mean():
    clustering = SpeakerClustering(threshold=0.8)
    first = np.array([1.0, 0.0], dtype=np.float32)
    short = np.array([0.4, np.sqrt(0.84)], dtype=np.float32)

    assert clustering.assign(first, duration=1.2) == "speaker-1"
    speaker = clustering.speakers[0]
    mean = speaker.mean_embedding.copy()

    assert clustering.assign(short, duration=0.5) == "speaker-1"
    assert speaker.count == 1
    np.testing.assert_array_equal(speaker.mean_embedding, mean)
    assert len(clustering.speakers) == 1


def test_short_phrase_with_a_very_low_score_uses_previous_system_speaker():
    clustering = SpeakerClustering(threshold=0.9)

    assert clustering.assign(np.array([1.0, 0.0], dtype=np.float32), duration=1.2) == "speaker-1"
    assert clustering.assign(np.array([0.0, 1.0], dtype=np.float32), duration=1.2) == "speaker-2"
    assert clustering.assign(np.array([-1.0, 0.0], dtype=np.float32), duration=0.5) == "speaker-2"


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


def _tracker(monkeypatch, embeddings, **options):
    vectors = iter(embeddings)
    config_values = {}
    streams = []

    class FakeConfig:
        def __init__(self, *, model, num_threads, debug, provider):
            config_values.update(
                model=model, num_threads=num_threads, debug=debug, provider=provider
            )

    class FakeStream:
        def accept_waveform(self, *, sample_rate, waveform):
            self.sample_rate = sample_rate
            self.waveform = waveform.copy()

        def input_finished(self):
            pass

    class FakeExtractor:
        def __init__(self, config):
            self.config = config

        def create_stream(self):
            stream = FakeStream()
            streams.append(stream)
            return stream

        def is_ready(self, stream):
            return True

        def compute(self, stream):
            return next(vectors)

    monkeypatch.setitem(
        sys.modules,
        "sherpa_onnx",
        SimpleNamespace(
            SpeakerEmbeddingExtractorConfig=FakeConfig,
            SpeakerEmbeddingExtractor=FakeExtractor,
        ),
    )
    tracker = SpeakerTracker("speaker.onnx", **options)
    return tracker, config_values, streams


def _assign(tracker, samples):
    return tracker.assign_embedding(tracker.embed(samples))


def test_tracker_extracts_samples_and_uses_the_default_label(monkeypatch):
    samples = np.array([0.15, -0.25, 0.4], dtype=np.float32)
    tracker, config, streams = _tracker(monkeypatch, [np.array([1.0, 0.0], dtype=np.float32)])

    assert _assign(tracker, samples) == "speaker-1"
    assert tracker.label("speaker-1") == "Speaker 1"
    assert config == {
        "model": "speaker.onnx",
        "num_threads": 2,
        "debug": False,
        "provider": "cpu",
    }
    assert streams[0].sample_rate == 16000
    np.testing.assert_array_equal(streams[0].waveform, samples)


def test_renaming_two_speakers_to_the_same_name_shares_the_label(monkeypatch):
    tracker, _, _ = _tracker(
        monkeypatch,
        [
            np.array([1.0, 0.0], dtype=np.float32),
            np.array([0.0, 1.0], dtype=np.float32),
        ],
    )
    first = _assign(tracker, np.array([0.1], dtype=np.float32))
    second = _assign(tracker, np.array([0.2], dtype=np.float32))

    tracker.rename(first, "Alice")
    tracker.rename(second, " Alice ")

    assert first == "speaker-1"
    assert second == "speaker-2"
    assert tracker.label(first) == "Alice"
    assert tracker.label(second) == "Alice"


def test_rename_refuses_empty_names(monkeypatch):
    tracker, _, _ = _tracker(monkeypatch, [np.array([1.0, 0.0], dtype=np.float32)])
    speaker_id = _assign(tracker, np.array([0.1], dtype=np.float32))

    with pytest.raises(ValueError):
        tracker.rename(speaker_id, "  \t ")


def test_public_speaker_clips_cluster_with_the_real_model():
    worktree = Path(__file__).resolve().parents[3]
    audio_dir = worktree / "tmp" / "live_audio"
    clip_paths = (
        audio_dir / "speaker1_a_en_16k.wav",
        audio_dir / "speaker1_b_en_16k.wav",
        audio_dir / "speaker2_a_en_16k.wav",
    )
    missing_clips = [path.name for path in clip_paths if not path.is_file()]
    if missing_clips:
        pytest.skip(f"public speaker clips are absent from tmp/live_audio: {missing_clips}")

    data_dir = current_platform().data_dir(
        {"XDG_DATA_HOME": str(worktree / "tmp" / "xdg-data")}, Path.home()
    )
    model_path = data_dir / "models" / "live" / LIVE_MODELS[1].filename
    if not model_path.is_file():
        pytest.skip(f"live speaker model is absent: {model_path}")
    pytest.importorskip("sherpa_onnx", reason="sherpa-onnx is not installed")

    recordings = []
    for path in clip_paths:
        samples, sample_rate = soundfile.read(path, dtype="float32")
        assert sample_rate == 16000
        recordings.append(samples)

    tracker = SpeakerTracker(model_path)
    first = _assign(tracker, recordings[0])
    second = _assign(tracker, recordings[1])
    third = _assign(tracker, recordings[2])

    assert first == second
    assert third != first


def test_clustering_id_prefix_keeps_room_ids_apart_from_system_ids():
    clustering = SpeakerClustering(threshold=0.5, id_prefix="room")

    assert clustering.assign(np.array([1.0, 0.0], dtype=np.float32)) == "room-1"
    assert clustering.assign(np.array([0.0, 1.0], dtype=np.float32)) == "room-2"


def test_room_tracker_labels_and_renames_room_speakers(monkeypatch):
    tracker, _, _ = _tracker(
        monkeypatch,
        [
            np.array([1.0, 0.0], dtype=np.float32),
            np.array([0.0, 1.0], dtype=np.float32),
        ],
        label_prefix="Room",
    )
    first = _assign(tracker, np.array([0.1], dtype=np.float32))
    second = _assign(tracker, np.array([0.2], dtype=np.float32))

    tracker.rename(second, "Dana")

    assert (first, second) == ("room-1", "room-2")
    assert tracker.label(first) == "Room 1"
    assert tracker.label(second) == "Dana"


A = np.array([1.0, 0.0, 0.0], dtype=np.float32)
B = np.array([0.0, 1.0, 0.0], dtype=np.float32)
C = np.array([0.0, 0.0, 1.0], dtype=np.float32)


def test_assign_nearest_creates_only_the_first_speaker():
    clustering = SpeakerClustering(threshold=0.5, id_prefix="room")

    assert clustering.assign_nearest(A) == "room-1"
    assert clustering.assign_nearest(B) == "room-1"
    assert len(clustering.speakers) == 1


def test_assign_nearest_picks_the_closest_speaker_below_the_threshold():
    clustering = SpeakerClustering(threshold=0.99, speakers=[Speaker("room-1", A.copy())])
    clustering.speakers.append(Speaker("room-2", B.copy()))

    assert clustering.assign_nearest(np.array([0.2, 0.3, 0.9], dtype=np.float32)) == "room-2"


@pytest.mark.parametrize(("score", "expected"), [(0.42, "speaker-1"), (0.38, "speaker-2")])
def test_a_default_tracker_joins_a_known_speaker_from_a_score_of_0_40(monkeypatch, score, expected):
    tracker, _, _ = _tracker(monkeypatch, [])
    tracker.assign_embedding(np.array([1.0, 0.0], dtype=np.float32), duration=2.0)

    phrase = np.array([score, np.sqrt(1 - score**2)], dtype=np.float32)

    assert tracker.assign_embedding(phrase, duration=2.0) == expected


def test_a_file_job_tracker_still_creates_speakers_as_phrases_arrive(monkeypatch):
    tracker, _, _ = _tracker(monkeypatch, [], label_prefix="Speaker")

    assert tracker.assign_embedding(A, duration=2.0) == "speaker-1"
    assert tracker.assign_embedding(B, duration=2.0) == "speaker-2"
    # A short phrase joins a known speaker and a long phrase near one joins it too.
    assert tracker.assign_embedding(C, duration=0.5) == "speaker-2"
    assert tracker.assign_embedding(A, duration=2.0) == "speaker-1"
    assert tracker.label("speaker-2") == "Speaker 2"


def _regroup(tracker, rows):
    """Regroup rows of ``(current ID, batch cluster, seconds, embedding)``, all grouped before."""
    current, clusters, durations, embeddings = zip(*rows, strict=True)
    tracker._grouped_phrases = len(rows)
    return tracker.regroup(current, clusters, durations, embeddings)


def test_regroup_keeps_each_number_when_batch_numbers_differ(monkeypatch):
    tracker, _, _ = _tracker(monkeypatch, [], label_prefix="Room")

    ids = _regroup(
        tracker,
        [
            ("room-3", "room-1", 5.0, A),
            ("room-1", "room-2", 5.0, B),
            ("room-3", "room-1", 5.0, A),
        ],
    )

    assert ids == ("room-3", "room-1", "room-3")


def test_regroup_gives_a_new_cluster_a_new_number_after_every_number_used(monkeypatch):
    tracker, _, _ = _tracker(monkeypatch, [], label_prefix="Room")
    assert tracker.assign_nearest(A) == "room-1"

    first = tracker.regroup(("room-1", "room-1"), ("x", "y"), (5.0, 4.0), (A, B))
    assert first == ("room-1", "room-2")

    # room-2 merges away, and its number stays unused for the next new person.
    second = _regroup(tracker, [("room-1", "x", 5.0, A), ("room-2", "x", 4.0, B)])
    assert second == ("room-1", "room-1")
    third = _regroup(
        tracker,
        [("room-1", "x", 5.0, A), ("room-1", "x", 4.0, B), ("room-1", "y", 1.0, C)],
    )
    assert third == ("room-1", "room-1", "room-3")


def test_regroup_gives_a_cluster_to_the_speaker_with_the_most_shared_speech(monkeypatch):
    tracker, _, _ = _tracker(monkeypatch, [], label_prefix="Room")

    ids = _regroup(tracker, [("room-1", "x", 2.0, A), ("room-2", "x", 9.0, A)])

    assert ids == ("room-2", "room-2")
    assert tracker.current_id("room-1") == "room-2"
    assert tracker.current_id("room-2") == "room-2"


def test_regroup_lets_a_renamed_speaker_choose_before_a_larger_speaker(monkeypatch):
    tracker, _, _ = _tracker(monkeypatch, [], label_prefix="Room")
    assert tracker.assign_embedding(A, duration=2.0) == "room-1"
    assert tracker.assign_embedding(B, duration=2.0) == "room-2"
    tracker.rename("room-1", "Dana")

    ids = _regroup(tracker, [("room-1", "x", 2.0, A), ("room-2", "x", 9.0, A)])

    assert ids == ("room-1", "room-1")
    assert tracker.label("room-1") == "Dana"


def test_current_id_follows_a_merge_chain(monkeypatch):
    tracker, _, _ = _tracker(monkeypatch, [], label_prefix="Room")

    _regroup(tracker, [("room-1", "x", 1.0, A), ("room-2", "x", 2.0, A), ("room-3", "y", 1.0, B)])
    _regroup(tracker, [("room-2", "x", 3.0, A), ("room-3", "x", 4.0, B)])

    assert tracker.current_id("room-1") == "room-3"


def test_regroup_sets_the_mean_of_all_phrases_of_a_speaker(monkeypatch):
    tracker, _, _ = _tracker(monkeypatch, [], label_prefix="Room")
    between = np.array([0.9, 0.9, 1.0], dtype=np.float32)

    _regroup(
        tracker, [("room-1", "x", 5.0, A), ("room-1", "x", 5.0, B), ("room-2", "y", 5.0, between)]
    )

    # The mean of A and B is this exact direction. A alone or B alone scores below room-2.
    assert tracker.assign_nearest(np.array([1.0, 1.0, 0.0], dtype=np.float32)) == "room-1"


def test_regroup_counts_only_phrases_that_an_earlier_pass_grouped(monkeypatch):
    tracker, _, _ = _tracker(monkeypatch, [], label_prefix="Room")
    assert tracker.assign_nearest(A) == "room-1"

    # Only the first phrase has evidence at the first pass, whatever speech the others have.
    first = tracker.regroup(("room-1", "room-1"), ("x", "y"), (1.0, 99.0), (A, B))
    assert first == ("room-1", "room-2")

    # The new phrase joined room-1 by nearest. Its speech does not move room-1 to cluster y.
    second = tracker.regroup(
        ("room-1", "room-2", "room-1"), ("x", "y", "y"), (1.0, 99.0, 500.0), (A, B, B)
    )
    assert second == ("room-1", "room-2", "room-2")


def test_saved_speakers_count_only_phrases_that_a_pass_grouped(monkeypatch):
    tracker, _, _ = _tracker(monkeypatch, [], label_prefix="Room")
    assert tracker.assign_nearest(A) == "room-1"
    tracker.rename("room-1", "Dana")

    saved = tracker.saved_speakers(("room-1", "room-1"), ("x", "y"), (1.0, 99.0))

    assert saved == (("room-1", "Dana"), ("room-2", "Room 2"))


def test_the_real_speaker_model_ignores_the_loudness_of_a_phrase():
    # The model expects features with their mean over time subtracted. A louder phrase adds
    # the same amount to every log feature, so with that step the voice does not change.
    worktree = Path(__file__).resolve().parents[3]
    data_dir = current_platform().data_dir(
        {"XDG_DATA_HOME": str(worktree / "tmp" / "xdg-data")}, Path.home()
    )
    model_path = data_dir / "models" / "live" / LIVE_MODELS[1].filename
    if not model_path.is_file():
        pytest.skip(f"live speaker model is absent: {model_path}")
    pytest.importorskip("sherpa_onnx", reason="sherpa-onnx is not installed")
    rate = 16000
    time = np.arange(3 * rate) / rate
    pitch = 120 + 30 * np.sin(2 * np.pi * 0.7 * time)
    phase = 2 * np.pi * np.cumsum(pitch) / rate
    voiced = sum(np.sin(k * phase) / k for k in range(1, 20)) * (1.5 + np.sin(6 * np.pi * time))
    noise = np.random.default_rng(0).standard_normal(time.size)
    samples = (0.04 * voiced + 0.01 * noise).astype(np.float32)

    tracker = SpeakerTracker(model_path)
    loud = tracker.embed(samples)
    quiet = tracker.embed(samples * np.float32(0.1))

    assert loud @ quiet / (np.linalg.norm(loud) * np.linalg.norm(quiet)) > 0.9999
