# SPDX-License-Identifier: GPL-3.0-or-later
"""Grouped doctor results, model status and privacy-safe warning summaries for the hub."""

from __future__ import annotations

import dataclasses
import pathlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stenographer.lib.config.models import Config

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_EVENT = re.compile(r"([a-z][a-z0-9_-]*):\s+([a-z][a-z0-9_-]*)\b")
_WARNING = re.compile(r"(\d{2}:\d{2}):\d{2} (WARN|ERROR) (\S+: \S+)\Z")
_TAIL_WINDOW_BYTES = 256 * 1024
CHECK_GROUPS = ("input", "engine", "other")
DOCTOR_STATE_GLYPHS = {"ok": "✓", "warn": "!", "fail": "\N{MULTIPLICATION SIGN}"}
DOCTOR_STATE_WORDS = {"ok": "pass", "warn": "warning", "fail": "failure"}
DOCTOR_STATE_TONES = {"ok": "ok", "warn": "warn", "fail": "danger"}
# README D16: a recent warning shows its event token and, for a known token,
# this fixed description. Nothing from the log line itself is shown.
WARNING_DESCRIPTIONS = {
    "analytics: unavailable": "Analytics could not open its database.",
    "asr: job_failed": "A transcription did not finish.",
    "deliver: restore_failed": "The clipboard was not restored after a paste.",
    "feedback: cue_failed": "A sound cue did not play.",
    "files: job_failed": "A file job did not finish.",
    "hotkey: enumerate_failed": "The keyboard devices could not be listed.",
    "hub: doctor_probe_failed": "The checks did not run.",
    "hub: session_job_failed": "A session job did not finish.",
    "hub: setup_test_failed": "A Checks test did not finish.",
    "live: model_load_failed": "A live model did not load.",
    "live: phrase_failed": "One live phrase was not transcribed.",
    "live: relabel_failed": "The speaker relabel pass did not finish.",
    "live: source_start_failed": "A live audio source did not start.",
    "live: system_source_failed": "System audio stopped; the mic went on recording.",
    "overlay: helper_restarting": "The overlay helper stopped and was restarted.",
    "overlay: helper_start_failed": "The overlay helper did not start.",
    "overlay: unavailable": "The overlay is not available on this display.",
    "overlay_helper: display_lost": "The overlay lost its display.",
    "pipeline: delivery_failed": "Dictated text was not delivered.",
    "pipeline: failed": "A dictation did not finish.",
    "pipeline: refine_failed": "Refine failed; the raw text was kept.",
    "recorder: failed": "The microphone recording failed.",
    "refine: warm_failed": "The refine model did not warm up.",
    "worker: request_timeout": "The speech engine did not answer in time.",
    "worker: spawn_failed": "The speech engine did not start.",
    "worker: warmup_failed": "The speech engine did not warm up.",
}
# What each check looks at; the detail pane shows it above the probe result.
_EXPLANATIONS = {
    "key_injector_ok": "Dictation types its text through a virtual keyboard.",
    "hotkey_access_ok": "The hotkey is read from the keyboard devices.",
    "has_mic": "Dictation and recordings read the configured input device.",
    "cue_player": "Sound cues play through a system audio player.",
    "model_cached": "The speech model turns audio into text on this machine.",
    "live_models_cached": "Recordings find speech and speakers with two small models.",
    "refine_service": "Refine sends text to the configured Ollama host to tidy it.",
    "system_capture": "Recordings can capture the system audio through PipeWire.",
    "system_service": "The user service runs the dictation daemon.",
    "ffmpeg": "File jobs read M4A and AAC files through ffmpeg.",
    "python_venv": "The speech model build needs a Python virtual environment.",
    "clipboard_ok": "Dictated text is pasted through the clipboard.",
    "overlay": "The overlay shows the dictation state on the screen.",
    "clipboard_restore": "The clipboard is put back after each paste.",
}


