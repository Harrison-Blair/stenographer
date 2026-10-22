# SPDX-License-Identifier: GPL-3.0-or-later
"""The Linux command runner, on real child processes."""

from __future__ import annotations

import sys

from stenographer.lib.platform.linux.subprocess_command_runner import SubprocessCommandRunner


def test_run_returns_the_child_exit_code_and_shows_its_output(capfd):
    code = SubprocessCommandRunner().run([sys.executable, "-c", "print('progress'); exit(3)"])

    assert code == 3
    assert capfd.readouterr().out == "progress\n"


def test_run_quiet_discards_the_child_output(capfd):
    code = SubprocessCommandRunner().run_quiet(
        [sys.executable, "-c", "import sys; print('noise'); sys.stderr.write('more')"]
    )

    assert code == 0
    assert capfd.readouterr() == ("", "")


def test_a_command_that_cannot_start_exits_127(tmp_path):
    runner = SubprocessCommandRunner()

    assert runner.run([str(tmp_path / "absent")]) == 127
    assert runner.run_quiet([str(tmp_path / "absent")]) == 127
