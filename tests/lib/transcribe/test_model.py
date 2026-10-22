# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for the decode helpers and the Model seam. No network, no model files."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from stenographer.lib.config.models import Config
from stenographer.lib.transcribe.decode import (
    _assemble,
    _validate_output,
    decode_segments,
    pad_samples,
    resolve_cpu_threads,
    words_from_tokens,
)
from stenographer.lib.transcribe.errors import PathologicalOutputError
from stenographer.lib.transcribe.results import SegmentInfo, WordInfo


def test_resolve_cpu_threads_explicit_passthrough():
    # An explicit config value wins even when the host counted its cores.
    assert resolve_cpu_threads(3, 16) == 3


def test_resolve_cpu_threads_uses_physical_core_count():
    assert resolve_cpu_threads(0, 4) == 4


def test_resolve_cpu_threads_caps_at_eight():
    # CTranslate2 scales badly past eight threads, so a big machine is capped.
    assert resolve_cpu_threads(0, 16) == 8


def test_resolve_cpu_threads_falls_back_when_host_cannot_count():
    # None is the host saying "cannot tell" (no affinity call or unreadable
    # topology) — never a guess derived from logical CPUs.
    assert resolve_cpu_threads(0, None) == 4


@pytest.mark.parametrize("count", [0, -1])
def test_resolve_cpu_threads_falls_back_on_nonsense_count(count):
    assert resolve_cpu_threads(0, count) == 4


def _valid_kwargs():
    return {
        "segment_timestamps": [(0.0, 1.0)],
        "word_timestamps": [(0.0, 0.5), (0.5, 1.0)],
        "word_count": 2,
        "audio_seconds": 2.0,
        "vad_seconds": 1.5,
    }


def test_validate_output_accepts_plausible_utterance():
    _validate_output(**_valid_kwargs())  # does not raise


def test_validate_output_rejects_end_before_start():
    kwargs = _valid_kwargs()
    kwargs["segment_timestamps"] = [(1.0, 0.5)]
    with pytest.raises(PathologicalOutputError):
        _validate_output(**kwargs)


def test_validate_output_rejects_timestamp_past_audio():
    kwargs = _valid_kwargs()
    kwargs["audio_seconds"] = 1.0
    kwargs["word_timestamps"] = [(0.0, 5.0)]
    with pytest.raises(PathologicalOutputError):
        _validate_output(**kwargs)


def test_validate_output_rejects_nonfinite_vad():
    kwargs = _valid_kwargs()
    kwargs["vad_seconds"] = math.inf
    with pytest.raises(PathologicalOutputError):
        _validate_output(**kwargs)


def test_validate_output_rejects_negative_vad():
    kwargs = _valid_kwargs()
    kwargs["vad_seconds"] = -0.1
    with pytest.raises(PathologicalOutputError):
        _validate_output(**kwargs)


def test_validate_output_rejects_word_density_runaway():
    kwargs = _valid_kwargs()
    kwargs["vad_seconds"] = 1.0  # limit = max(12, ceil(8*1)) = 12
    kwargs["word_count"] = 13
    with pytest.raises(PathologicalOutputError):
        _validate_output(**kwargs)


def test_validate_output_message_has_no_transcript_text():
    # The word "hello" is never passed in; the message must be counts-only.
    kwargs = _valid_kwargs()
    kwargs["vad_seconds"] = 1.0
    kwargs["word_count"] = 13
    with pytest.raises(PathologicalOutputError) as exc:
        _validate_output(**kwargs)
    message = str(exc.value)
    assert "13" in message and "12" in message
    assert not any(c.isalpha() for c in message.split("(", 1)[1])


def _segment(start, end, text, words=None):
    return SegmentInfo(start=start, end=end, text=text, words=words or [])


def test_assemble_keeps_every_segment_and_concatenates():
    w1 = WordInfo(0.0, 0.5, "hi", 0.9)
    w2 = WordInfo(1.0, 1.5, "there", 0.9)
    segments = [_segment(0.0, 0.5, " hi ", [w1]), _segment(1.0, 1.5, "there", [w2])]
    result = _assemble(segments, audio_seconds=2.0, vad_seconds=1.5)
    assert result.text == "hi there"
    assert result.duration_seconds == 2.0
    assert result.vad_seconds == 1.5
    assert result.segments == segments


