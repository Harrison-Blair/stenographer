# SPDX-License-Identifier: GPL-3.0-or-later
"""Engine status snapshot: state precedence and /proc gauges with fake services."""

from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace

import pytest

from stenographer.cli.hub import engine_sampler
from stenographer.cli.hub.engine_sampler import EngineSampler
from stenographer.lib.platform.linux.cpu import LinuxProcessCounters
from tests.lib.platform.support import NullProcessCounters

HUB_PID = 100
LIVE_PID = 200
FILES_PID = 300


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class FakeSession:
    def __init__(self, *, queue_depth=0, labelling=False, pids=(), deadline=None):
        self.queue_depth = queue_depth
        self.labelling_speakers = labelling
        self.process_ids = pids
        self.idle_unload_deadline = deadline


class FakeJob:
    def __init__(self, state="running", percent=0):
        self.state = state
        self.progress = SimpleNamespace(percent=percent)


class FakeEngine:
    def __init__(self, *, active_job=None, deadline=None, pids=()):
        self.active_job = active_job
        self.idle_unload_deadline = deadline
        self.process_ids = pids


class FakeServices:
    def __init__(self, *, session=None, stopping_sessions=(), files_engine=None):
        self.session = session
        self.stopping_sessions = stopping_sessions
        self.files_engine = files_engine


def _sampler(services, tmp_path, clock=None, **options):
    return EngineSampler(
        services,
        counters=options.pop(
            "counters", LinuxProcessCounters(tmp_path, clock_ticks=100, page_size=4096)
        ),
        monotonic=clock or FakeClock(),
        pid=HUB_PID,
        cpu_count=4,
        **options,
    )


@pytest.mark.parametrize(
    ("services", "expected"),
    [
        (FakeServices(), "idle"),
        (FakeServices(files_engine=FakeEngine()), "idle"),
        (FakeServices(files_engine=FakeEngine(deadline=1012.2)), "idle 13s"),
        (FakeServices(files_engine=FakeEngine(deadline=1030.0)), "idle 30s"),
        (FakeServices(session=FakeSession()), "ready"),
        (FakeServices(session=FakeSession(queue_depth=3)), "ready"),
        (FakeServices(files_engine=FakeEngine(active_job=FakeJob(percent=42))), "transcribing 42%"),
        (
            FakeServices(session=FakeSession(labelling=True)),
            "labelling",
        ),
        # Overlaps: the first state in precedence order wins.
        (
            FakeServices(
                session=FakeSession(labelling=True),
                files_engine=FakeEngine(active_job=FakeJob(percent=10)),
            ),
            "labelling",
        ),
        (
            FakeServices(
                stopping_sessions=(FakeSession(labelling=True),),
                session=FakeSession(queue_depth=1),
            ),
            "labelling",
        ),
        (
            FakeServices(
                stopping_sessions=(FakeSession(), FakeSession(labelling=True)),
            ),
            "labelling",
        ),
        (
            FakeServices(
                session=FakeSession(queue_depth=4),
                files_engine=FakeEngine(active_job=FakeJob(percent=77)),
            ),
            "transcribing 77%",
        ),
        (
            FakeServices(
                files_engine=FakeEngine(active_job=FakeJob(percent=5), deadline=1010.0),
            ),
            "transcribing 5%",
        ),
        (
            FakeServices(
                session=FakeSession(queue_depth=2),
                files_engine=FakeEngine(active_job=FakeJob(state="cancelled"), deadline=1010.0),
            ),
            "ready",
        ),
        (
            FakeServices(
                session=FakeSession(deadline=1005.0),
                files_engine=FakeEngine(deadline=1010.0),
            ),
            "ready",
        ),
        (
            FakeServices(
                stopping_sessions=(FakeSession(deadline=1003.5),),
                files_engine=FakeEngine(deadline=1010.0),
            ),
            "idle 4s",
        ),
    ],
)
def test_engine_state_line_takes_the_first_state_that_applies(services, expected, tmp_path):
    assert _sampler(services, tmp_path).snapshot().state == expected


