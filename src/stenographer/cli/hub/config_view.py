# SPDX-License-Identifier: GPL-3.0-or-later
"""Validated, conflict-aware configuration editing for the hub."""

from __future__ import annotations

import pathlib
from dataclasses import asdict, replace

from rich.text import Text

from stenographer.cli.hub.selection import append_line
from stenographer.lib.config.document import ConfigDocument
from stenographer.lib.config.errors import ConfigError
from stenographer.lib.config.models import Config
from stenographer.lib.config.save_result import SaveResult

_HELP = {
    "hotkey.binding": "Agent binding for cleanup of agent-directed dictation.",
    "hotkey.device": "Input device for the hotkey; blank uses the system default.",
    "hotkey.cancel_binding": "Global cancel key; blank disables it.",
    "hotkey.mode": "Choose hold, toggle, or hybrid hotkey behavior.",
    "hotkey.hybrid_threshold_seconds": "Press duration that separates a tap from a hold.",
    "hotkey.general_binding": "General binding for ordinary transcript cleanup.",
    "audio.input_device": "Audio input device name or index; blank uses the default.",
    "audio.min_speech_rms": "Ignore audio below this speech energy level; zero disables the gate.",
    "audio.max_recording_seconds": "Maximum length of one recording.",
    "asr.idle_unload_seconds": (
        "Unload the idle recognition worker after this many seconds; zero disables it."
    ),
    "asr.cpu_threads": "Recognition worker CPU threads; zero selects automatically.",
    "live.diarize_mic": (
        "Separate the speakers on the microphone as Room 1, Room 2, and so on; "
        "off labels every microphone line You."
    ),
    "refine.enabled": "Use the local text-refinement service when available.",
    "refine.host": "Refinement service URL. A remote host receives transcript text.",
    "refine.model": "Model name used by the local refinement service.",
    "refine.min_words": "Skip refinement for utterances with fewer words.",
    "refine.structured_output": "Ask the refinement model for structured output.",
    "refine.vocabulary": "Terms that refinement spells exactly as written.",
    "feedback.volume": "Playback volume for feedback sounds.",
    "feedback.mute": "Mute feedback sounds.",
    "feedback.overlay": "Show the best-effort status overlay.",
    "feedback.update_check": "Check for release metadata and show an update notice.",
    "feedback.spectrum_floor_dbfs": "Fixed audio-meter floor in dBFS, or one value per band.",
    "feedback.sound_pack": "Name of the feedback sound pack.",
    "feedback.log_level": "Minimum level for console log messages.",
    "analytics.enabled": (
        "Store local numeric usage history; no audio or transcript text is stored."
    ),
    "analytics.resource_profiling": "Measure local resource use during utterances.",
    "delivery.copy_original": "Copy the original transcript before cleanup.",
    "delivery.restore_clipboard": "Restore the previous clipboard item after delivery.",
    "delivery.restore_delay_ms": "Wait this many milliseconds before restoring the clipboard.",
}


