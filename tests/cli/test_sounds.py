# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure menu, listing, setup-choice, and restart-policy tests for sound packs."""

from __future__ import annotations

import io
import pathlib

import pytest

from stenographer.cli import sounds
from stenographer.cli.console import Console
from stenographer.cli.sounds import (
    MenuAction,
    format_menu_lines,
    format_sound_pack_list,
    parse_menu_action,
    parse_sound_pack_choice,
    post_save_lines,
    restart_disposition,
    selection_may_prompt,
)
from stenographer.config import Config
from stenographer.platform.base import HostGuidance

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
