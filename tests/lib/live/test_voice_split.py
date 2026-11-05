# SPDX-License-Identifier: GPL-3.0-or-later
"""Voice-change detection and splitting, with sample values that stand for voices."""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from stenographer.lib.live import voice_split
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.live.voice_split import (
    average_voices,
    group_and_split,
    source_segments,
    voice_change_cuts,
)

RATE = 16000
ANN, BOB, CAT = 0.004, 0.006, 0.008
UNIT = {
    ANN: np.array([1.0, 0.0, 0.0]),
    BOB: np.array([0.0, 1.0, 0.0]),
    CAT: np.array([0.0, 0.0, 1.0]),
}
VOICES = {"speaker-1": UNIT[ANN], "speaker-2": UNIT[BOB], "speaker-3": UNIT[CAT]}


def speech(*turns):
    """Join ``(voice, seconds)`` turns. All levels are below RMS 0.01, as quiet speech can be."""
    return np.concatenate(
        [np.full(round(seconds * RATE), voice, np.float32) for voice, seconds in turns]
    )


def embed(samples):
    """Mix the voices by share of samples, as an embedding of two talkers does in effect."""
    mix = np.zeros(3)
    for voice, unit in UNIT.items():
        mix += unit * np.mean(np.isclose(samples, voice, atol=1e-5))
    return mix


def line(start, end, speaker_id="speaker-1", wall="", text="whole phrase"):
    number = speaker_id.removeprefix("speaker-")
    return TranscriptLine(start, end, wall, "system", speaker_id, f"Speaker {number}", text)


def seconds(cuts):
    return [cut / RATE for cut in cuts]


def test_one_clear_change_gives_one_cut_near_it():
    samples = speech((ANN, 12.0), (BOB, 12.0))

    cuts = voice_change_cuts(samples, "speaker-1", VOICES, embed)

    assert len(cuts) == 1
    assert 10.5 <= cuts[0] / RATE <= 13.5


def test_one_voice_has_no_cut():
    assert voice_change_cuts(speech((ANN, 25.0)), "speaker-1", VOICES, embed) == ()


def test_a_session_with_one_voice_has_no_cut():
    samples = speech((ANN, 12.0), (BOB, 12.0))

    assert voice_change_cuts(samples, "speaker-1", {"speaker-1": UNIT[ANN]}, embed) == ()


def test_another_voice_in_one_slice_is_no_change():
    leaders = iter(["speaker-1", "speaker-1", "speaker-2", "speaker-1", "speaker-1"])
    vectors = {"speaker-1": UNIT[ANN], "speaker-2": UNIT[BOB]}

    cuts = voice_change_cuts(
        speech((ANN, 9.0)), "speaker-1", vectors, lambda _s: vectors[next(leaders)]
    )

    assert cuts == ()


def test_another_voice_in_only_the_first_slice_is_no_change():
    leaders = iter(["speaker-2", "speaker-1", "speaker-1", "speaker-1", "speaker-1"])
    vectors = {"speaker-1": UNIT[ANN], "speaker-2": UNIT[BOB]}

    cuts = voice_change_cuts(
        speech((ANN, 9.0)), "speaker-1", vectors, lambda _s: vectors[next(leaders)]
    )

    assert cuts == ()


def test_two_slices_with_a_lead_below_the_minimum_are_no_change():
    # After unit length the other voice leads by about 0.08 on the last slices.
    own = np.array([1.0, 0.0, 0.0])
    close = np.array([0.6, 0.67, 0.0])
    vectors = iter([own, own, own, close, close, close, close])

    cuts = voice_change_cuts(speech((ANN, 12.0)), "speaker-1", VOICES, lambda _s: next(vectors))

    assert cuts == ()


def test_a_lead_above_the_minimum_for_two_slices_is_a_change():
    # After unit length the other voice leads by about 0.16.
    other = np.array([0.5, 0.7, 0.0])
    own = np.array([1.0, 0.0, 0.0])
    vectors = iter([own, own, other, other, other, other, other])

    cuts = voice_change_cuts(speech((ANN, 12.0)), "speaker-1", VOICES, lambda _s: next(vectors))

    assert len(cuts) == 1


def test_several_changes_in_one_phrase_give_each_cut_in_time_order():
    samples = speech((ANN, 8.0), (BOB, 8.0), (ANN, 9.0))

    cuts = voice_change_cuts(samples, "speaker-1", VOICES, embed)

    assert len(cuts) == 2
    assert 6.5 <= cuts[0] / RATE <= 9.5
    assert 14.5 <= cuts[1] / RATE <= 17.5


