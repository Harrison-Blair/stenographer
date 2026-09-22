# SPDX-License-Identifier: GPL-3.0-or-later
"""Menu, listing, selection, restart-policy, and command-run tests for sound packs.

The pure halves are asserted directly; ``run`` and ``_post_save`` are driven
over string streams with the configuration document, the pack API, and the host
provider supplied, so no cue is ever played and no service is ever restarted.
"""

from __future__ import annotations

import dataclasses
import io
import pathlib
from types import SimpleNamespace

import pytest

from stenographer.cli.shared.console import Console
from stenographer.cli.sounds import workflow as sounds
from stenographer.cli.sounds.workflow import (
    MenuAction,
    format_menu_lines,
    format_sound_pack_list,
    parse_menu_action,
    parse_sound_pack_choice,
    post_save_lines,
    restart_disposition,
    selection_may_prompt,
)
from stenographer.lib.config.models import Config
from stenographer.lib.platform.host_guidance import HostGuidance

_BUNDLED = ("legacy", "warm-desk", "soft-electronic", "minimal-ui")

# Host prose is an input: every word below differs from the Linux provider's, so
# a hardcoded command in sounds.py cannot pass these cases.
_GUIDANCE = HostGuidance(
    capability_labels={},
    capability_fix_hints={},
    clipboard_fix_hints={},
    clipboard_fix_hint_default="enable a pasteboard",
    service_noun="host agent",
    service_name="steno-agent",
    service_installer="steno-agent install",
    service_unknown_detail="cannot query the agent manager",
    service_start_command="steno-agent start",
    service_restart_command="steno-agent restart",
    service_log_command="steno-agent logs -f",
    hotkey_device_comment="device id; empty auto-detects",
    run_with_config=lambda path: f"STENO_CONFIG={path} stenographer run",
)


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("1", MenuAction("select", 0)),
        (" 5 ", MenuAction("select", 4)),
        ("P2", MenuAction("preview", 1)),
        ("p5", MenuAction("preview", 4)),
        ("Q", MenuAction("cancel")),
    ],
)
def test_menu_action_parses_selection_preview_and_cancel(answer, expected):
    assert parse_menu_action(answer, 5) == expected


@pytest.mark.parametrize("answer", ["", "0", "6", "p", "p0", "p6", "quit", "legacy"])
def test_menu_action_rejects_invalid_input(answer):
    with pytest.raises(ValueError, match="P1-P5"):
        parse_menu_action(answer, 5)


def test_setup_sound_pack_choice_accepts_number_name_and_enter():
    choices = ("legacy", "warm-desk", "soft-electronic", "minimal-ui", "my-pack")

    assert parse_sound_pack_choice("", "minimal-ui", choices) == "minimal-ui"
    assert parse_sound_pack_choice("2", "minimal-ui", choices) == "warm-desk"
    assert parse_sound_pack_choice("MY-PACK", "minimal-ui", choices) == "my-pack"
    with pytest.raises(ValueError, match="available sound-pack"):
        parse_sound_pack_choice("missing", "minimal-ui", choices)


def test_list_marks_available_current_and_effective_pack():
    lines = format_sound_pack_list(
        ("legacy", "warm-desk", "soft-electronic", "minimal-ui", "my-pack"),
        ("legacy", "warm-desk", "soft-electronic", "minimal-ui"),
        current="my-pack",
        effective="my-pack",
    )

    assert lines[-1] == "* my-pack (custom, current, effective)"
    assert lines[0] == "  legacy (bundled)"


def test_list_reports_unavailable_configured_pack_and_effective_fallback():
    lines = format_sound_pack_list(
        ("legacy", "warm-desk", "soft-electronic", "minimal-ui"),
        ("legacy", "warm-desk", "soft-electronic", "minimal-ui"),
        current="gone-pack",
        effective="minimal-ui",
    )

    assert "* minimal-ui (bundled, effective)" in lines
    assert lines[-1] == "  configured: gone-pack (unavailable)"


def test_menu_numbers_every_pack_and_keeps_the_listing_labels():
    lines = format_menu_lines(
        ("legacy", "warm-desk", "my-pack"),
        _BUNDLED,
        current="my-pack",
        effective="my-pack",
    )

    assert lines == [
        "  1. legacy (bundled)",
        "  2. warm-desk (bundled)",
        "  3. my-pack (custom, current, effective)",
    ]


