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

from transcription_study.asr_grid import grid_settings, repeated_phrase_hallucinations  # noqa: E402
from transcription_study.context import build_prompt, recording_groups  # noqa: E402
from transcription_study.decode import Decoder  # noqa: E402
from transcription_study.grid_report import render_markdown_table  # noqa: E402
from transcription_study.profiles import select_clips  # noqa: E402
from transcription_study.real_audio import candidate_snippets, wait_until_stable  # noqa: E402
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


def test_wait_for_stable_file_restarts_window_after_size_change(tmp_path, monkeypatch):
    from transcription_study import real_audio

    path = tmp_path / "recording.wav"
    path.write_bytes(b"first")
    elapsed = 0.0
    sleeps = []

    def fake_monotonic():
        return elapsed

    def fake_sleep(seconds):
        nonlocal elapsed
        sleeps.append(seconds)
        elapsed += seconds
        if len(sleeps) == 1:
            path.write_bytes(b"second")

    monkeypatch.setattr(real_audio.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(real_audio.time, "sleep", fake_sleep)
    assert wait_until_stable(path, stable_seconds=2, max_wait_seconds=10) == 6
    assert sleeps == [2, 2]


def test_long_audio_samples_only_known_suspicious_output_windows():
    snippets = candidate_snippets(
        "Safe text, then Kadian was mentioned. Later: and more. and more!"
    )
    assert len(snippets) == 1
    assert "Kadian" in snippets[0]
    assert "and more. and more" in snippets[0]


def test_context_groups_recordings_in_order_and_never_uses_own_reference():
    clips = [
        {"id": "late", "meeting": "ES2002a", "capture": "Headset-0", "start_seconds": 30},
        {"id": "other", "meeting": "ES2002a", "capture": "Headset-1", "start_seconds": 15},
        {"id": "early", "meeting": "ES2002a", "capture": "Headset-0", "start_seconds": 10},
        {"id": "middle", "meeting": "ES2002a", "capture": "Headset-0", "start_seconds": 20},
        {"id": "latest", "meeting": "ES2002a", "capture": "Headset-0", "start_seconds": 40},
    ]
    groups = recording_groups(clips)
    assert [[clip["id"] for clip in group] for group in groups] == [
        ["early", "middle", "late", "latest"],
        ["other"],
    ]
    prompt, source_ids = build_prompt(
        clips[4],
        groups[0][:3],
        references={
            "early": "prior one",
            "middle": "prior two",
            "late": "prior three",
            "latest": "private target reference",
        },
        decoded={},
        mode="reference",
    )
    assert prompt == "prior one prior two prior three"
    assert source_ids == ["early", "middle", "late"]
    assert "private target reference" not in prompt


def test_grid_markdown_table_formats_metrics_and_labels_reference_context_upper_bound():
    row = {
        "model": "medium.en",
        "setting": "beam1-hotwords-on-context-reference",
        "beam_size": 1,
        "hotwords": True,
        "context": "reference",
        "errors": 9,
        "N": 100,
        "wer": 0.09,
        "latency_median_seconds": 1.2345,
        "latency_p90_seconds": 1.5678,
        "extra_latency_vs_default_seconds": -0.1234,
        "latency_rtf": 0.4,
        "rss_peak_bytes": 1073741824,
    }
    assert render_markdown_table([row]) == (
        "| Model | Setting | WER | Median | p90 | Extra vs default | RTF | RSS peak |\n"
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |\n"
        "| medium.en | beam 1; hotwords on; context reference (upper bound) | "
        "9.00% (9/100) | 1.234 s | 1.568 s | -0.123 s | 0.400x | 1.00 GiB |"
    )


def test_grid_settings_cover_beam_hotwords_and_context_without_float32():
    settings = grid_settings()
    assert len(settings) == 12
    assert {setting.beam_size for setting in settings} == {1, 5}
    assert {setting.hotwords for setting in settings} == {False, True}
    assert {setting.context for setting in settings} == {"off", "reference", "decoded"}
    assert all(setting.compute_type == "int8" for setting in settings)
    assert len({setting.id for setting in settings}) == 12


def test_grid_decoder_forwards_temporary_settings_without_changing_config(monkeypatch):
    import numpy as np
    from transcription_study import decode

    observed = {}

    class Backend:
        device = "cpu"
        compute_type = "int8"

        def transcribe(self, samples, **options):
            observed.update(options)
            return iter(()), SimpleNamespace(duration_after_vad=len(samples) / 16000)

    backend = Backend()
    model = SimpleNamespace(
        _impl=SimpleNamespace(model=backend, transcribe=backend.transcribe), cpu_threads=2
    )
    monkeypatch.setattr(decode, "Model", lambda cfg: model)
    monkeypatch.setattr(
        decode, "_assemble", lambda *args, **kwargs: SimpleNamespace(segments=[], text="")
    )
    cfg = Config.defaults().asr
    decoder = Decoder(cfg)
    decoder.transcribe(
        np.ones(16000, dtype=np.float32),
        Profile("grid"),
        beam_size=5,
        hotwords=None,
        initial_prompt="previous context",
    )
    assert observed["beam_size"] == 5
    assert observed["hotwords"] is None
    assert observed["initial_prompt"] == "previous context"
    assert cfg.beam_size == 1
    assert cfg.hotwords is None


def test_known_repeated_phrase_counter_counts_adjacent_duplicate_occurrences():
    assert repeated_phrase_hallucinations("And more. AND more!") == 1
    assert repeated_phrase_hallucinations("and more. and more. and more.") == 2
    assert repeated_phrase_hallucinations("and more, then a little more") == 0


def test_context_decoded_mode_uses_only_last_three_prior_clips_and_resets_recording():
    clips = [
        {"id": str(index), "meeting": "ES2002a", "capture": "Headset-0", "start_seconds": index}
        for index in range(5)
    ]
    groups = recording_groups(clips)
    prompt, source_ids = build_prompt(
        clips[4],
        groups[0][:-1],
        references={},
        decoded={str(index): f"decoded {index}" for index in range(5)},
        mode="decoded",
    )
    assert prompt == "decoded 1 decoded 2 decoded 3"
    assert source_ids == ["1", "2", "3"]
    with pytest.raises(ValueError, match="same recording"):
        build_prompt(
            clips[4],
            [clips[0], {"id": "foreign", "meeting": "other", "capture": "Headset-0"}],
            references={},
            decoded={},
            mode="reference",
        )


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
