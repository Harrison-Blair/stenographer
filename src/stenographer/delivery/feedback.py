# SPDX-License-Identifier: GPL-3.0-or-later
"""Sound-pack discovery, validation, resolution, and cue playback policy."""

from __future__ import annotations

import logging
import pathlib
import time
import wave
from dataclasses import dataclass
from importlib.resources import files
from typing import TYPE_CHECKING

from stenographer.config import DEFAULT_SOUND_PACK, SOUND_PACK_PATTERN

if TYPE_CHECKING:
    from stenographer.config import FeedbackConfig
    from stenographer.platform.base import CuePlayer

logger = logging.getLogger(__name__)

CUE_ORDER: tuple[str, ...] = ("record_start", "record_stop", "delivered", "error")
BUNDLED_PACKS: tuple[str, ...] = ("legacy", "warm-desk", "soft-electronic", DEFAULT_SOUND_PACK)
PREVIEW_VOLUME_WHEN_MUTED = 0.6
PREVIEW_PAUSE_SECONDS = 0.35

_MIN_SAMPLE_RATE = 8_000
_MAX_SAMPLE_RATE = 192_000
_MAX_DURATION_SECONDS = 0.3
_VALID_SAMPLE_WIDTHS = frozenset({1, 2, 3, 4})


@dataclass(frozen=True, slots=True)
class SoundPack:
    """A sound pack resolved to stable cue paths for one process lifetime.

    Strictly loaded packs have all four paths. The bundled fallback may carry
    ``None`` for a damaged or missing asset so feedback remains best-effort.
    """

    name: str
    root: pathlib.Path
    cue_paths: tuple[pathlib.Path | None, ...]
    bundled: bool
    fallback: bool = False

    def path_for(self, cue: str) -> pathlib.Path | None:
        """Return the resolved path for *cue*, or ``None`` when unavailable."""
        try:
            return self.cue_paths[CUE_ORDER.index(cue)]
        except ValueError:
            return None

    @property
    def complete(self) -> bool:
        """Whether all four lifecycle cues resolved successfully."""
        return len(self.cue_paths) == len(CUE_ORDER) and all(self.cue_paths)


def bundled_sound_root() -> pathlib.Path:
    """Return the installed nested sound-pack asset root."""
    return pathlib.Path(str(files("stenographer"))) / "assets" / "sounds"


def is_valid_pack_name(name: object) -> bool:
    """Whether *name* is a public sound-pack slug. PURE."""
    return isinstance(name, str) and SOUND_PACK_PATTERN.fullmatch(name) is not None


def _resolved_within(path: pathlib.Path, root: pathlib.Path) -> pathlib.Path | None:
    """Resolve an existing path only when it remains inside *root*."""
    try:
        resolved_root = root.resolve(strict=True)
        resolved = path.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved


def _wav_header_ok(
    channels: int,
    sample_width: int,
    sample_rate: int,
    frame_count: int,
    compression: str,
) -> bool:
    """Whether WAV header fields describe the bounded PCM cue subset. PURE."""
    return (
        compression == "NONE"
        and channels in (1, 2)
        and sample_width in _VALID_SAMPLE_WIDTHS
        and _MIN_SAMPLE_RATE <= sample_rate <= _MAX_SAMPLE_RATE
        and frame_count > 0
        and frame_count < sample_rate * _MAX_DURATION_SECONDS
    )


def _valid_wav(path: pathlib.Path) -> bool:
    """Validate the bounded PCM WAV subset accepted for lifecycle cues.

    Header bounds are checked before any payload is read, so an oversized or
    hostile frame count never allocates.
    """
    try:
        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            frame_count = wav.getnframes()
            compression = wav.getcomptype()
            if not _wav_header_ok(channels, sample_width, sample_rate, frame_count, compression):
                return False
            frames = wav.readframes(frame_count)
    except (EOFError, MemoryError, OSError, wave.Error):
        return False

    return _wav_payload_ok(len(frames), frame_count, channels, sample_width)


