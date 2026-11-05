# SPDX-License-Identifier: GPL-3.0-or-later
"""CLI routing and service-owner tests for the hub."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from io import StringIO
from types import SimpleNamespace

import pytest

from stenographer.cli.entry import dispatch


class Terminal(StringIO):
    def __init__(self, is_tty):
        super().__init__()
        self._is_tty = is_tty

    def isatty(self):
        return self._is_tty


def test_bare_command_opens_hub_only_when_both_streams_are_ttys(monkeypatch):
    import stenographer.cli.hub.handler as handler

    calls = []
    monkeypatch.setattr(handler, "cmd_hub", lambda args: calls.append(args) or 0)
    monkeypatch.setattr(sys, "stdin", Terminal(True))
    monkeypatch.setattr(sys, "stdout", Terminal(True))

    assert dispatch([]) == 0
    assert len(calls) == 1


def test_argument_separator_does_not_open_hub(monkeypatch):
    import stenographer.cli.hub.handler as handler

    monkeypatch.setattr(handler, "cmd_hub", lambda _args: pytest.fail("hub must not run"))
    monkeypatch.setattr(sys, "stdin", Terminal(True))
    terminal_out = Terminal(True)
    monkeypatch.setattr(sys, "stdout", terminal_out)

    with pytest.raises(SystemExit) as exc:
        dispatch(["--"])
    assert exc.value.code == 2
    assert terminal_out.getvalue() == ""


@pytest.mark.parametrize("stdin_tty,stdout_tty", [(False, True), (True, False), (False, False)])
def test_bare_command_prints_help_without_two_ttys(monkeypatch, stdin_tty, stdout_tty):
    import stenographer.cli.hub.handler as handler

    monkeypatch.setattr(handler, "cmd_hub", lambda _args: pytest.fail("hub must not run"))
    monkeypatch.setattr(sys, "stdin", Terminal(stdin_tty))
    terminal_out = Terminal(stdout_tty)
    monkeypatch.setattr(sys, "stdout", terminal_out)

    assert dispatch([]) == 0
    help_text = terminal_out.getvalue()
    assert "usage:" in help_text and "stenographer" in help_text


def test_hub_warms_worker_before_running_the_app(monkeypatch, tmp_path):
    import stenographer.cli.hub.handler as handler

    events = []

    class Process:
        def close(self):
            events.append("close")

    class Transport:
        def spawn(self, config, *, on_log):
            assert config is cfg.asr
            assert callable(on_log)
            events.append("spawn")
            return Process()

    platform = SimpleNamespace(
        asr_transport=lambda: Transport(),
        data_dir=lambda *_args: tmp_path,
    )
    monkeypatch.setattr(handler, "current_platform", lambda: platform)
    cfg = SimpleNamespace(asr=object(), feedback=SimpleNamespace(log_level="debug"))
    config_path = tmp_path / "config.toml"
    from stenographer.lib.config.defaults import default_toml

    config_path.write_text(default_toml(), encoding="utf-8")
    monkeypatch.setattr(handler, "resolve_config_path", lambda: config_path)
    monkeypatch.setattr(handler, "load_or_default", lambda: cfg)
    monkeypatch.setattr(
        handler,
        "apply_stderr_level",
        lambda level: events.append(f"level:{level}"),
    )
    monkeypatch.setattr(handler, "_run_app", lambda _services, _editor: events.append("app"))

    assert handler.cmd_hub(SimpleNamespace()) == 0
    assert events == ["level:debug", "spawn", "close", "app"]


def test_hub_opens_invalid_config_read_only_without_starting_worker(monkeypatch, tmp_path):
    import stenographer.cli.hub.handler as handler
    from stenographer.lib.config.errors import ConfigError
    from stenographer.lib.config.models import Config

    path = tmp_path / "config.toml"
    path.write_text("[stenographer.asr]\ncpu_threads = 100\n", encoding="utf-8")
    platform = SimpleNamespace()
    monkeypatch.setattr(handler, "resolve_config_path", lambda: path)
    monkeypatch.setattr(
        handler,
        "load_or_default",
        lambda: (_ for _ in ()).throw(ConfigError(path, "asr.cpu_threads", "must be in [0, 64]")),
    )
    monkeypatch.setattr(handler, "current_platform", lambda: platform)
    opened = []
    monkeypatch.setattr(
        handler,
        "_run_app",
        lambda services, editor: opened.append((services, editor)),
    )

    assert handler.cmd_hub(SimpleNamespace()) == 0
    services, editor = opened[0]
    assert editor.read_only
    assert str(path) in editor.error_text()
    assert services._config.asr.cpu_threads == Config.defaults().asr.cpu_threads


def test_hub_services_do_not_create_a_session_until_recording_starts(tmp_path):
    from stenographer.cli.hub.services import HubServices
    from stenographer.lib.live.models import LIVE_MODELS

    model_dir = tmp_path / "models" / "live"
    model_dir.mkdir(parents=True)
    for model in LIVE_MODELS:
        (model_dir / model.filename).touch()

    created = []

    class Session:
        def __init__(self, config, **_kwargs):
            self.config = config
            self.started = False
            self.stopped = False
            created.append(self)

        def start(self):
            assert services.recording
            self.started = True

        def stop(self):
            self.stopped = True

    platform = SimpleNamespace(data_dir=lambda *_args: tmp_path)
    initial_config = SimpleNamespace(asr=object(), live=SimpleNamespace(diarize_mic=False))
    next_config = SimpleNamespace(asr=object(), live=SimpleNamespace(diarize_mic=False))
    services = HubServices(initial_config, platform, session_factory=Session)

    assert not services.recording
    assert services.session is None
    assert created == []

    services.start_recording()
    assert services.recording
    assert services.session is created[0]
    assert created[0].started

    services.update_config(next_config)
    assert created[0].config is initial_config
    services.stop_recording()
    assert not services.recording
    assert services.session is None
    assert created[0].stopped

    services.start_recording()
    assert created[1].config is next_config
    services.stop_recording()


def test_hub_services_cancels_an_attached_files_job():
    from stenographer.cli.hub.services import HubServices

    class Job:
        def __init__(self):
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

    job = Job()
    services = HubServices(SimpleNamespace(asr=object()), SimpleNamespace())
    services.files_job = job

    assert services.files_running
    services.cancel_files()
    assert job.cancelled


def test_hub_services_start_sessions_with_the_configured_mic_diarization(tmp_path):
    from dataclasses import replace

    from stenographer.cli.hub.services import HubServices
    from stenographer.lib.config.models import Config
    from stenographer.lib.live.models import LIVE_MODELS

    model_dir = tmp_path / "models" / "live"
    model_dir.mkdir(parents=True)
    for model in LIVE_MODELS:
        (model_dir / model.filename).touch()
    choices = []

    class Session:
        def __init__(self, _config, **kwargs):
            choices.append(kwargs["diarize_mic"])

        def start(self):
            pass

        def stop(self):
            pass

    defaults = Config.defaults()
    platform = SimpleNamespace(data_dir=lambda *_args: tmp_path)
    services = HubServices(defaults, platform, session_factory=Session)

    services.start_recording()
    services.stop_recording()
    services.update_config(replace(defaults, live=replace(defaults.live, diarize_mic=True)))
    services.start_recording()
    services.stop_recording()

    assert choices == [False, True]


def _prepare_hub(monkeypatch, tmp_path, run_app):
    """Run ``cmd_hub`` with defaults, a stub worker, and ``run_app`` as the app."""
    import stenographer.cli.hub.handler as handler
    from stenographer.lib.config.defaults import default_toml

    class Transport:
        def spawn(self, _config, *, on_log):
            return SimpleNamespace(close=lambda: None)

    config_path = tmp_path / "config.toml"
    config_path.write_text(default_toml(), encoding="utf-8")
    monkeypatch.delenv("STENOGRAPHER_LOG_LEVEL", raising=False)
    monkeypatch.setattr(handler, "resolve_config_path", lambda: config_path)
    monkeypatch.setattr(
        handler, "current_platform", lambda: SimpleNamespace(asr_transport=Transport)
    )
    monkeypatch.setattr(handler, "_run_app", run_app)
    return handler


def _wait_for_log_line(path, text):
    # The listener writes the stderr sink before the file sink, so once the
    # file holds the line, the stderr sink has already taken its turn.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.is_file() and text in path.read_text(encoding="utf-8"):
            return
        time.sleep(0.01)
    pytest.fail(f"log file never received {text!r}")


def test_only_the_app_reaches_the_terminal_while_the_hub_runs(monkeypatch, tmp_path, capfd):
    from stenographer.lib.logging.pipeline import setup_logging, shutdown_logging

    log_file = tmp_path / "stenographer" / "stenographer.log"
    record_log = logging.getLogger("stenographer.cli.hub.test")
    child = "import os, sys; print('child-stdout', flush=True); os.write(2, b'child-stderr')"

    def run_app(_services, _editor):
        record_log.warning("warning-during-app")
        _wait_for_log_line(log_file, "warning-during-app")
        subprocess.run([sys.executable, "-c", child], check=True)
        os.write(1, b"native-fd1")
        os.write(2, b"native-fd2")
        # The streams that Textual's driver and its exit report write to.
        sys.__stderr__.write("app-frame")
        sys.__stderr__.flush()
        sys.stderr.write("exit-report")
        sys.stderr.flush()

    handler = _prepare_hub(monkeypatch, tmp_path, run_app)
    shutdown_logging()
    capfd.readouterr()
    # The real pipeline, bound like the real process: a text stream over fd 2.
    with open(2, "w", closefd=False) as terminal_stderr:
        setup_logging(env={"XDG_STATE_HOME": str(tmp_path)}, home=tmp_path, stderr=terminal_stderr)
        try:
            assert handler.cmd_hub(SimpleNamespace()) == 0
            during = capfd.readouterr()

            record_log.warning("warning-after-app")
            _wait_for_log_line(log_file, "warning-after-app")
            after = capfd.readouterr()
        finally:
            shutdown_logging()

    assert during.out == ""
    assert "warning-during-app" not in during.err
    assert "child-stderr" not in during.err
    assert "native-fd2" not in during.err
    assert "app-frame" in during.err
    assert "exit-report" in during.err
    assert "warning-during-app" in log_file.read_text(encoding="utf-8")
    assert "warning-after-app" in after.err


def test_terminal_streams_come_back_when_the_app_crashes(monkeypatch, tmp_path, capfd):
    def run_app(_services, _editor):
        raise RuntimeError("app crashed")

    handler = _prepare_hub(monkeypatch, tmp_path, run_app)
    streams = (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__)

    with pytest.raises(RuntimeError, match="app crashed"):
        handler.cmd_hub(SimpleNamespace())

    assert (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__) == streams
    capfd.readouterr()
    os.write(1, b"crash-fd1")
    os.write(2, b"crash-fd2")
    captured = capfd.readouterr()
    assert captured.out == "crash-fd1"
    assert captured.err == "crash-fd2"
