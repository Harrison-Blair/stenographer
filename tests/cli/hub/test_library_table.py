# SPDX-License-Identifier: GPL-3.0-or-later
"""The cells of the Library table: speakers with ``+N``, a title on two lines, sizes."""

from __future__ import annotations

import pytest

from stenographer.cli.hub.library_screen import LibraryScreen, format_size
from stenographer.cli.hub.library_table import speaker_lines, two_lines


def test_speakers_fill_two_lines_and_count_the_rest():
    names = ("You", "Dana", "Priya", "Marcus", "Room 3")
    assert speaker_lines(names, 22) == ("You, Dana, Priya,", "Marcus, Room 3")
    assert speaker_lines(names, 16) == ("You, Dana,", "Priya, Marcus +1")
    others = tuple(f"Speaker {n}" for n in range(1, 7))
    assert speaker_lines(("You", *others), 16) == (
        "You, Speaker 1,",
        "Speaker 2 +4",
    )


def test_twelve_speakers_and_a_long_name_stay_on_two_lines():
    long_name = "A speaker name of forty-five characters long!"
    assert len(long_name) == 45
    lines = speaker_lines((long_name, *(f"Speaker {n}" for n in range(1, 12))), 22)
    assert lines == ("A speaker name of fo…,", "Speaker 1 +10")
    assert all(len(line) <= 22 for line in lines)
    assert speaker_lines((long_name,), 16) == ("A speaker name…",)


def test_a_long_title_wraps_and_ends_with_an_ellipsis():
    assert two_lines("Capture service loses the microphone track", 36) == (
        "Capture service loses the microphone",
        "track",
    )
    title = "A title of two hundred characters " + "that keeps going " * 10
    first, second = two_lines(title, 30)
    assert first == "A title of two hundred"
    assert second == "characters that keeps going t…"
    assert two_lines("Short", 30) == ("Short", "")


@pytest.mark.parametrize(
    ("size", "text"),
    [
        (0, "0 M"),
        (9 * 1024**2, "9 M"),
        (176 * 1024**2, "176 M"),
        (int(1.6 * 1024**3), "1.6 G"),
        (int(999.9 * 1024**3), "999.9 G"),
    ],
)
def test_sizes_have_at_most_seven_cells(size, text):
    assert format_size(size) == text


def test_the_buttons_take_the_fewest_rows_and_hide_only_what_does_not_fit():
    # Play with its position, Rename, Re-diarize, Re-transcribe, Export, Delete; a gap of 3.
    widths = [30, 11, 14, 17, 11, 13]
    assert LibraryScreen._action_grid(widths, 116, 1) == (6, 6)
    assert LibraryScreen._action_grid(widths, 74, 2) == (6, 3)
    # Narrow: one row; the buttons that fit show from the start.
    narrow = [10, 11, 14, 17, 11, 13]
    assert LibraryScreen._action_grid(narrow, 56, 1) == (3, 3)
    assert LibraryScreen._action_grid(narrow, 61, 1) == (4, 4)
    assert LibraryScreen._action_grid(narrow, 78, 1) == (5, 5)
