# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure round-trip rendering tests for interactive setup configuration."""

from __future__ import annotations

from dataclasses import replace

import tomlkit

from stenographer.cli.setup_config import ConfigDocument
from stenographer.config import Config

PRESERVATION_FIXTURE = """\
# hand-written preface

[unrelated]
answer = 42 # unrelated inline comment

[stenographer.asr]
# model choice comment
beam_size = 3 # keep this inline comment
silence_threshold = 6e-1 # preserve equivalent hand formatting
mystery = "preserve me"

[stenographer.hotkey] # deliberately after ASR
binding = "KEY_F8"
"""


def test_render_preserves_comments_order_and_unknown_content():
    source = ConfigDocument.loads(PRESERVATION_FIXTURE)
    reviewed = replace(source.config, asr=replace(source.config.asr, beam_size=5))

    rendered = source.render(reviewed)

    assert "# hand-written preface" in rendered
    assert "answer = 42 # unrelated inline comment" in rendered
    assert "# model choice comment" in rendered
    assert "beam_size = 5 # keep this inline comment" in rendered
    assert "silence_threshold = 6e-1 # preserve equivalent hand formatting" in rendered
    assert 'mystery = "preserve me"' in rendered
    assert rendered.index("[stenographer.asr]") < rendered.index("[stenographer.hotkey]")
    assert Config.loads(rendered) == reviewed


def test_render_materializes_all_19_known_keys():
    rendered = ConfigDocument.loads("").render(Config.defaults())
    root = tomlkit.parse(rendered)["stenographer"]

    assert list(root["hotkey"]) == ["binding", "device", "mode"]
    assert list(root["audio"]) == ["input_device", "min_speech_rms", "max_recording_seconds"]
    assert list(root["asr"]) == [
        "model",
        "compute_type",
        "beam_size",
        "hotwords",
        "initial_prompt",
        "vad_filter",
        "silence_threshold",
        "idle_unload_seconds",
        "cpu_threads",
    ]
    assert list(root["feedback"]) == [
        "volume",
        "mute",
        "overlay",
        "spectrum_floor_dbfs",
    ]
    assert sum(len(root[name]) for name in ("hotkey", "audio", "asr", "feedback")) == 19


def test_render_encodes_optional_strings_as_empty_strings():
    rendered = ConfigDocument.loads("").render(Config.defaults())
    root = tomlkit.parse(rendered)["stenographer"]

    assert root["hotkey"]["device"] == ""
    assert root["audio"]["input_device"] == ""
    assert root["asr"]["hotwords"] == ""
    assert root["asr"]["initial_prompt"] == ""


def test_render_round_trips_nondefault_production_config():
    defaults = Config.defaults()
    reviewed = replace(
        defaults,
        hotkey=replace(
            defaults.hotkey,
            binding="KEY_F9",
            device="/dev/input/event7",
            mode="toggle",
        ),
        audio=replace(
            defaults.audio,
            input_device="USB microphone",
            min_speech_rms=0.0,
            max_recording_seconds=45,
        ),
        asr=replace(
            defaults.asr,
            model="local/model",
            compute_type="float32",
            beam_size=7,
            hotwords="Ada, Babbage",
            initial_prompt="Technical dictation.",
            vad_filter=False,
            silence_threshold=0.25,
            idle_unload_seconds=0,
            cpu_threads=4,
        ),
        feedback=replace(
            defaults.feedback,
            volume=0.25,
            mute=True,
            overlay=False,
            spectrum_floor_dbfs=-72.0,
        ),
    )

    rendered = ConfigDocument.loads(PRESERVATION_FIXTURE).render(reviewed)

    assert Config.loads(rendered) == reviewed


def test_render_round_trips_calibrated_spectrum_profile_as_toml_array():
    source = ConfigDocument.loads("")
    profile = tuple(float(-80 + index) for index in range(18))
    reviewed = replace(
        source.config,
        feedback=replace(source.config.feedback, spectrum_floor_dbfs=profile),
    )

    rendered = source.render(reviewed)

    assert tomlkit.parse(rendered)["stenographer"]["feedback"]["spectrum_floor_dbfs"] == list(
        profile
    )
    assert Config.loads(rendered) == reviewed
