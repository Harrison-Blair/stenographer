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


@dataclass(frozen=True)
class Capabilities:
    has_wtype: bool
    has_wl_copy: bool
    has_pw_play: bool
    has_paplay: bool
    has_input_group: bool
    has_mic: bool
    has_asr_model: bool

    @classmethod
    def probe(cls, cfg: Config) -> Capabilities:
        has_wtype = shutil.which("wtype") is not None
        has_wl_copy = shutil.which("wl-copy") is not None
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
            has_input_group = grp.getgrnam("input").gr_gid in os.getgrouplist(user, os.getgid())

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
            has_wtype=has_wtype,
            has_wl_copy=has_wl_copy,
            has_pw_play=has_pw_play,
            has_paplay=has_paplay,
            has_input_group=has_input_group,
            has_mic=has_mic,
            has_asr_model=has_asr_model,
        )
