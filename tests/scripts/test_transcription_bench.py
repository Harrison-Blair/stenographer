# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure scorer, selection, checkpoint and benchmark accounting regressions."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location(
    "transcription_bench", SCRIPTS / "transcription_bench.py"
)
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)

from transcription_study.profiles import select_clips  # noqa: E402
from transcription_study.records import Profile  # noqa: E402
from transcription_study.scoring import normalize, score  # noqa: E402

from stenographer.lib.config.models import Config  # noqa: E402


@pytest.mark.parametrize(
    ("reference", "hypothesis", "counts"),
    [
        ("one two three", "one four three", (1, 0, 0, 3)),
        ("one two three", "one three", (0, 1, 0, 3)),
        ("one two", "one new two", (0, 0, 1, 2)),
        ("one two", "", (0, 2, 0, 2)),
        ("", "invented words", (0, 0, 2, 0)),
        ("", "", (0, 0, 0, 0)),
    ],
)
def test_known_edit_counts(reference, hypothesis, counts):
    actual = score(reference, hypothesis)
    assert tuple(actual[key] for key in ("S", "D", "I", "N")) == counts
    assert actual["wer"] == (sum(counts[:3]) / counts[3] if counts[3] else None)


def test_normalization_keeps_meaning_and_unicode():
    assert normalize("Don\u2019t pay 1.7 to Ana Str\u00f6m!") == [
        "don't",
        "pay",
        "1.7",
        "to",
        "ana",
        "str\u00f6m",
    ]
    assert score("do not pay 17", "do pay 70")["exact"] is False
    assert score("Hello, WORLD!", "hello world")["exact"] is True
    result = score("don't pay 17", "do pay 70")
    assert result["negations_correct"] == result["numbers_correct"] == 0
    assert result["negation_count"] == result["number_count"] == 1


def test_boundary_and_nonspeech_accounting():
    result = score("opening middle ending", "middle ending")
    assert result["opening_correct"] is False
    assert result["closing_correct"] is True
    assert score("", "noise words")["false_speech"] is True
    assert score("", "")["false_speech"] is False


def test_selection_is_balanced_and_never_crosses_split():
    clips = [
        {"id": f"{split}-{corpus}-{i}", "split": split, "corpus": corpus, "selection_order": i}
        for split in ("dev", "heldout")
        for corpus in ("ami", "librispeech_clean", "librispeech_other")
        for i in range(30)
    ]
    selected = select_clips({"clips": clips}, "dev", 12)
    assert len(selected) == 12
    assert all(clip["split"] == "dev" for clip in selected)
    assert [
        sum(c["corpus"] == group for c in selected)
        for group in ("ami", "librispeech_clean", "librispeech_other")
    ] == [6, 3, 3]
    assert select_clips({"clips": list(reversed(clips))}, "dev", 12) == selected


def test_selection_includes_explicit_nonspeech_controls_after_speech():
    clips = [
        {"id": f"{corpus}-{index}", "split": "dev", "corpus": corpus}
        for corpus, count in (
            ("ami", 6),
            ("librispeech_clean", 3),
            ("librispeech_other", 3),
            ("synthetic_nonspeech", 4),
        )
        for index in range(count)
    ]
    selected = select_clips({"clips": clips}, "dev", 16)
    assert len(selected) == 16
    assert all(clip["corpus"] != "synthetic_nonspeech" for clip in selected[:12])
    assert all(clip["corpus"] == "synthetic_nonspeech" for clip in selected[12:])


def test_selection_rejects_unknown_corpus_labels():
    with pytest.raises(ValueError, match="unsupported_corpus"):
        select_clips({"clips": [{"id": "unknown", "split": "dev", "corpus": "typo"}]}, "dev", 12)


def test_resume_is_fingerprint_and_split_specific(tmp_path):
    path = tmp_path / "rows.jsonl"
    row = {"fingerprint": "old", "clip_id": "a", "split": "dev"}
    path.write_text(json.dumps(row) + '\n{"interrupted":')
    done = bench.completed_rows(path)
    assert ("old", "a", "dev") in done
    assert ("new", "a", "dev") not in done
    assert ("old", "a", "heldout") not in done


