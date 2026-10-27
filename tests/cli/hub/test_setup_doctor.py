# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import dataclasses
from datetime import datetime
from types import SimpleNamespace

from rich.color import Color
from textual.widgets import Static

from stenographer.cli.hub.app import HubApp
from stenographer.cli.hub.config_view import ConfigEditor
from stenographer.cli.hub.doctor_view import DoctorCheck, DoctorReport, safe_warning_lines
from stenographer.cli.shared.capabilities import Capabilities
from stenographer.lib.config.document import ConfigDocument
from stenographer.lib.config.models import Config
from stenographer.overlay.capabilities.models import OverlayCapability
from stenographer.overlay.protocol.unavailablereason import UnavailableReason


class FakeServices:
    recording = False
    files_running = False


def test_safe_warning_lines_only_keep_warning_event_names():
    text = "\n".join(
        (
            "2026-10-20 12:00:00,001 INFO stenographer.daemon daemon: started",
            "2026-10-20 12:00:01,001 WARNING stenographer.asr utt=7 "
            "asr: retry transcript=SENSITIVE_PAYLOAD",
            "2026-10-20 12:00:02,001 ERROR stenographer.audio audio: failed text=PRIVATE",
            "2026-10-20 12:00:03,001 WARNING stenographer.misc user dictated private words",
        )
    )

    warnings = safe_warning_lines(text)

    assert warnings == (
        "12:00:01 WARN asr: retry",
        "12:00:02 ERROR audio: failed",
    )
    assert "stenographer.asr" not in "\n".join(warnings)
    assert "SENSITIVE_PAYLOAD" not in "\n".join(warnings)


def test_recent_warnings_reads_logs_and_omits_message_fields(tmp_path):
    from stenographer.cli.hub.doctor_view import recent_warnings

    path = tmp_path / "stenographer.log"
    line = "2026-10-20 12:00:01,001 WARNING stenographer.asr "
    path.write_text(line + "asr: retry transcript=SENSITIVE\n")

    warnings = recent_warnings((path,))
    assert warnings == ("12:00:01 WARN asr: retry",)
    assert "stenographer.asr" not in "\n".join(warnings)
    assert "SENSITIVE" not in "\n".join(warnings)


def test_build_report_groups_fake_host_checks_and_counts_warnings(monkeypatch, tmp_path):
    from stenographer.cli.hub import doctor_view
    from stenographer.lib import platform as platform_module
    from stenographer.lib.diagnostics import additional_checks
    from stenographer.lib.diagnostics.additional_checks import DiagnosticCheck
    from stenographer.lib.logging import pipeline as logging_pipeline
    from stenographer.overlay import platform as overlay_platform
    from stenographer.overlay.platform.guidance import OverlayGuidance

    guidance = SimpleNamespace(
        capability_labels={
            "key_injector_ok": "input injector",
            "hotkey_access_ok": "global hotkey access",
            "has_mic": "microphone",
            "model_cached": "ASR model cached",
            "clipboard_ok": "clipboard",
        },
        capability_fix_hints={"hotkey_access_ok": "Join the input group."},
        clipboard_fix_hints={},
        clipboard_fix_hint_default="Install clipboard support.",
        clipboard_read_fix_hints={"test": "Enable clipboard reads."},
        service_noun="systemd unit",
        service_installer="scripts/install.sh",
        service_unknown_detail="service manager is unavailable",
        service_start_command="systemctl --user start stenographer.service",
    )
    overlay_guidance = OverlayGuidance(
        overlay_backend_labels={},
        overlay_fix_hints={UnavailableReason.NO_X_DISPLAY: "Enable XWayland."},
        overlay_fix_hint_default="Check the display.",
    )
    caps = Capabilities(
        key_injector_ok=True,
        hotkey_access_ok=False,
        has_mic=True,
        model_cached=True,
        clipboard_ok=True,
        clipboard_backend="test",
        clipboard_read_ok=False,
        cue_player=None,
        service_enabled=None,
        service_active="inactive",
        overlay=OverlayCapability.unavailable(UnavailableReason.NO_X_DISPLAY),
    )
    monkeypatch.setattr("stenographer.cli.shared.capability_probe.probe", lambda _config: caps)
    monkeypatch.setattr(
        platform_module,
        "current_platform",
        lambda: SimpleNamespace(guidance=lambda: guidance),
    )
    monkeypatch.setattr(
        overlay_platform,
        "current_platform",
        lambda: SimpleNamespace(guidance=lambda: overlay_guidance),
    )
    monkeypatch.setattr(
        additional_checks,
        "collect_additional_checks",
        lambda: (
            DiagnosticCheck("system_capture", "warn", "no default sink", "Select a sink."),
            DiagnosticCheck("live_models_cached", "ok", "cached", ""),
            DiagnosticCheck("ffmpeg", "warn", "not installed", "Install ffmpeg."),
        ),
    )
    monkeypatch.setattr(
        logging_pipeline,
        "log_paths",
        lambda: (tmp_path / "stenographer.log", tmp_path / "overlay.log"),
    )

    report = doctor_view.build_report(Config.defaults(), tmp_path / "config.toml")
    checks = {check.check_id: check for check in report.checks}

    assert checks["hotkey_access_ok"].status == "fail"
    assert checks["hotkey_access_ok"].fix == "Join the input group."
    assert checks["model_cached"].label == "ASR model cached · Underdog Bark 3.0 Pro"
    assert checks["system_capture"].group == "input and audio"
    assert checks["ffmpeg"].group == "engine and desktop"
    assert checks["ffmpeg"].status == "warn"
    assert checks["overlay"].fix == "Enable XWayland."
    assert checks["clipboard_restore"].fix == "Enable clipboard reads."
    assert report.warn_count == 6
    assert report.fail_count == 1


