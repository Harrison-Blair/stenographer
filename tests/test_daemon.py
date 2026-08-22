# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic and OS-level tests for daemon.py.

Covered here: the pipeline outcome policy (``classify_pipeline``), the
one-at-a-time admission rule (``can_start``), the toggle-mode press mapping
(``toggle_action``, seen to fail against a stub returning "start"
unconditionally), the stale-timer guard (``max_duration_applies``, seen to
fail against a stub that ignores the generation), the overlay publish policy as
bound by ``_publish_state`` (``should_publish_state``, seen to fail against a
dedup-only stub), and that ``Daemon.build`` wires all
collaborators lazily (no uinput device, stream, or model opened) with a safe
pre-start ``stop``, per ``hotkey.mode``. Nothing mocks
subprocess/UInput/wl-copy/Worker (§6.2); the real utterance path is the M5
manual dictation acceptance procedure.
"""

from __future__ import annotations

import dataclasses

import pytest

from stenographer.cli import doctor
from stenographer.daemon import (
    Outcome,
    can_start,
    classify_pipeline,
    max_duration_applies,
    should_publish_state,
    startup_clipboard_backend,
    toggle_action,
)
from stenographer.status import OverlayState


def _startup_caps(**overrides) -> doctor.Capabilities:
    fields = {
        "uinput_writable": True,
        "input_group": True,
        "has_mic": True,
        "model_cached": True,
        "clipboard": True,
        "clipboard_backend": "wl-copy",
        "audio_player": "pw-play",
        "service_enabled": "enabled",
        "service_active": "active",
        "overlay": doctor.OverlayCapability.disabled(),
    }
    fields.update(overrides)
    return doctor.Capabilities(**fields)


def test_gate_failure_is_silent():
    assert classify_pipeline(gate_passed=False, transcript_nonempty=False, deliver_result=None) == (
        Outcome.SILENT,
        None,
    )


def test_empty_transcript_is_silent():
    # Gate passed but the decode was empty/all-gated: success-shaped, no error (§4.7).
    assert classify_pipeline(gate_passed=True, transcript_nonempty=False, deliver_result=None) == (
        Outcome.SILENT,
        None,
    )


def test_delivered_transcript():
    assert classify_pipeline(gate_passed=True, transcript_nonempty=True, deliver_result=True) == (
        Outcome.DELIVERED,
        None,
    )


def test_failed_delivery_is_error_with_message():
    outcome, message = classify_pipeline(
        gate_passed=True, transcript_nonempty=True, deliver_result=False
    )
    # A False deliver on non-empty text is never silent (§4.3): the copy failed,
    # so the chord was withheld and the user must be told.
    assert outcome is Outcome.ERROR
    assert message


def test_can_start_only_when_fully_idle():
    assert can_start(recording=False, busy=False, stopping=False) is True
    assert can_start(recording=True, busy=False, stopping=False) is False
    assert can_start(recording=False, busy=True, stopping=False) is False
    assert can_start(recording=False, busy=False, stopping=True) is False


def test_toggle_action_maps_press_edges():
    # Idle press starts; a press while recording always stops, even during
    # shutdown, so a live capture is never stranded. A press during
    # transcription (busy) neither starts nor queues (§5, one at a time).
    assert toggle_action(recording=False, busy=False, stopping=False) == "start"
    assert toggle_action(recording=True, busy=False, stopping=False) == "stop"
    assert toggle_action(recording=False, busy=True, stopping=False) is None
    assert toggle_action(recording=False, busy=False, stopping=True) is None
    assert toggle_action(recording=True, busy=False, stopping=True) == "stop"


def test_max_duration_applies_guards_stale_generation():
    # A fired timer can be blocked on the state lock while a manual stop and an
    # immediate restart advance the generation; the stale timer must not stop
    # the newer recording, and a matching timer applies only while live.
    assert max_duration_applies(3, 3, recording=True) is True
    assert max_duration_applies(2, 3, recording=True) is False
    assert max_duration_applies(3, 3, recording=False) is False


def test_publish_policy_always_represents_error():
    # The helper auto-hides ERROR after a fixed timeout without notifying the
    # daemon, so the producer cache can be stale: a repeated ERROR (e.g. mic
    # failing twice in a row) must re-present rather than dedup away. Tested
    # against the name daemon.py binds in _publish_state. Seen to fail against
    # a dedup-only stub shadowing the helper.
    assert should_publish_state(OverlayState.ERROR, OverlayState.ERROR) is True


def test_publish_policy_dedups_stable_states():
    # Every non-ERROR state coalesces when repeated; any actual change passes.
    for state in OverlayState:
        if state is OverlayState.ERROR:
            continue
        assert should_publish_state(state, state) is False
    assert should_publish_state(OverlayState.HIDDEN, OverlayState.RECORDING) is True
    assert should_publish_state(OverlayState.RECORDING, OverlayState.TRANSCRIBING) is True
    assert should_publish_state(OverlayState.ERROR, OverlayState.HIDDEN) is True


def test_startup_gate_tracks_every_current_doctor_requirement():
    assert startup_clipboard_backend(_startup_caps()) == "wl-copy"
    for name in doctor.REQUIRED:
        caps = dataclasses.replace(_startup_caps(), **{name: False})
        assert startup_clipboard_backend(caps) is None, name


def test_startup_gate_ignores_optional_capabilities_and_reuses_backend():
    caps = _startup_caps(
        clipboard_backend="x11",
        audio_player=None,
        service_enabled=None,
        service_active=None,
        overlay=doctor.OverlayCapability.disabled(),
    )
    assert startup_clipboard_backend(caps) == "x11"


def test_build_wires_collaborators_lazily():
    # Package A (hotkey.py) is built concurrently against the documented
    # contract; skip this wiring check until it lands, then run it for real.
    pytest.importorskip("stenographer.hotkey")
    from stenographer.config import Config
    from stenographer.daemon import Daemon

    daemon = Daemon.build(Config.defaults(), clipboard_backend="wl-copy")
    try:
        # Built but nothing opened: startup preparation happens only after the
        # single-instance lock is acquired in run().
        assert daemon._recording is False
        assert daemon._busy is False
        assert daemon._listener is not None
        assert daemon._deliverer is not None
        assert daemon._worker.is_alive() is False
        assert daemon._recorder.is_active is False
        assert daemon._recorder.is_prepared is False
    finally:
        # stop() before run() must be a safe no-op.
        daemon.stop()


def test_build_wires_toggle_mode_press_only():
    # Seen to FAIL against a build that ignores hotkey.mode and wires toggle
    # like hold. Same real-build style as the lazy-wiring test above: nothing
    # is opened, no mocks.
    pytest.importorskip("stenographer.hotkey")
    from stenographer.config import Config
    from stenographer.daemon import Daemon

    hold = Daemon.build(Config.defaults(), clipboard_backend="wl-copy")
    try:
        assert hold._listener._on_start == hold.on_key_down
        assert hold._listener._on_stop == hold.on_key_up
    finally:
        hold.stop()

    defaults = Config.defaults()
    toggle_cfg = dataclasses.replace(
        defaults, hotkey=dataclasses.replace(defaults.hotkey, mode="toggle")
    )
    toggle = Daemon.build(toggle_cfg, clipboard_backend="wl-copy")
    try:
        # Only presses drive the session; the falling edge must be inert.
        assert toggle._listener._on_start == toggle.on_toggle_press
        assert toggle._listener._on_stop != toggle.on_key_up
        assert toggle._listener._on_stop != toggle.on_key_down
    finally:
        toggle.stop()
