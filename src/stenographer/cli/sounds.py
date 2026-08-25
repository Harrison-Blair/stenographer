# SPDX-License-Identifier: GPL-3.0-or-later
"""Sound-pack listing, audition, selection, and restart policy."""

from __future__ import annotations

import dataclasses
import pathlib
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, TextIO

from stenographer.cli.console import (
    Console,
    ask_yes_no,
    custom_config_selected,
    load_document,
    open_console,
    report_save,
    require_interactive,
    restart_service,
)
from stenographer.cli.setup_config import ConfigPersistenceError
from stenographer.config import Config, ConfigError

if TYPE_CHECKING:
    from stenographer.platform.base import HostGuidance


@dataclasses.dataclass(frozen=True, slots=True)
class MenuAction:
    """A validated sound-menu response."""

    kind: str
    index: int | None = None


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


def parse_sound_pack_choice(text: str, current: str, choices: Sequence[str]) -> str:
    """Parse a setup selection by number or case-insensitive pack name."""

    value = text.strip()
    if not value:
        return current
    if value.isdecimal() and 1 <= int(value) <= len(choices):
        return choices[int(value) - 1]
    matches = [choice for choice in choices if choice.casefold() == value.casefold()]
    if matches:
        return matches[0]
    raise ValueError(f"choose a number from 1-{len(choices)} or an available sound-pack name")


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


def _unavailable_line(current: str) -> str:
    """The trailing note for a configured pack that is not among the available ones."""

    return f"  configured: {current} (unavailable)"


def format_sound_pack_list(
    packs: Sequence[str],
    bundled: Sequence[str],
    *,
    current: str,
    effective: str | None,
) -> list[str]:
    """Render available packs, their source, and current/effective markers."""

    bundled_names = frozenset(bundled)
    lines = [
        f"{'*' if pack == effective else ' '} "
        f"{_pack_description(pack, bundled_names, current=current, effective=effective)}"
        for pack in packs
    ]
    if current not in packs:
        lines.append(_unavailable_line(current))
    return lines


def format_menu_lines(
    packs: Sequence[str],
    bundled: Sequence[str],
    *,
    current: str,
    effective: str | None,
) -> list[str]:
    """Render the numbered selection menu: one line per pack, then any unavailable note.

    The menu numbers the choices instead of marking the effective pack, but names
    and labels stay identical to the listing's.
    """

    bundled_names = frozenset(bundled)
    lines = [
        f"  {number}. "
        f"{_pack_description(pack, bundled_names, current=current, effective=effective)}"
        for number, pack in enumerate(packs, 1)
    ]
    if current not in packs:
        lines.append(_unavailable_line(current))
    return lines


def restart_disposition(
    *,
    changed: bool,
    custom_config: bool,
    interactive: bool,
    service_active: str | None,
) -> str:
    """Return the post-save restart action without performing host I/O."""

    if not changed:
        return "none"
    if custom_config:
        return "custom-guidance"
    if not interactive:
        return "restart-guidance"
    if service_active == "active":
        return "offer-restart"
    if service_active is None:
        return "unknown-guidance"
    return "inactive-guidance"


def post_save_lines(action: str, guidance: HostGuidance) -> tuple[list[str], int] | None:
    """Render the guidance a non-interactive restart disposition prints, with its exit code.

    ``None`` means the disposition is not one of the print-and-return arms —
    today only ``offer-restart``, whose prompt I/O stays with the caller.
    """

    if action == "none":
        return [], 0
    if action == "custom-guidance":
        return ["Custom STENOGRAPHER_CONFIG path: service restart was not offered."], 0
    if action == "restart-guidance":
        return [
            "Restart the daemon to apply the sound pack; for the standard active service, run "
            f"`{guidance.service_restart_command}`."
        ], 0
    if action == "unknown-guidance":
        return [
            f"Could not determine {guidance.service_name} status; restart the daemon manually "
            "to apply the sound pack."
        ], 0
    if action == "inactive-guidance":
        return [
            "Service is not active; sounds did not start it. "
            f"Run `{guidance.service_start_command}` when ready; "
            "the new pack applies when it starts."
        ], 0
    return None


def selection_may_prompt(*, terminal: bool) -> bool:
    """Menu and direct selections may prompt after saving only on a terminal."""

    return terminal


