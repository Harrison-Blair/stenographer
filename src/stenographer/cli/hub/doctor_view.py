# SPDX-License-Identifier: GPL-3.0-or-later
"""Grouped doctor results and privacy-safe warning summaries for the hub."""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from rich.text import Text

from stenographer.cli.hub.selection import append_line

if TYPE_CHECKING:
    from stenographer.lib.config.models import Config

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_EVENT = re.compile(r"([a-z][a-z0-9_-]*):\s+([a-z][a-z0-9_-]*)\b")
_TAIL_WINDOW_BYTES = 256 * 1024
DOCTOR_STATE_GLYPHS = {"ok": "✓", "warn": "!", "fail": "✗"}
DOCTOR_STATE_COLORS = {"ok": "#6ee69a", "warn": "#ffaf5f", "fail": "#ff5f5f"}


@dataclass(frozen=True)
class DoctorCheck:
    check_id: str
    label: str
    group: str
    status: str
    detail: str
    fix: str


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

    def sidebar_summary(self) -> Text:
        """Render the diagnostic counts and the time of this check."""
        return Text(
            "summary\n"
            f"{self.ok_count} ok · {self.warn_count} warn\n"
            f"{self.fail_count} fail\n"
            f"checked {self.checked_at:%H:%M}"
        )

    @property
    def first_issue_index(self) -> int:
        return next(
            (index for index, check in enumerate(self.checks) if check.status in {"fail", "warn"}),
            0,
        )

    def render(self, *, selected_index: int = 0, details: bool = False) -> Text:
        lines = Text()
        append_line(
            lines,
            f"{self.ok_count} ok · {self.warn_count} warn · {self.fail_count} fail",
        )
        append_line(lines, "")
        for group in ("input and audio", "engine and desktop"):
            append_line(lines, f"┤ {group} ├")
            for index, check in enumerate(self.checks):
                if check.group != group:
                    continue
                status = DOCTOR_STATE_GLYPHS[check.status]
                if lines:
                    lines.append("\n")
                selected = index == selected_index
                style = "bold #5fd7ff" if selected else None
                lines.append("▶ " if selected else "  ", style=style)
                lines.append(status, style=DOCTOR_STATE_COLORS[check.status])
                lines.append(f" {check.label} · {check.detail}", style=style)
            append_line(lines, "")
        selected = self.checks[selected_index] if self.checks else None
        if details and selected is not None and selected.status in {"warn", "fail"}:
            append_line(lines, selected.label)
            append_line(lines, f"Detail: {selected.detail}")
            if selected.fix:
                append_line(lines, f"Fix: {selected.fix}")
            append_line(lines, "")
        if self.warnings:
            append_line(lines, "Recent warnings · log")
            for warning in self.warnings:
                append_line(lines, warning)
        append_line(
            lines,
            "r re-check   enter details   f fix in Setup   l open log   c copy report",
        )
        return lines

    def report_text(self) -> str:
        lines = [
            f"Doctor report: {self.ok_count} ok, {self.warn_count} warn, {self.fail_count} fail"
        ]
        for group in ("input and audio", "engine and desktop"):
            lines.append(f"\n{group}")
            for check in self.checks:
                if check.group != group:
                    continue
                lines.append(f"{check.status.upper()} {check.label}: {check.detail}")
                if check.fix:
                    lines.append(f"Fix: {check.fix}")
        if self.warnings:
            lines.extend(("\nRecent warnings", *self.warnings))
        return "\n".join(lines)


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


