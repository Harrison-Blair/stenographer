# SPDX-License-Identifier: GPL-3.0-or-later
"""The standalone live command is gone; the hub Record screen replaces it."""

from __future__ import annotations

import pytest

from stenographer.cli.parser import build_parser


@pytest.mark.parametrize("argv", [["live"], ["live", "--help"]])
def test_live_command_is_an_invalid_choice(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(argv)

    assert exc.value.code == 2
    assert "invalid choice: 'live'" in capsys.readouterr().err
