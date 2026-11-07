# SPDX-License-Identifier: GPL-3.0-or-later
"""Speakers and splits of saved lines from pieces of speech, with values that stand for voices."""

from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from stenographer.lib.live import voice_split
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.live.voice_split import (
    average_voices,
    group_and_split,
    read_saved_source,
    source_segments,
)

RATE = 16000
ANN, BOB, CAT = 0.1, 0.4, 0.7
UNIT = {
    ANN: np.array([1.0, 0.0, 0.0]),
    BOB: np.array([0.0, 1.0, 0.0]),
    CAT: np.array([0.0, 0.0, 1.0]),
}


def speech(*turns):
    """Join ``(voice, seconds)`` turns. A voice of 0 is silence."""
    return np.concatenate(
        [np.full(round(seconds * RATE), voice, np.float32) for voice, seconds in turns]
    )


def embed(samples):
    """Return the unit vector of the most common voice."""
    level = float(np.median(samples))
    return UNIT[min(UNIT, key=lambda voice: abs(voice - level))]


def line(start, end, speaker_id="speaker-1", wall="", text="whole phrase", label=None):
    number = speaker_id.removeprefix("speaker-")
    return TranscriptLine(
        start, end, wall, "system", speaker_id, label or f"Speaker {number}", text
    )


class Words:
    """Decode a part as the names of its voices, in order, or as nothing."""

    def __init__(self, *silent):
        self.parts = []
        self.silent = silent

    def __call__(self, samples):
        self.parts.append(samples.copy())
        names = [
            name
            for name, voice in (("ann", ANN), ("bob", BOB), ("cat", CAT))
            if np.mean(np.isclose(samples, voice, atol=1e-5)) > 0.2
        ]
        if any(name in self.silent for name in names):
            return " \n"
        return " ".join(names)


@pytest.fixture
def run(monkeypatch):
    """Run the method on *samples*, with *pieces* as the result of the pass."""

    def go(lines, samples, pieces, *, vectors=None, decode=None, **options):
        monkeypatch.setattr(
            voice_split, "find_speech_pieces", lambda *_args, **_keys: tuple(pieces)
        )
        return group_and_split(
            lines,
            [embed(samples[int(i.start * RATE) : int(i.end * RATE)]) for i in lines]
            if vectors is None
            else vectors,
            read_source=lambda: samples,
            speaker_model="speaker.onnx",
            embed=options.pop("embed", embed),
            decode=decode or Words(),
            **options,
        )

    return go


# 20 s of Ann and 20 s of Bob: a clear pair of speakers for every test below.
TWO_VOICES = ((ANN, 20.0), (BOB, 20.0))
PIECES = [(0.0, 20.0), (20.0, 40.0)]


def speakers(result):
    return [item.speaker_id for item in result.lines]


def test_a_line_gets_the_speaker_with_the_most_overlap(run):
    samples = speech(*TWO_VOICES)

    # The line holds 0.5 s of Ann and 3 s of Bob, and neither run counts for a cut with one voice.
    result = run([line(0.0, 20.0), line(19.5, 23.0), line(30.0, 40.0)], samples, PIECES)

    assert speakers(result) == ["speaker-1", "speaker-2", "speaker-2"]
    assert result.parents == (0, 1, 2)


def test_many_short_overlaps_of_a_speaker_count_together(run):
    samples = speech((ANN, 5.0), (BOB, 5.0), (ANN, 20.0), (BOB, 20.0))
    pieces = [(0.0, 5.0), (5.0, 5.9), (5.9, 6.6), (6.6, 7.5), (10.0, 30.0), (30.0, 50.0)]

    # Bob holds 2.5 s in small pieces, Ann 0.5 s. No piece of Bob reaches 1 s in the line.
    result = run(
        [line(10.0, 30.0), line(30.0, 50.0), line(4.5, 7.5)],
        samples,
        pieces,
        vectors=[UNIT[ANN], UNIT[BOB], UNIT[BOB]],
        embed=lambda piece: (
            UNIT[ANN] if float(np.median(piece)) == pytest.approx(ANN) else UNIT[BOB]
        ),
    )

    assert result.parents == (0, 1, 2)
    assert result.lines[2].speaker_id == result.lines[1].speaker_id