def _sound_pack_api():
    from stenographer.delivery import feedback

    return feedback


def _effective_name(config: Config, config_dir: pathlib.Path) -> str | None:
    return _sound_pack_api().effective_sound_pack_name(config.feedback.sound_pack, config_dir)


def _preview(console: Console, config: Config, pack: object) -> bool:
    from stenographer.platform import current_platform

    api = _sound_pack_api()
    try:
        player = current_platform().cue_player()
    except Exception as exc:
        console.error(f"could not initialize cue playback: {exc}")
        return False
    if player is None:
        console.error("no supported cue player is available")
        return False
    try:
        api.preview_sound_pack(pack, player, api.preview_volume(config.feedback))
    except Exception as exc:
        console.error(f"sound-pack preview failed: {exc}")
        return False
    return True


def _choose_from_menu(
    console: Console,
    config: Config,
    config_dir: pathlib.Path,
    packs: Sequence[str],
    *,
    preview: Callable[[Console, Config, object], bool] = _preview,
    discover: Callable[[], Sequence[str]] | None = None,
    load: Callable[[str], object] | None = None,
) -> str | None:
    """Loop until a pack is selected or the menu is cancelled.

    A failed preview or a pack that vanished is reported and the menu re-prompts;
    the injectable callables exist so the loop stays testable without playback.
    """

    api = _sound_pack_api()

    def discover_packs() -> Sequence[str]:
        return api.discover_sound_packs(config_dir) if discover is None else discover()

    def load_pack(name: str) -> object:
        return api.load_sound_pack(name, config_dir) if load is None else load(name)

    while True:
        console.write("Sound packs")
        for line in format_menu_lines(
            packs,
            api.BUNDLED_PACKS,
            current=config.feedback.sound_pack,
            effective=_effective_name(config, config_dir),
        ):
            console.write(line)
        count = len(packs)
        action = console.validated(
            f"Select 1-{count}, preview P1-P{count}, or cancel Q: ",
            lambda text, count=count: parse_menu_action(text, count),
        )
        assert isinstance(action, MenuAction)
        if action.kind == "cancel":
            return None
        assert action.index is not None
        selected = packs[action.index]
        if action.kind == "select":
            return selected
        pack = load_pack(selected)
        if pack is None:
            console.error(f"invalid or unavailable sound pack: {selected}")
            packs = discover_packs()
        elif preview(console, config, pack):
            console.write()


def _post_save(
    console: Console,
    *,
    changed: bool,
    custom_config: bool,
    interactive: bool,
) -> int:
    from stenographer.platform import current_platform

    guidance = current_platform().guidance()
    service_active: str | None = None
    if changed and interactive and not custom_config:
        try:
            service_active = current_platform().probe_host().service_active
        except Exception as exc:
            console.error(f"could not determine {guidance.service_name} status: {exc}")
            console.write("Restart the daemon manually to apply the saved sound pack.")
            return 1

    action = restart_disposition(
        changed=changed,
        custom_config=custom_config,
        interactive=interactive,
        service_active=service_active,
    )
    reported = post_save_lines(action, guidance)
    if reported is not None:
        lines, exit_code = reported
        for line in lines:
            console.write(line)
        return exit_code
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
    from stenographer.utils.logging_setup import apply_stderr_level

    apply_stderr_level(document.config.feedback.log_level)

    config_dir = document.path.parent
    api = _sound_pack_api()
    try:
        packs = api.discover_sound_packs(config_dir)
    except KeyboardInterrupt:
        console.error("sounds interrupted")
        return 130
    except Exception as exc:
        console.error(f"could not discover sound packs: {exc}")
        return 1

    try:
        if list_only:
            for line in format_sound_pack_list(
                packs,
                api.BUNDLED_PACKS,
                current=document.config.feedback.sound_pack,
                effective=_effective_name(document.config, config_dir),
            ):
                console.write(line)
            return 0

        if preview_name is not None:
            pack = api.load_sound_pack(preview_name, config_dir)
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
        assert selected is not None
        if api.load_sound_pack(selected, config_dir) is None:
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
            interactive=selection_may_prompt(terminal=interactive),
        )
    except (KeyboardInterrupt, EOFError):
        console.write()
        console.error("sounds interrupted")
        return 130
