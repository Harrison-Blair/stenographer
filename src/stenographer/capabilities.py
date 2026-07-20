# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import grp
import os
import pwd
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING

import huggingface_hub
import sounddevice

if TYPE_CHECKING:
    from stenographer.config import Config


def detect_session_type() -> str:
    """Return the display-server session type: ``wayland``/``x11``/``unknown``.

    ``XDG_SESSION_TYPE`` is authoritative when set by the session; otherwise
    we fall back to the presence of ``WAYLAND_DISPLAY`` (Wayland) or ``DISPLAY``
    (X11). This is what selects the injection/clipboard backend -- evdev hotkey
    capture is session-agnostic, so only the delivery path cares.
    """
    stype = os.environ.get("XDG_SESSION_TYPE", "").strip().lower()
    if stype in ("wayland", "x11"):
        return stype
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


@dataclass(frozen=True)
class Capabilities:
    has_paste_trigger: bool
    has_clipboard: bool
    has_pw_play: bool
    has_paplay: bool
    has_input_group: bool
    has_mic: bool
    has_asr_model: bool
    session_type: str

    @classmethod
    def probe(cls, cfg: Config) -> Capabilities:
        # Named for the capability, not the tool: injection works via wtype
        # (Wayland) or xdotool (X11), clipboard via wl-copy (Wayland) or
        # xclip/xsel (X11). The concrete backend is picked later, by session
        # type, in the cli factory.
        has_paste_trigger = shutil.which("wtype") is not None or shutil.which("xdotool") is not None
        has_clipboard = (
            shutil.which("wl-copy") is not None
            or shutil.which("xclip") is not None
            or shutil.which("xsel") is not None
        )
        has_pw_play = shutil.which("pw-play") is not None
        has_paplay = shutil.which("paplay") is not None

        if os.getuid() == 0:
            has_input_group = True
        else:
            try:
                user: str | None = os.getlogin()
            except OSError:
                user = None
            if user is None:
                user = pwd.getpwuid(os.getuid()).pw_name
            try:
                input_gid = grp.getgrnam("input").gr_gid
            except KeyError:
                has_input_group = False
            else:
                has_input_group = input_gid in os.getgrouplist(user, os.getgid())

        try:
            has_mic = bool(sounddevice.query_devices(kind="input"))
        except sounddevice.PortAudioError:
            has_mic = False

        try:
            path = huggingface_hub.try_to_load_from_cache(
                repo_id=cfg.asr.model,
                filename="config.json",
            )
            has_asr_model = isinstance(path, str) and bool(path)
        except Exception:
            has_asr_model = False

        return cls(
            has_paste_trigger=has_paste_trigger,
            has_clipboard=has_clipboard,
            has_pw_play=has_pw_play,
            has_paplay=has_paplay,
            has_input_group=has_input_group,
            has_mic=has_mic,
            has_asr_model=has_asr_model,
            session_type=detect_session_type(),
        )
