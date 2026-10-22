# SPDX-License-Identifier: GPL-3.0-or-later
"""Command startup tests do not launch Textual or access audio hardware."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from stenographer.lib.live.models import LIVE_MODELS


def test_missing_live_models_report_explicit_download_command_without_app(
    monkeypatch, tmp_path, capsys
):
    import stenographer.cli.live.handler as handler

    fake_platform = SimpleNamespace(data_dir=lambda *_: tmp_path)
    monkeypatch.setattr(handler, "current_platform", lambda: fake_platform)
    monkeypatch.setattr(
        handler,
        "_run_app",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("UI opened")),
    )
    args = SimpleNamespace(mic=True, system=True, device=None, diarize_mic=None)
    cfg = SimpleNamespace(
        asr=SimpleNamespace(model="test-model"), live=SimpleNamespace(diarize_mic=False)
    )

    result = handler.cmd_live.__wrapped__(args, cfg)

    assert result != 0
    assert "stenographer model download --live" in capsys.readouterr().err


def test_live_command_starts_and_stops_session_without_run_lock(monkeypatch, tmp_path, capsys):
    import stenographer.cli.live.handler as handler

    fake_platform = SimpleNamespace(data_dir=lambda *_: tmp_path)
    model_dir = tmp_path / "models" / "live"
    model_dir.mkdir(parents=True)
    for model in LIVE_MODELS:
        (model_dir / model.filename).touch()
    monkeypatch.setattr(handler, "current_platform", lambda: fake_platform)
    sessions = []
    created_sessions = []
    events = []

    class FakeSession:
        path = Path("saved-session")
        relabel_error = "batch clustering unavailable"

        def __init__(self, cfg, **kwargs):
            sessions.append((cfg, kwargs))
            self.stopped = False
            created_sessions.append(self)

        def start(self):
            events.append("start")

        def stop(self):
            events.append("stop")
            self.stopped = True

    monkeypatch.setattr(handler, "LiveSession", FakeSession)
    monkeypatch.setattr(handler, "_run_app", lambda _session: events.append("app"))
    args = SimpleNamespace(mic=False, system=True, device="USB Mic", diarize_mic=None)
    cfg = SimpleNamespace(
        asr=SimpleNamespace(model="test-model"), live=SimpleNamespace(diarize_mic=False)
    )

    result = handler.cmd_live.__wrapped__(args, cfg)

    assert result == 0
    assert sessions == [
        (
            cfg,
            {
                "mic": False,
                "system": True,
                "device": "USB Mic",
                "diarize_mic": False,
                "platform": fake_platform,
            },
        )
    ]
    assert created_sessions[0].stopped
    assert events == ["start", "app", "stop"]
    captured = capsys.readouterr()
    assert "speaker relabel failed: batch clustering unavailable" in captured.err
    output = captured.out
    assert "loading model" in output
    assert "saved-session" in output


def test_live_model_load_failure_exits_before_opening_the_app(monkeypatch, tmp_path, capsys):
    import stenographer.cli.live.handler as handler

    fake_platform = SimpleNamespace(data_dir=lambda *_: tmp_path)
    model_dir = tmp_path / "models" / "live"
    model_dir.mkdir(parents=True)
    for model in LIVE_MODELS:
        (model_dir / model.filename).touch()
    monkeypatch.setattr(handler, "current_platform", lambda: fake_platform)
    events = []

    class FailedSession:
        path = Path("saved-session")

        def __init__(self, *_args, **_kwargs):
            pass

        def start(self):
            events.append("start")
            raise RuntimeError("model initialization failed")

        def stop(self):
            events.append("stop")

    monkeypatch.setattr(handler, "LiveSession", FailedSession)
    monkeypatch.setattr(handler, "_run_app", lambda _session: events.append("app"))
    args = SimpleNamespace(mic=True, system=True, device=None, diarize_mic=None)
    cfg = SimpleNamespace(
        asr=SimpleNamespace(model="test-model"), live=SimpleNamespace(diarize_mic=False)
    )

    result = handler.cmd_live.__wrapped__(args, cfg)

    assert result != 0
    assert events == ["start", "stop"]
    assert "could not load live ASR model" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("flag", "configured", "expected"),
    [
        (None, False, False),
        (None, True, True),
        (True, False, True),
        (False, True, False),
    ],
)
def test_diarize_mic_flag_overrides_the_config_value(
    monkeypatch, tmp_path, flag, configured, expected
):
    import stenographer.cli.live.handler as handler

    fake_platform = SimpleNamespace(data_dir=lambda *_: tmp_path)
    model_dir = tmp_path / "models" / "live"
    model_dir.mkdir(parents=True)
    for model in LIVE_MODELS:
        (model_dir / model.filename).touch()
    monkeypatch.setattr(handler, "current_platform", lambda: fake_platform)
    choices = []

    class FakeSession:
        path = Path("saved-session")
        relabel_error = None

        def __init__(self, _cfg, **kwargs):
            choices.append(kwargs["diarize_mic"])

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(handler, "LiveSession", FakeSession)
    monkeypatch.setattr(handler, "_run_app", lambda _session: None)
    args = SimpleNamespace(mic=True, system=True, device=None, diarize_mic=flag)
    cfg = SimpleNamespace(
        asr=SimpleNamespace(model="test-model"), live=SimpleNamespace(diarize_mic=configured)
    )

    assert handler.cmd_live.__wrapped__(args, cfg) == 0
    assert choices == [expected]