def test_resume_rejects_corrupt_middle_row(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_text('bad\n{"fingerprint":"old","clip_id":"a","split":"dev"}\n')
    with pytest.raises(json.JSONDecodeError):
        bench.completed_rows(path)


def test_fingerprint_changes_with_code_and_config_but_not_profile_list():
    metadata = {"profiles": [{"id": "baseline"}], "sources": {"scoring": "a"}, "config": 1}
    original = bench.fingerprint(metadata, "baseline")
    assert bench.fingerprint({**metadata, "sources": {"scoring": "b"}}, "baseline") != original
    assert bench.fingerprint({**metadata, "config": 2}, "baseline") != original
    assert (
        bench.fingerprint(
            {**metadata, "profiles": [{"id": "baseline"}, {"id": "beam3"}]}, "baseline"
        )
        == original
    )


def public_clip(tmp_path, samples, reference):
    import soundfile as sf

    audio = tmp_path / "public.wav"
    text = tmp_path / "reference.txt"
    sf.write(audio, samples, 16000)
    text.write_text(reference)
    return {
        "id": "public",
        "split": "dev",
        "corpus": "ami",
        "group": "speaker1",
        "audio_path": str(audio),
        "reference_path": str(text),
        "sha256": bench.digest(audio.read_bytes()),
        "reference_sha256": bench.digest(text.read_bytes()),
    }


def test_gate_rejection_is_all_deletions_and_never_decodes(tmp_path):
    import numpy as np

    clip = public_clip(tmp_path, np.zeros(16000, dtype=np.float32), "one two three")
    # The absent transcribe method makes any accidental decode fail this test.
    result = bench.measure_clip(
        clip, Profile("baseline"), Config.defaults(), SimpleNamespace(backend={})
    )
    assert result["status"] == "gate_rejected"
    assert result["stages"]["raw"] is None
    assert result["stages"]["assembled"] is None
    assert result["stages"]["formatted"]["D"] == 3
    assert "one two three" not in json.dumps(result)


def test_decode_failure_preserves_delivery_accounting_without_error_text(tmp_path):
    import numpy as np

    clip = public_clip(tmp_path, np.full(16000, 0.1, dtype=np.float32), "private phrase")

    def fail_decode(*args):
        raise ValueError("private phrase must not leak")

    result = bench.measure_clip(
        clip,
        Profile("baseline"),
        Config.defaults(),
        SimpleNamespace(backend={}, transcribe=fail_decode),
    )
    assert result["status"] == "decode_error"
    assert result["error_type"] == "ValueError"
    assert result["stages"]["formatted"]["D"] == 2
    assert "private phrase" not in json.dumps(result)


def test_clip_integrity_checked_before_decode(tmp_path):
    import numpy as np

    clip = public_clip(tmp_path, np.zeros(16000, dtype=np.float32), "test")
    Path(clip["reference_path"]).write_text("changed")
    with pytest.raises(ValueError, match="reference_checksum_mismatch"):
        bench.measure_clip(
            clip, Profile("baseline"), Config.defaults(), SimpleNamespace(backend={})
        )


def test_model_overrides_are_ephemeral_and_preserve_other_settings():
    cfg = Config.defaults()
    overridden = bench.override_config(
        cfg, model="cached-model", compute_type="float32", cpu_threads=2
    )
    assert cfg.asr.model == "dropbox-dash/faster-whisper-large-v3-turbo"
    assert cfg.asr.compute_type == "int8"
    assert overridden.asr.model == "cached-model"
    assert overridden.asr.compute_type == "float32"
    assert overridden.asr.cpu_threads == 2
    assert overridden.asr.beam_size == cfg.asr.beam_size
    assert overridden.audio is cfg.audio
    assert overridden.refine is cfg.refine
    assert bench.override_config(cfg) == cfg