def test_a_phrase_grouped_under_the_second_voice_cuts_at_the_same_change():
    samples = speech((ANN, 12.0), (BOB, 13.0))

    assert len(voice_change_cuts(samples, "speaker-2", VOICES, embed)) == 1


def test_a_phrase_that_is_all_another_voice_has_no_cut_inside():
    assert voice_change_cuts(speech((BOB, 12.0)), "speaker-1", VOICES, embed) == ()


def test_the_cut_falls_in_the_quietest_part_near_the_change_at_low_level():
    samples = speech((ANN, 10.0), (0.0002, 0.4), (BOB, 11.6))
    # A quieter stretch away from the change must not take the cut.
    samples[2 * RATE : int(2.5 * RATE)] = 0.00001

    cuts = voice_change_cuts(samples, "speaker-1", VOICES, embed)

    assert len(cuts) == 1
    assert 10.0 <= cuts[0] / RATE <= 10.4


def test_each_part_is_long_enough_for_the_speaker_model():
    samples = speech((BOB, 6.0), (ANN, 4.5), (BOB, 4.5), (CAT, 9.0))

    cuts = voice_change_cuts(samples, "speaker-1", VOICES, embed)

    edges = [0, *cuts, samples.size]
    assert len(cuts) >= 2
    assert all(right - left >= 1.5 * RATE for left, right in itertools.pairwise(edges))


OWN, OTHER, THIRD = "speaker-1", "speaker-2", "speaker-3"


def scripted_cuts(*leaders, own=OWN):
    """Return the cuts, in seconds, when each slice is led as given; ``None`` is unclear."""
    vectors = iter(np.ones(3) if leader is None else VOICES[leader] for leader in leaders)
    samples = speech((ANN, 3.0 + 1.5 * (len(leaders) - 1)))
    return seconds(voice_change_cuts(samples, own, VOICES, lambda _slice: next(vectors)))


def center(index):
    """Return the center, in seconds, of one slice."""
    return 1.5 + 1.5 * index


@pytest.mark.parametrize(
    "leaders",
    ((OWN, OTHER, OTHER), (THIRD, OTHER, OTHER)),
    ids=("own then other", "third then other"),
)
def test_one_clear_slice_before_a_run_of_another_voice_cuts_there(leaders):
    cuts = scripted_cuts(*leaders)

    assert len(cuts) == 1
    assert center(0) <= cuts[0] <= center(1)


@pytest.mark.parametrize(
    "leaders",
    ((OTHER, OTHER, OWN), (OTHER, OTHER, THIRD)),
    ids=("other then own", "other then third"),
)
def test_one_clear_slice_after_a_run_of_another_voice_cuts_there(leaders):
    cuts = scripted_cuts(*leaders)

    assert len(cuts) == 1
    assert center(1) <= cuts[0] <= center(2)


def test_unclear_slices_at_the_ends_of_a_run_make_no_cut():
    assert scripted_cuts(None, OTHER, OTHER, None) == []


def test_one_slice_of_a_third_voice_before_a_run_of_the_own_voice_makes_no_cut():
    cuts = scripted_cuts(THIRD, OWN, OWN, OTHER, OTHER)

    assert len(cuts) == 1
    assert center(2) <= cuts[0] <= center(3)


def test_one_slice_of_a_third_voice_after_a_run_of_the_own_voice_makes_no_cut():
    cuts = scripted_cuts(OTHER, OTHER, OWN, OWN, THIRD)

    assert len(cuts) == 1
    assert center(1) <= cuts[0] <= center(2)


def test_one_slice_of_a_third_voice_after_a_run_of_another_voice_cuts_there():
    cuts = scripted_cuts(OWN, OWN, OTHER, OTHER, THIRD)

    assert len(cuts) == 2
    assert center(1) <= cuts[0] <= center(2)
    assert center(3) <= cuts[1] <= center(4)


def test_average_voices_weigh_by_duration_and_skip_short_phrases():
    lines = [line(0, 3), line(3, 4.5), line(4.5, 5.5), line(5.5, 7, "speaker-2")]
    embeddings = [
        np.array([3.0, 0.0]),  # the length of an embedding does not count
        np.array([0.0, 2.0]),
        np.array([1.0, 0.0]),  # 1 s is below the limit, so this phrase does not count
        np.array([5.0, 5.0]),
    ]

    voices = average_voices(lines, embeddings)

    # Means: (3 * [1, 0] + 1.5 * [0, 1]) / 4.5 has the direction of (2, 1).
    assert voices["speaker-1"] == pytest.approx(np.array([2.0, 1.0]) / np.sqrt(5.0))
    assert voices["speaker-2"] == pytest.approx(np.array([1.0, 1.0]) / np.sqrt(2.0))