def test_engine_state_line_follows_one_recording_through_stop_file_job_and_unload(tmp_path):
    clock = FakeClock()
    services = FakeServices()
    sampler = _sampler(services, tmp_path, clock)
    states = []

    services.session = FakeSession(queue_depth=0)
    states.append(sampler.snapshot().state)
    services.session.queue_depth = 2
    states.append(sampler.snapshot().state)

    stopping = services.session
    stopping.labelling_speakers = True
    states.append(sampler.snapshot().state)
    stopping.labelling_speakers = False
    services.session = None
    states.append(sampler.snapshot().state)

    job = FakeJob(percent=50)
    services.files_engine = FakeEngine(active_job=job)
    states.append(sampler.snapshot().state)
    job.state = "completed"
    services.files_engine.active_job = None
    services.files_engine.idle_unload_deadline = clock.now + 30.0
    states.append(sampler.snapshot().state)
    clock.now += 29.5
    states.append(sampler.snapshot().state)
    services.files_engine.idle_unload_deadline = None
    states.append(sampler.snapshot().state)

    assert states == [
        "ready",
        "ready",
        "labelling",
        "idle",
        "transcribing 50%",
        "idle 30s",
        "idle 1s",
        "idle",
    ]


def test_engine_snapshot_names_the_model(tmp_path):
    assert _sampler(FakeServices(), tmp_path).snapshot().model == "bark-pro-int8"


class FakeProc:
    """A /proc-shaped folder with the files the sampler reads."""

    def __init__(self, root):
        self.root = root

    def process(self, pid, ticks, rss_pages):
        folder = self.root / str(pid)
        folder.mkdir(exist_ok=True)
        fields = ["S", "1", "1", "1", "0", "-1", "0", "0", "0", "0", "0", str(ticks), "0"]
        (folder / "stat").write_text(f"{pid} (proc) {' '.join(fields)} 0\n", encoding="ascii")
        (folder / "statm").write_text(f"1000 {rss_pages} 0 0 0 0 0\n", encoding="ascii")


def test_engine_gauges_are_none_before_the_first_sample(tmp_path):
    proc = FakeProc(tmp_path)
    proc.process(HUB_PID, 10, 100)

    status = _sampler(FakeServices(), tmp_path).snapshot()

    assert status.cpu_app_percent is None
    assert status.ram_app_bytes is None


def test_engine_samples_app_cpu_over_hub_and_worker_pids_and_app_ram(tmp_path):
    clock = FakeClock()
    proc = FakeProc(tmp_path)
    services = FakeServices(
        session=FakeSession(pids=(LIVE_PID,)),
        files_engine=FakeEngine(pids=(FILES_PID,)),
    )
    sampler = _sampler(services, tmp_path, clock)
    proc.process(HUB_PID, 1_000, 100)
    proc.process(LIVE_PID, 2_000, 200)
    proc.process(FILES_PID, 3_000, 300)

    sampler.sample()
    first = sampler.snapshot()

    assert first.cpu_app_percent is None
    assert first.ram_app_bytes == 600 * 4096

    clock.now += 1.0
    # 50 + 150 + 0 ticks at 100 ticks/s over 1 s on 4 CPUs is 50 %.
    proc.process(HUB_PID, 1_050, 110)
    proc.process(LIVE_PID, 2_150, 200)
    proc.process(FILES_PID, 3_000, 300)
    sampler.sample()
    second = sampler.snapshot()

    assert second.cpu_app_percent == pytest.approx(50.0)
    assert second.ram_app_bytes == 610 * 4096


