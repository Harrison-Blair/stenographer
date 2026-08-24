# SPDX-License-Identifier: GPL-3.0-or-later
"""TOML config: four frozen sections, key-scoped validation, default writer.

One flat module (the old five-file config package collapsed). ``""`` is the
documented "unset" for optional string keys — there is no ``null`` rewrite.
"""

from __future__ import annotations

import os
import pathlib
import re
import tomllib
from dataclasses import asdict, dataclass

from stenographer.status import SPECTRUM_BANDS

ALLOWED_COMPUTE_TYPES: frozenset[str] = frozenset(
    {"int8", "int8_float16", "float16", "float32", "default"}
)

ALLOWED_HOTKEY_MODES: frozenset[str] = frozenset({"hold", "toggle"})
MIN_SPECTRUM_FLOOR_DBFS = -96.0
MAX_SPECTRUM_FLOOR_DBFS = -13.0
SOUND_PACK_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
DEFAULT_SOUND_PACK = "minimal-ui"

SpectrumFloor = float | tuple[float, ...]


class ConfigError(Exception):
    """A validation error tied to a specific dotted config key."""

    def __init__(self, path: pathlib.Path, key: str, reason: str) -> None:
        self.path = path
        self.key = key
        self.reason = reason
        super().__init__(f"{path}: {key}: {reason}")


@dataclass(frozen=True)
class HotkeyConfig:
    binding: str
    device: str | None
    mode: str = "hold"


@dataclass(frozen=True)
class AudioConfig:
    input_device: str | None
    min_speech_rms: float
    max_recording_seconds: int


@dataclass(frozen=True)
class AsrConfig:
    model: str
    compute_type: str
    beam_size: int
    hotwords: str | None
    initial_prompt: str | None
    vad_filter: bool
    silence_threshold: float
    idle_unload_seconds: int
    cpu_threads: int


@dataclass(frozen=True)
class FeedbackConfig:
    volume: float
    mute: bool
    overlay: bool = True
    update_check: bool = True
    spectrum_floor_dbfs: SpectrumFloor = -45.0
    sound_pack: str = DEFAULT_SOUND_PACK


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
    return HotkeyConfig(binding, r.optional_str("device"), r.choice("mode", ALLOWED_HOTKEY_MODES))


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
        model=r.str("model"),
        compute_type=r.choice("compute_type", ALLOWED_COMPUTE_TYPES),
        beam_size=r.ranged_int("beam_size", 1, 10),
        hotwords=r.optional_str("hotwords"),
        initial_prompt=r.optional_str("initial_prompt"),
        vad_filter=r.bool("vad_filter"),
        silence_threshold=r.ranged_number("silence_threshold", 0.0, 1.0),
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
    )


def _merge(base: dict, overlay: dict) -> dict:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


_DEFAULT_TOML_TEMPLATE = """\
# stenographer configuration.

[stenographer.hotkey]
binding = "KEY_RIGHTCTRL"
device = ""                    # {hotkey_device_comment}
mode = "hold"                  # hold = push-to-talk; toggle = press to start, press again to stop

[stenographer.audio]
input_device = ""              # PortAudio device name/index; "" = system default
min_speech_rms = 0.0005        # pre-decode energy gate; 0 disables the gate
max_recording_seconds = 600

[stenographer.asr]
model = "Systran/faster-whisper-medium.en"
compute_type = "int8"          # int8 | int8_float16 | float16 | float32 | default
beam_size = 1
hotwords = ""                  # proper nouns; full models only (distil models drop words)
initial_prompt = ""            # style/domain context prepended to decoding
vad_filter = true
silence_threshold = 0.6        # post-decode no-speech-probability gate
idle_unload_seconds = 900      # kill the idle worker child; 0 disables
cpu_threads = 0                # 0 = auto (physical cores, capped at 8)

[stenographer.feedback]
volume = 0.6
mute = false
overlay = true                 # best-effort lifecycle pill; dictation is independent
update_check = true            # daily HTTPS check for a newer release; a notice, never self-update
spectrum_floor_dbfs = -45.0    # scalar manual floor; setup calibration writes 18 bands
sound_pack = "{sound_pack}"      # bundled pack name or valid pack under sounds/
"""


