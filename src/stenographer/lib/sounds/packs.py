# SPDX-License-Identifier: GPL-3.0-or-later
"""Sound-pack discovery, validation, resolution, and cue playback policy."""

from __future__ import annotations

import logging
import pathlib
from importlib.resources import files

from stenographer.lib.config.constants import DEFAULT_SOUND_PACK, SOUND_PACK_PATTERN
from stenographer.lib.sounds.constants import BUNDLED_PACKS, CUE_ORDER
from stenographer.lib.sounds.sound_pack import SoundPack
from stenographer.lib.sounds.validation import _resolved_within, _valid_wav

logger = logging.getLogger(__name__)


def bundled_sound_root() -> pathlib.Path:
    """Return the installed nested sound-pack asset root."""
    return pathlib.Path(str(files("stenographer"))) / "assets" / "sounds"


def is_valid_pack_name(name: object) -> bool:
    """Whether *name* is a public sound-pack slug. PURE."""
    return isinstance(name, str) and SOUND_PACK_PATTERN.fullmatch(name) is not None


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