def test_menu_appends_the_unavailable_note_for_a_configured_pack_that_is_gone():
    lines = format_menu_lines(
        ("legacy", "minimal-ui"),
        _BUNDLED,
        current="gone-pack",
        effective="minimal-ui",
    )

    assert lines == [
        "  1. legacy (bundled)",
        "  2. minimal-ui (bundled, effective)",
        "  configured: gone-pack (unavailable)",
    ]


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("none", []),
        ("custom-guidance", ["Custom STENOGRAPHER_CONFIG path: service restart was not offered."]),
        (
            "restart-guidance",
            [
                "Restart the daemon to apply the sound pack; for the standard active service, "
                "run `steno-agent restart`."
            ],
        ),
        (
            "unknown-guidance",
            [
                "Could not determine steno-agent status; restart the daemon manually "
                "to apply the sound pack."
            ],
        ),
        (
            "inactive-guidance",
            [
                "Service is not active; sounds did not start it. "
                "Run `steno-agent start` when ready; the new pack applies when it starts."
            ],
        ),
    ],
)
def test_post_save_guidance_arms_report_and_succeed(action, expected):
    assert post_save_lines(action, _GUIDANCE) == (expected, 0)


def test_post_save_leaves_the_offer_restart_arm_to_the_caller():
    assert post_save_lines("offer-restart", _GUIDANCE) is None


@pytest.mark.parametrize(
    ("changed", "custom", "interactive", "active", "expected"),
    [
        (False, False, True, "active", "none"),
        (True, True, True, "active", "custom-guidance"),
        (True, False, False, "active", "restart-guidance"),
        (True, False, True, "active", "offer-restart"),
        (True, False, True, "inactive", "inactive-guidance"),
        (True, False, True, "failed", "inactive-guidance"),
        (True, False, True, None, "unknown-guidance"),
    ],
)
def test_restart_disposition(changed, custom, interactive, active, expected):
    assert (
        restart_disposition(
            changed=changed,
            custom_config=custom,
            interactive=interactive,
            service_active=active,
        )
        == expected
    )


def test_only_tty_selection_may_offer_restart_prompt():
    assert selection_may_prompt(terminal=True) is True
    assert selection_may_prompt(terminal=False) is False


def _menu(answers: str, packs, *, load, preview, discover):
    stdout, stderr = io.StringIO(), io.StringIO()
    console = Console(io.StringIO(answers), stdout, stderr)
    chosen = sounds._choose_from_menu(
        console,
        Config.defaults(),
        pathlib.Path("/nonexistent-config-dir"),
        packs,
        preview=preview,
        discover=discover,
        load=load,
    )
    return chosen, stdout.getvalue(), stderr.getvalue()


def test_menu_reports_failed_preview_and_reprompts():
    packs = ("legacy", "warm-desk")
    previewed: list[object] = []

    def failing_preview(console, config, pack):
        previewed.append(pack)
        console.error("sound-pack preview failed: no player")
        return False

    chosen, stdout, stderr = _menu(
        "P1\n2\n",
        packs,
        load=lambda name: f"pack:{name}",
        preview=failing_preview,
        discover=lambda: packs,
    )

    assert chosen == "warm-desk"
    assert previewed == ["pack:legacy"]
    assert "sound-pack preview failed: no player" in stderr
    assert stdout.count("Sound packs") == 2


def test_menu_reports_vanished_pack_rediscovers_and_reprompts():
    discoveries = iter([("warm-desk",)])
    previewed: list[object] = []

    def preview(console, config, pack):
        previewed.append(pack)
        return True

    chosen, stdout, stderr = _menu(
        "P1\n1\n",
        ("legacy", "warm-desk"),
        load=lambda name: None if name == "legacy" else f"pack:{name}",
        preview=preview,
        discover=lambda: next(discoveries),
    )

    assert chosen == "warm-desk"
    assert previewed == []
    assert "invalid or unavailable sound pack: legacy" in stderr
    assert "1. legacy" in stdout
    assert "2. warm-desk" in stdout
    assert "1. warm-desk" in stdout