def test_doctor_report_groups_checks_and_shows_warning_details():
    report = DoctorReport(
        checks=(
            DoctorCheck(
                "has_mic",
                "microphone",
                "input and audio",
                "fail",
                "No input device was found.",
                "Connect a microphone.",
            ),
            DoctorCheck(
                "ffmpeg",
                "ffmpeg",
                "engine and desktop",
                "warn",
                "ffmpeg is not installed.",
                "Install ffmpeg.",
            ),
        ),
        warnings=("12:00:01 WARNING stenographer.asr asr: retry",),
    )

    rendered = report.render(selected_index=0, details=True)

    assert "input and audio" in rendered
    assert "engine and desktop" in rendered
    assert "No input device was found." in rendered
    assert "Fix: Connect a microphone." in rendered
    assert "12:00:01 WARNING stenographer.asr asr: retry" in rendered
    assert report.warn_count == 1
    assert report.fail_count == 1
    assert "PRIVATE" not in report.report_text()


async def _open_checks(pilot):
    await pilot.press("3", "left")
    await pilot.pause()


def test_pilot_checks_test_key_and_confirmed_model_download():
    async def exercise():
        calls = []
        report = DoctorReport(
            (DoctorCheck("has_mic", "microphone", "input and audio", "warn", "none", "x"),), ()
        )
        app = HubApp(
            FakeServices(),
            setup_test=lambda step_id, _config: f"tested {step_id}",
            model_download=lambda model: calls.append(model),
            doctor_probe=lambda _config, _path: report,
        )
        async with app.run_test() as pilot:
            await _open_checks(pilot)
            assert app.settings_screen.tab == "checks"
            await pilot.press("t")
            for _ in range(50):
                if app.checks_tab.test_status:
                    break
                await pilot.pause(0.01)
            status = app.screen.query_one("#checks-test-status", Static).render()
            assert str(status) == "test: tested microphone"

            await pilot.press("m")
            assert calls == []
            prompt = str(app.screen.query_one("#quit-prompt", Static).render())
            assert "download" in prompt.casefold()
            await pilot.press("n")
            assert calls == []
            await pilot.press("m")
            await pilot.press("y")
            await pilot.pause()
            # The hub downloads the one Bark model, never the Whisper config key.
            from stenographer.lib.transcribe.bark_download import MODEL_DIRNAME

            assert calls == [MODEL_DIRNAME]

    asyncio.run(exercise())