def test_a_cut_makes_a_line_per_voice_with_its_times_and_speaker(run):
    samples = speech(*TWO_VOICES, (ANN, 12.0), (BOB, 12.0))
    pieces = [*PIECES, (40.0, 52.0), (52.0, 64.0)]
    decode = Words()

    result = run(
        [line(0.0, 20.0), line(20.0, 40.0), line(40.0, 64.0)], samples, pieces, decode=decode
    )

    assert [item.text for item in result.lines] == ["whole phrase", "whole phrase", "ann", "bob"]
    assert result.parents == (0, 1, 2, 2)
    assert speakers(result) == ["speaker-1", "speaker-2", "speaker-1", "speaker-2"]
    ann_part, bob_part = result.lines[2:]
    assert (ann_part.start, ann_part.end) == (40.0, 52.0)
    assert (bob_part.start, bob_part.end) == (52.0, 64.0)
    assert [part.size for part in decode.parts] == [12 * RATE, 12 * RATE]
    assert np.array_equal(decode.parts[0], samples[40 * RATE : 52 * RATE])
    assert np.array_equal(decode.parts[1], samples[52 * RATE : 64 * RATE])


def test_a_short_line_cuts_because_a_line_has_no_minimum_length(run):
    samples = speech(*TWO_VOICES, (ANN, 1.25), (BOB, 1.25))
    pieces = [*PIECES, (40.0, 41.25), (41.25, 42.5)]

    result = run([line(0.0, 20.0), line(20.0, 40.0), line(40.0, 42.5)], samples, pieces)

    assert [item.text for item in result.lines[2:]] == ["ann", "bob"]


def test_a_voice_of_exactly_one_second_cuts_and_one_just_under_it_does_not(run):
    samples = speech(*TWO_VOICES, (ANN, 5.0), (BOB, 1.0), (ANN, 5.0), (BOB, 0.99), (ANN, 5.0))
    pieces = [
        *PIECES,
        (40.0, 45.0),
        (45.0, 46.0),
        (46.0, 51.0),
        (51.0, 51.99),
        (51.99, 56.99),
    ]
    lines = [line(0.0, 20.0), line(20.0, 40.0), line(40.0, 51.0), line(51.0, 56.99)]

    result = run(lines, samples, pieces)

    assert [item.text for item in result.lines[2:]] == ["ann", "bob", "ann", "whole phrase"]
    assert result.parents == (0, 1, 2, 2, 2, 3)
    assert result.lines[-1].speaker_id == "speaker-1"


def test_a_long_piece_counts_only_for_its_time_inside_the_line(run):
    samples = speech(*TWO_VOICES)

    # Bob's piece is 20 s long, but only 0.5 s of it is inside the line.
    result = run([line(0.0, 20.0), line(20.0, 40.0), line(15.0, 20.5)], samples, PIECES)

    assert result.parents == (0, 1, 2)
    assert result.lines[2].speaker_id == "speaker-1"


def test_two_runs_of_one_speaker_with_a_short_other_voice_between_them_make_no_cut(run):
    samples = speech(*TWO_VOICES, (ANN, 5.0), (BOB, 0.6), (ANN, 5.0))
    pieces = [*PIECES, (40.0, 45.0), (45.0, 45.6), (45.6, 50.6)]

    result = run([line(0.0, 20.0), line(20.0, 40.0), line(40.0, 50.6)], samples, pieces)

    assert [item.text for item in result.lines] == ["whole phrase"] * 3


def test_the_cut_falls_in_the_middle_of_a_gap_between_two_voices(run):
    samples = speech(*TWO_VOICES, (ANN, 5.0), (0.0, 2.0), (BOB, 5.0))
    pieces = [*PIECES, (40.0, 45.0), (47.0, 52.0)]

    result = run([line(0.0, 20.0), line(20.0, 40.0), line(40.0, 52.0)], samples, pieces)

    assert result.lines[2].end == result.lines[3].start == 46.0


def test_the_cut_falls_where_the_later_voice_starts_when_two_voices_overlap(run):
    samples = speech(*TWO_VOICES, (ANN, 6.0), (BOB, 6.0))
    pieces = [*PIECES, (40.0, 47.0), (45.0, 52.0)]

    result = run([line(0.0, 20.0), line(20.0, 40.0), line(40.0, 52.0)], samples, pieces)

    assert result.lines[2].end == result.lines[3].start == 45.0


