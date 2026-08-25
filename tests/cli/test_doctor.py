# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for the doctor report: the gate decision, the log tail, and
rendering only.

The gate (``stenographer.capabilities``) and its rendering (``cli/doctor.py``)
are exercised together here because the report is driven by ``REQUIRED``. The
"Logs" section is split the same way: ``run`` reads the files, and only its
pure half — ``tail_errors`` and ``decode_tail`` — is asserted here, over log
text written in the file sink's own format.

The environment probe itself is exercised by test_doctor_smoke.py (integration,
non-mocked) per the testing policy in AGENTS.md — nothing here stubs the
environment.

Host prose is an input, not a constant: ``render`` is handed a
``HostGuidance``. These cases pass the Linux wording explicitly so they assert
the same report on every OS; that the Linux provider really supplies those
strings is pinned by tests/platform/linux/test_guidance.py.
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

from stenographer.capabilities import Capabilities, OverlayCapability, missing_required
from stenographer.cli import doctor
from stenographer.config import Config
from stenographer.platform.base import HostGuidance
from stenographer.status import Backend, UnavailableReason

# One config path for every render case. Asserted through ``str()`` because
# ``render`` interpolates the path: the rendered separator is the host's, so a
# POSIX literal would not match on Windows.
_CONFIG_PATH = pathlib.Path("/tmp/config.toml")

# ``chmod 000`` denies nobody when the caller is root, and Windows ignores the
# mode bits outright; the state itself is still asserted through ``LogStatus``.
_MODE_BITS_BIND = sys.platform != "win32" and os.getuid() != 0

# Log facts are an input to ``render`` too: ``run`` does the reading.
_DAEMON_LOG = pathlib.Path("/state/stenographer.log")
_HELPER_LOG = pathlib.Path("/state/overlay-helper.log")
_LOGS = (
    doctor.LogStatus("daemon", _DAEMON_LOG, 4096),
    doctor.LogStatus("helper", _HELPER_LOG, None),
)

_XCLIP_HINT = "install xclip (the compositor lacks a data-control protocol; GNOME 46 and older)"

_GUIDANCE = HostGuidance(
    capability_labels={
        "key_injector_ok": "/dev/uinput writable",
        "hotkey_access_ok": "input group membership",
        "has_mic": "microphone",
        "model_cached": "ASR model cached",
        "clipboard_ok": "clipboard",
    },
    capability_fix_hints={
        "key_injector_ok": (
            "grant write access to /dev/uinput (udev rule or the uinput group), then re-login"
        ),
        "hotkey_access_ok": "sudo usermod -aG input $USER, then re-login",
        "has_mic": "no audio input device found; check the microphone / PortAudio",
        "model_cached": "run: stenographer model download",
    },
    clipboard_fix_hints={"wl-copy": "install wl-clipboard", "x11": _XCLIP_HINT},
    clipboard_fix_hint_default="install wl-clipboard",
    overlay_backend_labels={"layer-shell": "layer-shell", "xwayland": "XWayland fallback"},
    overlay_fix_hints={
        UnavailableReason.NO_X_DISPLAY: "no X display; set DISPLAY or enable XWayland",
        UnavailableReason.X_EXTENSIONS_UNAVAILABLE: (
            "XWayland requires the Shape and RandR extensions"
        ),
    },
    overlay_fix_hint_default=(
        "no usable layer-shell or XWayland backend; check the graphical session"
    ),
    service_noun="systemd unit",
    service_name="stenographer.service",
    service_installer="scripts/install.sh",
    service_unknown_detail="cannot query the systemd user manager",
    service_start_command="systemctl --user start stenographer.service",
    service_restart_command="systemctl --user restart stenographer.service",
    service_log_command="journalctl --user -u stenographer -f",
    hotkey_device_comment='explicit /dev/input/event* path; "" = auto-detect',
    run_with_config=lambda path: f"STENOGRAPHER_CONFIG={path} stenographer run",
)