@dataclass(frozen=True)
class DoctorCheck:
    check_id: str
    label: str
    group: str
    status: str
    detail: str
    fix: str
    explanation: str = ""
    path: str = ""

    @property
    def display_group(self) -> str:
        return self.group if self.group in CHECK_GROUPS else "other"


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]
    warnings: tuple[str, ...]
    checked_at: datetime = field(default_factory=lambda: datetime.now().astimezone())

    @property
    def warn_count(self) -> int:
        return sum(check.status == "warn" for check in self.checks)

    @property
    def fail_count(self) -> int:
        return sum(check.status == "fail" for check in self.checks)

    @property
    def ok_count(self) -> int:
        return sum(check.status == "ok" for check in self.checks)

    @property
    def first_issue_index(self) -> int:
        return next(
            (index for index, check in enumerate(self.checks) if check.status in {"fail", "warn"}),
            0,
        )

    def in_group_order(self) -> DoctorReport:
        """Return this report with its checks in the shown group order."""
        checks = sorted(self.checks, key=lambda check: CHECK_GROUPS.index(check.display_group))
        return dataclasses.replace(self, checks=tuple(checks))

    def warning_entries(self) -> tuple[tuple[str, str, str, str], ...]:
        """Return ``(HH:MM, level, token, description)`` for each recent warning."""
        entries = []
        for warning in self.warnings:
            match = _WARNING.fullmatch(warning)
            if match is not None:
                time, level, token = match.groups()
                entries.append((time, level, token, WARNING_DESCRIPTIONS.get(token, "")))
        return tuple(entries)

    def warning_lines(self) -> tuple[str, ...]:
        """Return the recent warnings as plain lines in the allowlisted form."""
        lines = []
        for time, level, token, description in self.warning_entries():
            lines.append(f"{time}  {level:<5}  {token}")
            if description:
                lines.append(f"{'':7}{description}")
        return tuple(lines)

    def report_text(self) -> str:
        lines = [
            f"Checks report: {self.ok_count} pass, {self.warn_count} warn, {self.fail_count} fail"
        ]
        for group in CHECK_GROUPS:
            checks = [check for check in self.checks if check.display_group == group]
            if not checks:
                continue
            lines.append(f"\n{group}")
            for check in checks:
                lines.append(f"{check.status.upper()} {check.label}: {check.detail}")
                if check.fix and check.status != "ok":
                    lines.append(f"Fix: {check.fix}")
        if self.warnings:
            lines.extend(("\nRecent warnings (no transcript text)", *self.warning_lines()))
        return "\n".join(lines)


@dataclass(frozen=True)
class ModelEntry:
    model_id: str
    label: str
    name: str
    present: bool
    size: str


def safe_warning_lines(text: str, limit: int = 10) -> tuple[str, ...]:
    """Keep warning and error event names; omit loggers and arbitrary message fields."""
    warnings = []
    for line in text.splitlines():
        columns = line.split(maxsplit=3)
        if len(columns) != 4 or not _DATE.fullmatch(columns[0]):
            continue
        if columns[2] not in {"WARNING", "ERROR"}:
            continue
        record = re.match(r"(\S+)(?:\s+utt=\d+)?\s+(.+)", columns[3])
        if record is None:
            continue
        event = _EVENT.match(record.group(2))
        if event is None:
            continue
        timestamp = columns[1].split(",", 1)[0]
        level = "WARN" if columns[2] == "WARNING" else "ERROR"
        warnings.append(f"{timestamp} {level} {event[1]}: {event[2]}")
    return tuple(warnings[-limit:])


def recent_warnings(paths: tuple[pathlib.Path, ...], limit: int = 10) -> tuple[str, ...]:
    """Read a bounded tail from each log and return safe recent warning summaries."""
    records: list[tuple[str, str]] = []
    for path in paths:
        try:
            size = path.stat().st_size
            with path.open("rb") as handle:
                handle.seek(max(0, size - _TAIL_WINDOW_BYTES))
                text = handle.read().decode("utf-8", errors="replace")
        except OSError:
            continue
        for raw_line in text.splitlines():
            safe = safe_warning_lines(raw_line, limit=1)
            if safe:
                columns = raw_line.split(maxsplit=1)
                records.append((f"{columns[0]} {columns[1]}", safe[0]))
    return tuple(line for _, line in sorted(records)[-limit:])


