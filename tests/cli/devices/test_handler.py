# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure input-device command calculations."""

from stenographer.cli.devices.handler import _default_input_index


def test_default_input_index_takes_the_input_half_of_the_pair():
    assert _default_input_index((3, 7)) == 3
    assert _default_input_index([-1, 4]) == -1


def test_default_input_index_normalises_unusable_pairs_to_the_sentinel():
    assert _default_input_index(None) == -1
    assert _default_input_index(()) == -1
    assert _default_input_index(("default", "default")) == -1