def test_a_voice_inside_a_longer_piece_gets_a_run_and_the_longer_voice_continues(run):
    samples = speech(*TWO_VOICES, (ANN, 3.0), (BOB, 2.0), (ANN, 5.0))
    pieces = [*PIECES, (40.0, 50.0), (43.0, 45.0)]

    result = run([line(0.0, 20.0), line(20.0, 40.0), line(40.0, 50.0)], samples, pieces)

    assert [item.text for item in result.lines[2:]] == ["ann", "bob", "ann"]
    assert [(item.start, item.end) for item in result.lines[2:]] == [
        (40.0, 43.0),
        (43.0, 45.0),
        (45.0, 50.0),
    ]


def test_the_piece_that_started_last_holds_the_time_when_both_start_before_the_line(run):
    samples = speech(*TWO_VOICES, (ANN, 3.0), (BOB, 4.0), (ANN, 3.0))
    # Bob starts after Ann, and both start before the line at 45 s.
    pieces = [*PIECES, (40.0, 50.0), (43.0, 47.0)]

    result = run([line(0.0, 20.0), line(20.0, 40.0), line(45.0, 49.0)], samples, pieces)

    assert [item.text for item in result.lines[2:]] == ["bob", "ann"]
    assert [(item.start, item.end) for item in result.lines[2:]] == [(45.0, 47.0), (47.0, 49.0)]
    assert speakers(result)[2:] == [result.lines[1].speaker_id, result.lines[0].speaker_id]


def test_a_voice_cut_short_by_overlaps_on_both_sides_joins_its_neighbours_with_no_cut(run):
    samples = speech(*TWO_VOICES, (ANN, 1.6), (BOB, 0.9), (ANN, 2.5))
    # Bob overlaps the line for 1.2 s but holds only 0.9 s, so one run of Ann remains.
    pieces = [*PIECES, (40.0, 42.0), (41.6, 42.8), (42.5, 45.0)]

    result = run([line(0.0, 20.0), line(20.0, 40.0), line(40.0, 45.0)], samples, pieces)

    assert [item.text for item in result.lines] == ["whole phrase"] * 3
    assert result.parents == (0, 1, 2)
    assert result.lines[2].speaker_id == result.lines[0].speaker_id


def test_a_voice_that_loses_its_time_to_an_overlap_makes_no_cut(run):
    samples = speech(*TWO_VOICES, (ANN, 1.5), (BOB, 7.0))
    # Ann overlaps the line for 2 s, but Bob starts after 0.5 s and holds the rest.
    pieces = [*PIECES, (40.0, 42.0), (40.5, 48.5)]

    result = run([line(0.0, 20.0), line(20.0, 40.0), line(40.0, 48.5)], samples, pieces)

    assert result.parents == (0, 1, 2)
    assert result.lines[2].speaker_id == "speaker-2"


def test_a_line_with_no_piece_gets_the_closest_voice_and_stays(run):
    samples = speech(*TWO_VOICES, (0.0, 10.0))

    result = run(
        [line(0.0, 20.0), line(20.0, 40.0), line(41.0, 43.0)],
        samples,
        PIECES,
        vectors=[UNIT[ANN], UNIT[BOB], np.array([0.1, 0.9, 0.0])],
    )

    assert speakers(result) == ["speaker-1", "speaker-2", "speaker-2"]
    assert result.parents == (0, 1, 2)


def test_a_line_with_no_piece_has_a_voice_when_every_piece_is_short(run):
    samples = speech((ANN, 1.0), (0.0, 9.0))

    result = run(
        [line(0.0, 1.0), line(5.0, 6.0)],
        samples,
        [(0.0, 1.0)],
        vectors=[UNIT[ANN], UNIT[BOB]],
    )

    assert speakers(result) == ["speaker-1", "speaker-1"]


def test_speakers_number_from_one_by_their_first_line(run):
    samples = speech(*TWO_VOICES, (CAT, 20.0))

    # Ann has pieces but no line, so Bob and Cat are the only speakers with lines.
    result = run([line(20.0, 40.0), line(40.0, 60.0)], samples, [*PIECES, (40.0, 60.0)])

    assert speakers(result) == ["speaker-1", "speaker-2"]
    assert [item.label for item in result.lines] == ["Speaker 1", "Speaker 2"]


