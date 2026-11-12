# SPDX-License-Identifier: GPL-3.0-or-later
"""One microphone listing for the whole program.

The capability gate, ``setup``, the hub pickers, and ``devices`` ask the same
question: which microphones can record. :func:`query_devices` asks the
platform once. The listing is advisory at every call site, so it never
raises on the host: a failure is an empty result that carries a human-readable ``error``.
The pure adapters below give each caller its own shape.
"""

from __future__ import annotations

from stenographer.lib.platform import current_platform
from stenographer.lib.platform.errors import UnsupportedPlatformError
from stenographer.lib.platform.mic_capture import InputSources


def query_devices() -> InputSources:
    """List the microphones of the host, or say why not."""
    try:
        return current_platform().input_sources()
    except UnsupportedPlatformError as exc:
        return InputSources(error=str(exc))


def mic_issue(query: InputSources) -> str | None:
    """Pure: why no microphone can record, or ``None``."""
    if query.error is not None:
        return query.error
    if not query.sources:
        return "no microphone found"
    return None


def input_device_choices(query: InputSources) -> list[tuple[str, str]]:
    """Pure: selectable microphones as ``(value, label)``: the source name and its description."""
    return [(source.name, source.description) for source in query.sources]
