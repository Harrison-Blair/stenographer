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
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from textual.app import App
import stenographer.cli.live.handler as handler
from stenographer.lib.config.models import Config
from stenographer.lib.live.models import LIVE_MODELS
from stenographer.lib.platform.multiprocessing_asr_transport import MultiprocessingAsrTransport

root = Path(tempfile.mkdtemp())
model_dir = root / "models" / "live"
model_dir.mkdir(parents=True)
for model in LIVE_MODELS:
    (model_dir / model.filename).touch()
config = Config.defaults()
transport = MultiprocessingAsrTransport()

class ProbeSession:
    path = root

    def __init__(self, *_args, **_kwargs):
        pass

    def start(self):
        # Spawn and stop a real child before model loading.
        process = transport.spawn(config.asr, on_log=lambda _record: None)
        process.close()

    def stop(self):
        pass

async def run_app(_session):
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

handler.current_platform = lambda: SimpleNamespace(data_dir=lambda *_: root)
handler.LiveSession = ProbeSession
handler._run_app = lambda session: asyncio.run(run_app(session))
args = SimpleNamespace(mic=False, system=False, device=None)
try:
    assert handler.cmd_live.__wrapped__(args, config) == 0
finally:
    shutil.rmtree(root)
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