def test_a_name_on_a_split_line_follows_the_voice_with_the_most_of_its_speech(run):
    samples = speech(*TWO_VOICES, (ANN, 12.0), (BOB, 12.0))
    lines = [line(0.0, 20.0), line(20.0, 40.0, label="Bea"), line(40.0, 64.0)]

    result = run(lines, samples, [*PIECES, (40.0, 52.0), (52.0, 64.0)])

    assert [(item.text, item.label) for item in result.lines[2:]] == [
        ("ann", "Speaker 1"),
        ("bob", "Bea"),
    ]


def test_each_piece_embeds_only_its_own_audio(run):
    samples = speech(*TWO_VOICES)
    embedded = []

    def record(piece):
        embedded.append(piece.copy())
        return embed(piece)

    run([line(0.0, 20.0), line(20.0, 40.0)], samples, [(1.0, 3.0), (25.0, 30.5)], embed=record)

    assert [piece.size for piece in embedded] == [2 * RATE, round(5.5 * RATE)]
    assert np.array_equal(embedded[0], samples[RATE : 3 * RATE])
    assert np.array_equal(embedded[1], samples[25 * RATE : round(30.5 * RATE)])


def test_pieces_group_at_the_limit_of_one_half(run):
    samples = speech((ANN, 20.0), (BOB, 20.0))
    other = {
        0.51: np.array([0.51, np.sqrt(1 - 0.51**2)]),
        0.49: np.array([0.49, np.sqrt(1 - 0.49**2)]),
    }

    def count(score):
        vectors = iter([np.array([1.0, 0.0]), other[score]])
        result = run(
            [line(0.0, 20.0), line(20.0, 40.0)],
            samples,
            PIECES,
            vectors=[np.array([1.0, 0.0]), other[score]],
            embed=lambda _piece: next(vectors),
        )
        return len(set(speakers(result)))

    assert count(0.51) == 1
    assert count(0.49) == 2


def test_a_set_speaker_count_applies_to_the_pieces(run):
    samples = speech((ANN, 20.0), (BOB, 20.0), (CAT, 20.0))
    pieces = [*PIECES, (40.0, 60.0)]
    lines = [line(0.0, 20.0), line(20.0, 40.0), line(40.0, 60.0)]

    assert len(set(speakers(run(lines, samples, pieces)))) == 3
    assert len(set(speakers(run(lines, samples, pieces, speaker_count=2)))) == 2


def test_a_part_with_no_text_keeps_the_line_whole_with_its_words(run):
    samples = speech(*TWO_VOICES, (ANN, 9.0), (BOB, 15.0))
    pieces = [*PIECES, (40.0, 49.0), (49.0, 64.0)]

    result = run(
        [line(0.0, 20.0), line(20.0, 40.0), line(40.0, 64.0)],
        samples,
        pieces,
        decode=Words("ann"),
    )

    assert [item.text for item in result.lines] == ["whole phrase"] * 3
    assert result.parents == (0, 1, 2)
    assert (result.lines[2].start, result.lines[2].end) == (40.0, 64.0)
    assert result.lines[2].speaker_id == result.lines[1].speaker_id


def test_a_part_gets_its_wall_time_from_the_line(run):
    samples = speech(*TWO_VOICES, (ANN, 12.0), (BOB, 12.0))
    lines = [line(0.0, 20.0), line(20.0, 40.0), line(40.0, 64.0, wall="2026-11-05T10:00:40+00:00")]

    result = run(lines, samples, [*PIECES, (40.0, 52.0), (52.0, 64.0)])

    assert [item.wall for item in result.lines[2:]] == [
        "2026-11-05T10:00:40+00:00",
        "2026-11-05T10:00:52+00:00",
    ]


def test_a_part_of_a_line_without_a_wall_time_stays_without_one(run):
    samples = speech(*TWO_VOICES, (ANN, 12.0), (BOB, 12.0))
    lines = [line(0.0, 20.0), line(20.0, 40.0), line(40.0, 64.0)]

    result = run(lines, samples, [*PIECES, (40.0, 52.0), (52.0, 64.0)])

    assert [item.wall for item in result.lines[2:]] == ["", ""]


