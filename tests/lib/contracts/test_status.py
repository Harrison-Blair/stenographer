# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared lifecycle contract regression tests."""

from __future__ import annotations

from stenographer.lib.contracts.null_status_sink import NullStatusSink
from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.lib.contracts.publication import should_publish_state


def test_visible_state_set_has_no_loading_pill() -> None:
    assert tuple(OverlayState) == (
        OverlayState.HIDDEN,
        OverlayState.RECORDING,
        OverlayState.TRANSCRIBING,
        OverlayState.DELIVERING,
        OverlayState.CANCELLED,
        OverlayState.ERROR,
    )


def test_state_publication_repeats_transient_states_but_suppresses_stable_duplicates() -> None:
    assert should_publish_state(OverlayState.RECORDING, OverlayState.TRANSCRIBING) is True
    assert should_publish_state(OverlayState.RECORDING, OverlayState.RECORDING) is False
    assert should_publish_state(OverlayState.ERROR, OverlayState.ERROR) is True
    assert should_publish_state(OverlayState.CANCELLED, OverlayState.CANCELLED) is True


def test_null_sink_accepts_all_fixed_display_metadata():
    sink = NullStatusSink()
    sink.publish(OverlayState.RECORDING)
    sink.loading_activity(True)
    sink.loading_activity(False)
    sink.audio_block(object(), 16000, 4)
    sink.close()
