# SPDX-License-Identifier: GPL-3.0-or-later
"""Construct validated configuration sections without altering their schema."""

from __future__ import annotations

import pathlib
from itertools import combinations

from stenographer.lib.config.constants import (
    ALLOWED_HOTKEY_MODES,
    ALLOWED_LOG_LEVELS,
    ALLOWED_REFINE_SCHEMES,
    MAX_REFINE_WORDS,
    MAX_RESTORE_DELAY_MS,
    MAX_VOCABULARY_TERM_CHARS,
    MAX_VOCABULARY_TERMS,
    MIN_REFINE_WORDS,
    SOUND_PACK_PATTERN,
)
from stenographer.lib.config.errors import ConfigError
from stenographer.lib.config.models import (
    AsrConfig,
    AudioConfig,
    DeliveryConfig,
    FeedbackConfig,
    HotkeyConfig,
    RefineConfig,
)
from stenographer.lib.config.reader import _Reader
from stenographer.lib.hotkey.keycodes import CODE_NAMES, KEY_CODES
from stenographer.lib.refine.endpoints import host_name, normalize_host, userinfo


def _build_hotkey(table: dict, path: pathlib.Path) -> HotkeyConfig:
    r = _Reader(table, path, "hotkey")
    binding = r.str("binding")
    if not binding:
        raise ConfigError(path, "hotkey.binding", "must be non-empty")
    general_binding = r.str("general_binding")
    if not general_binding:
        raise ConfigError(path, "hotkey.general_binding", "must be non-empty")
    cancel_binding = r.optional_str("cancel_binding")
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
    host = normalize_host(r.str("host"))
    scheme = host.partition("://")[0]
    if scheme not in ALLOWED_REFINE_SCHEMES:
        raise ConfigError(
            path,
            "refine.host",
            f"must be an http:// or https:// URL, got {r.str('host')!r}",
        )
    if not host_name(host):
        raise ConfigError(path, "refine.host", "must name a host")
    if userinfo(host):
        # Ollama has no authentication to use these for, and the daemon reports
        # its configured host at start; a secret in the URL would be a secret
        # in the log. The message never echoes the value.
        raise ConfigError(path, "refine.host", "must not embed credentials")
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