def _refine_check(config: Config) -> DoctorCheck:
    """Ask the configured Ollama host for its model list; a metadata-only request."""
    from stenographer.lib.refine.client import installed_model_bytes
    from stenographer.lib.refine.endpoints import host_name

    refine = config.refine
    explanation = _EXPLANATIONS["refine_service"]
    if not refine.enabled:
        return DoctorCheck(
            "refine_service", "refine service", "engine", "ok", "off", "", explanation
        )
    detail = f"{host_name(refine.host)} · {refine.model}"
    if installed_model_bytes(refine.host, refine.model) is None:
        return DoctorCheck(
            "refine_service",
            "refine service",
            "engine",
            "warn",
            f"{detail} not found",
            "Start Ollama on the refine host, then run `stenographer model download --refine`.",
            explanation,
        )
    return DoctorCheck("refine_service", "refine service", "engine", "ok", detail, "", explanation)


def build_report(config: Config, config_path: pathlib.Path | None = None) -> DoctorReport:
    """Probe the host and build the doctor checks in the groups of the Checks tab."""
    import os

    from stenographer.cli.doctor import report as cli_doctor
    from stenographer.cli.shared.capability_probe import probe
    from stenographer.lib.diagnostics import additional_checks
    from stenographer.lib.logging.pipeline import log_paths
    from stenographer.lib.platform import current_platform
    from stenographer.lib.transcribe import bark_download
    from stenographer.overlay.platform import current_platform as overlay_platform
    from stenographer.overlay.protocol.unavailablereason import UnavailableReason

    caps = probe(config)
    host = current_platform().guidance()
    overlay = overlay_platform().guidance()
    data_dir = current_platform().data_dir(os.environ, pathlib.Path.home())
    checks: list[DoctorCheck] = []

    def add(
        check_id: str,
        label: str,
        group: str,
        ok: bool,
        detail: str,
        fix: str,
        *,
        failed: str = "fail",
        path: str = "",
    ) -> None:
        checks.append(
            DoctorCheck(
                check_id,
                label,
                group,
                "ok" if ok else failed,
                detail,
                "" if ok else fix,
                _EXPLANATIONS.get(check_id, ""),
                path,
            )
        )

    def capability_fix(name: str) -> str:
        return host.capability_fix_hints.get(name, "")

    add(
        "key_injector_ok",
        "input access",
        "input",
        caps.key_injector_ok,
        "keyboard injection ok" if caps.key_injector_ok else "keyboard injection unavailable",
        capability_fix("key_injector_ok"),
    )
    add(
        "has_mic",
        "microphone",
        "input",
        caps.has_mic,
        config.audio.input_device or "default input" if caps.has_mic else "no input device",
        capability_fix("has_mic"),
    )
    add(
        "hotkey_access_ok",
        "hotkey",
        "input",
        caps.hotkey_access_ok,
        f"{config.hotkey.binding} · {config.hotkey.mode}"
        if caps.hotkey_access_ok
        else "no hotkey access",
        capability_fix("hotkey_access_ok"),
    )
    add(
        "cue_player",
        "sounds",
        "input",
        caps.cue_player is not None,
        f"pack {config.feedback.sound_pack} · {caps.cue_player}"
        if caps.cue_player
        else "no cue player; sound cues are off",
        "Install a supported cue player, such as pw-play.",
        failed="warn",
    )
    add(
        "model_cached",
        "speech model",
        "engine",
        caps.model_cached,
        bark_download.MODEL_NAME if caps.model_cached else f"{bark_download.MODEL_NAME} missing",
        capability_fix("model_cached"),
        path=str(bark_download.model_dir(data_dir)),
    )
    extra = {check.check_id: check for check in additional_checks.collect_additional_checks()}
    live = extra.pop("live_models_cached")
    add(
        "live_models_cached",
        "voice models",
        "engine",
        live.status == "ok",
        live.detail,
        live.fix,
        failed="warn",
        path=str(data_dir / "models" / "live"),
    )
    checks.append(_refine_check(config))
    capture = extra.pop("system_capture")
    add(
        "system_capture",
        "system audio",
        "engine",
        capture.status == "ok",
        capture.detail,
        capture.fix,
        failed="warn",
    )
    service_ok = caps.service_active == "active"
    add(
        "system_service",
        "system service",
        "engine",
        service_ok,
        cli_doctor.format_service_status(caps.service_enabled, caps.service_active, host),
        host.service_start_command if caps.service_enabled is not None else host.service_installer,
        failed="warn",
    )
    for check in extra.values():
        add(
            check.check_id,
            {"python_venv": "python venv"}.get(check.check_id, check.check_id),
            "other",
            check.status == "ok",
            check.detail,
            check.fix,
            failed="warn",
        )
    add(
        "clipboard_ok",
        f"clipboard · {caps.clipboard_backend}",
        "other",
        caps.clipboard_ok,
        "available" if caps.clipboard_ok else f"{caps.clipboard_backend} is unavailable",
        host.clipboard_fix_hints.get(caps.clipboard_backend, host.clipboard_fix_hint_default),
    )
    overlay_reason = caps.overlay.reason or UnavailableReason.BACKENDS_UNAVAILABLE
    add(
        "overlay",
        "overlay",
        "other",
        not caps.overlay.enabled or caps.overlay.backend is not None,
        cli_doctor.format_overlay_status(caps.overlay, overlay),
        overlay.overlay_fix_hints.get(overlay_reason, overlay.overlay_fix_hint_default),
        failed="warn",
    )
    add(
        "clipboard_restore",
        "clipboard restore",
        "other",
        not config.delivery.restore_clipboard or caps.clipboard_read_ok,
        cli_doctor.format_clipboard_restore_status(caps, config, host),
        host.clipboard_read_fix_hints.get(caps.clipboard_backend, host.clipboard_fix_hint_default),
        failed="warn",
    )
    daemon_log, helper_log = log_paths()
    warnings = recent_warnings((daemon_log, helper_log))
    return DoctorReport(tuple(checks), warnings)


