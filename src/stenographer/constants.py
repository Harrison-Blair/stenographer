# SPDX-License-Identifier: GPL-3.0-or-later
"""Pipeline-wide constants. Stdlib-only, so the ASR child can import it freely.

``SAMPLE_RATE`` is the fixed rate the whole pipeline speaks: capture resamples
to it, the energy gate frames at it, and the decoder measures audio seconds by
it. It is not configurable — Whisper only accepts 16 kHz.
"""

from __future__ import annotations

SAMPLE_RATE = 16000
