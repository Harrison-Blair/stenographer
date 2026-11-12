# SPDX-License-Identifier: GPL-3.0-or-later
"""Common CLI test inputs and streams."""

import io

from stenographer.cli.shared.capabilities import Capabilities
from stenographer.cli.shared.console import Console
from stenographer.lib.config.models import Config
from stenographer.lib.platform.host_guidance import HostGuidance

GUIDANCE = HostGuidance(
    capability_labels={},
    capability_fix_hints={},
    clipboard_fix_hints={},
    clipboard_fix_hint_default="enable a pasteboard",
    service_noun="host agent",
    service_name="steno-agent",
    service_installer="steno-agent install",
    service_unknown_detail="cannot query the agent manager",
    service_start_command="steno-agent start",
    service_restart_command="steno-agent restart",
    service_log_command="steno-agent logs -f",
    run_with_config=lambda path: f"STENO_CONFIG={path} stenographer run",
)


def capabilities(**overrides) -> Capabilities:
    fields = {
        "key_injector_ok": True,
        "hotkey_access_ok": True,
        "has_mic": True,
        "model_cached": True,
        "clipboard_ok": True,
        "clipboard_backend": "wl-copy",
        "clipboard_read_ok": True,
        "cue_player": "pw-play",
        "service_enabled": "enabled",
        "service_active": "active",
    }
    fields.update(overrides)
    return Capabilities(**fields)


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def console(answers: str = "") -> Console:
    return Console(io.StringIO(answers), io.StringIO(), io.StringIO())


def document(tmp_path, *, save):
    class Document:
        def __init__(self):
            self.path = tmp_path / "config.toml"
            self.config = Config.defaults()

        def save(self, config):
            return save(config, self.path)

    return Document()
