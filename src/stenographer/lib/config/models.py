# SPDX-License-Identifier: GPL-3.0-or-later
"""Frozen configuration sections and their validated aggregate."""

from __future__ import annotations

import pathlib
import tomllib
from dataclasses import asdict, dataclass, fields
from itertools import combinations

from stenographer.lib.config.constants import (
    ALLOWED_HOTKEY_MODES,
    ALLOWED_LOG_LEVELS,
    DEFAULT_SOUND_PACK,
    MAX_REFINE_WORDS,
    MAX_RESTORE_DELAY_MS,
    MAX_SPECTRUM_FLOOR_DBFS,
    MAX_VOCABULARY_TERM_CHARS,
    MAX_VOCABULARY_TERMS,
    MIN_REFINE_WORDS,
    MIN_SPECTRUM_FLOOR_DBFS,
    SOUND_PACK_PATTERN,
    SpectrumFloor,
)
from stenographer.lib.config.errors import ConfigError
from stenographer.lib.contracts.constants import SPECTRUM_BANDS
from stenographer.lib.hotkey.binding import parse_binding
from stenographer.lib.hotkey.errors import BindingError
from stenographer.lib.hotkey.keycodes import CODE_NAMES, KEY_CODES
from stenographer.lib.platform import current_platform
from stenographer.lib.refine.endpoints import validated_host
from stenographer.lib.refine.prompt import DEFAULT_MODEL, DEFAULT_STRUCTURED_OUTPUT


@dataclass(frozen=True)
class HotkeyConfig:
    """Shared trigger behavior with one binding per built-in refine profile.

    ``binding`` retains its historic name for configuration compatibility. It
    is the Agent binding; old partial configurations therefore acquire the
    universal default profile without a migration.
    """

    binding: str = "KEY_RIGHTCTRL"
    device: str | None = None
    cancel_binding: str | None = "KEY_ESC"
    mode: str = "hybrid"
    hybrid_threshold_seconds: float = 0.5
    general_binding: str = "KEY_RIGHTALT"


@dataclass(frozen=True)
class AudioConfig:
    input_device: str | None = None
    min_speech_rms: float = 0.0005
    max_recording_seconds: int = 600


@dataclass(frozen=True)
class AsrConfig:
    idle_unload_seconds: int = 900
    cpu_threads: int = 0


@dataclass(frozen=True)
class FeedbackConfig:
    volume: float = 0.6
    mute: bool = False
    overlay: bool = True
    update_check: bool = True
    spectrum_floor_dbfs: SpectrumFloor = -45.0
    sound_pack: str = DEFAULT_SOUND_PACK
    log_level: str = "info"


@dataclass(frozen=True)
class RefineConfig:
    """The local-model cleanup pass. On by default, loopback by default."""

    enabled: bool = True
    host: str = "http://127.0.0.1:11434"
    model: str = DEFAULT_MODEL
    min_words: int = 10
    structured_output: bool = DEFAULT_STRUCTURED_OUTPUT
    vocabulary: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeliveryConfig:
    """The clipboard around a paste: the Agent original copy and the restore."""

    copy_original: bool = True
    restore_clipboard: bool = True
    restore_delay_ms: int = 500


@dataclass(frozen=True)
class LiveConfig:
    """Live-session options; mic diarization separates the speakers in one room."""

    diarize_mic: bool = False


@dataclass(frozen=True)
class AnalyticsConfig:
    enabled: bool = True
    resource_profiling: bool = True


