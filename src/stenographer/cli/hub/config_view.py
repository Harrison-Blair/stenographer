# SPDX-License-Identifier: GPL-3.0-or-later
"""Validated, conflict-aware configuration editing for the hub, with row metadata."""

from __future__ import annotations

import pathlib
from dataclasses import asdict, replace

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
    "asr.idle_unload_seconds": "seconds before the idle worker unloads · 0 never",
    "asr.cpu_threads": "0 = automatic",
    "live.diarize_mic": (
        "Separate the speakers on the microphone as Room 1, Room 2, and so on; "
        "off labels every microphone line You."
    ),
    "refine.enabled": "local text cleanup after each utterance",
    "refine.host": "a remote host receives transcript text",
    "refine.model": "the model name of the local refine service",
    "refine.min_words": "shorter utterances skip refine",
    "refine.structured_output": "ask the model for structured output",
    "refine.vocabulary": "terms spelled this way by refine",
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
_LABELS = {
    "hotkey.binding": "Agent key",
    "hotkey.device": "Hotkey device",
    "hotkey.cancel_binding": "Cancel key",
    "hotkey.mode": "Hotkey mode",
    "hotkey.hybrid_threshold_seconds": "Hold threshold",
    "hotkey.general_binding": "General key",
    "audio.input_device": "Microphone",
    "audio.min_speech_rms": "Minimum speech level",
    "audio.max_recording_seconds": "Longest recording",
    "asr.idle_unload_seconds": "Idle unload",
    "asr.cpu_threads": "CPU threads",
    "live.diarize_mic": "Separate room speakers",
    "refine.enabled": "Refine",
    "refine.host": "Host",
    "refine.model": "Model",
    "refine.min_words": "Minimum words",
    "refine.structured_output": "Structured output",
    "refine.vocabulary": "Vocabulary",
    "feedback.volume": "Volume",
    "feedback.mute": "Mute sounds",
    "feedback.overlay": "Overlay",
    "feedback.update_check": "Update check",
    "feedback.spectrum_floor_dbfs": "Meter floor dBFS",
    "feedback.sound_pack": "Sound pack",
    "feedback.log_level": "Log level",
    "analytics.enabled": "Usage history",
    "analytics.resource_profiling": "Resource profiling",
    "delivery.copy_original": "Copy original",
    "delivery.restore_clipboard": "Restore clipboard",
    "delivery.restore_delay_ms": "Restore delay",
}
_UNITS = {
    "hotkey.hybrid_threshold_seconds": "s",
    "audio.max_recording_seconds": "s",
    "asr.idle_unload_seconds": "s",
    "delivery.restore_delay_ms": "ms",
}
_CHOICES = {
    "hotkey.mode": ("hold", "toggle", "hybrid"),
    "feedback.log_level": ("debug", "info", "warning", "error"),
}
_DEVICE_KEYS = frozenset({"audio.input_device", "hotkey.device"})
# Keys whose value is not a single number although the default is one.
_TEXT_KEYS = frozenset({"feedback.spectrum_floor_dbfs"})


