# SPDX-License-Identifier: GPL-3.0-or-later
"""The shell of one hub screen: top bar, body and footer hint row."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Input

from stenographer.cli.hub.widgets.key_hints import KeyHints
from stenographer.cli.hub.widgets.top_bar import TopBar
from stenographer.cli.shared.transcript_scroll import TranscriptScroll

if TYPE_CHECKING:
    from textual.app import ComposeResult


class HubScreen(Screen):
    """Compose the shared shell; a subclass owns its body, keys and hints.

    The app draws the top bar of the current screen once the screen is
    ``ready`` (mounted with its children). A subclass gives ``compose_body``,
    ``refresh_body`` and ``footer_hints``. While a text input has focus,
    letters, ``?`` and ``q`` go to it, so the footer shows only the keys that
    still act and drops ``? help · q quit`` (README §4.6).
    """

    SCREEN_TITLE = ""
    AUTO_FOCUS = ""
    ready = False

    def compose(self) -> ComposeResult:
        yield TopBar(id="top-bar")
        with Vertical(id="screen-body"):
            yield from self.compose_body()
        yield KeyHints(id="key-hints")

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

    def on_mount(self) -> None:
        self.ready = True

    def on_screen_resume(self) -> None:
        self.app.refresh_view()

    def _transcript(self) -> TranscriptScroll:
        return self.query_one(TranscriptScroll)

    def action_scroll_page(self, offset: int) -> None:
        self._transcript().scroll_page(offset)

    def action_scroll_home(self) -> None:
        self._transcript().scroll_top()

    def action_scroll_end(self) -> None:
        self._transcript().scroll_bottom()