@dataclass(frozen=True)
class Config:
    hotkey: HotkeyConfig = HotkeyConfig()
    audio: AudioConfig = AudioConfig()
    asr: AsrConfig = AsrConfig()
    feedback: FeedbackConfig = FeedbackConfig()
    refine: RefineConfig = RefineConfig()
    analytics: AnalyticsConfig = AnalyticsConfig()
    delivery: DeliveryConfig = DeliveryConfig()
    live: LiveConfig = LiveConfig()

    @classmethod
    def defaults(cls) -> Config:
        return cls()

    @classmethod
    def load(cls, path: pathlib.Path) -> Config:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as e:
            raise ConfigError(path, "<file>", f"cannot read: {e}") from e
        except UnicodeDecodeError as e:
            raise ConfigError(path, "<file>", f"cannot decode as UTF-8: {e}") from e

        return cls.loads(content, path)

    @classmethod
    def loads(cls, content: str, path: pathlib.Path = pathlib.Path("<memory>")) -> Config:
        """Load and validate TOML already held in memory."""

        try:
            raw = tomllib.loads(content)
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(path, "<toml>", f"malformed TOML: {e}") from e
        table = raw.get("stenographer", {})
        if not isinstance(table, dict):
            raise ConfigError(path, "stenographer", f"must be a table, got {type(table).__name__}")
        merged = _merge(asdict(cls.defaults()), table)
        _migrate_hotkey_defaults(merged, table, path)
        for field in fields(cls):
            name = field.name
            if not isinstance(merged[name], dict):
                raise ConfigError(path, name, f"must be a table, got {type(merged[name]).__name__}")
        return cls(
            hotkey=_build_hotkey(merged["hotkey"], path),
            audio=_build_audio(merged["audio"], path),
            asr=_build_asr(merged["asr"], path),
            feedback=_build_feedback(merged["feedback"], path),
            refine=_build_refine(merged["refine"], path),
            analytics=_build_analytics(merged["analytics"], path),
            delivery=_build_delivery(merged["delivery"], path),
            live=_build_live(merged["live"], path),
        )


@dataclass(frozen=True)
class _Reader:
    """Typed accessors over one TOML table, raising a dotted ConfigError."""

    table: dict
    path: pathlib.Path
    prefix: str

    def _err(self, key: str, reason: str) -> ConfigError:
        return ConfigError(self.path, f"{self.prefix}.{key}", reason)

    def str(self, key: str) -> str:
        value = self.table.get(key)
        if not isinstance(value, str):
            raise self._err(key, f"expected string, got {type(value).__name__}: {value!r}")
        return value

    def bool(self, key: str) -> bool:
        value = self.table.get(key)
        if not isinstance(value, bool):
            raise self._err(key, f"expected bool, got {type(value).__name__}: {value!r}")
        return value

    def optional_str(self, key: str) -> str | None:
        value = self.table.get(key)
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise self._err(key, f"expected string, got {type(value).__name__}: {value!r}")
        return value

    def str_list(self, key: str) -> list[str]:
        """A TOML array of strings; the tuple is a merged dataclass default."""
        value = self.table.get(key)
        if not isinstance(value, list | tuple):
            raise self._err(key, f"expected a list of strings, got {type(value).__name__}")
        for position, item in enumerate(value, start=1):
            if not isinstance(item, str):
                raise self._err(key, f"term {position} must be a string, got {type(item).__name__}")
        return list(value)

    def _in_range(self, key: str, value: float, lo: float, hi: float) -> None:
        if not lo <= value <= hi:
            raise self._err(key, f"must be in [{lo}, {hi}], got {value}")

    def ranged_int(self, key: str, lo: int, hi: int) -> int:
        value = self.table.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise self._err(key, f"expected int, got {type(value).__name__}: {value!r}")
        self._in_range(key, value, lo, hi)
        return value

    def ranged_number(self, key: str, lo: float, hi: float) -> float:
        value = self.table.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise self._err(key, f"expected number, got {type(value).__name__}: {value!r}")
        self._in_range(key, value, lo, hi)
        return float(value)

    def choice(self, key: str, allowed: frozenset[str]) -> str:
        value = self.str(key)
        if value not in allowed:
            raise self._err(key, f"must be one of {sorted(allowed)}, got {value!r}")
        return value

    def folded_choice(self, key: str, allowed: frozenset[str]) -> str:
        """A choice matched case-insensitively; the canonical lower-case name is kept."""
        raw = self.str(key)
        value = raw.casefold()
        if value not in allowed:
            raise self._err(key, f"must be one of {sorted(allowed)}, got {raw!r}")
        return value

    def spectrum_floor(self, key: str) -> SpectrumFloor:
        value = self.table.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool):
            floor = float(value)
            if MIN_SPECTRUM_FLOOR_DBFS <= floor <= MAX_SPECTRUM_FLOOR_DBFS:
                return floor
            raise self._err(
                key,
                f"must be in [{MIN_SPECTRUM_FLOOR_DBFS}, {MAX_SPECTRUM_FLOOR_DBFS}], got {value}",
            )
        if not isinstance(value, list) or len(value) != SPECTRUM_BANDS:
            raise self._err(key, f"expected a number or exactly {SPECTRUM_BANDS} numbers")
        floors: list[float] = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, int | float):
                raise self._err(key, f"expected a number or exactly {SPECTRUM_BANDS} numbers")
            floor = float(item)
            if not MIN_SPECTRUM_FLOOR_DBFS <= floor <= MAX_SPECTRUM_FLOOR_DBFS:
                raise self._err(
                    key,
                    f"each band must be in "
                    f"[{MIN_SPECTRUM_FLOOR_DBFS}, {MAX_SPECTRUM_FLOOR_DBFS}], got {item}",
                )
            floors.append(floor)
        return tuple(floors)


