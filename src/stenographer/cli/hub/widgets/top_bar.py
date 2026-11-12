# SPDX-License-Identifier: GPL-3.0-or-later
"""The top line of every screen: navigation with badges, then the engine status."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.containers import Horizontal
from textual.widgets import Static

from stenographer.cli.hub.widgets.button import HubButton
from stenographer.cli.hub.widgets.status_token import StatusToken
from stenographer.cli.hub.widgets.tier import tier_for
from stenographer.cli.hub.widgets.update_changed import update_changed

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from stenographer.cli.hub.engine_status import EngineStatus

_ACCENT_BOLD = "bold #5fd7ff"
_DIM = StatusToken.TONES["dim"]
_STATE_TONES = {"labelling": "warn", "transcribing": "warn", "ready": "ok", "idle": "dim"}
# Slot widths, each with its trailing gap: the clock, the Library count and the Settings badge.
_CLOCK_SLOT = {"wide": 11, "medium": 11, "narrow": 2}
_COUNT_SLOT = 3
_BADGE_SLOT = 2
_MODEL_SLOT = 15
_STATUS_SLOT = {"wide": 17, "medium": 17, "narrow": 12}
_CPU_SLOT = 4
_RAM_SLOT = 5
# Engine values in the order they drop as the width decreases; the status always stays.
_DROP_ORDER = ("model", "ram", "cpu")


class EngineLine(Static):
    """Show model, status, cpu and ram in fixed slots; drop values that do not fit."""

    def __init__(self, **kwargs) -> None:
        super().__init__("", markup=False, **kwargs)
        self.status: EngineStatus | None = None

    def show(self, status: EngineStatus) -> None:
        self.status = status
        self._draw()

    def on_resize(self) -> None:
        self._draw()

    def _draw(self) -> None:
        if self.status is not None:
            tier = tier_for(self.app.size.width)
            update_changed(self, engine_text(self.status, tier, self.content_size.width))


class TopBar(Horizontal):
    """Show one button per screen and one ``EngineStatus`` snapshot; ``▶`` marks the screen.

    Each changing value has a slot of fixed width, so nothing beside it moves.
    """

    DEFAULT_CSS = """
    TopBar {
        height: 1;
        padding: 0 1;
    }
    TopBar #top-engine {
        width: 1fr;
        height: 1;
        text-align: right;
        text-wrap: nowrap;
    }
    """
    SCREENS = (("record", "Record"), ("library", "Library"), ("settings", "Settings"))

    def compose(self) -> ComposeResult:
        for name, _label in self.SCREENS:
            yield HubButton("", action=f"show_screen('{name}')", tight=True, id=f"nav-{name}")
        yield EngineLine(id="top-engine")

    def show(self, current: str, badges: dict, status: EngineStatus) -> None:
        """Draw the navigation of screen ``current`` and the engine snapshot.

        ``badges`` may hold ``record`` (glyph, clock, tone), ``library`` (entry
        count) and ``settings`` (badge text, tone).
        """
        tier = tier_for(self.app.size.width)
        for index, (name, label) in enumerate(self.SCREENS, start=1):
            button = self.query_one(f"#nav-{name}", HubButton)
            text = self.nav_text(
                f"{index} {label}", name, badges.get(name), selected=name == current, tier=tier
            )
            if str(button.label) != text.plain:
                button.set_label(text)
        self.query_one("#top-engine", EngineLine).show(status)

    @staticmethod
    def nav_text(label: str, name: str, badge, *, selected: bool, tier: str) -> Text:
        """Return one navigation label with its badge slot; ``▶`` or two blanks lead it."""
        text = Text("▶ " if selected else "  ", style=_ACCENT_BOLD if selected else "")
        text.append(f"{label} ")
        if name == "record":
            slot = _CLOCK_SLOT[tier]
            if badge is not None:
                glyph, clock, tone = badge
                shown = glyph if tier == "narrow" else f"{glyph} {clock}"
                text.append(shown, style=StatusToken.TONES[tone])
                text.append(" " * (slot - len(shown)))
            else:
                text.append(" " * slot)
        elif name == "library":
            if tier != "narrow":
                count = "" if badge is None else str(badge)
                text.append(f"{count:>{_COUNT_SLOT}} ")
        elif badge is not None:
            word, tone = badge
            text.append(f"{word:<{_BADGE_SLOT}}", style=StatusToken.TONES[tone])
            text.append(" ")
        else:
            text.append(" " * (_BADGE_SLOT + 1))
        return text


def engine_text(status: EngineStatus, tier: str, width: int) -> Text:
    """Return model, status and gauges in their slots; drop values until the rest fits ``width``.

    A dash shows a gauge before its first sample. The narrow tier shows the first word of the
    status only.
    """
    shown = set(_DROP_ORDER)
    parts = _engine_parts(status, tier)
    for name in _DROP_ORDER:
        if sum(part.cell_len for key, part in parts if key in shown or key == "status") <= width:
            break
        shown.discard(name)
    text = Text(no_wrap=True)
    for key, part in parts:
        if key in shown or key == "status":
            text.append_text(part)
    return text


def _engine_parts(status: EngineStatus, tier: str) -> list[tuple[str, Text]]:
    model = status.model
    if len(model) > _MODEL_SLOT:
        model = model[: _MODEL_SLOT - 1] + "…"
    word = status.state.split(" ", 1)[0]
    shown = word if tier == "narrow" else status.state
    state = Text(word, style=StatusToken.TONES[_STATE_TONES[word]])
    state.append(f"{shown[len(word) :]:<{_STATUS_SLOT[tier] - len(word)}}")
    cpu = Text("  cpu ", style=_DIM)
    cpu.append(f"{_percent(status.cpu_app_percent):>{_CPU_SLOT}}")
    ram = Text("  ram ", style=_DIM)
    size = status.ram_app_bytes
    ram.append(f"{'—' if size is None else f'{size / 1024**3:.1f}G':>{_RAM_SLOT}}")
    return [
        ("model", Text(f"{model:<{_MODEL_SLOT}} ")),
        ("status", state),
        ("cpu", cpu),
        ("ram", ram),
    ]


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f}%"
