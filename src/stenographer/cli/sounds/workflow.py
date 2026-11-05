# SPDX-License-Identifier: GPL-3.0-or-later
"""Sound-pack listing, audition, selection, and restart policy."""

from __future__ import annotations

import dataclasses
import pathlib
from collections.abc import Sequence
from typing import TextIO

from stenographer.cli.shared.console import Console
from stenographer.cli.shared.terminal import (
    ask_yes_no,
    custom_config_selected,
    load_document,
    open_console,
    report_save,
    require_interactive,
    restart_service,
)
from stenographer.lib.config.errors import ConfigError, ConfigPersistenceError
from stenographer.lib.config.models import Config
from stenographer.lib.sounds import packs as sound_packs


@dataclasses.dataclass(frozen=True, slots=True)
class MenuAction:
    """A validated sound-menu response."""

    kind: str
    index: int | None = None


def _preview(console: Console, config: Config, pack: object) -> bool:
    from stenographer.lib.platform import current_platform
    from stenographer.lib.sounds import playback

    try:
        player = current_platform().cue_player()
    except Exception as exc:
        console.error(f"could not initialize cue playback: {exc}")
        return False
    if player is None:
        console.error("no supported cue player is available")
        return False
    try:
        playback.preview_sound_pack(pack, player, playback.preview_volume(config.feedback))
    except Exception as exc:
        console.error(f"sound-pack preview failed: {exc}")
        return False
    return True


def parse_menu_action(text: str, choice_count: int) -> MenuAction:
    """Parse number-to-select, ``P<number>``-to-preview, or ``Q``-to-cancel."""

    value = text.strip().casefold()
    if value == "q":
        return MenuAction("cancel")
    kind = "preview" if value.startswith("p") else "select"
    number = value[1:] if kind == "preview" else value
    if number.isdecimal() and 1 <= int(number) <= choice_count:
        return MenuAction(kind, int(number) - 1)
    raise ValueError(f"enter 1-{choice_count}, P1-P{choice_count}, or Q")


def _pack_description(
    pack: str,
    bundled_names: frozenset[str],
    *,
    current: str,
    effective: str | None,
) -> str:
    """Render one pack's name with its source and current/effective labels."""

    labels = ["bundled" if pack in bundled_names else "custom"]
    if pack == current:
        labels.append("current")
    if pack == effective:
        labels.append("effective")
    return f"{pack} ({', '.join(labels)})"


def format_pack_lines(
    packs: Sequence[str],
    bundled: Sequence[str],
    *,
    current: str,
    effective: str | None,
    numbered: bool,
) -> list[str]:
    """Render pack names and labels for the list or the numbered menu."""
    bundled_names = frozenset(bundled)
    lines = []
    for number, pack in enumerate(packs, 1):
        prefix = f"  {number}. " if numbered else f"{'*' if pack == effective else ' '} "
        lines.append(
            prefix + _pack_description(pack, bundled_names, current=current, effective=effective)
        )
    if current not in packs:
        lines.append(f"  configured: {current} (unavailable)")
    return lines


def _effective_name(config: Config, config_dir: pathlib.Path) -> str | None:
    return sound_packs.effective_sound_pack_name(config.feedback.sound_pack, config_dir)


def _choose_from_menu(
    console: Console,
    config: Config,
    config_dir: pathlib.Path,
    packs: Sequence[str],
) -> str | None:
    """Loop until a pack is selected or the menu is cancelled."""

    while True:
        if not packs:
            console.error(
                "no valid sound packs available; restore bundled assets "
                "or install a valid custom pack"
            )
            return None
        console.write("Sound packs")
        for line in format_pack_lines(
            packs,
            sound_packs.BUNDLED_PACKS,
            current=config.feedback.sound_pack,
            effective=_effective_name(config, config_dir),
            numbered=True,
        ):
            console.write(line)
        count = len(packs)
        action = console.validated(
            f"Select 1-{count}, preview P1-P{count}, or cancel Q: ",
            lambda text, count=count: parse_menu_action(text, count),
        )
        if action.kind == "cancel":
            return None
        selected = packs[action.index]
        if action.kind == "select":
            return selected
        pack = sound_packs.load_sound_pack(selected, config_dir)
        if pack is None:
            console.error(f"invalid or unavailable sound pack: {selected}")
            packs = sound_packs.discover_sound_packs(config_dir)
        elif _preview(console, config, pack):
            console.write()


