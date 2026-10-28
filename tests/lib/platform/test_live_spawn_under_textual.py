# SPDX-License-Identifier: GPL-3.0-or-later
"""Live ASR spawning remains safe under Textual's stderr capture."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_real_asr_spawn_is_primed_before_textual_captures_stderr():
    source_dir = Path(__file__).parents[3] / "src"
    script = """
import asyncio
import sys
from textual.app import App
from stenographer.lib.config.models import Config
from stenographer.lib.platform.multiprocessing_asr_transport import MultiprocessingAsrTransport

config = Config.defaults()
transport = MultiprocessingAsrTransport()

async def run_app():
    app = App()
    async with app.run_test():
        previous_stderr = sys.stderr
        sys.stderr = app._capture_stderr
        try:
            assert sys.stderr.fileno() == -1
            process = transport.spawn(config.asr, on_log=lambda _record: None)
            process.close()
        finally:
            sys.stderr = previous_stderr

# Spawn and stop a real child before Textual captures stderr.
process = transport.spawn(config.asr, on_log=lambda _record: None)
process.close()
asyncio.run(run_app())
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source_dir) + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=False,
        env=env,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