def _build_hotkey(table: dict, path: pathlib.Path) -> HotkeyConfig:
    r = _Reader(table, path, "hotkey")
    binding = r.str("binding")
    if not binding:
        raise ConfigError(path, "hotkey.binding", "must be non-empty")
    general_binding = r.str("general_binding")
    if not general_binding:
        raise ConfigError(path, "hotkey.general_binding", "must be non-empty")
    cancel_binding = r.optional_str("cancel_binding")
    keys = current_platform().keys()
    for name, value in (
        ("binding", binding),
        ("general_binding", general_binding),
        ("cancel_binding", cancel_binding),
    ):
        if value is not None:
            try:
                parse_binding(value, keys)
            except BindingError as exc:
                raise ConfigError(
                    path, f"hotkey.{name}", str(exc).removeprefix("hotkey.binding: ")
                ) from exc
    _validate_binding_overlap(path, binding, general_binding, cancel_binding)
    return HotkeyConfig(
        binding,
        r.optional_str("device"),
        cancel_binding,
        r.choice("mode", ALLOWED_HOTKEY_MODES),
        r.ranged_number("hybrid_threshold_seconds", 0.05, 5.0),
        general_binding,
    )


def _binding_tokens(binding: str) -> frozenset[tuple[str, int | str]]:
    tokens = []
    for raw in binding.split("+"):
        token = raw.strip().upper()
        if not token:
            continue
        code = KEY_CODES.get(token)
        tokens.append(("code", code) if code is not None else ("name", token.casefold()))
    return frozenset(tokens)


def _validate_binding_overlap(
    path: pathlib.Path,
    agent: str,
    general: str,
    cancel: str | None,
) -> None:
    """Reject equal/subset chords whose edges cannot be selected unambiguously."""

    bindings = [("binding", agent), ("general_binding", general)]
    if cancel is not None:
        bindings.append(("cancel_binding", cancel))
    parsed = [(name, _binding_tokens(value)) for name, value in bindings]
    for index, (left_name, left) in enumerate(parsed):
        for right_name, right in parsed[index + 1 :]:
            if left <= right or right <= left:
                raise ConfigError(
                    path,
                    f"hotkey.{right_name}",
                    f"overlap with hotkey.{left_name}: equal/subset chords are ambiguous",
                )


def _migrate_hotkey_defaults(merged: dict, overlay: dict, path: pathlib.Path) -> None:
    """Give old partial configs a non-conflicting General chord.

    Before profiles, ``binding`` could itself be Right Alt. Keep it as the
    Agent binding after upgrade. If no explicit General binding exists, select
    the normal Right Alt default unless it overlaps Agent or cancel. Then use
    the first conservative fallback.
    """

    raw_hotkey = overlay.get("hotkey")
    if not isinstance(raw_hotkey, dict) or "general_binding" in raw_hotkey:
        return
    hotkey = merged["hotkey"]
    occupied = [
        _binding_tokens(value)
        for value in (hotkey.get("binding"), hotkey.get("cancel_binding"))
        if isinstance(value, str) and value
    ]
    preferred = (
        "KEY_RIGHTALT",
        "KEY_RIGHTCTRL",
        *(f"KEY_F{number}" for number in range(12, 0, -1)),
    )
    canonical = tuple(
        name for _code, name in sorted(CODE_NAMES.items()) if name.startswith(("KEY_", "BTN_"))
    )
    candidates = tuple(dict.fromkeys((*preferred, *canonical)))
    for size in (1, 2):
        for names in combinations(candidates, size):
            candidate = "+".join(names)
            chord = _binding_tokens(candidate)
            if all(not (chord <= other or other <= chord) for other in occupied):
                hotkey["general_binding"] = candidate
                return
    raise ConfigError(
        path,
        "hotkey.general_binding",
        "no non-overlapping implicit General binding is available; configure one explicitly",
    )