def cue_audible(mute: bool, volume: float, *, has_player: bool) -> bool:
    """Whether a cue may make sound at all: unmuted, positive volume, a player. PURE."""
    return not mute and volume > 0.0 and has_player


def _wav_payload_ok(frames_len: int, frame_count: int, channels: int, sample_width: int) -> bool:
    """A truncated payload must fail validation even when the header parses. PURE."""
    return frames_len == frame_count * channels * sample_width


def sound_pack_cue_paths(
    pack_root: pathlib.Path,
    *,
    containment_root: pathlib.Path | None = None,
) -> tuple[pathlib.Path, ...] | None:
    """Resolve and validate a complete pack atomically; unrelated files are ignored."""
    boundary = containment_root if containment_root is not None else pack_root
    resolved_pack = _resolved_within(pack_root, boundary)
    if resolved_pack is None or not resolved_pack.is_dir():
        return None

    resolved: list[pathlib.Path] = []
    for cue in CUE_ORDER:
        path = _resolved_within(resolved_pack / f"{cue}.wav", resolved_pack)
        if path is None or not path.is_file() or not _valid_wav(path):
            return None
        resolved.append(path)
    return tuple(resolved)


def _pack_location(
    name: str,
    config_dir: pathlib.Path,
    bundled_root: pathlib.Path,
) -> tuple[pathlib.Path, pathlib.Path, bool]:
    if name in BUNDLED_PACKS:
        return bundled_root / name, bundled_root, True
    custom_root = config_dir / "sounds"
    return custom_root / name, custom_root, False


def load_sound_pack(
    name: str,
    config_dir: pathlib.Path,
    *,
    bundled_root: pathlib.Path | None = None,
) -> SoundPack | None:
    """Strictly resolve one named pack, with bundled names taking precedence."""
    if not is_valid_pack_name(name):
        return None
    assets = bundled_root if bundled_root is not None else bundled_sound_root()
    root, boundary, bundled = _pack_location(name, config_dir, assets)
    if not bundled:
        resolved_custom_root = _resolved_within(boundary, config_dir)
        if resolved_custom_root is None or not resolved_custom_root.is_dir():
            return None
        boundary = resolved_custom_root
        root = boundary / name
    cue_paths = sound_pack_cue_paths(root, containment_root=boundary)
    if cue_paths is None:
        return None
    return SoundPack(name=name, root=root, cue_paths=cue_paths, bundled=bundled)


def discover_sound_packs(
    config_dir: pathlib.Path,
    *,
    bundled_root: pathlib.Path | None = None,
) -> tuple[str, ...]:
    """Return valid packs in stable UI order: bundled, then sorted custom names.

    Bundled packs are listed only when complete and valid in the installation.
    """
    assets = bundled_root if bundled_root is not None else bundled_sound_root()
    bundled_names = tuple(
        name
        for name in BUNDLED_PACKS
        if sound_pack_cue_paths(assets / name, containment_root=assets) is not None
    )
    custom_root = _resolved_within(config_dir / "sounds", config_dir)
    if custom_root is None or not custom_root.is_dir():
        return bundled_names
    custom_names: list[str] = []
    try:
        candidates = tuple(custom_root.iterdir())
    except OSError:
        candidates = ()
    for candidate in candidates:
        name = candidate.name
        if name in BUNDLED_PACKS or not is_valid_pack_name(name):
            continue
        if sound_pack_cue_paths(candidate, containment_root=custom_root) is not None:
            custom_names.append(name)
    return (*bundled_names, *sorted(custom_names))


def _partial_bundled_fallback(bundled_root: pathlib.Path) -> SoundPack:
    root = bundled_root / DEFAULT_SOUND_PACK
    cue_paths: list[pathlib.Path | None] = []
    for cue in CUE_ORDER:
        path = _resolved_within(root / f"{cue}.wav", root)
        cue_paths.append(path if path is not None and path.is_file() and _valid_wav(path) else None)
    return SoundPack(
        name=DEFAULT_SOUND_PACK,
        root=root,
        cue_paths=tuple(cue_paths),
        bundled=True,
        fallback=True,
    )


