# SPDX-License-Identifier: GPL-3.0-or-later
"""The line rule: cut at speaker changes, number speakers, keep given names."""

from __future__ import annotations

import numpy as np
import pytest

from stenographer.lib.live.speaker_lines import (
    Piece,
    SpeakerNames,
    StreamClock,
    given_name,
    relabel_lines,
    speaker_pieces,
)
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.platform.speaker_diarizer import SpeakerSegment as S

RATE = 16000


def test_a_span_inside_one_segment_is_one_piece():
    assert speaker_pieces(1.0, 2.0, [S(0, 0.0, 5.0)]) == (Piece(1.0, 2.0, 0),)


def test_a_speaker_change_cuts_the_span():
    assert speaker_pieces(0.0, 4.0, [S(0, 0.0, 1.5), S(1, 1.5, 4.0)]) == (
        Piece(0.0, 1.5, 0),
        Piece(1.5, 4.0, 1),
    )


def test_overlap_stays_with_the_speaker_who_holds_the_time():
    # Speaker 1 starts while speaker 0 still talks: the overlap stays with speaker 0.
    assert speaker_pieces(0.0, 4.0, [S(0, 0.0, 2.0), S(1, 1.0, 4.0)]) == (
        Piece(0.0, 2.0, 0),
        Piece(2.0, 4.0, 1),
    )


def test_overlap_at_the_start_goes_to_who_started_first():
    assert speaker_pieces(1.0, 3.0, [S(1, 0.5, 3.0), S(0, 0.0, 3.0)]) == (Piece(1.0, 3.0, 0),)


def test_a_gap_joins_the_piece_before_it_or_the_piece_after_it_at_the_start():
    segments = [S(0, 1.0, 2.0), S(1, 3.0, 4.0)]

    assert speaker_pieces(0.0, 5.0, segments) == (Piece(0.0, 3.0, 0), Piece(3.0, 5.0, 1))


def test_a_span_with_no_segment_inside_takes_the_nearest_speaker():
    segments = [S(0, 0.0, 1.0), S(1, 5.0, 6.0)]

    assert speaker_pieces(3.5, 4.5, segments) == (Piece(3.5, 4.5, 1),)
    assert speaker_pieces(1.5, 2.0, segments) == (Piece(1.5, 2.0, 0),)


def test_no_segments_at_all_give_no_speaker():
    assert speaker_pieces(0.0, 1.0, []) == (Piece(0.0, 1.0, None),)


def test_names_number_speakers_by_first_line_per_source():
    system, mic = SpeakerNames("system"), SpeakerNames("mic")

    assert system.speaker(7) == ("speaker-1", "Speaker 1")
    assert system.speaker(2) == ("speaker-2", "Speaker 2")
    assert system.speaker(7) == ("speaker-1", "Speaker 1")
    assert mic.speaker(2) == ("room-1", "Room 1")
    assert system.speaker(None) == ("system", "System")
    assert mic.speaker(None) == ("you", "You")
    assert SpeakerNames("file").speaker(None) == ("speaker-1", "Speaker 1")


def test_a_rename_needs_a_known_speaker_and_a_name():
    names = SpeakerNames("system")
    names.speaker(0)

    with pytest.raises(ValueError, match="empty"):
        names.checked_label("speaker-1", "  ")
    with pytest.raises(ValueError, match="Unknown"):
        names.checked_label("speaker-2", "Dana")
    names.rename("speaker-1", " Dana ")
    assert names.speaker(0) == ("speaker-1", "Dana")


def test_the_stream_clock_maps_each_run_to_its_session_time():
    clock = StreamClock()
    clock.start_run(0.0, 0.0)
    clock.start_run(10.0, 25.0)

    assert clock.session_time(4.0) == 4.0
    assert clock.session_time(12.5) == 27.5
    assert clock.session_time(float("inf")) == float("inf")


@pytest.mark.parametrize(
    ("speaker_id", "label", "name"),
    [
        ("speaker-3", "Speaker 3", None),
        ("room-2", "Room 2", None),
        ("you", "You", None),
        ("system", "System", None),
        ("speaker-3", "Alex", "Alex"),
        # A re-imported recording source.
        ("mic-file-r2-2", "Room 2", None),
        ("system-file-r3-1", "Speaker 1", None),
        ("mic-file-r2-1", "You", None),
        ("system-file-r2-1", "System", None),
        ("mic-file-r2-1", "Dana", "Dana"),
        # A file session without speaker separation.
        ("speaker-1", "Speaker 1", None),
    ],
)
def test_given_name_tells_a_name_from_a_default_label(speaker_id, label, name):
    line = TranscriptLine(0.0, 1.0, "", "system", speaker_id, label, "text")
    assert given_name(line) == name


