# SPDX-License-Identifier: GPL-3.0-or-later
"""Typed model, worker, and protocol failures."""

from __future__ import annotations


class PathologicalOutputError(RuntimeError):
    """The decoder returned structurally invalid or implausibly dense output."""


class WorkerError(RuntimeError):
    """Any worker-surfaced failure: child crash, mid-request death, or a
    decode error round-tripped from the child."""


class WorkerPathologicalError(WorkerError):
    """The child rejected a degenerate decode. Surfaced distinctly so
    the daemon can discard rather than deliver; carries only the serialised
    detail string, since the original instance cannot cross the boundary."""


class WorkerProtocolError(WorkerError):
    """The child sent a malformed or out-of-order protocol response."""


class WorkerCrashedError(WorkerError):
    """The registered inference process exited before completing its response."""


class WorkerModelError(WorkerError):
    """Model loading failed before inference could begin."""


class WorkerTimeoutError(WorkerError):
    """A fixed inference or model-loading deadline expired."""


class _WorkerTimeoutError(WorkerTimeoutError):
    """An internal phase deadline expired while the child remained alive."""