def _resolve_sound_pack_quietly(
    name: str,
    config_dir: pathlib.Path,
    assets: pathlib.Path,
) -> tuple[SoundPack, int]:
    """Resolve strict -> bundled default -> partial default; report the fallback depth."""
    selected = load_sound_pack(name, config_dir, bundled_root=assets)
    if selected is not None:
        return selected, 0

    fallback = load_sound_pack(DEFAULT_SOUND_PACK, config_dir, bundled_root=assets)
    if fallback is not None:
        return (
            SoundPack(
                name=fallback.name,
                root=fallback.root,
                cue_paths=fallback.cue_paths,
                bundled=True,
                fallback=True,
            ),
            1,
        )

    return _partial_bundled_fallback(assets), 2


def resolve_sound_pack(
    name: str,
    config_dir: pathlib.Path,
    *,
    bundled_root: pathlib.Path | None = None,
) -> SoundPack:
    """Resolve the configured pack once, falling back to the bundled default."""
    assets = bundled_root if bundled_root is not None else bundled_sound_root()
    pack, depth = _resolve_sound_pack_quietly(name, config_dir, assets)
    if depth >= 1:
        logger.warning("feedback: sound_pack_unavailable fallback=%s", DEFAULT_SOUND_PACK)
    if depth >= 2:
        logger.warning(
            "feedback: bundled_pack_incomplete pack=%s detail=unavailable_cues_disabled",
            DEFAULT_SOUND_PACK,
        )
    return pack


def effective_sound_pack_name(
    name: str,
    config_dir: pathlib.Path,
    *,
    bundled_root: pathlib.Path | None = None,
) -> str | None:
    """Return the pack name the daemon would use for *name*, without logging.

    Follows ``resolve_sound_pack`` exactly; the partial bundled fallback counts
    only when at least one cue resolved, otherwise ``None``.
    """
    assets = bundled_root if bundled_root is not None else bundled_sound_root()
    pack, _depth = _resolve_sound_pack_quietly(name, config_dir, assets)
    if any(path is not None for path in pack.cue_paths):
        return pack.name
    return None


def preview_volume(cfg: FeedbackConfig) -> float:
    """Return audible preview volume without mutating mute or volume settings."""
    if cfg.mute or cfg.volume <= 0.0:
        return PREVIEW_VOLUME_WHEN_MUTED
    return cfg.volume


def preview_sound_pack(
    pack: SoundPack,
    player: CuePlayer,
    volume: float,
    *,
    pause_seconds: float = PREVIEW_PAUSE_SECONDS,
) -> None:
    """Play all lifecycle cues in order with silence between them."""
    if not pack.complete:
        raise ValueError(f"sound pack {pack.name!r} is incomplete")
    for index, path in enumerate(pack.cue_paths):
        assert path is not None  # narrowed by ``complete`` above
        player.preview(path, volume)
        if index + 1 < len(pack.cue_paths):
            time.sleep(pause_seconds)


class Feedback:
    """Own mute, volume, and one-time sound-pack resolution policy."""

    def __init__(
        self,
        *,
        cfg: FeedbackConfig,
        player: CuePlayer | None,
        config_dir: pathlib.Path,
        asset_root: pathlib.Path | None = None,
    ) -> None:
        self._cfg = cfg
        self._player = player
        self._pack = resolve_sound_pack(
            cfg.sound_pack,
            config_dir,
            bundled_root=asset_root,
        )

    @property
    def sound_pack(self) -> SoundPack:
        """The effective pack fixed for this ``Feedback`` lifetime."""
        return self._pack

    def play(self, name: str) -> None:
        if not cue_audible(self._cfg.mute, self._cfg.volume, has_player=self._player is not None):
            return
        path = self._pack.path_for(name)
        if path is None:
            return
        self._player.play(path, self._cfg.volume)

    def close(self) -> None:
        return None