def test_no_argument_non_tty_use_exits_two_before_loading_configuration():
    stderr = io.StringIO()

    assert sounds.run(stdin=io.StringIO(), stdout=io.StringIO(), stderr=stderr) == 2
    assert "requires an interactive terminal" in stderr.getvalue()


def test_sounds_applies_the_loaded_log_level_before_discovery(monkeypatch, tmp_path):
    from stenographer.lib.logging import pipeline as logging_setup

    events: list[str] = []
    defaults = Config.defaults()
    loaded = dataclasses.replace(
        defaults,
        feedback=dataclasses.replace(defaults.feedback, log_level="warning"),
    )
    document = SimpleNamespace(path=tmp_path / "config.toml", config=loaded)
    api = SimpleNamespace(
        BUNDLED_PACKS=("minimal-ui",),
        discover_sound_packs=lambda config_dir: events.append("discover") or ("minimal-ui",),
        effective_sound_pack_name=lambda name, config_dir: "minimal-ui",
    )

    monkeypatch.setattr(sounds, "load_document", lambda *args, **kwargs: document)
    monkeypatch.setattr(sounds, "_sound_pack_api", lambda: api)
    monkeypatch.setattr(
        logging_setup,
        "apply_stderr_level",
        lambda level: events.append(f"level:{level}"),
    )

    assert sounds.run(list_only=True, stdout=io.StringIO(), stderr=io.StringIO()) == 0
    assert events == ["level:warning", "discover"]


class _Terminal(io.StringIO):
    """A stream that claims to be a terminal."""

    def isatty(self) -> bool:
        return True


def _platform(*, service_active="active", restart=(True, ""), probe_error=None):
    class Plat:
        def guidance(self):
            return _GUIDANCE

        def probe_host(self):
            if probe_error is not None:
                raise probe_error
            return SimpleNamespace(service_active=service_active)

        def restart_service(self):
            return restart

    return Plat


def test_menu_spaces_the_listing_after_a_successful_preview():
    packs = ("legacy", "warm-desk")
    previewed: list[object] = []

    def preview(console, config, pack):
        previewed.append(pack)
        return True

    chosen, stdout, stderr = _menu(
        "P1\n2\n",
        packs,
        load=lambda name: f"pack:{name}",
        preview=preview,
        discover=lambda: packs,
    )

    assert chosen == "warm-desk"
    assert previewed == ["pack:legacy"]
    assert stderr == ""
    assert stdout.count("Sound packs") == 2
    # The audition ends the prompt line before the menu is listed again.
    assert "or cancel Q: \nSound packs" in stdout


def _post_save(answers="", **kwargs):
    console = Console(io.StringIO(answers), io.StringIO(), io.StringIO())
    code = sounds._post_save(console, **kwargs)
    return code, console.stdout.getvalue(), console.stderr.getvalue()


def test_post_save_never_probes_the_host_when_nothing_changed(monkeypatch):
    from stenographer.lib import platform as platform_module

    monkeypatch.setattr(
        platform_module,
        "current_platform",
        _platform(probe_error=AssertionError("the host was probed")),
    )

    code, stdout, stderr = _post_save(changed=False, custom_config=False, interactive=True)

    assert (code, stdout, stderr) == (0, "", "")


def test_post_save_reports_an_unreadable_service_status_and_fails(monkeypatch):
    from stenographer.lib import platform as platform_module

    monkeypatch.setattr(
        platform_module,
        "current_platform",
        _platform(probe_error=OSError("systemctl is not on PATH")),
    )

    code, stdout, stderr = _post_save(changed=True, custom_config=False, interactive=True)

    assert code == 1
    assert stderr == (
        "stenographer: could not determine steno-agent status: systemctl is not on PATH\n"
    )
    assert stdout == "Restart the daemon manually to apply the saved sound pack.\n"


def test_post_save_prints_the_guidance_arm_without_prompting(monkeypatch):
    from stenographer.lib import platform as platform_module

    monkeypatch.setattr(platform_module, "current_platform", _platform(service_active="inactive"))

    code, stdout, stderr = _post_save(changed=True, custom_config=False, interactive=True)

    assert code == 0
    assert stdout == (
        "Service is not active; sounds did not start it. "
        "Run `steno-agent start` when ready; the new pack applies when it starts.\n"
    )
    assert stderr == ""