class Words:
    """Decode a part as the names of its voices, in order, or as nothing."""

    def __init__(self, *silent):
        self.calls = []
        self.silent = silent

    def __call__(self, samples):
        self.calls.append(samples.size)
        names = []
        for name, voice in (("ann", ANN), ("bob", BOB), ("cat", CAT)):
            if np.mean(np.isclose(samples, voice, atol=1e-5)) > 0.3:
                names.append(name)
        if any(name in self.silent for name in names):
            return " \n"
        return " ".join(names)


def two_voice_session(mixed):
    """Enough speech of Ann and Bob to group them, then one *mixed* phrase of 24 s."""
    lines = [line(0.0, 20.0), line(20.0, 40.0, "speaker-2"), line(40.0, 64.0)]
    embeddings = [UNIT[ANN], UNIT[BOB], embed(mixed)]
    return lines, embeddings


def reader(samples_by_start):
    def read(lines):
        for item in lines:
            yield samples_by_start[item.start]

    return read


def split(lines, embeddings, samples_by_start, decode, **options):
    return group_and_split(
        lines,
        embeddings,
        read_audio=reader(samples_by_start),
        embed=embed,
        decode=decode,
        **options,
    )


def audio_for(mixed):
    return {0.0: speech((ANN, 20.0)), 20.0: speech((BOB, 20.0)), 40.0: mixed}


def test_a_split_makes_a_line_per_voice_with_its_times_and_speaker():
    mixed = speech((ANN, 12.0), (BOB, 12.0))
    lines, embeddings = two_voice_session(mixed)

    result = split(lines, embeddings, audio_for(mixed), Words())

    assert [item.text for item in result.lines] == ["whole phrase", "whole phrase", "ann", "bob"]
    assert result.parents == (0, 1, 2, 2)
    ann_part, bob_part = result.lines[2:]
    assert ann_part.speaker_id == result.lines[0].speaker_id
    assert bob_part.speaker_id == result.lines[1].speaker_id
    assert ann_part.start == 40.0
    assert bob_part.end == 64.0
    assert ann_part.end == bob_part.start
    assert 50.5 <= ann_part.end <= 53.5


def test_a_split_line_gets_its_wall_time_from_the_phrase():
    mixed = speech((ANN, 12.0), (BOB, 12.0))
    lines, embeddings = two_voice_session(mixed)
    lines[2] = line(40.0, 64.0, wall="2026-11-05T10:00:40+00:00")

    result = split(lines, embeddings, audio_for(mixed), Words())

    first, second = result.lines[2:]
    assert first.wall == "2026-11-05T10:00:40+00:00"
    offset = second.start - 40.0
    whole_seconds = int(offset)
    assert second.wall.startswith(f"2026-11-05T10:00:{40 + whole_seconds:02d}")


def test_a_line_without_a_wall_time_stays_without_one():
    mixed = speech((ANN, 12.0), (BOB, 12.0))
    lines, embeddings = two_voice_session(mixed)

    result = split(lines, embeddings, audio_for(mixed), Words())

    assert [item.wall for item in result.lines[2:]] == ["", ""]


def test_a_phrase_splits_more_than_once():
    mixed = speech((ANN, 8.0), (BOB, 8.0), (ANN, 8.0))
    lines, embeddings = two_voice_session(mixed)

    result = split(lines, embeddings, audio_for(mixed), Words())

    assert [item.text for item in result.lines[2:]] == ["ann", "bob", "ann"]
    assert result.parents == (0, 1, 2, 2, 2)


def test_a_part_with_no_text_keeps_the_phrase_whole_with_its_words():
    mixed = speech((ANN, 12.0), (BOB, 12.0))
    lines, embeddings = two_voice_session(mixed)

    result = split(lines, embeddings, audio_for(mixed), Words("bob"))

    assert [item.text for item in result.lines] == ["whole phrase"] * 3
    assert result.parents == (0, 1, 2)
    assert (result.lines[2].start, result.lines[2].end) == (40.0, 64.0)


