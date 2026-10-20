# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import dataclasses
from datetime import datetime
from types import SimpleNamespace

from rich.color import Color
from textual.containers import Vertical
from textual.widgets import Static

from stenographer.cli.hub.app import HubApp
from stenographer.cli.hub.config_view import ConfigEditor
from stenographer.cli.hub.doctor_view import DoctorCheck, DoctorReport, safe_warning_lines
from stenographer.cli.hub.setup_state import SetupWizard
from stenographer.cli.shared.capabilities import Capabilities
from stenographer.lib.config.document import ConfigDocument
from stenographer.lib.config.models import Config
from stenographer.overlay.capabilities.models import OverlayCapability
from stenographer.overlay.protocol.unavailablereason import UnavailableReason


class FakeServices:
    recording = False
    files_running = False


def test_setup_wizard_navigation_skip_and_quick_path():
    wizard = SetupWizard()

    assert [step.step_id for step in wizard.steps] == [
        "input_access",
        "microphone",
        "hotkey",
        "models",
        "sounds",
        "system_service",
    ]
    wizard.next()
    wizard.back()
    assert wizard.step.step_id == "input_access"
    wizard.skip()
    assert wizard.step.step_id == "microphone"

    wizard.start_quick()
    assert wizard.quick
    assert wizard.step.step_id == "input_access"
    wizard.next()
    wizard.next()
    wizard.next()
    assert wizard.finished


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


def test_pilot_setup_keys_and_confirmed_model_download():
    async def exercise():
        calls = []
        app = HubApp(
            FakeServices(),
            setup_test=lambda step_id, _config: f"tested {step_id}",
            model_download=lambda model: calls.append(model),
        )
        async with app.run_test() as pilot:
            await pilot.press("5")
            await pilot.press("t")
            await pilot.pause()
            assert "tested input_access" in str(app.query_one("#section-content", Static).render())

            await pilot.press("enter")
            await pilot.press("s")
            assert app.setup_wizard.step.step_id == "hotkey"
            await pilot.press("shift+q")
            assert app.setup_wizard.quick
            assert app.setup_wizard.step.step_id == "input_access"
            await pilot.press("enter", "enter", "enter")
            assert app.setup_wizard.finished

            app.setup_wizard.index = 3
            app.setup_wizard.finished = False
            await pilot.press("m")
            assert calls == []
            prompt = str(app.screen.query_one("#quit-prompt", Static).render())
            assert "download" in prompt.casefold()
            await pilot.press("n")
            assert calls == []
            await pilot.press("m")
            await pilot.press("y")
            await pilot.pause()
            assert calls == [Config.defaults().asr.model]

    asyncio.run(exercise())


def test_setup_microphone_edit_uses_workflow_device_choices(monkeypatch, tmp_path):
    async def exercise():
        from stenographer.cli.setup import workflow

        monkeypatch.setattr(workflow, "_audio_devices", lambda: [("2", "2: USB mic")])
        path = tmp_path / "config.toml"
        app = HubApp(
            FakeServices(),
            config_editor=ConfigEditor(path),
            doctor_probe=lambda _config, _path: DoctorReport((), ()),
        )
        async with app.run_test() as pilot:
            await pilot.press("5")
            await pilot.press("enter")
            await pilot.press("e")
            await pilot.pause()
            await pilot.press("1", "enter")

        assert app.config_editor.config.audio.input_device == "2"

    asyncio.run(exercise())


def test_setup_defaults_replace_config_and_preserve_a_backup(tmp_path):
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
        async with app.run_test() as pilot:
            await pilot.press("5")
            await pilot.press("shift+d")
            await pilot.pause()

        saved = Config.loads(path.read_text())
        assert saved == defaults
        backups = tuple(tmp_path.glob("config.toml.bak-*"))
        assert len(backups) == 1
        assert backups[0].read_bytes() == original

    asyncio.run(exercise())


def test_setup_quit_prompts_to_save_draft_changes(tmp_path):
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
            await pilot.press("5")
            await pilot.press("q")
            prompt = str(app.screen.query_one("#config-prompt-message", Static).render()).casefold()
            assert "save or discard" in prompt
            await pilot.click("#choice-save")

        assert Config.loads(path.read_text()).audio.input_device == "test microphone"

    asyncio.run(exercise())