def test_post_save_declined_restart_names_the_command_to_run_later(monkeypatch):
    from stenographer.lib import platform as platform_module

    monkeypatch.setattr(platform_module, "current_platform", _platform())

    code, stdout, stderr = _post_save(
        "n\n",
        changed=True,
        custom_config=False,
        interactive=True,
    )

    assert code == 0
    assert "Restart the active steno-agent to apply the sound pack? [Y/n]: " in stdout
    assert stdout.endswith("Run `steno-agent restart` to apply it later.\n")
    assert stderr == ""


def test_post_save_accepted_restart_reports_the_restart(monkeypatch):
    from stenographer.lib import platform as platform_module

    monkeypatch.setattr(platform_module, "current_platform", _platform())

    code, stdout, stderr = _post_save(
        "\n",
        changed=True,
        custom_config=False,
        interactive=True,
    )

    assert code == 0
    assert stdout.endswith("Restarted steno-agent.\n")
    assert stderr == ""


def test_post_save_failed_restart_reports_the_detail_and_fails(monkeypatch):
    from stenographer.lib import platform as platform_module

    monkeypatch.setattr(
        platform_module,
        "current_platform",
        _platform(restart=(False, "unit not loaded")),
    )

    code, _, stderr = _post_save(
        "y\n",
        changed=True,
        custom_config=False,
        interactive=True,
    )

    assert code == 1
    assert stderr == "stenographer: could not restart steno-agent: unit not loaded\n"


def _api(packs=("legacy", "warm-desk"), *, loadable=("legacy", "warm-desk"), discover=None):
    def discover_sound_packs(config_dir):
        if discover is not None:
            return discover()
        return packs

    return SimpleNamespace(
        BUNDLED_PACKS=("legacy", "warm-desk"),
        discover_sound_packs=discover_sound_packs,
        load_sound_pack=lambda name, config_dir: f"pack:{name}" if name in loadable else None,
        effective_sound_pack_name=lambda name, config_dir: name if name in packs else packs[0],
    )


def _document(tmp_path, saved, *, changed=True, error=None):
    from stenographer.lib.config.save_result import SaveResult

    path = tmp_path / "config.toml"

    class Document:
        def __init__(self):
            self.path = path
            self.config = Config.defaults()

        def save(self, config):
            if error is not None:
                raise error
            saved.append(config)
            return SaveResult(changed, path)

    return Document()


@pytest.fixture
def sounds_run(monkeypatch):
    """Run ``sounds`` with the document, pack API, and log threshold supplied."""

    from stenographer.lib.logging import pipeline as logging_setup

    monkeypatch.delenv("STENOGRAPHER_CONFIG", raising=False)
    monkeypatch.setattr(logging_setup, "apply_stderr_level", lambda level: None)

    def invoke(*, document, api, answers="", terminal=False, **kwargs):
        monkeypatch.setattr(sounds, "load_document", lambda *args, **kw: document)
        monkeypatch.setattr(sounds, "_sound_pack_api", lambda: api)
        stream = _Terminal if terminal else io.StringIO
        stdin, stdout, stderr = stream(answers), stream(), io.StringIO()
        code = sounds.run(stdin=stdin, stdout=stdout, stderr=stderr, **kwargs)
        return code, stdout.getvalue(), stderr.getvalue()

    return invoke


def test_run_returns_the_load_ladders_own_exit_code(sounds_run):
    code, stdout, _ = sounds_run(document=78, api=_api(), list_only=True)

    assert code == 78
    assert stdout == ""


def test_run_reports_a_failed_discovery_and_fails(sounds_run, tmp_path):
    def explode():
        raise OSError("permission denied")

    code, _, stderr = sounds_run(
        document=_document(tmp_path, []),
        api=_api(discover=explode),
        list_only=True,
    )

    assert code == 1
    assert stderr == "stenographer: could not discover sound packs: permission denied\n"


def test_run_treats_an_interrupted_discovery_as_an_interruption(sounds_run, tmp_path):
    def interrupt():
        raise KeyboardInterrupt

    code, _, stderr = sounds_run(
        document=_document(tmp_path, []),
        api=_api(discover=interrupt),
        list_only=True,
    )

    assert code == 130
    assert stderr == "stenographer: sounds interrupted\n"


