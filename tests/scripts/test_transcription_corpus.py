# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure corpus-selection and audio-transformation regression checks."""

import json

import numpy as np
import pytest

from scripts.transcription_study.audio import transform
from scripts.transcription_study.corpus import (
    balanced_order,
    disjoint_groups,
    group_words,
    prepare_controls,
    write_clip,
)


def test_balanced_order_keeps_pilot_and_screen_balanced():
    clips = [
        {"id": f"{corpus}-{i}", "corpus": corpus}
        for corpus, count in (("ami", 30), ("librispeech_clean", 15), ("librispeech_other", 15))
        for i in range(count)
    ]
    ordered = balanced_order(clips)
    assert [sum(c["corpus"] == "ami" for c in ordered[:n]) for n in (12, 24)] == [6, 12]
    for corpus in ("librispeech_clean", "librispeech_other"):
        assert [sum(c["corpus"] == corpus for c in ordered[:n]) for n in (12, 24)] == [3, 6]


def test_disjoint_groups_detects_speaker_leakage():
    assert disjoint_groups([{"split": "dev", "group": "a"}, {"split": "heldout", "group": "b"}])
    assert not disjoint_groups([{"split": "dev", "group": "a"}, {"split": "heldout", "group": "a"}])


def test_speaker_split_is_balanced_and_independent_of_input_order():
    from scripts.transcription_study.corpus import split_speakers

    speakers = [str(i) for i in range(33)]
    first = split_speakers(speakers)
    assert first == split_speakers(speakers[::-1])
    assert list(first.values()).count("dev") == 16
    assert list(first.values()).count("heldout") == 17


def test_group_words_preserves_pause_boundaries():
    words = [(0.0, 0.2, "one"), (0.2, 0.4, "two"), (1.0, 1.2, "three")]
    assert group_words(words) == [words[:2], words[2:]]


def test_amplification_does_not_clip_and_preserves_silence():
    original = np.array([-0.9, 0.0, 0.9], dtype=np.float32)
    amplified = transform(original, gain_db=12)
    assert np.max(np.abs(amplified)) <= 0.999
    assert amplified[0] == -amplified[2]
    assert np.array_equal(transform(np.zeros(10), normalize_rms_dbfs=-18), np.zeros(10))


def test_baseline_preserves_full_scale_samples_exactly():
    audio = np.array([-1.0, -0.9999, 0.0, 0.9999, 1.0], dtype=np.float32)
    assert np.array_equal(transform(audio), audio)


def test_channel_average_exposes_phase_cancellation():
    stereo = np.array([[0.5, -0.5], [0.25, -0.25]], dtype=np.float32)
    assert np.array_equal(transform(stereo, channel="mean"), np.zeros(2))
    assert np.array_equal(transform(stereo, channel="first"), stereo[:, 0])
    assert np.array_equal(transform(stereo, channel="last"), stereo[:, 1])


def test_padding_and_trimming_use_exact_sample_counts():
    audio = np.ones(1600, dtype=np.float32) * 0.1
    result = transform(audio, leading_ms=100, trailing_ms=250, trim_leading_ms=50)
    assert len(result) == 6400
    assert np.count_nonzero(result) == 800


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_nonfinite_audio_is_rejected(value):
    with pytest.raises(ValueError, match="finite"):
        transform(np.array([value]))


def test_stress_controls_preserve_source_groups_and_primary_manifest(tmp_path):
    for folder in ("clips", "references"):
        (tmp_path / folder).mkdir()
    audio = np.sin(np.arange(16000) * 0.03).astype(np.float32) * 0.1
    clips = [
        write_clip(
            tmp_path,
            f"source-{i}",
            audio,
            "test",
            {"split": "dev", "corpus": corpus, "group": f"group-{i}"},
        )
        for i, corpus in enumerate(("ami", "ami", "librispeech_clean", "librispeech_other"))
    ]
    primary = json.dumps({"clips": clips})
    (tmp_path / "manifest.json").write_text(primary)
    manifest = prepare_controls(tmp_path)
    assert len(manifest["clips"]) == 16
    assert (tmp_path / "manifest.json").read_text() == primary
    assert all(c["split"] == "dev" for c in manifest["clips"])
    for clip in manifest["clips"][:12]:
        assert clip["group"] == next(c["group"] for c in clips if c["id"] == clip["variant_of"])
        assert clip["duration_seconds"] == 4
    assert all(c["reference_words"] == 0 for c in manifest["clips"][12:])
