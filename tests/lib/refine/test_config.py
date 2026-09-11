# SPDX-License-Identifier: GPL-3.0-or-later
"""``[stenographer.refine]``: defaults, validation, and the preservation round trip."""

from __future__ import annotations

from dataclasses import replace

import pytest
import tomlkit

from stenographer.lib.config.document import ConfigDocument
from stenographer.lib.config.errors import ConfigError
from stenographer.lib.config.models import Config, RefineConfig
from stenographer.lib.refine.prompt import DEFAULT_MODEL, DEFAULT_STRUCTURED_OUTPUT


def test_the_stage_ships_off_and_loopback():
    section = Config.defaults().refine

    assert section.enabled is False
    assert section.host == "http://127.0.0.1:11434"
    assert section.model == DEFAULT_MODEL
    assert section.min_words == 10
    assert section.structured_output is DEFAULT_STRUCTURED_OUTPUT


def test_a_config_written_before_refine_existed_loads_without_migration():
    """Every key defaults, so an existing file keeps working untouched and the
    stage stays off for a user who never asked for it."""
    cfg = Config.loads('[stenographer.asr]\nmodel = "local/model"\n')

    assert cfg.refine == RefineConfig()


def test_enabling_the_stage_does_not_require_restating_the_section():
    cfg = Config.loads("[stenographer.refine]\nenabled = true\n")

    assert cfg.refine.enabled is True
    assert cfg.refine.model == DEFAULT_MODEL


def test_a_host_without_a_scheme_is_normalized_rather_than_rejected():
    cfg = Config.loads('[stenographer.refine]\nhost = "127.0.0.1:11434/"\n')

    assert cfg.refine.host == "http://127.0.0.1:11434"


@pytest.mark.parametrize(
    ("toml_text", "key"),
    [
        ('[stenographer.refine]\nenabled = "yes"\n', "refine.enabled"),
        ('[stenographer.refine]\nhost = "ftp://host:11434"\n', "refine.host"),
        ('[stenographer.refine]\nhost = ""\n', "refine.host"),
        ("[stenographer.refine]\nhost = 11434\n", "refine.host"),
        ('[stenographer.refine]\nmodel = "  "\n', "refine.model"),
        ("[stenographer.refine]\nmin_words = 0\n", "refine.min_words"),
        ("[stenographer.refine]\nmin_words = 1.5\n", "refine.min_words"),
        ('[stenographer.refine]\nstructured_output = "on"\n', "refine.structured_output"),
    ],
)
def test_a_rejected_value_names_its_own_key(toml_text, key):
    with pytest.raises(ConfigError) as failure:
        Config.loads(toml_text)
    assert failure.value.key == key


def test_a_scalar_refine_section_is_a_scoped_error():
    with pytest.raises(ConfigError) as failure:
        Config.loads("[stenographer]\nrefine = 1\n")
    assert failure.value.key == "refine"


def test_the_annotated_template_ships_the_section_off():
    from stenographer.lib.config.defaults import default_toml

    rendered = default_toml()

    assert "[stenographer.refine]" in rendered
    assert Config.loads(rendered).refine == RefineConfig()
    # The privacy statement the section's one dangerous key needs.
    assert "leave the network" in rendered or "over the network" in rendered


def test_render_materializes_every_refine_key_in_declaration_order():
    rendered = ConfigDocument.loads("").render(Config.defaults())
    section = tomlkit.parse(rendered)["stenographer"]["refine"]

    assert list(section) == ["enabled", "host", "model", "min_words", "structured_output"]


def test_save_round_trips_a_configured_refine_section_through_preservation():
    """Seen to FAIL before ``refine`` joined ``Config.loads``'s section tuple:
    the rendered document reloaded with the defaults and ``render`` raised."""
    source = ConfigDocument.loads(
        "# hand-written preface\n[stenographer.refine]\nenabled = true # mine\n"
    )
    reviewed = replace(
        source.config,
        refine=replace(
            source.config.refine,
            enabled=True,
            host="http://192.168.1.5:11434",
            model="some/other:tag",
            min_words=25,
            structured_output=False,
        ),
    )

    rendered = source.render(reviewed)

    assert Config.loads(rendered) == reviewed
    assert "# hand-written preface" in rendered
    assert "enabled = true # mine" in rendered


def test_an_upper_case_scheme_is_accepted_and_stored_folded():
    cfg = Config.loads('[stenographer.refine]\nhost = "HTTP://127.0.0.1:11434"\n')

    assert cfg.refine.host == "http://127.0.0.1:11434"


@pytest.mark.parametrize("host", ["http://", "https://", "http:///api"])
def test_a_host_that_names_no_server_is_refused(host):
    with pytest.raises(ConfigError) as failure:
        Config.loads(f'[stenographer.refine]\nhost = "{host}"\n')
    assert failure.value.key == "refine.host"


@pytest.mark.parametrize(
    "host",
    ["http://user:secret@ollama.example.com:11434", "http://token@127.0.0.1:11434"],
)
def test_credentials_in_the_host_are_refused_rather_than_carried(host):
    """Userinfo in the URL would be a secret living in a config file that the
    daemon then echoes at start. Ollama has no authentication to use it for."""
    with pytest.raises(ConfigError) as failure:
        Config.loads(f'[stenographer.refine]\nhost = "{host}"\n')
    assert failure.value.key == "refine.host"