def test_pilot_setup_uses_bordered_step_and_hotkey_detail_panels():
    async def exercise():
        app = HubApp(FakeServices())
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("5")
            app.setup_wizard.index = 2
            app.setup_wizard.record_test("key capture passed")
            app._refresh_view()

            steps = app.query_one("#setup-steps", Static)
            detail = app.query_one("#setup-detail", Vertical)
            content = app.query_one("#setup-detail-content", Static)
            test_status = app.query_one("#setup-test-status", Static)
            assert steps.styles.border.top[0] == "round"
            assert detail.styles.border.top[0] == "round"
            assert steps.region.x < detail.region.x
            assert test_status.region.y > content.region.y
            step_text = steps.render().plain
            detail_text = content.render().plain
            assert "▶ 3 hotkey" in step_text
            for expected in (
                "capture target: KEY_RIGHTCTRL",
                "mode: ● hybrid  ○ hold  ○ toggle",
                "hybrid threshold: 0.5 s",
                "general binding: KEY_RIGHTALT",
                "cancel binding: KEY_ESC",
                "device: any keyboard",
            ):
                assert expected in detail_text
            assert test_status.render().plain == "test status: key capture passed"
            content_render = content.render()
            mode_style = content_render.get_style_at_offset(content_render.plain.index("● hybrid"))
            assert mode_style.bold
            assert (
                mode_style.rich_style.color.get_truecolor()
                == Color.parse("#5fd7ff").get_truecolor()
            )
            assert not content_render.get_style_at_offset(content_render.plain.index("○ hold")).bold

    asyncio.run(exercise())


def test_pilot_doctor_uses_sidebar_summary_and_bordered_board_panels():
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
        app = HubApp(FakeServices())
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("6")
            app._doctor_report = report
            app._doctor_index = 1
            app._refresh_view()
            await pilot.press("enter")

            inputs = app.query_one("#doctor-input-group", Static)
            engine = app.query_one("#doctor-engine-group", Static)
            issue = app.query_one("#doctor-issue", Static)
            warnings = app.query_one("#doctor-warnings", Static)
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
            assert "1 warn" in app.query_one("#sidebar-card", Static).render().plain
            assert "checked 21:23" in app.query_one("#sidebar-card", Static).render().plain

    asyncio.run(exercise())


def test_pilot_doctor_colors_check_glyphs_and_warning_levels():
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
        app = HubApp(FakeServices())
        app._doctor_report = report
        app._doctor_index = 1
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("6")
            app._refresh_view()
            group = app.query_one("#doctor-engine-group", Static).render()
            for glyph, color in (
                ("✓", "#6ee69a"),
                ("!", "#ffaf5f"),
                ("✗", "#ff5f5f"),
            ):
                style = group.get_style_at_offset(group.plain.index(glyph))
                assert style.rich_style.color.get_truecolor() == Color.parse(color).get_truecolor()

            warnings = app.query_one("#doctor-warnings", Static).render()
            assert "21:11:37 WARN overlay: helper_restarting" in warnings.plain
            assert "21:10:03 ERROR audio: device_lost" in warnings.plain
            assert "stenographer." not in warnings.plain
            for token, color in (("WARN", "#ffaf5f"), ("ERROR", "#ff5f5f")):
                style = warnings.get_style_at_offset(warnings.plain.index(token))
                assert style.rich_style.color.get_truecolor() == Color.parse(color).get_truecolor()
            time_style = warnings.get_style_at_offset(warnings.plain.index("21:11:37"))
            assert time_style.dim

    asyncio.run(exercise())


def test_pilot_doctor_rechecks_shows_badge_and_routes_fix_to_setup():
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
        app = HubApp(
            FakeServices(),
            doctor_probe=lambda _config, _path: calls.append("probe") or report,
            open_log=lambda: calls.append("log"),
            copy_report=lambda text: calls.append(("copy", text)),
        )
        async with app.run_test() as pilot:
            await pilot.press("6")
            await pilot.pause()
            doctor_row = str(app.query_one("#sidebar", Static).render()).splitlines()[-1]
            assert "1W 1F" in doctor_row
            await pilot.press("enter")
            rendered = str(app.query_one("#section-content", Static).render())
            assert "Connect a microphone." in rendered
            await pilot.press("r")
            await pilot.pause()
            assert calls.count("probe") == 2
            await pilot.press("l")
            await pilot.press("c")
            assert "log" in calls
            assert any(isinstance(call, tuple) and call[0] == "copy" for call in calls)
            await pilot.press("f")
            assert app.current_section == "setup"
            assert app.setup_wizard.step.step_id == "microphone"

    asyncio.run(exercise())