def default_toml() -> str:
    """The annotated default config, with the host's ``hotkey.device`` comment.

    Rendered at write time rather than at import: what a hotkey device *is*
    differs per host, so that one comment comes from ``HostGuidance`` and the
    core never spells a device-node convention.
    """

    from stenographer.platform import current_platform

    return _DEFAULT_TOML_TEMPLATE.format(
        hotkey_device_comment=current_platform().guidance().hotkey_device_comment,
        sound_pack=DEFAULT_SOUND_PACK,
    )


@dataclass(frozen=True)
class Config:
    hotkey: HotkeyConfig
    audio: AudioConfig
    asr: AsrConfig
    feedback: FeedbackConfig

    @classmethod
    def defaults(cls) -> Config:
        return cls(
            hotkey=HotkeyConfig(binding="KEY_RIGHTCTRL", device=None, mode="hold"),
            audio=AudioConfig(input_device=None, min_speech_rms=0.0005, max_recording_seconds=600),
            asr=AsrConfig(
                model="Systran/faster-whisper-medium.en",
                compute_type="int8",
                beam_size=1,
                hotwords=None,
                initial_prompt=None,
                vad_filter=True,
                silence_threshold=0.6,
                idle_unload_seconds=900,
                cpu_threads=0,
            ),
            feedback=FeedbackConfig(
                volume=0.6,
                mute=False,
                overlay=True,
                update_check=True,
                spectrum_floor_dbfs=-45.0,
                sound_pack=DEFAULT_SOUND_PACK,
            ),
        )

    @classmethod
    def load(cls, path: pathlib.Path) -> Config:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as e:
            raise ConfigError(path, "<file>", f"cannot read: {e}") from e

        return cls.loads(content, path)

    @classmethod
    def loads(cls, content: str, path: pathlib.Path = pathlib.Path("<memory>")) -> Config:
        """Load and validate TOML already held in memory."""

        try:
            raw = tomllib.loads(content)
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(path, "<toml>", f"malformed TOML: {e}") from e
        if not isinstance(raw, dict):
            raise ConfigError(path, "<file>", "top-level value must be a table")
        table = raw.get("stenographer", {})
        if not isinstance(table, dict):
            raise ConfigError(path, "stenographer", f"must be a table, got {type(table).__name__}")
        merged = _merge(asdict(cls.defaults()), table)
        for name in ("hotkey", "audio", "asr", "feedback"):
            if not isinstance(merged[name], dict):
                raise ConfigError(path, name, f"must be a table, got {type(merged[name]).__name__}")
        return cls(
            hotkey=_build_hotkey(merged["hotkey"], path),
            audio=_build_audio(merged["audio"], path),
            asr=_build_asr(merged["asr"], path),
            feedback=_build_feedback(merged["feedback"], path),
        )

    @classmethod
    def write_default(cls, path: pathlib.Path) -> None:
        # Bytes, not text mode: setup writes LF bytes, and a CRLF default on
        # Windows would make the first setup save always rewrite the file.
        path.write_bytes(default_toml().encode("utf-8"))


def resolve_config_path(*, create_parent: bool = True) -> pathlib.Path:
    """Return the configured path, optionally creating its parent directory."""

    env_path = os.environ.get("STENOGRAPHER_CONFIG")
    if env_path:
        path = pathlib.Path(env_path)
    else:
        from stenographer.platform import current_platform

        path = current_platform().config_path(os.environ, pathlib.Path.home())
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_or_default() -> Config:
    path = resolve_config_path()
    if path.is_file():
        return Config.load(path)
    Config.write_default(path)
    return Config.defaults()