class ConfigEditor:
    """Keep one validated draft, its saved twin and its preserved source document."""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = pathlib.Path(path)
        self.document: ConfigDocument | None = None
        self.error: ConfigError | None = None
        self.config: Config | None = None
        self._saved: Config | None = None
        self._undo: list[Config] = []
        self.shown_keys: tuple[str, ...] | None = None
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
        return sum(self.is_changed(key) for key in self.all_keys)

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
        """Return the search matches of every tab, else the shown keys in their order."""
        if self.search_term:
            term = self.search_term.casefold()
            return tuple(
                key
                for key in self.all_keys
                if term in key.casefold() or term in self.label(key).casefold()
            )
        if self.shown_keys is not None:
            return self.shown_keys
        return self.all_keys

    @property
    def selected_key(self) -> str | None:
        keys = self.visible_keys
        if not keys:
            return None
        self.key_index = max(0, min(self.key_index, len(keys) - 1))
        return keys[self.key_index]

    def show_keys(self, keys: tuple[str, ...]) -> None:
        """Show only ``keys`` (one settings tab) in order and select the first one."""
        self.shown_keys = tuple(keys)
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
        """Show the keys of every tab whose name matches; false keeps the tab."""
        self.search_term = term.strip()
        self.key_index = 0
        if self.search_term and self.visible_keys:
            return True
        self.search_term = ""
        return False

    def clear_search(self) -> bool:
        if not self.search_term:
            return False
        self.search_term = ""
        self.key_index = 0
        return True

    def value(self, dotted_key: str) -> object:
        if self.config is None:
            raise RuntimeError("configuration is read-only")
        return self._get(self.config, dotted_key)

    def saved_value(self, dotted_key: str) -> object:
        if self._saved is None:
            raise RuntimeError("configuration is read-only")
        return self._get(self._saved, dotted_key)

    def default(self, dotted_key: str) -> object:
        return self._get(Config.defaults(), dotted_key)

    def is_changed(self, dotted_key: str) -> bool:
        """Return whether the draft value differs from the saved file."""
        if self.config is None or self._saved is None:
            return False
        return self.value(dotted_key) != self.saved_value(dotted_key)

    def help(self, dotted_key: str) -> str:
        return _HELP[dotted_key]

    def label(self, dotted_key: str) -> str:
        return _LABELS[dotted_key]

    def unit(self, dotted_key: str) -> str:
        return _UNITS.get(dotted_key, "")

    def kind(self, dotted_key: str) -> str:
        """Return the control of a key: toggle, number, text, choice, device or list."""
        if dotted_key == "refine.vocabulary":
            return "list"
        if dotted_key in _DEVICE_KEYS:
            return "device"
        if dotted_key in _CHOICES or dotted_key == "feedback.sound_pack":
            return "choice"
        default = self.default(dotted_key)
        if isinstance(default, bool):
            return "toggle"
        if isinstance(default, int | float) and dotted_key not in _TEXT_KEYS:
            return "number"
        return "text"

    def choices(self, dotted_key: str) -> tuple[str, ...]:
        """Return the allowed values of a choice key; the current value is always one."""
        if dotted_key == "feedback.sound_pack":
            from stenographer.lib.sounds.packs import discover_sound_packs

            values = discover_sound_packs(self.path.parent)
        else:
            values = _CHOICES[dotted_key]
        current = str(self.value(dotted_key))
        return values if current in values else (*values, current)

    def backups(self) -> tuple[pathlib.Path, ...]:
        """Return the timestamped backups of the config file, oldest first."""
        found = self.path.parent.glob(f"{self.path.name}.bak-*")
        return tuple(sorted(found, key=lambda path: path.name))

    def edit(self, dotted_key: str, raw_value: str) -> None:
        if self.config is None or self.document is None:
            raise RuntimeError("configuration is read-only")
        old_value = self.value(dotted_key)
        self.set_value(dotted_key, self._parse_value(raw_value, old_value, dotted_key))

    def set_value(self, dotted_key: str, value: object) -> None:
        """Validate the draft with ``value``; a change becomes one undo step."""
        checked = self._checked(dotted_key, value)
        if checked != self.config:
            self._undo.append(self.config)
            self.config = checked

    def check_vocabulary(self, terms: tuple[str, ...]) -> tuple[str, ...]:
        """Return the terms as the config reads them, or raise ``ConfigError``."""
        trimmed = tuple(term.strip() for term in terms)
        return self._checked("refine.vocabulary", trimmed).refine.vocabulary

    def undo(self) -> bool:
        if not self._undo:
            return False
        self.config = self._undo.pop()
        return True

    def reset(self, dotted_key: str) -> None:
        if self.config is not None:
            self.set_value(dotted_key, self.default(dotted_key))

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

    def error_text(self) -> str:
        return f"Configuration is invalid and read-only.\n{self.error}\nFix this file: {self.path}"

    def _checked(self, dotted_key: str, value: object) -> Config:
        if self.config is None or self.document is None:
            raise RuntimeError("configuration is read-only")
        group, _, key = dotted_key.partition(".")
        section = replace(getattr(self.config, group), **{key: value})
        candidate = replace(self.config, **{group: section})
        return Config.loads(self.document.render(candidate), self.path)

    @staticmethod
    def _get(config: Config, dotted_key: str) -> object:
        group, _, key = dotted_key.partition(".")
        return getattr(getattr(config, group), key)

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
    def format_value(value: object) -> str:
        if value is None:
            return "(unset)"
        if isinstance(value, bool):
            return "on" if value else "off"
        if isinstance(value, tuple):
            return ", ".join(str(item) for item in value)
        return str(value)