def test_run_lists_every_pack_without_touching_the_configuration(sounds_run, tmp_path):
    saved: list[Config] = []

    code, stdout, _ = sounds_run(
        document=_document(tmp_path, saved),
        api=_api(),
        list_only=True,
    )

    assert code == 0
    assert saved == []
    assert "legacy (bundled" in stdout
    assert "warm-desk (bundled" in stdout


def test_run_refuses_to_preview_a_pack_that_is_not_available(sounds_run, tmp_path):
    code, _, stderr = sounds_run(
        document=_document(tmp_path, []),
        api=_api(),
        preview_name="gone-pack",
    )

    assert code == 2
    assert stderr == "stenographer: invalid or unavailable sound pack: gone-pack\n"


@pytest.mark.parametrize(("succeeds", "expected"), [(True, 0), (False, 1)])
def test_run_preview_exit_code_follows_the_audition(
    sounds_run,
    monkeypatch,
    tmp_path,
    succeeds,
    expected,
):
    auditioned: list[object] = []
    monkeypatch.setattr(
        sounds,
        "_preview",
        lambda console, config, pack: auditioned.append(pack) or succeeds,
    )

    code, _, _ = sounds_run(
        document=_document(tmp_path, []),
        api=_api(),
        preview_name="warm-desk",
    )

    assert code == expected
    assert auditioned == ["pack:warm-desk"]


def test_run_refuses_to_select_a_pack_that_is_not_available(sounds_run, tmp_path):
    saved: list[Config] = []

    code, _, stderr = sounds_run(
        document=_document(tmp_path, saved),
        api=_api(),
        pack_name="gone-pack",
    )

    assert code == 2
    assert saved == []
    assert stderr == "stenographer: invalid or unavailable sound pack: gone-pack\n"


def test_run_saves_the_named_pack_and_reports_the_save(sounds_run, monkeypatch, tmp_path):
    from stenographer.lib import platform as platform_module

    monkeypatch.setattr(platform_module, "current_platform", _platform(service_active="inactive"))
    saved: list[Config] = []

    code, stdout, _ = sounds_run(
        document=_document(tmp_path, saved),
        api=_api(),
        pack_name="warm-desk",
    )

    assert code == 0
    assert [config.feedback.sound_pack for config in saved] == ["warm-desk"]
    assert f"Selected sound pack warm-desk; saved {tmp_path / 'config.toml'}" in stdout


def test_run_reports_a_refused_save_and_fails(sounds_run, tmp_path):
    from stenographer.lib.config.errors import ConfigPersistenceError

    code, _, stderr = sounds_run(
        document=_document(tmp_path, [], error=ConfigPersistenceError("cannot replace config")),
        api=_api(),
        pack_name="warm-desk",
    )

    assert code == 1
    assert stderr == "stenographer: cannot replace config\n"


def test_run_menu_selection_saves_the_chosen_pack(sounds_run, monkeypatch, tmp_path):
    from stenographer.lib import platform as platform_module

    monkeypatch.setattr(platform_module, "current_platform", _platform(service_active="inactive"))
    saved: list[Config] = []

    code, _, _ = sounds_run(
        document=_document(tmp_path, saved),
        api=_api(),
        answers="2\n",
        terminal=True,
    )

    assert code == 0
    assert [config.feedback.sound_pack for config in saved] == ["warm-desk"]


def test_run_cancelled_menu_leaves_the_configuration_alone(sounds_run, tmp_path):
    saved: list[Config] = []

    code, stdout, _ = sounds_run(
        document=_document(tmp_path, saved),
        api=_api(),
        answers="q\n",
        terminal=True,
    )

    assert code == 0
    assert saved == []
    assert stdout.endswith("Sound-pack selection cancelled; configuration was not changed.\n")


def test_run_treats_an_exhausted_menu_input_as_an_interruption(sounds_run, tmp_path):
    code, _, stderr = sounds_run(
        document=_document(tmp_path, []),
        api=_api(),
        answers="",
        terminal=True,
    )

    assert code == 130
    assert stderr == "stenographer: sounds interrupted\n"
