# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


@dataclass(frozen=True, slots=True)
class HostGuidance:
    """The host's user-facing prose: what the core prints but cannot phrase.

    Everything the CLI shows a user that is true only of one OS lives here —
    capability labels and fix hints, the words for the background service and
    the commands that control it, the config template's hotkey-device comment,
    and the shell syntax for running against an explicit config path. The core
    supplies the sentence frames; the host supplies the clauses.

    ``capability_labels`` and ``capability_fix_hints`` are keyed by the
    semantic ``HostProbe`` / ``capabilities.Capabilities`` field names, so no
    core dict needs a per-OS branch; ``clipboard_fix_hints`` is keyed by the
    backend name the probe reported, with ``clipboard_fix_hint_default`` for a
    backend the host did not anticipate. Commands are printed verbatim.
    """

    capability_labels: Mapping[str, str]
    capability_fix_hints: Mapping[str, str]
    clipboard_fix_hints: Mapping[str, str]
    clipboard_fix_hint_default: str
    service_noun: str
    """What the user-visible background service is called (``doctor``'s row label)."""
    service_name: str
    """The service instance's name, embedded verbatim in core sentence frames."""
    service_installer: str
    """What installs the service; printed after "run" and inside backticks."""
    service_unknown_detail: str
    """Why the service state could not be determined, as a parenthetical clause."""
    service_start_command: str
    service_restart_command: str
    service_log_command: str
    hotkey_device_comment: str
    """The ``hotkey.device`` comment written into the annotated default config."""
    run_with_config: Callable[[str], str]
    """Build the shell line that runs the daemon against an explicit config path."""
