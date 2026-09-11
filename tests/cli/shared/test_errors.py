# SPDX-License-Identifier: GPL-3.0-or-later
"""The shared capability/config failure presentation."""

from __future__ import annotations

from stenographer.cli.shared.errors import _fatal


def test_fatal_reports_on_stderr_and_returns_the_configuration_exit_code(capsys):
    assert _fatal("ASR model not found; run `stenographer model download`") == 78

    captured = capsys.readouterr()
    assert captured.err == (
        "stenographer: ASR model not found; run `stenographer model download`\n"
    )
    assert captured.out == ""
