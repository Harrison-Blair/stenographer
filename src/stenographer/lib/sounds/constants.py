# SPDX-License-Identifier: GPL-3.0-or-later
"""Sound-pack identities, cue order, and bounded playback limits."""

from __future__ import annotations

from stenographer.lib.config.constants import DEFAULT_SOUND_PACK

CUE_ORDER: tuple[str, ...] = ("record_start", "record_stop", "delivered", "error")


BUNDLED_PACKS: tuple[str, ...] = ("legacy", "warm-desk", "soft-electronic", DEFAULT_SOUND_PACK)


PREVIEW_VOLUME_WHEN_MUTED = 0.6


PREVIEW_PAUSE_SECONDS = 0.35


_MIN_SAMPLE_RATE = 8_000


_MAX_SAMPLE_RATE = 192_000


_MAX_DURATION_SECONDS = 0.3


_VALID_SAMPLE_WIDTHS = frozenset({1, 2, 3, 4})
