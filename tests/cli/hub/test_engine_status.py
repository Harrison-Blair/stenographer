# SPDX-License-Identifier: GPL-3.0-or-later
"""Engine card snapshot: state precedence and /proc gauges with fake services."""

from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace

import pytest

from stenographer.cli.hub import engine_sampler
from stenographer.cli.hub.engine_sampler import EngineSampler
from stenographer.cli.hub.engine_status import EngineStatus
from stenographer.lib.platform.linux.proc_counters import LinuxProcessCounters
from stenographer.lib.platform.null_process_counters import NullProcessCounters

HUB_PID = 100
LIVE_PID = 200
FILES_PID = 300


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class FakeSession:
    def __init__(self, *, queue_depth=0, relabel_progress=None, pids=(), deadline=None):
        self.queue_depth = queue_depth
        self.relabel_progress = relabel_progress
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
        (FakeServices(), "idle · unloaded"),
        (FakeServices(files_engine=FakeEngine()), "idle · unloaded"),
        (FakeServices(files_engine=FakeEngine(deadline=1012.2)), "idle · unloads in 13 s"),
        (FakeServices(files_engine=FakeEngine(deadline=1030.0)), "idle · unloads in 30 s"),
        (FakeServices(session=FakeSession()), "ready"),
        (FakeServices(session=FakeSession(queue_depth=3)), "ready · 3 queued"),
        (FakeServices(files_engine=FakeEngine(active_job=FakeJob(percent=42))), "transcribing 42%"),
        (
            FakeServices(session=FakeSession(relabel_progress=(3, 7))),
            "relabeling 3 of 7",
        ),
        # Overlaps: the first state in precedence order wins.
        (
            FakeServices(
                session=FakeSession(relabel_progress=(1, 4)),
                files_engine=FakeEngine(active_job=FakeJob(percent=10)),
            ),
            "relabeling 1 of 4",
        ),
        (
            FakeServices(
                stopping_sessions=(FakeSession(relabel_progress=(2, 5)),),
                session=FakeSession(queue_depth=1),
            ),
            "relabeling 2 of 5",
        ),
        (
            FakeServices(
                stopping_sessions=(
                    FakeSession(relabel_progress=(6, 9)),
                    FakeSession(relabel_progress=(1, 2)),
                ),
            ),
            "relabeling 6 of 9",
        ),
        (
            FakeServices(
                stopping_sessions=(FakeSession(), FakeSession(relabel_progress=(1, 2))),
            ),
            "relabeling 1 of 2",
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
            "ready · 2 queued",
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
            "idle · unloads in 4 s",
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
    stopping.relabel_progress = (0, 4)
    states.append(sampler.snapshot().state)
    stopping.relabel_progress = (3, 4)
    states.append(sampler.snapshot().state)
    stopping.relabel_progress = None
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
        "ready · 2 queued",
        "relabeling 0 of 4",
        "relabeling 3 of 4",
        "idle · unloaded",
        "transcribing 50%",
        "idle · unloads in 30 s",
        "idle · unloads in 1 s",
        "idle · unloaded",
    ]


def test_engine_snapshot_names_the_model(tmp_path):
    assert _sampler(FakeServices(), tmp_path).snapshot().model == "bark-pro-int8"


class FakeProc:
    """A /proc-shaped folder with the files the sampler reads."""

    def __init__(self, root):
        self.root = root

    def system(self, total, idle):
        # user nice system idle iowait irq softirq steal
        busy = total - idle
        (self.root / "stat").write_text(f"cpu  {busy} 0 0 {idle} 0 0 0 0 0 0\n", encoding="ascii")

    def process(self, pid, ticks, rss_pages):
        folder = self.root / str(pid)
        folder.mkdir(exist_ok=True)
        fields = ["S", "1", "1", "1", "0", "-1", "0", "0", "0", "0", "0", str(ticks), "0"]
        (folder / "stat").write_text(f"{pid} (proc) {' '.join(fields)} 0\n", encoding="ascii")
        (folder / "statm").write_text(f"1000 {rss_pages} 0 0 0 0 0\n", encoding="ascii")


def test_engine_gauges_are_none_before_the_first_sample(tmp_path):
    proc = FakeProc(tmp_path)
    proc.system(1000, 500)
    proc.process(HUB_PID, 10, 100)

    status = _sampler(FakeServices(), tmp_path).snapshot()

    assert status.cpu_app_percent is None
    assert status.cpu_all_percent is None
    assert status.ram_app_bytes is None
    assert status.cpu_history == ()


