# SPDX-License-Identifier: GPL-3.0-or-later
"""Command startup tests do not launch Textual or access audio hardware."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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
    args = SimpleNamespace(mic=True, system=True, device=None)
    cfg = SimpleNamespace(asr=SimpleNamespace(model="test-model"))

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

    class FakeSession:
        path = Path("saved-session")

        def __init__(self, cfg, **kwargs):
            sessions.append((cfg, kwargs))
            self.stopped = False
            created_sessions.append(self)

        def stop(self):
            self.stopped = True

    monkeypatch.setattr(handler, "LiveSession", FakeSession)
    monkeypatch.setattr(handler, "_run_app", lambda _session: None)
    args = SimpleNamespace(mic=False, system=True, device="USB Mic")
    cfg = SimpleNamespace(asr=SimpleNamespace(model="test-model"))

    result = handler.cmd_live.__wrapped__(args, cfg)

    assert result == 0
    assert sessions == [
        (
            cfg,
            {
                "mic": False,
                "system": True,
                "device": "USB Mic",
                "platform": fake_platform,
            },
        )
    ]
    assert created_sessions[0].stopped
    assert "saved-session" in capsys.readouterr().out
