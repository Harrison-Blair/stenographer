# SPDX-License-Identifier: GPL-3.0-or-later
"""Round-trip rendering and real-filesystem persistence for setup configuration."""

from __future__ import annotations

import os
from dataclasses import replace

import pytest
import tomlkit

from stenographer.lib.config.defaults import default_toml
from stenographer.lib.config.document import ConfigDocument
from stenographer.lib.config.errors import (
    ConfigChangedError,
    ConfigError,
    ConfigPersistenceError,
)
from stenographer.lib.config.models import Config

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


def test_render_materializes_all_24_known_keys():
    rendered = ConfigDocument.loads("").render(Config.defaults())
    root = tomlkit.parse(rendered)["stenographer"]

    assert list(root["hotkey"]) == [
        "binding",
        "device",
        "cancel_binding",
        "mode",
        "hybrid_threshold_seconds",
    ]
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
        "update_check",
        "spectrum_floor_dbfs",
        "sound_pack",
        "log_level",
    ]
    assert sum(len(root[name]) for name in ("hotkey", "audio", "asr", "feedback")) == 24


def test_render_encodes_optional_strings_as_empty_strings():
    rendered = ConfigDocument.loads("").render(Config.defaults())
    root = tomlkit.parse(rendered)["stenographer"]

    assert root["hotkey"]["device"] == ""
    assert root["hotkey"]["cancel_binding"] == "KEY_ESC"
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
            cancel_binding=None,
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
            sound_pack="warm-desk",
        ),
    )

    rendered = ConfigDocument.loads(PRESERVATION_FIXTURE).render(reviewed)

    assert Config.loads(rendered) == reviewed
    assert 'cancel_binding = ""' in rendered


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


def test_defaults_document_renders_the_annotated_template_verbatim(tmp_path):
    """Seen to FAIL against a writer built on ``ConfigDocument.load`` (the
    hand-written comment survived and none of the annotations appeared)."""
    path = tmp_path / "config.toml"
    path.write_text("[stenographer.asr]\nbeam_size = 3 # mine\n", encoding="utf-8")

    rendered = ConfigDocument.defaults(path).render(Config.defaults())

    assert rendered == default_toml()
    assert "# mine" not in rendered


def test_load_reports_an_unreadable_path_without_inventing_defaults(tmp_path):
    # A directory where the config belongs is the mode-independent form of
    # "present but unreadable": silently starting from defaults here would
    # later overwrite whatever the user actually has.
    path = tmp_path / "config.toml"
    path.mkdir()

    with pytest.raises(ConfigError) as failure:
        ConfigDocument.load(path)

    assert "cannot read" in str(failure.value)
    assert str(path) in str(failure.value)


def test_load_reports_a_file_that_is_not_utf8(tmp_path):
    path = tmp_path / "config.toml"
    path.write_bytes(b'[stenographer.asr]\nhotwords = "caf\xe9"\n')

    with pytest.raises(ConfigError) as failure:
        ConfigDocument.load(path)

    assert "cannot decode as UTF-8" in str(failure.value)
    assert path.read_bytes().endswith(b'caf\xe9"\n')


def test_save_writes_the_reviewed_config_and_keeps_the_previous_bytes(tmp_path):
    path = tmp_path / "config.toml"
    original = b"# exact original\n[stenographer.feedback]\nvolume = 0.25 # comment\n"
    path.write_bytes(original)
    document = ConfigDocument.load(path)
    reviewed = replace(document.config, feedback=replace(document.config.feedback, mute=True))

    result = document.save(reviewed)

    assert result.changed is True
    assert result.path == path.resolve()
    assert result.backup_path is not None
    assert result.backup_path.read_bytes() == original
    assert Config.load(path) == reviewed
    assert "# exact original" in path.read_text(encoding="utf-8")
    assert not list(tmp_path.glob("*.tmp"))


def test_save_of_unchanged_bytes_writes_nothing_at_all(tmp_path):
    path = tmp_path / "config.toml"
    Config.write_default(path)
    document = ConfigDocument.load(path)
    before = path.read_bytes()

    result = document.save(document.config)

    assert result.changed is False
    assert result.backup_path is None
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


def test_save_refuses_a_config_edited_since_it_was_loaded(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[stenographer.feedback]\nmute = false\n", encoding="utf-8")
    document = ConfigDocument.load(path)
    edited = "[stenographer.feedback]\nmute = true # edited in another window\n"
    path.write_text(edited, encoding="utf-8")

    with pytest.raises(ConfigChangedError):
        document.save(document.config)

    assert path.read_text(encoding="utf-8") == edited
    assert not list(tmp_path.glob("*.bak-*"))


def test_save_refuses_a_symlink_repointed_since_it_was_loaded(tmp_path):
    first = tmp_path / "first.toml"
    first.write_text("[stenographer.feedback]\nmute = false\n", encoding="utf-8")
    second = tmp_path / "second.toml"
    second.write_text("[stenographer.feedback]\nmute = false\n", encoding="utf-8")
    link = tmp_path / "config.toml"
    link.symlink_to(first.name)
    document = ConfigDocument.load(link)

    link.unlink()
    link.symlink_to(second.name)
    reviewed = replace(document.config, feedback=replace(document.config.feedback, mute=True))

    with pytest.raises(ConfigChangedError):
        document.save(reviewed)

    assert second.read_text(encoding="utf-8") == "[stenographer.feedback]\nmute = false\n"
    assert not list(tmp_path.glob("*.bak-*"))


@pytest.mark.skipif(
    getattr(os, "geteuid", lambda: 1)() == 0, reason="root ignores directory permissions"
)
def test_save_reports_a_parent_directory_it_cannot_create(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.mkdir(mode=0o555)
    path = blocked / "nested" / "config.toml"
    document = ConfigDocument.load(path)
    try:
        with pytest.raises(ConfigPersistenceError) as failure:
            document.save(document.config)
    finally:
        blocked.chmod(0o755)

    assert "cannot create" in str(failure.value)
    assert not path.parent.exists()


def test_save_materializes_a_config_whose_directory_does_not_exist_yet(tmp_path):
    path = tmp_path / "nested" / "deeper" / "config.toml"
    document = ConfigDocument.load(path)

    result = document.save(document.config)

    assert result.changed is True
    assert result.backup_path is None
    assert Config.load(path) == Config.defaults()
    assert path.read_text(encoding="utf-8").startswith("# stenographer configuration.")