def test_assemble_validates_word_density():
    words = [WordInfo(0.0, 0.01, "x", 0.9) for _ in range(13)]
    segments = [_segment(0.0, 1.0, "x" * 13, words)]
    with pytest.raises(PathologicalOutputError):
        _assemble(segments, audio_seconds=1.5, vad_seconds=1.0)


def test_segment_info_has_no_speech_probability():
    # Bark gives no no-speech estimate; silence is decided by the VAD instead.
    assert "no_speech_prob" not in {f.name for f in dataclasses.fields(SegmentInfo)}


# --- leading-silence pad ---


def test_pad_samples_prepends_a_quarter_second_of_zeros():
    speech = np.full(100, 0.5, dtype=np.float32)
    padded = pad_samples(speech, 0.25)
    assert padded.dtype == np.float32
    assert padded.shape == (4000 + 100,)
    assert not padded[:4000].any()
    assert padded[4000:].tolist() == speech.tolist()


# --- tokens to words ---


def test_tokens_join_into_words_at_the_word_marker():
    words = words_from_tokens(
        ["▁hel", "lo", "▁world"], [0.25, 0.33, 0.65], [0.08, 0.16, 0.24], [], offset=0.25
    )
    assert [w.word for w in words] == ["hello", "world"]
    assert words[0].start == pytest.approx(0.0)
    assert words[0].end == pytest.approx(0.24)  # 0.33 + 0.16 - 0.25
    assert words[1].start == pytest.approx(0.40)
    assert words[1].end == pytest.approx(0.64)


def test_a_space_prefix_also_starts_a_word():
    words = words_from_tokens([" so", " it", "s"], [0.0, 0.1, 0.2], [], [], offset=0.0)
    assert [w.word for w in words] == ["so", "its"]


def test_a_bare_marker_token_starts_the_next_word():
    words = words_from_tokens(["▁one", "▁", "two"], [0.0, 0.3, 0.4], [], [], offset=0.0)
    assert [w.word for w in words] == ["one", "two"]
    assert words[1].start == pytest.approx(0.4)


def test_punctuation_joins_the_word_and_keeps_its_span():
    words = words_from_tokens(
        ["▁yes", ",", "▁no", "."], [0.0, 0.5, 0.8, 1.6], [0.2, 0.08, 0.2, 0.08], [], offset=0.0
    )
    assert [w.word for w in words] == ["yes,", "no."]
    assert words[0].end == pytest.approx(0.2)
    assert words[1].end == pytest.approx(1.0)


def test_unknown_tokens_are_dropped():
    words = words_from_tokens(["▁a", "<unk>", "▁b"], [0.0, 0.2, 0.4], [], [], offset=0.0)
    assert [w.word for w in words] == ["a", "b"]


def test_timestamps_inside_the_pad_clamp_at_zero():
    words = words_from_tokens(["▁hi"], [0.1], [0.08], [], offset=0.25)
    assert words[0].start == 0.0
    assert words[0].end == 0.0


def test_missing_durations_give_point_spans():
    words = words_from_tokens(["▁hi"], [0.5], [], [], offset=0.25)
    assert (words[0].start, words[0].end) == (pytest.approx(0.25), pytest.approx(0.25))


def test_word_probability_is_exp_of_mean_token_log_prob():
    words = words_from_tokens(
        ["▁hel", "lo", "▁x"], [0.0, 0.1, 0.2], [], [-0.2, -0.4, 0.0], offset=0.0
    )
    assert words[0].probability == pytest.approx(math.exp(-0.3))
    assert words[1].probability == pytest.approx(1.0)


def test_word_probability_is_one_without_log_probs():
    words = words_from_tokens(["▁hi", "▁yo"], [0.0, 0.2], [], [], offset=0.0)
    assert [w.probability for w in words] == [1.0, 1.0]


def test_word_probability_is_one_when_log_probs_do_not_align():
    words = words_from_tokens(["▁hi", "▁yo"], [0.0, 0.2], [], [-0.5], offset=0.0)
    assert [w.probability for w in words] == [1.0, 1.0]


# --- one segment per decode ---


def test_a_decode_gives_one_segment_spanning_its_words():
    words = [WordInfo(0.1, 0.4, "hi", 1.0), WordInfo(0.5, 0.9, "there", 1.0)]
    [segment] = decode_segments(" hi there ", words)
    assert (segment.start, segment.end, segment.text) == (0.1, 0.9, "hi there")
    assert segment.words == words


