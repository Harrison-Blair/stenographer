# SPDX-License-Identifier: GPL-3.0-or-later
"""The shell of one hub screen: top bar, body and footer hint row."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Input, Static

from stenographer.cli.hub.widgets.key_hints import KeyHints
from stenographer.cli.hub.widgets.tier import (
    FLOOR_HEIGHT,
    FLOOR_WIDTH,
    TIERS,
    below_floor,
    tier_for,
)
from stenographer.cli.hub.widgets.top_bar import TopBar
from stenographer.cli.shared.transcript_scroll import TranscriptScroll

if TYPE_CHECKING:
    from textual.app import ComposeResult

_TIMES = "\N{MULTIPLICATION SIGN}"


class HubScreen(Screen):
    """Compose the shared shell; a subclass owns its body, keys and hints.

    The app draws the top bar of the current screen once the screen is
    ``ready`` (mounted with its children). A subclass gives ``compose_body``,
    ``refresh_body`` and ``footer_hints``. While a text input has focus,
    letters, ``?`` and ``q`` go to it, so the footer shows only the keys that
    still act and drops ``? help · q quit`` (README §4.6).

    The screen has the class of its size tier (``-wide``, ``-medium`` or
    ``-narrow``). Below 60x16 it has ``-floor`` and shows only the size line;
    the work of the services goes on. The classes are set on each resize and
    each resume: Textual's ``HORIZONTAL_BREAKPOINTS`` update only the screen
    that is active during the resize, and the hub switches screens by mode.
    """

    DEFAULT_CSS = """
    HubScreen #floor-line {
        display: none;
        width: 1fr;
        height: 1fr;
        content-align: center middle;
    }
    HubScreen.-floor #floor-line { display: block; }
    HubScreen.-floor #top-bar, HubScreen.-floor #screen-body, HubScreen.-floor #key-hints {
        display: none;
    }
    """

    SCREEN_TITLE = ""
    AUTO_FOCUS = ""
    ready = False

    def compose(self) -> ComposeResult:
        yield TopBar(id="top-bar")
        with Vertical(id="screen-body"):
            yield from self.compose_body()
        yield KeyHints(id="key-hints")
        yield Static("", id="floor-line", markup=False)

    def compose_body(self) -> ComposeResult:
        yield from ()

    def refresh_body(self) -> None:
        """Redraw the body from the app and service state."""

    @property
    def typing(self) -> bool:
        """Whether a text input has focus."""
        return isinstance(self.focused, Input)

    def footer_hints(self) -> tuple[tuple[str, str], ...]:
        """Return the footer items; the footer adds ``? help · q quit``."""
        return ()

    def draw_hints(self) -> None:
        self.query_one("#key-hints", KeyHints).set_hints(*self.footer_hints(), end=not self.typing)

    def on_descendant_focus(self) -> None:
        if self.ready:
            self.draw_hints()

    def on_descendant_blur(self) -> None:
        if self.ready:
            self.draw_hints()

    @property
    def tier(self) -> str:
        """Return ``wide``, ``medium`` or ``narrow`` for the current terminal width."""
        return tier_for(self.app.size.width)

    def apply_size(self) -> None:
        """Set the tier and floor classes and the size line from the terminal size."""
        width, height = self.app.size
        tier = tier_for(width)
        for name in TIERS:
            self.set_class(name == tier, f"-{name}")
        self.set_class(below_floor(width, height), "-floor")
        self.query_one("#floor-line", Static).update(
            f"{FLOOR_WIDTH}{_TIMES}{FLOOR_HEIGHT} needed · now {width:>3}{_TIMES}{height:<3}"
        )

    def on_mount(self) -> None:
        self.apply_size()
        self.ready = True

    def on_resize(self) -> None:
        self.apply_size()
        self.app.refresh_view()

    def on_screen_resume(self) -> None:
        self.apply_size()
        self.app.refresh_view()

    def _transcript(self) -> TranscriptScroll:
        return self.query_one(TranscriptScroll)

    def action_scroll_page(self, offset: int) -> None:
        self._transcript().scroll_page(offset)

    def action_scroll_home(self) -> None:
        self._transcript().scroll_top()

    def action_scroll_end(self) -> None:
        self._transcript().scroll_bottom()