# A second host whose every word differs, so a hardcoded string in ``render``
# cannot hide behind the Linux wording above.
_OTHER_GUIDANCE = HostGuidance(
    capability_labels={
        "key_injector_ok": "paste injection",
        "hotkey_access_ok": "global hotkey hook",
        "has_mic": "audio capture",
        "model_cached": "recognizer weights",
        "clipboard_ok": "pasteboard",
    },
    capability_fix_hints={
        "key_injector_ok": "enable the injector",
        "hotkey_access_ok": "permit the hook",
        "has_mic": "attach a capture device",
        "model_cached": "fetch the weights",
    },
    clipboard_fix_hints={"native": "enable the pasteboard bridge"},
    clipboard_fix_hint_default="no pasteboard backend",
    overlay_backend_labels={},
    overlay_fix_hints={},
    overlay_fix_hint_default="no display backend",
    service_noun="background agent",
    service_name="the stenographer agent",
    service_installer="the agent installer",
    service_unknown_detail="the agent manager did not answer",
    service_start_command="agentctl start",
    service_restart_command="agentctl restart",
    service_log_command="agentctl logs",
    hotkey_device_comment="opaque device id",
    run_with_config=lambda path: f"with-config {path}",
)


def _caps(**overrides) -> Capabilities:
    fields = {
        "key_injector_ok": True,
        "hotkey_access_ok": True,
        "has_mic": True,
        "model_cached": True,
        "clipboard_ok": True,
        "clipboard_backend": "wl-copy",
        "cue_player": "pw-play",
        "service_enabled": "enabled",
        "service_active": "active",
        "overlay": OverlayCapability.available(Backend.LAYER_SHELL),
    }
    fields.update(overrides)
    return Capabilities(**fields)


def test_missing_required_empty_when_all_present():
    assert missing_required(_caps()) == []


def test_missing_required_names_each_absent_capability():
    caps = _caps(key_injector_ok=False, model_cached=False)
    assert missing_required(caps) == ["key_injector_ok", "model_cached"]


def test_cue_player_is_not_required():
    assert missing_required(_caps(cue_player=None)) == []


def test_render_all_present():
    report = doctor.render(_caps(), Config.defaults(), _CONFIG_PATH, _GUIDANCE, _LOGS)
    assert "all required capabilities present" in report
    assert "MISSING" not in report
    assert str(_CONFIG_PATH) in report
    assert "audio player: pw-play" in report
    assert report.count("  overlay: ") == 1
    assert "  overlay: layer-shell" in report


def test_render_missing_capability_carries_fix_hint():
    caps = _caps(model_cached=False, clipboard_ok=False)
    report = doctor.render(caps, Config.defaults(), _CONFIG_PATH, _GUIDANCE, _LOGS)
    assert "ASR model cached: MISSING — run: stenographer model download" in report
    assert "clipboard (wl-copy): MISSING — install wl-clipboard" in report
    assert "missing required capabilities: ASR model cached, clipboard" in report


def test_render_clipboard_line_names_the_detected_backend():
    report = doctor.render(
        _caps(clipboard_backend="x11"), Config.defaults(), _CONFIG_PATH, _GUIDANCE, _LOGS
    )
    assert "clipboard (x11): ok" in report

    report = doctor.render(
        _caps(clipboard_ok=False, clipboard_backend="x11"),
        Config.defaults(),
        _CONFIG_PATH,
        _GUIDANCE,
        _LOGS,
    )
    assert (
        "clipboard (x11): MISSING — install xclip "
        "(the compositor lacks a data-control protocol; GNOME 46 and older)"
    ) in report


def test_render_absent_cue_player_is_informational():
    report = doctor.render(
        _caps(cue_player=None), Config.defaults(), _CONFIG_PATH, _GUIDANCE, _LOGS
    )
    assert "audio player: none (sound cues disabled)" in report
    assert "all required capabilities present" in report


def test_service_status_is_not_required():
    assert missing_required(_caps(service_enabled=None, service_active=None)) == []


