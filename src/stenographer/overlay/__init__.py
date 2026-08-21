# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional isolated visual feedback: helper supervision, backends, rendering, spectrum."""

from stenographer.overlay.entry import private_entry_requested

__all__ = [
    "OverlaySupervisor",
    "private_entry_requested",
    "run_overlay_helper",
]


def __getattr__(name: str) -> object:
    # The supervisor pulls in numpy via spectrum; resolve these lazily so
    # `import stenographer.overlay` stays importable with only the stdlib
    # present (the completion CI job installs the CLI with --no-deps).
    if name in ("OverlaySupervisor", "run_overlay_helper"):
        from stenographer.overlay import supervisor

        return getattr(supervisor, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