def test_engine_samples_app_cpu_over_hub_and_worker_pids_system_cpu_and_app_ram(tmp_path):
    clock = FakeClock()
    proc = FakeProc(tmp_path)
    services = FakeServices(
        session=FakeSession(pids=(LIVE_PID,)),
        files_engine=FakeEngine(pids=(FILES_PID,)),
    )
    sampler = _sampler(services, tmp_path, clock)
    proc.system(10_000, 6_000)
    proc.process(HUB_PID, 1_000, 100)
    proc.process(LIVE_PID, 2_000, 200)
    proc.process(FILES_PID, 3_000, 300)

    sampler.sample()
    first = sampler.snapshot()

    assert first.cpu_app_percent is None
    assert first.cpu_all_percent is None
    assert first.ram_app_bytes == 600 * 4096
    assert first.cpu_history == ()

    clock.now += 1.0
    # 50 + 150 + 0 ticks at 100 ticks/s over 1 s on 4 CPUs is 50 %.
    proc.process(HUB_PID, 1_050, 110)
    proc.process(LIVE_PID, 2_150, 200)
    proc.process(FILES_PID, 3_000, 300)
    # 1000 jiffies pass, 250 of them idle: 75 % busy.
    proc.system(11_000, 6_250)
    sampler.sample()
    second = sampler.snapshot()

    assert second.cpu_app_percent == pytest.approx(50.0)
    assert second.cpu_all_percent == pytest.approx(75.0)
    assert second.ram_app_bytes == 610 * 4096
    assert second.cpu_history == pytest.approx((50.0,))
    assert isinstance(second, EngineStatus)


def test_engine_app_cpu_counts_a_new_worker_and_drops_a_gone_one(tmp_path):
    clock = FakeClock()
    proc = FakeProc(tmp_path)
    engine = FakeEngine(pids=(FILES_PID,))
    services = FakeServices(files_engine=engine)
    sampler = _sampler(services, tmp_path, clock)
    proc.system(10_000, 5_000)
    proc.process(HUB_PID, 0, 10)
    proc.process(FILES_PID, 5_000, 10)
    sampler.sample()

    # The files worker unloads and a live worker starts within one second.
    clock.now += 1.0
    engine.process_ids = ()
    proc.process(LIVE_PID, 80, 20)
    services.session = FakeSession(pids=(LIVE_PID,))
    proc.system(11_000, 5_500)
    sampler.sample()

    status = sampler.snapshot()
    assert status.cpu_app_percent == pytest.approx(20.0)
    assert status.ram_app_bytes == 30 * 4096


def test_engine_cpu_history_keeps_the_last_sixty_seconds(tmp_path):
    clock = FakeClock()
    proc = FakeProc(tmp_path)
    sampler = _sampler(FakeServices(), tmp_path, clock)
    ticks = 0
    proc.system(1_000, 500)
    proc.process(HUB_PID, ticks, 1)
    sampler.sample()
    for second in range(1, 66):
        clock.now += 1.0
        # Second n uses n ticks: n / 100 s of CPU on 4 CPUs is n / 4 %.
        ticks += second
        proc.process(HUB_PID, ticks, 1)
        proc.system(1_000 + 100 * second, 500)
        sampler.sample()

    history = sampler.snapshot().cpu_history
    assert len(history) == 60
    assert history == pytest.approx(tuple(second / 4 for second in range(6, 66)))


def test_engine_gauges_stay_none_when_proc_is_unreadable(tmp_path):
    clock = FakeClock()
    sampler = _sampler(FakeServices(), tmp_path, clock)
    sampler.sample()
    clock.now += 1.0
    sampler.sample()

    status = sampler.snapshot()
    assert (status.cpu_app_percent, status.cpu_all_percent, status.ram_app_bytes) == (
        None,
        None,
        None,
    )
    assert status.cpu_history == ()


def test_engine_gauges_stay_none_on_a_host_without_counters(tmp_path):
    clock = FakeClock()
    sampler = _sampler(FakeServices(), tmp_path, clock, counters=NullProcessCounters())
    sampler.sample()
    clock.now += 1.0
    sampler.sample()

    status = sampler.snapshot()
    assert (status.cpu_app_percent, status.cpu_all_percent, status.ram_app_bytes) == (
        None,
        None,
        None,
    )
    assert status.cpu_history == ()
    assert status.state == "idle · unloaded"


def test_engine_sampler_and_its_linux_counters_import_no_subprocess():
    from stenographer.lib.platform.linux import cpu, proc_counters

    for module in (engine_sampler, proc_counters, cpu):
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
    assert sampler.snapshot().state == "idle · unloaded"
    services.submit_file(tmp_path / "voice.wav")
    assert services.files_engine is engine
    assert sampler.snapshot().state == "transcribing 64%"
    services.close_files()
    assert services.files_engine is None


def test_engine_sampler_feeds_the_sidebar_engine_card(tmp_path):
    import asyncio

    from textual.widgets import Static

    from stenographer.cli.hub.app import HubApp

    clock = FakeClock()
    proc = FakeProc(tmp_path)
    proc.system(1_000, 500)
    proc.process(HUB_PID, 0, 1)
    services = SimpleNamespace(recording=False, files_running=False)
    sampler = _sampler(services, tmp_path, clock)
    app = HubApp(
        services,
        engine_sampler=sampler,
        doctor_probe=lambda _config, _path: None,
    )

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("2")
            await pilot.pause()
            gauge = app.screen.query_one("#engine-cpu-all", Static)
            assert str(gauge.render()) == "    all      — ▕········▏"

            # 1000 jiffies pass, 250 of them idle: 75 % busy.
            clock.now += 1.0
            proc.system(2_000, 750)
            app._sample_engine()
            await pilot.pause()
            gauge = app.screen.query_one("#engine-cpu-all", Static)
            assert str(gauge.render()) == "    all    75% ▕██████··▏"

    asyncio.run(exercise())