def test_a_source_without_audio_groups_whole_lines_and_runs_no_pass(monkeypatch):
    def no_pass(*_args, **_options):
        raise AssertionError("a source without audio runs no pass")

    monkeypatch.setattr(voice_split, "find_speech_pieces", no_pass)

    result = group_and_split(
        [line(0.0, 20.0), line(20.0, 40.0), line(40.0, 64.0)],
        [UNIT[ANN], UNIT[BOB], UNIT[ANN]],
        read_source=None,
        speaker_model="speaker.onnx",
        embed=embed,
        decode=Words(),
    )

    assert speakers(result) == ["speaker-1", "speaker-2", "speaker-1"]
    assert result.parents == (0, 1, 2)


def test_no_speech_groups_whole_lines(run):
    samples = speech((0.0, 40.0))

    result = run([line(0.0, 20.0), line(20.0, 40.0)], samples, [], vectors=[UNIT[ANN], UNIT[BOB]])

    assert speakers(result) == ["speaker-1", "speaker-2"]


def test_a_source_with_no_lines_reads_no_audio_and_runs_no_pass(monkeypatch):
    def no_pass(*_args, **_options):
        raise AssertionError("a source with no lines runs no pass")

    monkeypatch.setattr(voice_split, "find_speech_pieces", no_pass)
    seen = []

    result = group_and_split(
        [],
        [],
        read_source=no_pass,
        speaker_model="speaker.onnx",
        embed=embed,
        decode=Words(),
        progress=seen.append,
    )

    assert (result.lines, result.parents) == ((), ())
    assert seen == [1.0]


def test_a_cancel_in_the_pass_ends_the_method(monkeypatch):
    monkeypatch.setattr(voice_split, "find_speech_pieces", lambda *_args, **_options: None)
    samples = speech(*TWO_VOICES)

    result = group_and_split(
        [line(0.0, 20.0)],
        [UNIT[ANN]],
        read_source=lambda: samples,
        speaker_model="speaker.onnx",
        embed=embed,
        decode=Words(),
    )

    assert result is None


def test_a_cancel_between_piece_embeddings_ends_the_method(run):
    samples = speech(*TWO_VOICES)
    embedded = []

    def record(piece):
        embedded.append(piece.size)
        return embed(piece)

    result = run(
        [line(0.0, 20.0), line(20.0, 40.0)],
        samples,
        PIECES,
        embed=record,
        should_cancel=lambda: len(embedded) >= 1,
    )

    assert result is None
    assert len(embedded) == 1


def test_a_cancel_during_the_decode_of_a_part_ends_the_method(run):
    samples = speech(*TWO_VOICES, (ANN, 12.0), (BOB, 12.0))
    decode = Words()

    result = run(
        [line(0.0, 20.0), line(20.0, 40.0), line(40.0, 64.0)],
        samples,
        [*PIECES, (40.0, 52.0), (52.0, 64.0)],
        decode=decode,
        should_cancel=lambda: len(decode.parts) >= 1,
    )

    assert result is None
    assert len(decode.parts) == 1


def test_progress_rises_to_one_and_never_falls_through_the_method(monkeypatch):
    samples = speech(*TWO_VOICES, (ANN, 12.0), (BOB, 12.0))

    def find(_samples, _model, *, progress, should_cancel):
        assert not should_cancel()
        progress(0.5)
        progress(1.0)
        return (*PIECES, (40.0, 52.0), (52.0, 64.0))

    monkeypatch.setattr(voice_split, "find_speech_pieces", find)
    seen = []

    group_and_split(
        [line(0.0, 20.0), line(20.0, 40.0), line(40.0, 64.0)],
        [UNIT[ANN], UNIT[BOB], UNIT[ANN]],
        read_source=lambda: samples,
        speaker_model="speaker.onnx",
        embed=embed,
        decode=Words(),
        progress=seen.append,
    )

    assert seen == sorted(seen)
    assert seen[-1] == 1.0
    assert len(set(seen)) > 3


