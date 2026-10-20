# SPDX-License-Identifier: GPL-3.0-or-later
"""CLI routing and service-owner tests for the hub."""

from __future__ import annotations

import sys
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
    path.write_text("[stenographer.asr]\nbeam_size = 0\n", encoding="utf-8")
    platform = SimpleNamespace()
    monkeypatch.setattr(handler, "resolve_config_path", lambda: path)
    monkeypatch.setattr(
        handler,
        "load_or_default",
        lambda: (_ for _ in ()).throw(ConfigError(path, "asr.beam_size", "must be at least 1")),
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
    assert str(path) in editor.render()
    assert services._config.asr.beam_size == Config.defaults().asr.beam_size


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
    initial_config = SimpleNamespace(asr=object())
    next_config = SimpleNamespace(asr=object())
    services = HubServices(initial_config, platform, session_factory=Session)

    assert not services.recording
    assert created == []

    services.start_recording()
    assert services.recording
    assert created[0].started

    services.update_config(next_config)
    assert created[0].config is initial_config
    services.stop_recording()
    assert not services.recording
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