def test_a_short_phrase_is_not_read_or_checked():
    lines = [line(0.0, 20.0), line(20.0, 40.0, "speaker-2"), line(40.0, 45.9)]
    embeddings = [UNIT[ANN], UNIT[BOB], UNIT[ANN]]
    read = []

    def read_audio(long_lines):
        read.extend(item.start for item in long_lines)
        return reader({0.0: speech((ANN, 20.0)), 20.0: speech((BOB, 20.0))})(long_lines)

    result = group_and_split(lines, embeddings, read_audio=read_audio, embed=embed, decode=Words())

    assert read == [0.0, 20.0]
    assert result.parents == (0, 1, 2)


def test_a_phrase_of_exactly_the_limit_is_read_and_one_just_under_it_is_not():
    lines = [line(0.0, 20.0), line(20.0, 40.0, "speaker-2"), line(40.0, 46.0), line(50.0, 55.99)]
    embeddings = [UNIT[ANN], UNIT[BOB], UNIT[ANN], UNIT[ANN]]
    audio = {0.0: speech((ANN, 20.0)), 20.0: speech((BOB, 20.0)), 40.0: speech((ANN, 6.0))}
    read = []

    def read_audio(long_lines):
        read.extend(item.start for item in long_lines)
        return reader(audio)(long_lines)

    group_and_split(lines, embeddings, read_audio=read_audio, embed=embed, decode=Words())

    assert read == [0.0, 20.0, 40.0]


def test_a_phrase_between_six_and_seven_seconds_splits():
    mixed = speech((ANN, 2.0), (BOB, 4.5))
    lines = [line(0.0, 20.0), line(20.0, 40.0, "speaker-2"), line(40.0, 46.5)]
    embeddings = [UNIT[ANN], UNIT[BOB], UNIT[ANN]]
    audio = {0.0: speech((ANN, 20.0)), 20.0: speech((BOB, 20.0)), 40.0: mixed}

    result = split(lines, embeddings, audio, Words())

    assert [item.text for item in result.lines[2:]] == ["ann", "bob"]


def test_each_part_gets_an_embedding_of_only_its_own_audio():
    mixed = speech((ANN, 12.0), (BOB, 12.0))
    lines, embeddings = two_voice_session(mixed)
    embedded = []

    def recording_embed(samples):
        embedded.append(samples.copy())
        return embed(samples)

    result = group_and_split(
        lines,
        embeddings,
        read_audio=reader(audio_for(mixed)),
        embed=recording_embed,
        decode=Words(),
    )

    first, _second = result.lines[2:]
    cut = round((first.end - first.start) * RATE)
    # A slice has 3 s of audio, so the last two calls are the parts of the phrase.
    assert [part.size for part in embedded[-2:]] == [cut, mixed.size - cut]
    assert np.array_equal(embedded[-2], mixed[:cut])
    assert np.array_equal(embedded[-1], mixed[cut:])


def test_a_set_speaker_count_holds_where_automatic_grouping_gives_another_count():
    # Ann and Cat score 0.45: below the automatic limit of 0.5, but the closest pair.
    near_ann = np.array([0.45, 0.0, np.sqrt(1 - 0.45**2)])

    def near_embed(samples):
        return near_ann if np.isclose(np.median(samples), CAT, atol=1e-5) else embed(samples)

    mixed = speech((ANN, 12.0), (BOB, 12.0))
    lines = [
        line(0.0, 20.0),
        line(20.0, 40.0, "speaker-2"),
        line(40.0, 60.0, "speaker-3"),
        line(60.0, 84.0),
    ]
    embeddings = [UNIT[ANN], UNIT[BOB], near_ann, UNIT[ANN]]
    audio = {
        0.0: speech((ANN, 20.0)),
        20.0: speech((BOB, 20.0)),
        40.0: speech((CAT, 20.0)),
        60.0: mixed,
    }

    def grouped(count):
        return group_and_split(
            lines,
            embeddings,
            read_audio=reader(audio),
            embed=near_embed,
            decode=Words(),
            speaker_count=count,
        )

    assert len({item.speaker_id for item in grouped(None).lines}) == 3
    result = grouped(2)
    assert len(result.lines) == 5
    assert len({item.speaker_id for item in result.lines}) == 2


def test_a_source_with_one_voice_reads_no_audio():
    lines = [line(0.0, 20.0), line(20.0, 40.0)]

    def read_audio(_long_lines):
        raise AssertionError("no audio is needed for one voice")

    result = group_and_split(
        lines, [UNIT[ANN], UNIT[ANN]], read_audio=read_audio, embed=embed, decode=Words()
    )

    assert result.parents == (0, 1)


