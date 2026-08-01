# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared bits across the daemon indicator and the GTK helper process."""

_STOP = object()


# Single source of truth for the HUD status labels the overlay child renders per
# state slug. Slugs are produced by StatusIndicator.show_* and cross the JSON IPC
# boundary; unknown slugs fall back to a title-cased rendering.
_HUD_STATE_LABELS = {
    "ready": "Ready",
    "listening": "Listening",
    "loading": "Loading model · Listening",
    "transcribing": "Transcribing",
    "unloaded": "Speech model unloaded",
    "update_available": "Update Available",
}
