# SPDX-License-Identifier: GPL-3.0-or-later
"""``doctor`` rendering: the human half of the capability gate.

The gate itself — :class:`~stenographer.capabilities.Capabilities`,
``REQUIRED``, :func:`~stenographer.capabilities.probe` and
:func:`~stenographer.capabilities.missing_required` — is core
(``stenographer.capabilities``) because the daemon's startup gate shares it.
What lives here is the report layout: the sentence frames and the pure
:func:`render`, plus :func:`run` for the subcommand. Every host-specific
word in it — capability labels, fix hints, the service noun and its installer
— comes from the platform's :class:`~stenographer.platform.base.HostGuidance`,
so this module carries no Linux prose.

The report also names both log files and replays the daemon log's recent
complaints, so a report can be pasted from one command. Reading a log is the
only I/O this module does on its own: :func:`run` turns each file into a
:class:`LogStatus` — a missing or unreadable log is a fact to print, never a
failure — and the classification (:func:`tail_errors`) and the tolerant decode
(:func:`decode_tail`) stay pure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from stenographer.capabilities import (
    REQUIRED,
    Capabilities,
    OverlayCapability,
    missing_required,
    probe,
)
from stenographer.status import UnavailableReason

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Sequence

    from stenographer.config import Config
    from stenographer.platform.base import HostGuidance

#: Levels worth replaying in the report; DEBUG and INFO are the healthy path.
_TAIL_LEVELS = frozenset({"WARNING", "ERROR", "CRITICAL"})
#: The file sink's format puts the level third, after a two-token ``asctime``.
_LEVEL_COLUMN = 2
#: How much of the log's tail is read. The file rotates at 5 MiB; ten lines
#: live far inside this window, and a report must not load the whole file.
_TAIL_WINDOW_BYTES = 256 * 1024


@dataclass(frozen=True, slots=True)
class LogStatus:
    """One log file as the report sees it: ``size is None`` means absent."""

    name: str
    path: pathlib.Path
    size: int | None
    tail: tuple[str, ...] = ()


def tail_errors(text: str, n: int = 10) -> list[str]:
    """The last *n* WARNING-or-worse lines of *text*, in file order. PURE.

    The level is read from its column, not searched for: a line reporting a
    handled error at INFO is not a complaint, and a WARNING whose message
    happens to name one is. Anything without that column — a traceback's
    continuation lines, or the fragment of a record left at the head of a tail
    window — is not a record and is dropped.
    """
    lines = [line for line in text.splitlines() if _level_of(line) in _TAIL_LEVELS]
    return lines[-n:]


def decode_tail(data: bytes) -> str:
    """Decode a tail window that may begin mid-character. PURE.

    The window is cut at a byte offset, so its first bytes can be the tail of a
    multi-byte character. Replacing them keeps the whole log readable at the
    cost of one glyph in a line that is dropped as a fragment anyway.
    """
    return data.decode("utf-8", errors="replace")


def _level_of(line: str) -> str:
    columns = line.split(maxsplit=_LEVEL_COLUMN + 1)
    return columns[_LEVEL_COLUMN] if len(columns) > _LEVEL_COLUMN else ""


def format_service_status(enabled: str | None, active: str | None, guidance: HostGuidance) -> str:
    """Pure: one-line summary of the host service's state, in the host's words."""
    if enabled is None and active is None:
        return f"unknown ({guidance.service_unknown_detail})"
    if enabled is None:
        return f"not installed — run {guidance.service_installer}"
    return f"{enabled}, {active or 'unknown'}"


def format_overlay_status(capability: OverlayCapability, guidance: HostGuidance) -> str:
    """Pure one-line status for an optional overlay capability."""
    if not capability.enabled:
        return "disabled"
    if capability.backend is not None:
        return guidance.overlay_backend_labels.get(
            capability.backend.value, capability.backend.value
        )
    reason = capability.reason or UnavailableReason.BACKENDS_UNAVAILABLE
    hint = guidance.overlay_fix_hints.get(reason, guidance.overlay_fix_hint_default)
    return f"unavailable — {hint}"


def render(
    caps: Capabilities,
    cfg: Config,
    config_path: pathlib.Path,
    guidance: HostGuidance,
    logs: Sequence[LogStatus],
) -> str:
    """Pure: the doctor report, with an exact fix hint per missing capability.

    *logs* is the already-gathered facts for each log file — :func:`run` does
    the reading, so this stays a function of its arguments.
    """
    lines = [
        f"config: {config_path}",
        f"model: {cfg.asr.model}",
        f"hotkey binding: {cfg.hotkey.binding}",
        "",
    ]
    for name in REQUIRED:
        ok = bool(getattr(caps, name))
        label = guidance.capability_labels[name]
        if name == "clipboard_ok":
            label = f"{label} ({caps.clipboard_backend})"
        line = f"  {label}: {'ok' if ok else 'MISSING'}"
        if not ok:
            hint = (
                guidance.clipboard_fix_hints.get(
                    caps.clipboard_backend, guidance.clipboard_fix_hint_default
                )
                if name == "clipboard_ok"
                else guidance.capability_fix_hints[name]
            )
            line += f" — {hint}"
        lines.append(line)
    player = caps.cue_player or "none (sound cues disabled)"
    lines.append(f"  audio player: {player}")
    service = format_service_status(caps.service_enabled, caps.service_active, guidance)
    lines.append(f"  {guidance.service_noun}: {service}")
    lines.append(f"  overlay: {format_overlay_status(caps.overlay, guidance)}")
    lines.append("")
    lines.append("logs:")
    for log in logs:
        size = "absent" if log.size is None else f"{log.size} bytes"
        lines.append(f"  {log.name}: {log.path} ({size})")
        lines.extend(f"    {line}" for line in log.tail)
    lines.append("")
    missing = missing_required(caps)
    labels = [guidance.capability_labels.get(name, name) for name in missing]
    if missing:
        lines.append(f"missing required capabilities: {', '.join(labels)}")
    else:
        lines.append("all required capabilities present")
    return "\n".join(lines)


def run(cfg: Config, config_path: pathlib.Path) -> int:
    from stenographer.platform import current_platform
    from stenographer.utils.logging_setup import log_paths

    caps = probe(cfg)
    daemon_log, helper_log = log_paths()
    logs = (
        _log_status("daemon", daemon_log, tail=True),
        _log_status("helper", helper_log, tail=False),
    )
    print(render(caps, cfg, config_path, current_platform().guidance(), logs))
    return 78 if missing_required(caps) else 0


def _log_status(name: str, path: pathlib.Path, *, tail: bool) -> LogStatus:
    """Read one log file's facts. A log this process cannot read is "absent"."""
    try:
        size = path.stat().st_size
        if not tail:
            return LogStatus(name, path, size)
        with path.open("rb") as handle:
            handle.seek(max(0, size - _TAIL_WINDOW_BYTES))
            window = handle.read()
    except OSError:
        return LogStatus(name, path, None)
    return LogStatus(name, path, size, tuple(tail_errors(decode_tail(window))))
