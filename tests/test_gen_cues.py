# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for :mod:`scripts.gen_cues` (cue synthesis)."""

from __future__ import annotations

import importlib.util
import pathlib

_SPEC = importlib.util.spec_from_file_location(
    "gen_cues", pathlib.Path(__file__).parent.parent / "scripts" / "gen_cues.py"
)
assert _SPEC is not None and _SPEC.loader is not None
gen_cues = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gen_cues)

SAMPLE_RATE = gen_cues.SAMPLE_RATE


def test_build_cues_excludes_prompt_variants() -> None:
    cues = gen_cues.build_cues(SAMPLE_RATE)

    for prompt_name in ("ptt_on_prompt", "ptt_off_prompt", "toggle_on_prompt", "toggle_off_prompt"):
        assert prompt_name not in cues