def test_format_service_status_installed():
    assert doctor.format_service_status("enabled", "active", _GUIDANCE) == "enabled, active"
    assert doctor.format_service_status("disabled", "inactive", _GUIDANCE) == "disabled, inactive"
    assert doctor.format_service_status("enabled", "failed", _GUIDANCE) == "enabled, failed"


def test_format_service_status_not_installed():
    # is-enabled yields nothing for an unknown unit; is-active still says "inactive"
    assert doctor.format_service_status(None, "inactive", _GUIDANCE) == (
        "not installed — run scripts/install.sh"
    )


def test_format_service_status_unreachable_manager():
    assert doctor.format_service_status(None, None, _GUIDANCE) == (
        "unknown (cannot query the systemd user manager)"
    )


def test_render_carries_service_status_line():
    report = doctor.render(_caps(), Config.defaults(), _CONFIG_PATH, _GUIDANCE, _LOGS)
    assert "systemd unit: enabled, active" in report

    report = doctor.render(
        _caps(service_enabled=None, service_active="inactive"),
        Config.defaults(),
        _CONFIG_PATH,
        _GUIDANCE,
        _LOGS,
    )
    assert "systemd unit: not installed — run scripts/install.sh" in report
    assert "all required capabilities present" in report


def test_render_takes_every_host_word_from_the_supplied_guidance():
    """No Linux prose may survive in ``render`` itself.

    Rendering a fully-missing gate under a host whose every label, hint, and
    service word differs must reproduce that host verbatim and leak none of the
    Linux wording. Seen to FAIL against the pre-change tree, where ``render``
    read module-level ``_LABELS`` / ``_FIX_HINTS`` / ``_CLIPBOARD_FIX_HINTS``
    dicts and hardcoded "systemd unit" and "run scripts/install.sh".
    """

    caps = _caps(
        key_injector_ok=False,
        hotkey_access_ok=False,
        has_mic=False,
        model_cached=False,
        clipboard_ok=False,
        clipboard_backend="native",
        service_enabled=None,
        service_active="inactive",
    )
    report = doctor.render(caps, Config.defaults(), _CONFIG_PATH, _OTHER_GUIDANCE, _LOGS)

    assert "  paste injection: MISSING — enable the injector" in report
    assert "  global hotkey hook: MISSING — permit the hook" in report
    assert "  audio capture: MISSING — attach a capture device" in report
    assert "  recognizer weights: MISSING — fetch the weights" in report
    assert "  pasteboard (native): MISSING — enable the pasteboard bridge" in report
    assert "  background agent: not installed — run the agent installer" in report
    for linux_word in (
        "/dev/uinput",
        "input group",
        "usermod",
        "wl-clipboard",
        "xclip",
        "systemd",
        "install.sh",
    ):
        assert linux_word not in report


def test_render_falls_back_to_the_hosts_default_clipboard_hint():
    """An unanticipated backend name still gets that host's hint, not another's."""

    caps = _caps(clipboard_ok=False, clipboard_backend="something-new")
    report = doctor.render(caps, Config.defaults(), _CONFIG_PATH, _OTHER_GUIDANCE, _LOGS)
    assert "  pasteboard (something-new): MISSING — no pasteboard backend" in report


def test_overlay_report_variants_are_informational_only():
    variants = (
        (OverlayCapability.disabled(), "disabled"),
        (OverlayCapability.available(Backend.LAYER_SHELL), "layer-shell"),
        (OverlayCapability.available(Backend.XWAYLAND), "XWayland fallback"),
        (
            OverlayCapability.unavailable(UnavailableReason.X_EXTENSIONS_UNAVAILABLE),
            "unavailable — XWayland requires the Shape and RandR extensions",
        ),
    )
    for overlay, expected in variants:
        caps = _caps(overlay=overlay)
        report = doctor.render(caps, Config.defaults(), _CONFIG_PATH, _GUIDANCE, _LOGS)
        assert report.count("  overlay: ") == 1
        assert f"  overlay: {expected}" in report
        assert missing_required(caps) == []