class ConfigEditor:
    """Keep one validated draft and its preserved source document."""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = pathlib.Path(path)
        self.document: ConfigDocument | None = None
        self.error: ConfigError | None = None
        self.config: Config | None = None
        self._saved: Config | None = None
        self._undo: list[Config] = []
        self.shown_keys: frozenset[str] | None = None
        self.key_index = 0
        self.search_term = ""
        try:
            self.document = ConfigDocument.load(self.path)
        except ConfigError as exc:
            self.error = exc
        else:
            self.config = self.document.config
            self._saved = self.config

    @property
    def read_only(self) -> bool:
        return self.config is None

    @property
    def dirty(self) -> bool:
        return self.config is not None and self.config != self._saved

    @property
    def unsaved_change_count(self) -> int:
        if self.config is None or self._saved is None:
            return 0
        current = asdict(self.config)
        saved = asdict(self._saved)
        return sum(
            current[group][key] != saved[group][key] for group in current for key in current[group]
        )

    @property
    def all_keys(self) -> tuple[str, ...]:
        """Return every dotted key in the order of the configuration model."""
        if self.config is None:
            return ()
        return tuple(
            f"{group}.{key}" for group, section in asdict(self.config).items() for key in section
        )

    @property
    def visible_keys(self) -> tuple[str, ...]:
        keys = self.all_keys
        if self.search_term:
            return tuple(key for key in keys if self.search_term.casefold() in key.casefold())
        if self.shown_keys is not None:
            return tuple(key for key in keys if key in self.shown_keys)
        return keys

    @property
    def selected_key(self) -> str | None:
        keys = self.visible_keys
        if not keys:
            return None
        self.key_index = max(0, min(self.key_index, len(keys) - 1))
        return keys[self.key_index]

    def show_keys(self, keys: tuple[str, ...]) -> None:
        """Show only ``keys`` (one settings tab) and select the first one."""
        self.shown_keys = frozenset(keys)
        self.search_term = ""
        self.key_index = 0

    def select(self, dotted_key: str) -> None:
        """Select a shown key; an unknown or hidden key raises ``KeyError``."""
        keys = self.visible_keys
        if dotted_key not in keys:
            raise KeyError(dotted_key)
        self.key_index = keys.index(dotted_key)

    def move_key(self, offset: int) -> None:
        count = len(self.visible_keys)
        if count:
            self.key_index = (self.key_index + offset) % count

    def search(self, term: str) -> bool:
        self.search_term = term.strip()
        self.key_index = 0
        if self.visible_keys:
            return True
        self.search_term = ""
        return False

    def value(self, dotted_key: str) -> object:
        if self.config is None:
            raise RuntimeError("configuration is read-only")
        group, _, key = dotted_key.partition(".")
        return getattr(getattr(self.config, group), key)

    def default(self, dotted_key: str) -> object:
        group, _, key = dotted_key.partition(".")
        return getattr(getattr(Config.defaults(), group), key)

    def help(self, dotted_key: str) -> str:
        return _HELP[dotted_key]

    def edit(self, dotted_key: str, raw_value: str) -> None:
        if self.config is None or self.document is None:
            raise RuntimeError("configuration is read-only")
        group, _, key = dotted_key.partition(".")
        old_value = getattr(getattr(self.config, group), key)
        value = self._parse_value(raw_value, old_value, dotted_key)
        section = replace(getattr(self.config, group), **{key: value})
        candidate = replace(self.config, **{group: section})
        checked = Config.loads(self.document.render(candidate), self.path)
        if checked != self.config:
            self._undo.append(self.config)
            self.config = checked

    def undo(self) -> bool:
        if not self._undo:
            return False
        self.config = self._undo.pop()
        return True

    def reset(self, dotted_key: str) -> None:
        if self.config is None:
            return
        value = self.default(dotted_key)
        if value != self.value(dotted_key):
            group, _, key = dotted_key.partition(".")
            section = replace(getattr(self.config, group), **{key: value})
            candidate = replace(self.config, **{group: section})
            assert self.document is not None
            checked = Config.loads(self.document.render(candidate), self.path)
            self._undo.append(self.config)
            self.config = checked

    def discard(self) -> None:
        if self._saved is not None:
            self.config = self._saved
            self._undo.clear()

    def save(self) -> SaveResult:
        if self.config is None or self.document is None:
            raise RuntimeError("configuration is read-only")
        result = self.document.save(self.config)
        self.document = ConfigDocument.load(self.path)
        self.config = self.document.config
        self._saved = self.config
        self._undo.clear()
        return result

    def render(self) -> Text:
        if self.config is None:
            return Text(
                f"Configuration is invalid and read-only.\n{self.error}\nFix this file: {self.path}"
            )

        lines = Text()
        if self.search_term:
            append_line(lines, f"Search: {self.search_term}")
        keys = self.visible_keys
        if not keys:
            append_line(lines, "No settings match this search.")
        name_width = max((len(key.rpartition(".")[2]) for key in keys), default=0)
        for index, dotted_key in enumerate(keys):
            name = dotted_key.rpartition(".")[2]
            selected = index == self.key_index
            if lines:
                lines.append("\n")
            style = "bold #5fd7ff" if selected else None
            prefix = "▶ " if selected else "  "
            lines.append(prefix + name + " " * (name_width - len(name) + 2), style=style)
            lines.append(self._display(self.value(dotted_key)))
            if self.value(dotted_key) != self.default(dotted_key):
                lines.append(" ")
                lines.append("●", style="#ffaf5f")
        return lines

    def render_selected_help(self) -> Text:
        dotted_key = self.selected_key
        if self.config is None or dotted_key is None:
            return Text()
        name = dotted_key.rpartition(".")[2]
        return Text(
            f"{name}: {self.help(dotted_key)} Default: {self._display(self.default(dotted_key))}"
        )

    @staticmethod
    def _parse_value(raw_value: str, current: object, dotted_key: str) -> object:
        value = raw_value.strip()
        if dotted_key == "feedback.spectrum_floor_dbfs":
            if "," in value:
                return tuple(float(part.strip()) for part in value.split(","))
            return float(value)
        if isinstance(current, bool):
            if value.casefold() not in {"true", "false"}:
                raise ValueError("Enter true or false.")
            return value.casefold() == "true"
        if isinstance(current, int):
            return int(value)
        if isinstance(current, float):
            return float(value)
        if isinstance(current, tuple):
            return tuple(float(part.strip()) for part in value.split(","))
        if current is None:
            return value or None
        return raw_value

    @staticmethod
    def _display(value: object) -> str:
        if value is None:
            return "(unset)"
        if isinstance(value, bool):
            return "on" if value else "off"
        if isinstance(value, tuple):
            return ", ".join(str(item) for item in value)
        return str(value)
