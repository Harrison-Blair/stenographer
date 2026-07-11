# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for :mod:`scripts.gen_cues` (cue synthesis)."""

from __future__ import annotations

import importlib.util
import pathlib

import numpy as np

_SPEC = importlib.util.spec_from_file_location(
    "gen_cues", pathlib.Path(__file__).parent.parent / "scripts" / "gen_cues.py"
)
assert _SPEC is not None and _SPEC.loader is not None
gen_cues = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gen_cues)

SAMPLE_RATE = gen_cues.SAMPLE_RATE


def test_build_cues_includes_pitched_down_prompt_variants() -> None:
    cues = gen_cues.build_cues(SAMPLE_RATE)

    # Single-beep cues: pitched-down variant is exactly the base tone's
    # frequency divided by four, same duration/dBFS.
    for prompt_name, base_freq in (("ptt_on_prompt", 220.0), ("toggle_on_prompt", 110.0)):
        assert prompt_name in cues
        expected = gen_cues.tone(base_freq, 0.080, gen_cues.DBFS_BEEP, SAMPLE_RATE)
        np.testing.assert_array_equal(cues[prompt_name], expected)

    # Double-beep cues: same structure (beep, gap, beep) as their base tone,
    # just at a quarter of the frequency.
    for prompt_name, base_freq in (("ptt_off_prompt", 220.0), ("toggle_off_prompt", 110.0)):
        assert prompt_name in cues
        expected = np.concatenate(
            [
                gen_cues.tone(base_freq, 0.080, gen_cues.DBFS_BEEP, SAMPLE_RATE),
                gen_cues.silence(gen_cues.GAP_S, SAMPLE_RATE),
                gen_cues.tone(base_freq, 0.080, gen_cues.DBFS_BEEP, SAMPLE_RATE),
            ]
        )
        np.testing.assert_array_equal(cues[prompt_name], expected)

    # Duration (sample count) is unchanged between each base tone and its
    # pitched-down variant -- only frequency changes.
    for prompt_name, base_name in (
        ("ptt_on_prompt", "ptt_on"),
        ("toggle_on_prompt", "toggle_on"),
        ("ptt_off_prompt", "ptt_off"),
        ("toggle_off_prompt", "toggle_off"),
    ):
        assert cues[prompt_name].shape == cues[base_name].shape