def _line(start, end, speaker_id="speaker-1", label="Speaker 1", text="old"):
    wall = f"2026-11-09T10:00:{int(start):02d}+00:00"
    return TranscriptLine(start, end, wall, "system", speaker_id, label, text)


def _relabel(lines, segments, *, decode_all=False, texts=None):
    texts = iter(texts or ("a", "b", "c", "d"))
    decoded = []

    def decode(samples):
        decoded.append(samples.size)
        return next(texts)

    result = relabel_lines(
        lines,
        segments,
        SpeakerNames("system"),
        read_audio=lambda start, end: np.zeros(round((end - start) * RATE), np.float32),
        decode=decode,
        decode_all=decode_all,
    )
    return result, decoded


def test_relabel_keeps_the_text_of_a_one_speaker_line_and_cuts_a_changing_one():
    lines = [_line(0.0, 2.0), _line(2.0, 6.0)]

    result, decoded = _relabel(lines, [S(0, 0.0, 3.0), S(1, 3.0, 6.0)])

    assert [(line.start, line.end, line.label, line.text) for line in result] == [
        (0.0, 2.0, "Speaker 1", "old"),
        (2.0, 3.0, "Speaker 1", "a"),
        (3.0, 6.0, "Speaker 2", "b"),
    ]
    assert result[2].wall == "2026-11-09T10:00:03+00:00"
    assert decoded == [RATE, 3 * RATE]


def test_relabel_drops_an_empty_part_and_keeps_a_line_whose_parts_are_all_empty():
    segments = [S(0, 0.0, 1.0), S(1, 1.0, 3.0)]

    one_empty, _ = _relabel([_line(0.0, 3.0)], segments, texts=("", "kept"))
    all_empty, _ = _relabel([_line(0.0, 3.0)], segments, texts=("", " "))

    assert [(line.start, line.label, line.text) for line in one_empty] == [
        (1.0, "Speaker 1", "kept")
    ]
    assert [(line.start, line.end, line.label, line.text) for line in all_empty] == [
        (0.0, 3.0, "Speaker 1", "old")
    ]


def test_relabel_with_decode_all_decodes_every_line():
    result, decoded = _relabel(
        [_line(0.0, 1.0), _line(1.0, 2.0)], [S(0, 0.0, 2.0)], decode_all=True
    )

    assert [line.text for line in result] == ["a", "b"]
    assert decoded == [RATE, RATE]


def test_relabel_gives_a_new_speaker_the_name_of_most_of_its_time():
    lines = [
        _line(0.0, 4.0, "speaker-2", "Alex"),
        _line(4.0, 5.0, "speaker-1", "Bea"),
        _line(5.0, 9.0, "speaker-1", "Speaker 1"),
    ]

    result, _ = _relabel(lines, [S(0, 0.0, 5.0), S(1, 5.0, 9.0)])

    assert [(line.speaker_id, line.label) for line in result] == [
        ("speaker-1", "Alex"),
        ("speaker-1", "Alex"),
        ("speaker-2", "Speaker 2"),
    ]


def test_relabel_stops_on_a_cancel():
    result = relabel_lines(
        [_line(0.0, 1.0)],
        [S(0, 0.0, 1.0)],
        SpeakerNames("system"),
        read_audio=lambda *_times: np.zeros(RATE, np.float32),
        decode=lambda _samples: "a",
        should_cancel=lambda: True,
    )

    assert result is None


def test_relabel_numbers_a_re_imported_source_by_first_appearance():
    lines = [
        TranscriptLine(0.0, 4.0, "", "mic", "mic-file-r2-2", "Room 2", "old"),
        TranscriptLine(4.0, 8.0, "", "mic", "mic-file-r2-1", "Room 1", "old"),
    ]

    result = relabel_lines(
        lines,
        [S(0, 0.0, 4.0), S(1, 4.0, 8.0)],
        SpeakerNames("mic"),
        read_audio=lambda start, end: np.zeros(round((end - start) * RATE), np.float32),
        decode=lambda _samples: "a",
    )

    assert [(line.speaker_id, line.label) for line in result] == [
        ("room-1", "Room 1"),
        ("room-2", "Room 2"),
    ]
