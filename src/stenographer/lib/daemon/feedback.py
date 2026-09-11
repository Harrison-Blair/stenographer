# SPDX-License-Identifier: GPL-3.0-or-later
"""Failure-isolating cue and lifecycle-status publication."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from stenographer.lib.logging.pipeline import log_failure

if TYPE_CHECKING:
    from stenographer.lib.contracts.overlay_state import OverlayState
    from stenographer.lib.contracts.status_sink import StatusSink
    from stenographer.lib.sounds.feedback import Feedback

log = logging.getLogger("stenographer.lib.daemon")


def _play_cue(feedback: Feedback, name: str) -> None:
    """Launch a cue without allowing player failure to break daemon state."""
    try:
        feedback.play(name)
    except Exception as exc:
        log_failure(log, logging.WARNING, "feedback: cue_failed", exc, safe=True, cue=name)


def _publish_status(status: StatusSink, state: OverlayState) -> None:
    """Enqueue fixed lifecycle metadata without allowing overlay failure through."""
    try:
        status.publish(state)
    except Exception as exc:
        log_failure(
            log, logging.WARNING, "overlay: publish_failed", exc, safe=True, state=state.value
        )


def _publish_loading_activity(status: StatusSink, active: bool) -> None:
    try:
        status.loading_activity(active)
    except Exception as exc:
        log_failure(
            log,
            logging.WARNING,
            "overlay: loading_activity_failed",
            exc,
            safe=True,
            active=int(active),
        )
