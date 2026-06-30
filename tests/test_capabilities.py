# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import dataclasses

from stenographer.capabilities import Capabilities


def test_capabilities_round_trip() -> None:
    caps = Capabilities(
        has_wtype=True,
        has_wl_copy=True,
        has_pw_play=False,
        has_paplay=True,
        has_input_group=False,
        has_mic=True,
        has_asr_model=False,
        has_swaync=False,
    )
    assert caps.has_wtype is True
    assert caps.has_wl_copy is True
    assert caps.has_pw_play is False
    assert caps.has_paplay is True
    assert caps.has_input_group is False
    assert caps.has_mic is True
    assert caps.has_asr_model is False
    assert caps.has_swaync is False


def test_capabilities_is_frozen() -> None:
    caps = Capabilities(
        has_wtype=True,
        has_wl_copy=True,
        has_pw_play=False,
        has_paplay=True,
        has_input_group=False,
        has_mic=True,
        has_asr_model=False,
        has_swaync=False,
    )
    try:
        caps.has_wtype = False  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("expected FrozenInstanceError when mutating a frozen Capabilities")