@pytest.mark.parametrize("speaker_count", [None, 2])
def test_progress_never_falls_when_the_pass_finds_no_speech(monkeypatch, speaker_count):
    def find(_samples, _model, *, progress, should_cancel):
        assert not should_cancel()
        progress(1.0)
        return ()

    monkeypatch.setattr(voice_split, "find_speech_pieces", find)
    seen = []

    group_and_split(
        [line(0.0, 20.0), line(20.0, 40.0)],
        [UNIT[ANN], UNIT[BOB]],
        read_source=lambda: speech((0.0, 40.0)),
        speaker_model="speaker.onnx",
        embed=embed,
        decode=Words(),
        progress=seen.append,
        speaker_count=speaker_count,
    )

    assert seen == sorted(seen)
    assert seen[-1] == 1.0


@pytest.mark.parametrize("speaker_count", [None, 2])
def test_progress_never_falls_with_pieces_and_any_speaker_count(run, speaker_count):
    samples = speech(*TWO_VOICES, (ANN, 12.0), (BOB, 12.0))
    seen = []

    run(
        [line(0.0, 20.0), line(20.0, 40.0), line(40.0, 64.0)],
        samples,
        [*PIECES, (40.0, 52.0), (52.0, 64.0)],
        progress=seen.append,
        speaker_count=speaker_count,
    )

    assert seen == sorted(seen)
    assert seen[-1] == 1.0


def test_progress_never_falls_with_only_short_pieces(run):
    samples = speech((ANN, 1.0), (0.0, 1.0))
    seen = []

    run([line(0.0, 1.0)], samples, [(0.0, 1.0)], progress=seen.append)

    assert seen == sorted(seen)
    assert seen[-1] == 1.0


def test_progress_never_falls_when_grouping_counts_past_its_total(monkeypatch, run):
    samples = speech(*TWO_VOICES)
    real = voice_split.relabel_system_lines

    def overshoot(items, vectors, **options):
        result = real(items, vectors, **options)
        options["progress"](9, 5)
        return result

    monkeypatch.setattr(voice_split, "relabel_system_lines", overshoot)
    seen = []

    run([line(0.0, 20.0), line(20.0, 40.0)], samples, PIECES, progress=seen.append)

    assert seen == sorted(seen)
    assert seen[-1] == 1.0


def test_average_voices_weigh_by_duration_and_ignore_vector_length():
    lines = [line(0, 3), line(3, 4.5), line(5.5, 7, "speaker-2")]
    embeddings = [np.array([3.0, 0.0]), np.array([0.0, 2.0]), np.array([5.0, 5.0])]

    voices = average_voices(lines, embeddings)

    # Means: (3 * [1, 0] + 1.5 * [0, 1]) / 4.5 has the direction of (2, 1).
    assert voices["speaker-1"] == pytest.approx(np.array([2.0, 1.0]) / np.sqrt(5.0))
    assert voices["speaker-2"] == pytest.approx(np.array([1.0, 1.0]) / np.sqrt(2.0))


def test_read_saved_source_returns_every_sample_of_a_mono_file(tmp_path):
    path = tmp_path / "mic.flac"
    samples = np.linspace(-0.5, 0.5, 40001, dtype=np.float32)
    sf.write(path, samples, RATE, format="FLAC", subtype="PCM_24")

    read = read_saved_source(path)

    assert read.size == samples.size
    assert read == pytest.approx(samples, abs=1e-5)


def test_read_saved_source_mixes_two_channels(tmp_path):
    path = tmp_path / "mic.flac"
    sf.write(path, np.full((RATE, 2), (0.2, 0.4), np.float32), RATE, format="FLAC")

    assert read_saved_source(path) == pytest.approx(np.full(RATE, 0.3), abs=1e-4)


def test_read_saved_source_rejects_another_rate(tmp_path):
    path = tmp_path / "mic.flac"
    sf.write(path, np.zeros(8000, np.float32), 8000, format="FLAC")

    with pytest.raises(ValueError, match="16000 Hz"):
        read_saved_source(path)


def test_source_segments_gives_each_interval_across_chunks():
    chunks = iter(
        [np.arange(0, 16000, dtype=np.float32), np.arange(16000, 48000, dtype=np.float32)]
    )

    found = list(source_segments(chunks, [line(0.5, 1.5), line(2.0, 2.5)]))

    assert [index for index, _ in found] == [0, 1]
    assert found[0][1][0] == 8000
    assert found[0][1].size == 16000
    assert found[1][1][0] == 32000
    assert found[1][1].size == 8000