def build_report(config: Config, config_path: pathlib.Path | None = None) -> DoctorReport:
    """Probe the host and build the same required and optional doctor checks."""
    from stenographer.cli.doctor import report as cli_doctor
    from stenographer.cli.shared.capability_probe import probe
    from stenographer.lib.diagnostics import additional_checks
    from stenographer.lib.logging.pipeline import log_paths
    from stenographer.lib.platform import current_platform
    from stenographer.overlay.platform import current_platform as overlay_platform
    from stenographer.overlay.protocol.unavailablereason import UnavailableReason

    caps = probe(config)
    host = current_platform().guidance()
    overlay = overlay_platform().guidance()
    checks: list[DoctorCheck] = []

    def add_capability(name: str, label: str, group: str) -> None:
        ok = bool(getattr(caps, name))
        if ok:
            fix = ""
            detail = "available"
        elif name == "clipboard_ok":
            fix = host.clipboard_fix_hints.get(
                caps.clipboard_backend, host.clipboard_fix_hint_default
            )
            detail = f"{caps.clipboard_backend} is unavailable"
        else:
            fix = host.capability_fix_hints.get(name, "")
            detail = "not available"
        checks.append(DoctorCheck(name, label, group, "ok" if ok else "fail", detail, fix))

    for name in ("key_injector_ok", "hotkey_access_ok", "has_mic"):
        add_capability(name, host.capability_labels[name], "input and audio")
    for check in additional_checks.collect_additional_checks():
        group = "input and audio" if check.check_id == "system_capture" else "engine and desktop"
        label = {
            "system_capture": "system capture",
            "live_models_cached": "live models cached",
            "ffmpeg": "ffmpeg",
        }.get(check.check_id, check.check_id)
        checks.append(
            DoctorCheck(
                check.check_id,
                label,
                group,
                "ok" if check.status == "ok" else "warn",
                check.detail,
                check.fix,
            )
        )
    checks.append(
        DoctorCheck(
            "cue_player",
            "audio player",
            "input and audio",
            "ok" if caps.cue_player else "warn",
            caps.cue_player or "sound cues disabled",
            "Install a supported cue player, such as pw-play.",
        )
    )
    add_capability("model_cached", f"ASR model cached · {config.asr.model}", "engine and desktop")
    add_capability("clipboard_ok", f"clipboard · {caps.clipboard_backend}", "engine and desktop")
    service_detail = cli_doctor.format_service_status(
        caps.service_enabled, caps.service_active, host
    )
    service_ok = caps.service_active == "active"
    service_fix = (
        ""
        if service_ok
        else host.service_start_command
        if caps.service_enabled is not None
        else host.service_installer
    )
    checks.append(
        DoctorCheck(
            "system_service",
            host.service_noun,
            "engine and desktop",
            "ok" if service_ok else "warn",
            service_detail,
            service_fix,
        )
    )
    overlay_detail = cli_doctor.format_overlay_status(caps.overlay, overlay)
    overlay_ok = not caps.overlay.enabled or caps.overlay.backend is not None
    overlay_reason = caps.overlay.reason or UnavailableReason.BACKENDS_UNAVAILABLE
    overlay_fix = overlay.overlay_fix_hints.get(overlay_reason, overlay.overlay_fix_hint_default)
    checks.append(
        DoctorCheck(
            "overlay",
            "overlay",
            "engine and desktop",
            "ok" if overlay_ok else "warn",
            overlay_detail,
            overlay_fix if not overlay_ok else "",
        )
    )
    restore_detail = cli_doctor.format_clipboard_restore_status(caps, config, host)
    restore_ok = not config.delivery.restore_clipboard or caps.clipboard_read_ok
    checks.append(
        DoctorCheck(
            "clipboard_restore",
            "clipboard restore",
            "engine and desktop",
            "ok" if restore_ok else "warn",
            restore_detail,
            host.clipboard_read_fix_hints.get(
                caps.clipboard_backend, host.clipboard_fix_hint_default
            )
            if not restore_ok
            else "",
        )
    )
    daemon_log, helper_log = log_paths()
    warnings = recent_warnings((daemon_log, helper_log))
    return DoctorReport(tuple(checks), warnings)


def default_log_opener() -> bool:
    """Open the daemon log in the user's configured desktop handler."""
    import webbrowser

    from stenographer.lib.logging.pipeline import log_paths

    path, _ = log_paths()
    if not path.exists():
        return False
    return webbrowser.open(path.as_uri())
