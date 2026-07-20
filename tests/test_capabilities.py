# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock, patch

import pytest

from stenographer.capabilities import Capabilities


@pytest.mark.parametrize("present", [True, False])
def test_has_paste_trigger(present: bool) -> None:
    """The capability is named for the trigger, not the tool: it is True when
    any injection backend (wtype on Wayland, xdotool on X11) is on ``PATH``."""
    names = {f.name for f in dataclasses.fields(Capabilities)}
    assert "has_paste_trigger" in names
    assert "has_wtype" not in names
    assert "has_xdotool" not in names

    with patch(
        "stenographer.capabilities.shutil.which",
        side_effect=lambda name: "/usr/bin/wtype" if (name == "wtype" and present) else None,
    ):
        caps = Capabilities.probe(MagicMock())
    assert caps.has_paste_trigger is present


def test_has_paste_trigger_via_xdotool() -> None:
    """On X11, xdotool alone satisfies the injection capability."""
    with patch(
        "stenographer.capabilities.shutil.which",
        side_effect=lambda name: "/usr/bin/xdotool" if name == "xdotool" else None,
    ):
        caps = Capabilities.probe(MagicMock())
    assert caps.has_paste_trigger is True


def test_has_clipboard_via_xclip() -> None:
    """xclip (or xsel) alone satisfies the clipboard capability on X11."""
    with patch(
        "stenographer.capabilities.shutil.which",
        side_effect=lambda name: "/usr/bin/xclip" if name == "xclip" else None,
    ):
        caps = Capabilities.probe(MagicMock())
    assert caps.has_clipboard is True
    assert "has_wl_copy" not in {f.name for f in dataclasses.fields(Capabilities)}


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"XDG_SESSION_TYPE": "wayland"}, "wayland"),
        ({"XDG_SESSION_TYPE": "x11"}, "x11"),
        ({"WAYLAND_DISPLAY": "wayland-0"}, "wayland"),
        ({"DISPLAY": ":0"}, "x11"),
        ({}, "unknown"),
    ],
)
def test_detect_session_type(env: dict[str, str], expected: str) -> None:
    from stenographer.capabilities import detect_session_type

    with patch.dict("os.environ", env, clear=True):
        assert detect_session_type() == expected


def test_capabilities_round_trip() -> None:
    caps = Capabilities(
        has_paste_trigger=True,
        has_clipboard=True,
        has_pw_play=False,
        has_paplay=True,
        has_input_group=False,
        has_mic=True,
        has_asr_model=False,
        session_type="wayland",
    )
    assert caps.has_paste_trigger is True
    assert caps.has_clipboard is True
    assert caps.has_pw_play is False
    assert caps.has_paplay is True
    assert caps.has_input_group is False
    assert caps.has_mic is True
    assert caps.has_asr_model is False
    assert caps.session_type == "wayland"


def test_capabilities_is_frozen() -> None:
    caps = Capabilities(
        has_paste_trigger=True,
        has_clipboard=True,
        has_pw_play=False,
        has_paplay=True,
        has_input_group=False,
        has_mic=True,
        has_asr_model=False,
        session_type="wayland",
    )
    try:
        caps.has_paste_trigger = False  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("expected FrozenInstanceError when mutating a frozen Capabilities")