def _post_save(
    console: Console,
    *,
    changed: bool,
    custom_config: bool,
    interactive: bool,
) -> int:
    from stenographer.lib.platform import current_platform

    guidance = current_platform().guidance()
    if not changed:
        return 0
    if custom_config:
        console.write("Custom STENOGRAPHER_CONFIG path: service restart was not offered.")
        return 0
    if not interactive:
        console.write(
            "Restart the daemon to apply the sound pack; for the standard active service, run "
            f"`{guidance.service_restart_command}`."
        )
        return 0
    try:
        service_active = current_platform().probe_host().service_active
    except Exception as exc:
        console.error(f"could not determine {guidance.service_name} status: {exc}")
        console.write("Restart the daemon manually to apply the saved sound pack.")
        return 1
    if service_active is None:
        console.write(
            f"Could not determine {guidance.service_name} status; restart the daemon manually "
            "to apply the sound pack."
        )
        return 0
    if service_active != "active":
        console.write(
            "Service is not active; sounds did not start it. "
            f"Run `{guidance.service_start_command}` when ready; "
            "the new pack applies when it starts."
        )
        return 0
    if not ask_yes_no(
        console,
        f"Restart the active {guidance.service_name} to apply the sound pack?",
        default=True,
    ):
        console.write(f"Run `{guidance.service_restart_command}` to apply it later.")
        return 0
    return 0 if restart_service(console) else 1


def run(
    *,
    pack_name: str | None = None,
    list_only: bool = False,
    preview_name: str | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run ``stenographer sounds`` in direct, listing, preview, or menu mode."""

    console = open_console(stdin, stdout, stderr)
    menu_mode = pack_name is None and not list_only and preview_name is None
    interactive = console.interactive
    gate = require_interactive(
        console,
        "sounds requires an interactive terminal when no pack or option is given",
        when=menu_mode,
    )
    if gate is not None:
        return gate

    loaded = load_document(
        console,
        interrupt_message="sounds interrupted",
        blank_line_before_interrupt=False,
    )
    if isinstance(loaded, int):
        return loaded
    document = loaded
    from stenographer.lib.logging.pipeline import apply_stderr_level

    apply_stderr_level(document.config.feedback.log_level)

    config_dir = document.path.parent
    try:
        packs = sound_packs.discover_sound_packs(config_dir)
    except KeyboardInterrupt:
        console.error("sounds interrupted")
        return 130
    except Exception as exc:
        console.error(f"could not discover sound packs: {exc}")
        return 1

    try:
        if list_only:
            for line in format_pack_lines(
                packs,
                sound_packs.BUNDLED_PACKS,
                current=document.config.feedback.sound_pack,
                effective=_effective_name(document.config, config_dir),
                numbered=False,
            ):
                console.write(line)
            return 0

        if preview_name is not None:
            pack = sound_packs.load_sound_pack(preview_name, config_dir)
            if pack is None:
                console.error(f"invalid or unavailable sound pack: {preview_name}")
                return 2
            return 0 if _preview(console, document.config, pack) else 1

        selected = pack_name
        if menu_mode:
            selected = _choose_from_menu(console, document.config, config_dir, packs)
            if selected is None:
                console.write("Sound-pack selection cancelled; configuration was not changed.")
                return 0
        if sound_packs.load_sound_pack(selected, config_dir) is None:
            console.error(f"invalid or unavailable sound pack: {selected}")
            return 2

        reviewed = dataclasses.replace(
            document.config,
            feedback=dataclasses.replace(document.config.feedback, sound_pack=selected),
        )
        try:
            result = document.save(reviewed)
        except (ConfigPersistenceError, ConfigError) as exc:
            console.error(str(exc))
            return 1
        report_save(
            console,
            result,
            saved_prefix=f"Selected sound pack {selected}; saved",
            unchanged_message=f"Sound pack {selected} is already selected; no file was written.",
        )
        return _post_save(
            console,
            changed=result.changed,
            custom_config=custom_config_selected(),
            interactive=interactive,
        )
    except (KeyboardInterrupt, EOFError):
        console.write()
        console.error("sounds interrupted")
        return 130
