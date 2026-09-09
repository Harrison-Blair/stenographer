# SPDX-License-Identifier: GPL-3.0-or-later
"""Real-process smoke for the private overlay entry and its logging isolation.

The helper keeps its own diagnostics: it must write ``overlay-helper.log`` in
the state directory and must never touch the daemon's ``stenographer.log``,
whose rotation it does not coordinate with.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from stenographer.status import (
    Backend,
    Command,
    CommandMessage,
    ReadyMessage,
    UnavailableMessage,
    decode_message,
    encode_message,
)

pytestmark = pytest.mark.integration


def _assert_private_helper_logs_only_its_own_file(command: tuple[str, ...], tmp_path: Path) -> None:
    env = os.environ.copy()
    env["XDG_STATE_HOME"] = str(tmp_path)
    result = subprocess.run(
        command,
        input=encode_message(CommandMessage(Command.SHUTDOWN)),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    response = decode_message(result.stdout)
    assert isinstance(response, ReadyMessage | UnavailableMessage)
    if isinstance(response, ReadyMessage):
        assert response.backend in (Backend.LAYER_SHELL, Backend.XWAYLAND)
    assert list(tmp_path.rglob("overlay-helper.log*"))
    assert not list(tmp_path.rglob("stenographer.log*"))


def test_source_private_overlay_responds_and_logs_to_its_own_file(tmp_path):
    _assert_private_helper_logs_only_its_own_file(
        (sys.executable, "-m", "stenographer.cli", "_overlay"), tmp_path
    )


def test_frozen_private_overlay_responds_and_logs_to_its_own_file(tmp_path):
    executable = Path(__file__).parents[2] / "dist" / "stenographer" / "stenographer"
    if not executable.is_file():
        pytest.skip("frozen bundle has not been built")
    _assert_private_helper_logs_only_its_own_file((str(executable), "_overlay"), tmp_path)