def test_a_source_without_audio_is_grouped_and_not_split():
    mixed = speech((ANN, 12.0), (BOB, 12.0))
    lines, embeddings = two_voice_session(mixed)

    result = group_and_split(lines, embeddings, read_audio=None, embed=embed, decode=Words())

    assert result.parents == (0, 1, 2)
    assert result.lines[0].speaker_id != result.lines[1].speaker_id


def test_a_set_speaker_count_holds_after_the_split():
    mixed = speech((ANN, 12.0), (CAT, 12.0))
    lines = [line(0.0, 20.0), line(20.0, 40.0, "speaker-2"), line(40.0, 64.0)]
    embeddings = [UNIT[ANN], UNIT[CAT], embed(mixed)]
    audio = {0.0: speech((ANN, 20.0)), 20.0: speech((CAT, 20.0)), 40.0: mixed}

    result = split(lines, embeddings, audio, Words(), speaker_count=2)

    assert len(result.lines) == 4
    assert len({item.speaker_id for item in result.lines}) == 2


def test_a_given_name_stays_with_its_voice_after_the_split():
    mixed = speech((ANN, 12.0), (BOB, 12.0))
    lines, embeddings = two_voice_session(mixed)
    lines[1] = TranscriptLine(20.0, 40.0, "", "system", "speaker-2", "Bea", "whole phrase")

    result = split(lines, embeddings, audio_for(mixed), Words())

    assert [(item.text, item.label) for item in result.lines[2:]] == [
        ("ann", "Speaker 1"),
        ("bob", "Bea"),
    ]


def test_progress_rises_to_one_and_never_falls_through_a_split():
    mixed = speech((ANN, 12.0), (BOB, 12.0))
    lines, embeddings = two_voice_session(mixed)
    seen = []

    split(lines, embeddings, audio_for(mixed), Words(), progress=seen.append)

    assert seen == sorted(seen)
    assert seen[0] == 0.0
    assert seen[-1] == 1.0


def test_progress_reaches_one_without_a_split():
    lines = [line(0.0, 20.0), line(20.0, 40.0, "speaker-2")]
    seen = []

    group_and_split(
        lines,
        [UNIT[ANN], UNIT[BOB]],
        read_audio=reader({0.0: speech((ANN, 20.0)), 20.0: speech((BOB, 20.0))}),
        embed=embed,
        decode=Words(),
        progress=seen.append,
    )

    assert seen == sorted(seen)
    assert seen[-1] == 1.0


def test_a_cancel_during_the_decode_of_a_part_ends_the_pass():
    mixed = speech((ANN, 12.0), (BOB, 12.0))
    lines, embeddings = two_voice_session(mixed)
    decode = Words()

    result = split(
        lines, embeddings, audio_for(mixed), decode, should_cancel=lambda: len(decode.calls) >= 1
    )

    assert result is None
    assert len(decode.calls) == 1


def test_a_cancel_closes_the_audio_reader():
    mixed = speech((ANN, 12.0), (BOB, 12.0))
    lines, embeddings = two_voice_session(mixed)
    closed = []

    def read_audio(long_lines):
        try:
            yield from reader(audio_for(mixed))(long_lines)
        finally:
            closed.append(True)

    checks = iter([False, False, False, True])
    # Relabel checks the cancel flag many times; let it pass, then cancel in the audio loop.
    calls = {"reader": False}

    def should_cancel():
        return calls["reader"] and next(checks, True)

    def start_reader(long_lines):
        calls["reader"] = True
        return read_audio(long_lines)

    result = group_and_split(
        lines,
        embeddings,
        read_audio=start_reader,
        embed=embed,
        decode=Words(),
        should_cancel=should_cancel,
    )

    assert result is None
    assert closed == [True]


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


def test_progress_never_falls_when_grouping_counts_past_its_total(monkeypatch):
    mixed = speech((ANN, 12.0), (BOB, 12.0))
    lines, embeddings = two_voice_session(mixed)
    real = voice_split.relabel_system_lines

    def overshoot(items, vectors, **options):
        result = real(items, vectors, **options)
        options["progress"](9, 5)
        return result

    monkeypatch.setattr(voice_split, "relabel_system_lines", overshoot)
    seen = []

    split(lines, embeddings, audio_for(mixed), Words(), progress=seen.append)

    assert seen == sorted(seen)
    assert seen[-1] == 1.0