def test_engine_app_cpu_counts_a_new_worker_and_drops_a_gone_one(tmp_path):
    clock = FakeClock()
    proc = FakeProc(tmp_path)
    engine = FakeEngine(pids=(FILES_PID,))
    services = FakeServices(files_engine=engine)
    sampler = _sampler(services, tmp_path, clock)
    proc.process(HUB_PID, 0, 10)
    proc.process(FILES_PID, 5_000, 10)
    sampler.sample()

    # The files worker unloads and a live worker starts within one second.
    clock.now += 1.0
    engine.process_ids = ()
    proc.process(LIVE_PID, 80, 20)
    services.session = FakeSession(pids=(LIVE_PID,))
    sampler.sample()

    status = sampler.snapshot()
    assert status.cpu_app_percent == pytest.approx(20.0)
    assert status.ram_app_bytes == 30 * 4096


def test_engine_gauges_stay_none_when_proc_is_unreadable(tmp_path):
    clock = FakeClock()
    sampler = _sampler(FakeServices(), tmp_path, clock)
    sampler.sample()
    clock.now += 1.0
    sampler.sample()

    status = sampler.snapshot()
    assert (status.cpu_app_percent, status.ram_app_bytes) == (None, None)


def test_engine_gauges_stay_none_on_a_host_without_counters(tmp_path):
    clock = FakeClock()
    sampler = _sampler(FakeServices(), tmp_path, clock, counters=NullProcessCounters())
    sampler.sample()
    clock.now += 1.0
    sampler.sample()

    status = sampler.snapshot()
    assert (status.cpu_app_percent, status.ram_app_bytes) == (None, None)
    assert status.state == "idle"


def test_engine_sampler_and_its_linux_counters_import_no_subprocess():
    from stenographer.lib.platform.linux import cpu

    for module in (engine_sampler, cpu):
        tree = ast.parse(inspect.getsource(module))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in (
                node.names if isinstance(node, ast.Import) else [ast.alias(node.module or "")]
            )
        }
        assert "subprocess" not in imported, module.__name__
        assert "psutil" not in imported, module.__name__


def test_engine_reads_the_files_engine_that_hub_services_create(tmp_path):
    from stenographer.cli.hub.services import HubServices
    from stenographer.lib.config.models import Config

    engine = FakeEngine(active_job=FakeJob(percent=64))
    engine.submit = lambda _path, **_options: engine.active_job
    engine.close = lambda: None
    platform = SimpleNamespace(data_dir=lambda _env, _home: tmp_path)
    services = HubServices(
        Config.defaults(), platform, files_engine_factory=lambda _config, *, platform: engine
    )
    sampler = _sampler(services, tmp_path)

    assert services.files_engine is None
    assert sampler.snapshot().state == "idle"
    services.submit_file(tmp_path / "voice.wav")
    assert services.files_engine is engine
    assert sampler.snapshot().state == "transcribing 64%"
    services.close_files()
    assert services.files_engine is None


def test_engine_sampler_feeds_the_top_line(tmp_path):
    import asyncio

    from textual.widgets import Static

    from tests.cli.hub.support import make_app

    clock = FakeClock()
    proc = FakeProc(tmp_path)
    proc.process(HUB_PID, 0, 1)
    services = SimpleNamespace(recording=False, files_running=False)
    sampler = _sampler(services, tmp_path, clock)
    app = make_app(
        tmp_path,
        services,
        engine_sampler=sampler,
        doctor_probe=lambda _config: None,
    )

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("2")
            await pilot.pause()
            engine = app.screen.query_one("#top-engine", Static)
            assert str(engine.render()).endswith("cpu    —  ram  0.0G")

            # 200 ticks at 100 ticks/s over 1 s on 4 CPUs is 50 %; 1 page of RAM.
            clock.now += 1.0
            proc.process(HUB_PID, 200, 1)
            app._sample_engine()
            await pilot.pause()
            assert str(engine.render()).endswith("cpu  50%  ram  0.0G")
            assert " all " not in str(engine.render())

    asyncio.run(exercise())