def default_log_opener(path: pathlib.Path) -> bool:
    """Open a log file in the user's configured desktop handler."""
    import webbrowser

    if not path.exists():
        return False
    return webbrowser.open(path.as_uri())


def default_model_status() -> tuple[ModelEntry, ...]:
    """Return the speech model and each live model, present or missing on disk."""
    import os

    from stenographer.cli.model.download.handler import ASR_SIZE_TEXT
    from stenographer.lib.live.models import LIVE_MODELS
    from stenographer.lib.platform import current_platform
    from stenographer.lib.transcribe import bark_download

    live_dir = current_platform().data_dir(os.environ, pathlib.Path.home()) / "models" / "live"
    names = {"silero_vad.onnx": "vad", "nemo_en_titanet_small.onnx": "speaker"}
    labels = {"vad": "voice activity", "speaker": "speaker model"}
    sizes = {"vad": "about 0.6 MB", "speaker": "about 40 MB"}
    entries = [
        ModelEntry(
            "asr",
            "speech model",
            bark_download.MODEL_NAME,
            bark_download.is_model_cached(),
            ASR_SIZE_TEXT,
        )
    ]
    for model in LIVE_MODELS:
        model_id = names[model.filename]
        entries.append(
            ModelEntry(
                model_id,
                labels[model_id],
                model.filename,
                (live_dir / model.filename).is_file(),
                sizes[model_id],
            )
        )
    return tuple(entries)


def default_model_download(model_id: str) -> None:
    """Fetch one model, as ``stenographer model download`` does for it."""
    import os

    from stenographer.lib.live.download import download_live_models
    from stenographer.lib.live.models import LIVE_MODELS
    from stenographer.lib.platform import current_platform
    from stenographer.lib.transcribe.bark_download import download_bark_pro

    data_dir = current_platform().data_dir(os.environ, pathlib.Path.home())
    if model_id == "asr":
        download_bark_pro(data_dir)
        return
    filename = {"vad": "silero_vad.onnx", "speaker": "nemo_en_titanet_small.onnx"}[model_id]
    download_live_models(data_dir, models=tuple(m for m in LIVE_MODELS if m.filename == filename))