def _build_audio(table: dict, path: pathlib.Path) -> AudioConfig:
    r = _Reader(table, path, "audio")
    return AudioConfig(
        r.optional_str("input_device"),
        r.ranged_number("min_speech_rms", 0.0, 1.0),
        r.ranged_int("max_recording_seconds", 1, 86400),
    )


def _build_asr(table: dict, path: pathlib.Path) -> AsrConfig:
    r = _Reader(table, path, "asr")
    return AsrConfig(
        idle_unload_seconds=r.ranged_int("idle_unload_seconds", 0, 86400),
        cpu_threads=r.ranged_int("cpu_threads", 0, 64),
    )


def _build_feedback(table: dict, path: pathlib.Path) -> FeedbackConfig:
    r = _Reader(table, path, "feedback")
    sound_pack = r.str("sound_pack")
    if SOUND_PACK_PATTERN.fullmatch(sound_pack) is None:
        raise ConfigError(
            path,
            "feedback.sound_pack",
            "must match [a-z0-9][a-z0-9-]{0,63}",
        )
    return FeedbackConfig(
        volume=r.ranged_number("volume", 0.0, 1.0),
        mute=r.bool("mute"),
        overlay=r.bool("overlay"),
        update_check=r.bool("update_check"),
        spectrum_floor_dbfs=r.spectrum_floor("spectrum_floor_dbfs"),
        sound_pack=sound_pack,
        log_level=r.folded_choice("log_level", ALLOWED_LOG_LEVELS),
    )


def _build_refine(table: dict, path: pathlib.Path) -> RefineConfig:
    r = _Reader(table, path, "refine")
    raw_host = r.str("host")
    try:
        host = validated_host(raw_host)
    except ValueError as exc:
        raise ConfigError(path, "refine.host", str(exc)) from exc
    model = r.str("model").strip()
    if not model:
        raise ConfigError(path, "refine.model", "must be non-empty")
    return RefineConfig(
        enabled=r.bool("enabled"),
        host=host,
        model=model,
        min_words=r.ranged_int("min_words", MIN_REFINE_WORDS, MAX_REFINE_WORDS),
        structured_output=r.bool("structured_output"),
        vocabulary=_vocabulary(r, path),
    )


def _vocabulary(r: _Reader, path: pathlib.Path) -> tuple[str, ...]:
    """Trimmed refine terms. Errors name the term's position, never its text."""

    key = "refine.vocabulary"
    terms = tuple(term.strip() for term in r.str_list("vocabulary"))
    if len(terms) > MAX_VOCABULARY_TERMS:
        raise ConfigError(path, key, f"must hold at most {MAX_VOCABULARY_TERMS} terms")
    seen: set[str] = set()
    for position, term in enumerate(terms, start=1):
        if not term:
            raise ConfigError(path, key, f"term {position} must be non-empty")
        if "\n" in term or "\r" in term:
            raise ConfigError(path, key, f"term {position} must not hold a line break")
        if len(term) > MAX_VOCABULARY_TERM_CHARS:
            limit = MAX_VOCABULARY_TERM_CHARS
            raise ConfigError(path, key, f"term {position} must have at most {limit} characters")
        folded = term.casefold()
        if folded in seen:
            raise ConfigError(path, key, f"term {position} repeats an earlier term")
        seen.add(folded)
    return terms


def _build_analytics(table: dict, path: pathlib.Path) -> AnalyticsConfig:
    r = _Reader(table, path, "analytics")
    return AnalyticsConfig(
        enabled=r.bool("enabled"), resource_profiling=r.bool("resource_profiling")
    )


def _build_live(table: dict, path: pathlib.Path) -> LiveConfig:
    r = _Reader(table, path, "live")
    return LiveConfig(diarize_mic=r.bool("diarize_mic"))


def _build_delivery(table: dict, path: pathlib.Path) -> DeliveryConfig:
    r = _Reader(table, path, "delivery")
    return DeliveryConfig(
        copy_original=r.bool("copy_original"),
        restore_clipboard=r.bool("restore_clipboard"),
        restore_delay_ms=r.ranged_int("restore_delay_ms", 0, MAX_RESTORE_DELAY_MS),
    )


def _merge(base: dict, overlay: dict) -> dict:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result
