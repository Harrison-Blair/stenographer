# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock, patch

import pytest

from stenographer.capabilities import Capabilities


@pytest.mark.parametrize("present", [True, False])
def test_has_paste_trigger(present: bool) -> None:
    """The capability is named for the trigger, not the tool, and is
    presence-only: ``shutil.which("wtype")`` and nothing more."""
    names = {f.name for f in dataclasses.fields(Capabilities)}
    assert "has_paste_trigger" in names
    assert "has_wtype" not in names

    with patch(
        "stenographer.capabilities.shutil.which",
        side_effect=lambda name: "/usr/bin/wtype" if (name == "wtype" and present) else None,
    ):
        caps = Capabilities.probe(MagicMock())
    assert caps.has_paste_trigger is present


def test_capabilities_round_trip() -> None:
    caps = Capabilities(
        has_paste_trigger=True,
        has_wl_copy=True,
        has_pw_play=False,
        has_paplay=True,
        has_input_group=False,
        has_mic=True,
        has_asr_model=False,
    )
    assert caps.has_paste_trigger is True
    assert caps.has_wl_copy is True
    assert caps.has_pw_play is False
    assert caps.has_paplay is True
    assert caps.has_input_group is False
    assert caps.has_mic is True
    assert caps.has_asr_model is False


def test_capabilities_is_frozen() -> None:
    caps = Capabilities(
        has_paste_trigger=True,
        has_wl_copy=True,
        has_pw_play=False,
        has_paplay=True,
        has_input_group=False,
        has_mic=True,
        has_asr_model=False,
    )
    try:
        caps.has_paste_trigger = False  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("expected FrozenInstanceError when mutating a frozen Capabilities")