def test_an_empty_or_unknown_only_decode_gives_no_segment():
    assert decode_segments("  ", []) == []
    assert decode_segments("<unk>", []) == []


def test_unknown_markers_leave_the_segment_text():
    [segment] = decode_segments("a <unk>b", [])
    assert segment.text == "a b"


# --- Model wiring through an injected recognizer ---


class _Result:
    def __init__(self, text, tokens, timestamps, durations, ys_log_probs=()):
        self.text = text
        self.tokens = tokens
        self.timestamps = timestamps
        self.durations = durations
        self.ys_log_probs = ys_log_probs


class _Stream:
    def __init__(self, result):
        self.result = result
        self.accepted = []

    def accept_waveform(self, sample_rate, samples):
        self.accepted.append((sample_rate, np.array(samples)))


class _Recognizer:
    """Stands in for ``sherpa_onnx.OfflineRecognizer``, the one external dependency."""

    def __init__(self, result):
        self._result = result
        self.streams = []

    def create_stream(self):
        stream = _Stream(self._result)
        self.streams.append(stream)
        return stream

    def decode_stream(self, stream):
        stream.decoded = True


def _model(result):
    from stenographer.lib.transcribe.model import Model

    cfg = dataclasses.replace(Config.defaults().asr, cpu_threads=2)
    recognizer = _Recognizer(result)
    return Model(cfg, recognizer=recognizer), recognizer


def test_model_decodes_padded_samples_and_shifts_timestamps_back():
    model, recognizer = _model(
        _Result(" hi there", ["▁hi", "▁there"], [0.33, 0.65], [0.16, 0.24], [-0.1, -0.2])
    )
    speech = np.full(8000, 0.1, dtype=np.float32)
    result = model.transcribe(speech)

    [stream] = recognizer.streams
    [(rate, accepted)] = stream.accepted
    assert rate == 16000
    assert accepted.shape == (4000 + 8000,)
    assert not accepted[:4000].any()
    assert result.text == "hi there"
    assert result.duration_seconds == pytest.approx(0.5)
    assert result.vad_seconds == pytest.approx(0.5)
    [segment] = result.segments
    assert [(w.word, round(w.start, 2), round(w.end, 2)) for w in segment.words] == [
        ("hi", 0.08, 0.24),
        ("there", 0.4, 0.64),
    ]


def test_model_returns_an_empty_result_for_an_empty_decode():
    model, _ = _model(_Result("", [], [], []))
    result = model.transcribe(np.zeros(16000, dtype=np.float32))
    assert result.text == ""
    assert result.segments == []


def test_model_rejects_a_runaway_decode():
    tokens = [f"▁w{i}" for i in range(40)]
    model, _ = _model(_Result(" ".join(tokens), tokens, [0.25] * 40, []))
    with pytest.raises(PathologicalOutputError):
        model.transcribe(np.zeros(16000, dtype=np.float32))


def test_model_load_names_the_download_when_the_model_is_missing(tmp_path):
    from stenographer.lib.transcribe.model import Model

    cfg = dataclasses.replace(Config.defaults().asr, cpu_threads=2)
    with pytest.raises(FileNotFoundError, match="model download --asr"):
        Model(cfg, data_dir=tmp_path)


def test_only_an_empty_capture_skips_the_decoder():
    from stenographer.lib.transcribe.model import Model

    assert Model._is_silent_input(np.empty(0, dtype=np.float32)) is True
    # Silence is not the same as no audio: the dictation VAD decides silence
    # before the decode; a captured silent buffer still reaches the decoder.
    assert Model._is_silent_input(np.zeros(16000, dtype=np.float32)) is False


def test_multichannel_captures_are_downmixed_to_one_dimension():
    from stenographer.lib.transcribe.model import Model

    stereo = np.array([[1.0, 0.0], [0.5, 0.5]], dtype=np.float32)
    single = np.array([[0.25], [0.75]], dtype=np.float32)
    mono = np.array([0.25, 0.75], dtype=np.float32)

    assert Model._prepare_samples(stereo).tolist() == [0.5, 0.5]
    assert Model._prepare_samples(single).tolist() == [0.25, 0.75]
    assert Model._prepare_samples(single).ndim == 1
    assert Model._prepare_samples(mono) is mono