def _log_line(level: str, message: str, *, utt: int = 1) -> str:
    """One line in the file sink's format (utils/logging_setup._FORMAT)."""
    return f"2026-08-24 09:15:02,431 {level} stenographer.audio utt={utt} {message}"


def test_tail_errors_keeps_only_warning_and_worse_in_file_order():
    text = "\n".join(
        [
            _log_line("DEBUG", "audio: block_copied frames=800"),
            _log_line("WARNING", "audio: gate_failed peak_rms=0.0004"),
            _log_line("INFO", "daemon: utterance outcome=delivered"),
            _log_line("ERROR", "clipboard: copy_failed error=CalledProcessError"),
            _log_line("CRITICAL", "worker: child_lost error=BrokenPipeError"),
        ]
    )
    assert doctor.tail_errors(text) == [
        _log_line("WARNING", "audio: gate_failed peak_rms=0.0004"),
        _log_line("ERROR", "clipboard: copy_failed error=CalledProcessError"),
        _log_line("CRITICAL", "worker: child_lost error=BrokenPipeError"),
    ]


def test_tail_errors_keeps_the_last_n_only():
    text = "\n".join(_log_line("ERROR", f"daemon: failed seq={index}") for index in range(25))
    tail = doctor.tail_errors(text)
    assert len(tail) == 10
    assert tail[0] == _log_line("ERROR", "daemon: failed seq=15")
    assert tail[-1] == _log_line("ERROR", "daemon: failed seq=24")
    assert doctor.tail_errors(text, 3) == [
        _log_line("ERROR", f"daemon: failed seq={index}") for index in (22, 23, 24)
    ]


def test_tail_errors_ignores_lines_that_are_not_records():
    """A record opens with the sink's date; nothing else is a record.

    A window opens mid-line, a DEBUG traceback spans several lines, and the
    helper writes raw stderr into its own log. None of that is a complaint,
    however loudly the exception text reads — and the fragment the window
    cut out of a timestamp must not pass as one either.
    """

    complaint = _log_line("WARNING", "audio: gate_failed peak_rms=0.0004")
    text = "\n".join(
        [
            "ed error=TimeoutExpired",
            "6-08-24 09:15:02,431 ERROR stenographer.audio utt=2 audio: stream_lost",
            "grapher.clipboard utt=2 clipboard: copy_failed error=CalledProcessError",
            _log_line("DEBUG", "clipboard: copy_failed error=CalledProcessError"),
            "Traceback (most recent call last):",
            '  File "/x/delivery/deliver.py", line 42, in copy',
            "ValueError: bad ERROR value",
            complaint,
            "",
        ]
    )
    assert doctor.tail_errors(text) == [complaint]


def test_tail_errors_reads_the_level_column_not_the_message():
    """``ERROR`` inside a message is prose; the level is the third column."""

    recovered = _log_line("INFO", "worker: restarted after=ERROR job=decode")
    complained = _log_line("WARNING", "delivery: release_wait timed out, an ERROR may follow")
    assert doctor.tail_errors("\n".join([recovered, complained])) == [complained]


def test_decode_tail_survives_a_character_split_by_the_window_edge():
    """The window can open mid-character; a replaced byte beats an exception."""

    complaint = _log_line("ERROR", "config: invalid key=asr.model detail=missing")
    half_a_character = "café".encode()[-1:]
    window = half_a_character + b" fragment\n" + complaint.encode()
    text = doctor.decode_tail(window)
    assert text.endswith(complaint)
    assert doctor.tail_errors(text) == [complaint]


def test_render_names_each_log_with_its_size_absence_or_refusal():
    logs = (*_LOGS, doctor.LogStatus("other", _DAEMON_LOG, 512, readable=False))
    report = doctor.render(_caps(), Config.defaults(), _CONFIG_PATH, _GUIDANCE, logs)
    assert "logs:" in report
    assert f"  daemon: {_DAEMON_LOG} (4096 bytes)" in report
    assert f"  helper: {_HELPER_LOG} (absent)" in report
    assert f"  other: {_DAEMON_LOG} (512 bytes, unreadable)" in report