def test_checks_defaults_replace_config_and_preserve_a_backup(tmp_path, monkeypatch):
    async def exercise():
        path = tmp_path / "config.toml"
        defaults = Config.defaults()
        changed = dataclasses.replace(
            defaults,
            audio=dataclasses.replace(defaults.audio, input_device="test microphone"),
        )
        ConfigDocument.defaults(path).save(changed)
        original = path.read_bytes()
        report = DoctorReport((), ())
        app = HubApp(
            FakeServices(),
            config_editor=ConfigEditor(path),
            doctor_probe=lambda _config, _path: report,
        )
        workers = []
        run_worker = app.run_worker

        def track_worker(*args, **kwargs):
            worker = run_worker(*args, **kwargs)
            if worker.group == "setup":
                workers.append(worker)
            return worker

        monkeypatch.setattr(app, "run_worker", track_worker)
        async with app.run_test() as pilot:
            await _open_checks(pilot)
            await pilot.press("shift+d")
            assert len(workers) == 1
            await workers[0].wait()

        saved = Config.loads(path.read_text())
        assert saved == defaults
        backups = tuple(tmp_path.glob("config.toml.bak-*"))
        assert len(backups) == 1
        assert backups[0].read_bytes() == original

    asyncio.run(exercise())


def test_settings_quit_prompts_to_save_draft_changes(tmp_path):
    async def exercise():
        path = tmp_path / "config.toml"
        editor = ConfigEditor(path)
        editor.edit("audio.input_device", "test microphone")
        app = HubApp(
            FakeServices(),
            config_editor=editor,
            doctor_probe=lambda _config, _path: DoctorReport((), ()),
        )
        async with app.run_test() as pilot:
            await _open_checks(pilot)
            await pilot.press("q")
            prompt = str(app.screen.query_one("#config-prompt-message", Static).render()).casefold()
            assert "save or discard" in prompt
            await pilot.click("#choice-save")

        assert Config.loads(path.read_text()).audio.input_device == "test microphone"

    asyncio.run(exercise())


def test_pilot_checks_use_sidebar_summary_and_bordered_board_panels():
    report = DoctorReport(
        checks=(
            DoctorCheck("mic", "microphone", "input and audio", "ok", "available", ""),
            DoctorCheck(
                "overlay",
                "overlay",
                "engine and desktop",
                "warn",
                "No X display.",
                "Enable XWayland.",
            ),
        ),
        warnings=("21:11:37 WARN overlay: helper_restarting",),
        checked_at=datetime(2026, 10, 20, 21, 23),
    )

    async def exercise():
        app = HubApp(FakeServices(), doctor_probe=lambda _config, _path: report)
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_checks(pilot)
            assert app.checks_tab.index == 1
            await pilot.press("enter")

            inputs = app.screen.query_one("#doctor-input-group", Static)
            engine = app.screen.query_one("#doctor-engine-group", Static)
            issue = app.screen.query_one("#doctor-issue", Static)
            warnings = app.screen.query_one("#doctor-warnings", Static)
            assert all(
                panel.styles.border.top[0] == "round" for panel in (inputs, engine, issue, warnings)
            )
            assert inputs.region.y == engine.region.y
            assert inputs.region.x < engine.region.x
            assert issue.region.y > inputs.region.y
            assert warnings.region.y > issue.region.y
            assert "microphone" in inputs.render().plain
            overlay_row = next(
                row for row in engine.render().plain.splitlines() if "overlay" in row
            )
            assert overlay_row.endswith("! overlay · No X display.")
            assert overlay_row.count("No X display.") == 1
            issue_content = issue.render()
            issue_text = issue_content.plain
            assert issue_text.startswith("overlay unavailable\n")
            assert "No X display. Enable XWayland." in issue_text
            assert "WARN ·" not in issue_text
            assert "Detail:" not in issue_text
            assert "Fix:" not in issue_text
            assert issue.styles.border.top[1].hex.lower() == "#ffaf5f"
            title_style = issue_content.get_style_at_offset(0)
            assert title_style.bold
            assert (
                title_style.rich_style.color.get_truecolor()
                == Color.parse("#ffaf5f").get_truecolor()
            )
            assert "helper_restarting" in warnings.render().plain
            assert "stenographer.overlay" not in warnings.render().plain
            card = app.screen.query_one("#sidebar-card", Static).render().plain
            assert app.screen.query_one("#sidebar-context").border_title == "checks"
            assert "1 pass · 1 warn · 0 fail" in card
            assert f"last run {app.checks_tab.ran_at:%H:%M}" in card

    asyncio.run(exercise())


