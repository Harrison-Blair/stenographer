# SPDX-License-Identifier: GPL-3.0-or-later
"""The shell of one hub screen: sidebar, body and footer hint row."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Horizontal, Vertical
from textual.screen import Screen

from stenographer.cli.hub.widgets.key_hints import KeyHints
from stenographer.cli.hub.widgets.sidebar import Sidebar

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from stenographer.cli.hub.widgets.row_selected import RowSelected


class HubScreen(Screen):
    """Compose the shared shell; a subclass owns its body, keys, hints and card.

    The app draws the sidebar of the current screen once the screen is
    ``ready`` (mounted with its children). A subclass gives ``compose_body``,
    ``refresh_body`` and ``footer_hints``.
    """

    SCREEN_NAME = ""
    SCREEN_TITLE = ""
    AUTO_FOCUS = ""
    ready = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="hub-layout"):
            yield Sidebar(id="hub-sidebar")
            with Vertical(id="screen-body"):
                yield from self.compose_body()
        yield KeyHints(id="key-hints")

    def compose_body(self) -> ComposeResult:
        yield from ()

    def refresh_body(self) -> None:
        """Redraw the body from the app and service state."""

    def footer_hints(self) -> tuple[tuple[str, str], ...]:
        """Return the footer items; the footer adds ``? help · q quit``."""
        return (("1 2 3", "screens"),)

    def on_mount(self) -> None:
        self.ready = True

    def on_screen_resume(self) -> None:
        self.app.refresh_view()

    def on_row_selected(self, event: RowSelected) -> None:
        if event.control.id == "sidebar":
            event.stop()
            self.app.show_screen(Sidebar.SCREENS[event.index][0])