def test_render_replays_each_log_tail_under_its_own_file():
    copy_failed = _log_line("ERROR", "clipboard: copy_failed error=CalledProcessError")
    backend_lost = _log_line("WARNING", "overlay: backend_lost reason=backend_lost")
    logs = (
        doctor.LogStatus("daemon", _DAEMON_LOG, 4096, (copy_failed,)),
        doctor.LogStatus("helper", _HELPER_LOG, 128, (backend_lost,)),
    )
    report = doctor.render(_caps(), Config.defaults(), _CONFIG_PATH, _GUIDANCE, logs)
    lines = report.splitlines()
    daemon = lines.index(f"  daemon: {_DAEMON_LOG} (4096 bytes)")
    helper = lines.index(f"  helper: {_HELPER_LOG} (128 bytes)")
    assert lines[daemon + 1] == f"    {copy_failed}"
    assert lines[helper + 1] == f"    {backend_lost}"
    assert "all required capabilities present" in report


def test_render_absent_log_contributes_one_line_and_no_body():
    logs = (doctor.LogStatus("daemon", _DAEMON_LOG, None),)
    report = doctor.render(_caps(), Config.defaults(), _CONFIG_PATH, _GUIDANCE, logs)
    lines = report.splitlines()
    index = lines.index(f"  daemon: {_DAEMON_LOG} (absent)")
    assert lines[index + 1] == ""
    assert "None" not in report
    assert "all required capabilities present" in report


def test_log_status_reads_only_the_window_at_the_end_of_a_long_log(tmp_path):
    """The daemon log rotates at 5 MiB; the report reads its tail, not the file.

    The old complaint below sits before the window, so a reader that opened
    the whole file would replay a line the user has long since dealt with.
    """

    path = tmp_path / "stenographer.log"
    old = _log_line("ERROR", "daemon: startup_failed reason=stale")
    new = _log_line("ERROR", "clipboard: copy_failed error=CalledProcessError")
    padding = _log_line("DEBUG", "audio: block_copied frames=800")
    filler = "\n".join([padding] * (300 * 1024 // len(padding)))
    path.write_text("\n".join([old, filler, new]), encoding="utf-8")

    status = doctor._log_status("daemon", path)

    assert status.size == path.stat().st_size
    assert status.size > 256 * 1024
    assert status.tail == (new,)


def test_log_status_reads_a_log_shorter_than_the_window(tmp_path):
    path = tmp_path / "stenographer.log"
    complaint = _log_line("WARNING", "audio: gate_failed peak_rms=0.0004")
    path.write_text(complaint + "\n", encoding="utf-8")

    status = doctor._log_status("daemon", path)

    assert status.size == path.stat().st_size
    assert status.tail == (complaint,)
    assert status.readable


def test_log_status_treats_an_absent_log_as_a_fact(tmp_path):
    status = doctor._log_status("helper", tmp_path / "overlay-helper.log")

    assert status.size is None
    assert status.tail == ()


@pytest.mark.skipif(not _MODE_BITS_BIND, reason="mode bits do not deny this caller")
def test_log_status_keeps_the_size_of_a_log_it_may_not_open(tmp_path):
    """A daemon once started under another account leaves a log like this.

    It exists, and saying so is the whole point: reported as absent, the
    reader goes looking for a log that is right there.
    """

    path = tmp_path / "stenographer.log"
    path.write_text(_log_line("ERROR", "daemon: startup_failed reason=stale"), encoding="utf-8")
    path.chmod(0o000)
    try:
        status = doctor._log_status("daemon", path)
    finally:
        path.chmod(0o600)

    assert status.size == path.stat().st_size
    assert not status.readable
    assert status.tail == ()