def test_pilot_checks_color_check_glyphs_and_warning_levels():
    report = DoctorReport(
        checks=(
            DoctorCheck("mic", "microphone", "engine and desktop", "ok", "QuadCast 2 S", ""),
            DoctorCheck(
                "capture",
                "system capture",
                "engine and desktop",
                "warn",
                "no default sink",
                "Select a sink.",
            ),
            DoctorCheck(
                "overlay",
                "overlay",
                "engine and desktop",
                "fail",
                "helper exited",
                "Restart the overlay helper.",
            ),
        ),
        warnings=(
            "21:11:37 WARN overlay: helper_restarting",
            "21:10:03 ERROR audio: device_lost",
        ),
    )

    async def exercise():
        app = HubApp(FakeServices(), doctor_probe=lambda _config, _path: report)
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_checks(pilot)
            group = app.screen.query_one("#doctor-engine-group", Static).render()
            for glyph, color in (
                ("✓", "#6ee69a"),
                ("!", "#ffaf5f"),
                ("✗", "#ff5f5f"),
            ):
                style = group.get_style_at_offset(group.plain.index(glyph))
                assert style.rich_style.color.get_truecolor() == Color.parse(color).get_truecolor()

            warnings = app.screen.query_one("#doctor-warnings", Static).render()
            assert "21:11:37 WARN overlay: helper_restarting" in warnings.plain
            assert "21:10:03 ERROR audio: device_lost" in warnings.plain
            assert "stenographer." not in warnings.plain
            for token, color in (("WARN", "#ffaf5f"), ("ERROR", "#ff5f5f")):
                style = warnings.get_style_at_offset(warnings.plain.index(token))
                assert style.rich_style.color.get_truecolor() == Color.parse(color).get_truecolor()
            time_style = warnings.get_style_at_offset(warnings.plain.index("21:11:37"))
            assert time_style.dim

    asyncio.run(exercise())


def test_pilot_checks_rerun_badges_and_fix_opens_the_setting(tmp_path):
    async def exercise():
        calls = []
        report = DoctorReport(
            checks=(
                DoctorCheck(
                    "has_mic",
                    "microphone",
                    "input and audio",
                    "fail",
                    "No microphone.",
                    "Connect a microphone.",
                ),
                DoctorCheck(
                    "ffmpeg",
                    "ffmpeg",
                    "engine and desktop",
                    "warn",
                    "ffmpeg is not installed.",
                    "Install ffmpeg.",
                ),
            ),
            warnings=(),
        )
        path = tmp_path / "config.toml"
        app = HubApp(
            FakeServices(),
            config_editor=ConfigEditor(path),
            doctor_probe=lambda _config, _path: calls.append("probe") or report,
            open_log=lambda: calls.append("log"),
            copy_report=lambda text: calls.append(("copy", text)),
        )
        async with app.run_test() as pilot:
            await _open_checks(pilot)
            settings_row = str(app.screen.query_one("#sidebar", Static).render()).splitlines()[-1]
            assert settings_row.endswith("1 F")
            assert str(app.screen.query_one("#tab-checks").label) == "Checks ●2"
            await pilot.press("enter")
            rendered = str(app.screen.query_one("#doctor-issue", Static).render())
            assert "Connect a microphone." in rendered
            await pilot.press("r")
            await pilot.pause()
            assert calls.count("probe") == 2
            await pilot.press("l")
            await pilot.press("c")
            assert "log" in calls
            assert any(isinstance(call, tuple) and call[0] == "copy" for call in calls)
            await pilot.press("f")
            assert app.current_mode == "settings"
            assert app.settings_screen.tab == "audio"
            assert app.config_editor.selected_key == "audio.input_device"

    asyncio.run(exercise())


def test_the_models_step_probes_the_installed_bark_model(monkeypatch, tmp_path):
    # The root conftest does not redirect XDG_DATA_HOME; never touch the real one.
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    import json
    import os
    from pathlib import Path

    from stenographer.cli.hub.setup_test import test_step
    from stenographer.lib.platform import current_platform
    from stenographer.lib.transcribe import bark_download
    from stenographer.lib.transcribe.bark_pins import BARK_PRO_PINS

    config = Config.defaults()
    assert test_step("models", config, tmp_path).startswith("ASR model not cached")

    root = bark_download.model_dir(current_platform().data_dir(os.environ, Path.home()))
    root.mkdir(parents=True)
    hashes = {name: "0" * 64 for name in bark_download.CONVERTED_FILES}
    for name in hashes:
        (root / name).write_bytes(b"")
    manifest = bark_download.build_manifest(BARK_PRO_PINS, hashes)
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert test_step("models", config, tmp_path).startswith("ASR model cached")
