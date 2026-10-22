# SPDX-License-Identifier: GPL-3.0-or-later
"""Scroll a transcript while following new lines at the bottom."""

from __future__ import annotations

from rich.console import RenderableType
from textual import events
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static


class TranscriptScroll(VerticalScroll):
    """Show transcript content and preserve the user's scroll position."""

    def __init__(self, *children, **kwargs):
        self._following = True
        super().__init__(*children, **kwargs)

    def compose(self) -> ComposeResult:
        yield Static("", id="transcript-scroll-content", markup=False)

    def update_content(self, content: RenderableType | str) -> None:
        """Update the transcript and follow only when the view was at the bottom."""
        was_at_bottom = self._following or self.scroll_y >= self.max_scroll_y
        self._following = was_at_bottom
        old_scroll_y = self.scroll_y
        self.query_one("#transcript-scroll-content", Static).update(content)
        self.call_after_refresh(self._restore_scroll, was_at_bottom, old_scroll_y)

    def watch_virtual_size(self, _old_size, _new_size) -> None:
        if self._following:
            self.scroll_end(animate=False, immediate=True, x_axis=False)

    def scroll_line(self, offset: int) -> None:
        self.scroll_relative(y=offset, animate=False, immediate=True)
        self._update_following()

    def scroll_page(self, offset: int) -> None:
        if offset < 0:
            self._following = False
            self.scroll_page_up(animate=False)
        else:
            self.scroll_page_down(animate=False)
            self.call_after_refresh(self._update_following)

    def scroll_top(self) -> None:
        self.scroll_home(animate=False, immediate=True, x_axis=False)
        self._update_following()

    def scroll_bottom(self) -> None:
        self._following = True
        self.scroll_end(animate=False, immediate=True, x_axis=False)

    def _update_following(self) -> None:
        self._following = self.scroll_y >= self.max_scroll_y

    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        self._following = False
        super()._on_mouse_scroll_up(event)
        self.call_after_refresh(self._update_following)

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        super()._on_mouse_scroll_down(event)
        self.call_after_refresh(self._update_following)

    def _restore_scroll(self, was_at_bottom: bool, old_scroll_y: float) -> None:
        if was_at_bottom:
            self.scroll_bottom()
        else:
            self.scroll_to(y=min(old_scroll_y, self.max_scroll_y), animate=False, immediate=True)
