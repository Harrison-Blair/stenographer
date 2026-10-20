# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import dataclasses
from types import SimpleNamespace

from textual.widgets import Static

from stenographer.cli.hub.app import HubApp
from stenographer.cli.hub.config_view import ConfigEditor
from stenographer.cli.hub.doctor_view import DoctorCheck, DoctorReport, safe_warning_lines
from stenographer.cli.hub.setup_wizard import SetupWizard
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

    assert warnings == ("12:00:01 WARNING stenographer.asr asr: retry",)
    assert "SENSITIVE_PAYLOAD" not in "\n".join(warnings)


def test_recent_warnings_reads_logs_and_omits_message_fields(tmp_path):
    from stenographer.cli.hub.doctor_view import recent_warnings

    path = tmp_path / "stenographer.log"
    line = "2026-10-20 12:00:01,001 WARNING stenographer.asr "
    path.write_text(line + "asr: retry transcript=SENSITIVE\n")

    warnings = recent_warnings((path,))
    assert warnings == ("12:00:01 WARNING stenographer.asr asr: retry",)
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
