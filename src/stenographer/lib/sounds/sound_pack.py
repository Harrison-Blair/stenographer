# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolved cue paths for one sound-pack lifetime."""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

from stenographer.lib.sounds.constants import CUE_ORDER


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
