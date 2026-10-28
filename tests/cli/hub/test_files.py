# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the file engine that the hub services own."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


class FakeJob:
    def __init__(self, path: Path):
        self.id = f"file-{path.stem}"
        self.state = "queued"

    def cancel(self):
        self.state = "cancelled"
        return True


class FakeFilesEngine:
    def __init__(self):
        self.jobs = []
        self.submitted = []
        self.closed = False

    def submit(self, path: Path, **options):
        job = FakeJob(path)
        self.jobs.append(job)
        self.submitted.append((path, options))
        return job

    def close(self):
        self.closed = True


def test_hub_services_create_the_file_engine_lazily_and_close_it(tmp_path):
    from stenographer.cli.hub.services import HubServices
    from stenographer.lib.config.models import Config

    engines = []

    def make_engine(_config, *, platform):
        assert platform.data_dir({}, Path.home()) == tmp_path
        engine = FakeFilesEngine()
        engines.append(engine)
        return engine

    platform = SimpleNamespace(data_dir=lambda _env, _home: tmp_path)
    services = HubServices(Config.defaults(), platform, files_engine_factory=make_engine)

    assert services.files_jobs == ()
    assert not services.files_running
    assert not hasattr(services, "files_output_folder")
    job = services.submit_file(tmp_path / "voice.wav", diarize=False)
    assert len(engines) == 1
    assert services.files_jobs == (job,)
    assert services.files_running
    assert engines[0].submitted == [(tmp_path / "voice.wav", {"diarize": False})]

    assert services.cancel_file(job)
    assert not services.files_running
    assert not hasattr(services, "open_files_result")
    services.close_files()
    assert engines[0].closed
    assert services.files_jobs == ()
