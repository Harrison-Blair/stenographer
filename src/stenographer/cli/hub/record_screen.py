# SPDX-License-Identifier: GPL-3.0-or-later
"""The Record screen: the live recording panels and transcript."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.binding import Binding
from textual.widgets import Static

from stenographer.cli.hub.hub_screen import HubScreen
from stenographer.cli.hub.live_view import LiveView
from stenographer.cli.live.rename_dialog import RenameDialog
from stenographer.lib.logging.pipeline import fmt_event, log_failure

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.app import ComposeResult

log = logging.getLogger(__name__)


class RecordScreen(HubScreen):
    """Start, pause and watch a recording; rename its speakers."""

    SCREEN_NAME = "record"
    SCREEN_TITLE = "Record"
    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        Binding("space", "record_toggle", "Record, pause or resume", key_display="space"),
        ("m", "toggle_mic", "Microphone on or off"),
        ("s", "toggle_system", "System audio on or off"),
        ("v", "toggle_view", "Mixed or split transcript"),
        ("r", "rename_speaker", "Rename a speaker"),
        ("up", "scroll_line(-1)", "Scroll transcript up one line"),
        ("down", "scroll_line(1)", "Scroll transcript down one line"),
        ("pageup", "scroll_page(-1)", "Scroll transcript up one page"),
        ("pagedown", "scroll_page(1)", "Scroll transcript down one page"),
        ("home", "scroll_home", "Scroll to transcript start"),
        ("end", "scroll_end", "Scroll to latest transcript line"),
    ]
    DEFAULT_CSS = """
    RecordScreen #section-content {
        height: auto;
        padding: 1 2;
        border: round #3a4150;
        display: none;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.live_view = LiveView(id="live-view")
        self.split = False

    def compose_body(self) -> ComposeResult:
        yield Static("", id="section-content", markup=False)
        yield self.live_view

    @property
    def session(self):
        return getattr(self.app.services, "session", None)

    def refresh_body(self) -> None:
        app = self.app
        session = self.session
        self.live_view.refresh_view(
            session,
            mic_device=self._mic_device_name(),
            split=self.split,
            recording_active=app.services.recording and session is None,
        )
        activity = self.query_one("#section-content", Static)
        activity.update(app.activity_status or "")
        activity.display = app.activity_status is not None
        self.live_view.display = app.activity_status is None
        app.set_context_card("record", self._speakers_card(session), title="speakers")

    def footer_hints(self) -> tuple[tuple[str, str], ...]:
        if self.app.services.recording:
            session = self.session
            space = ("space", "resume" if session is not None and session.paused else "pause")
        else:
            space = ("space", "record")
        return (
            ("↑↓", "line"),
            ("PgUp/Dn", "page"),
            ("Home/End", "top/bot"),
            space,
            ("m", "mic"),
            ("s", "system"),
            ("v", "view"),
            ("r", "rename"),
            ("1 2 3", "screens"),
        )

    @staticmethod
    def _speakers_card(session) -> Text:
        card = Text()
        speakers = session.speakers if session is not None else ()
        for speaker_id, label in speakers:
            if card:
                card.append("\n")
            card.append(label or speaker_id)
        if not card:
            card.append("no speakers yet", style="#8b93a1")
        failed = session.failed_phrase_count if session is not None else 0
        if failed:
            noun = "phrase" if failed == 1 else "phrases"
            card.append(f"\n! {failed} {noun} failed", style="#ffaf5f")
        card.append("\n[r] Rename…")
        return card

    def _mic_device_name(self) -> str:
        device = self.app.current_config().audio.input_device
        return str(device) if device else "Default input"

    def action_record_toggle(self) -> None:
        app = self.app
        if app.activity_status is not None:
            return
        if app.services.recording:
            session = self.session
            if session is None:
                return
            action = session.resume if session.paused else session.pause
            status = "Resuming recording..." if session.paused else "Pausing recording..."
            self._run_live_action(action, status=status, name="toggle-recording")
            return
        if app.config_editor is not None and app.config_editor.read_only:
            app.notify("Fix the invalid configuration before recording.", severity="error")
            return
        app.activity_status = "Starting recording..."
        app.refresh_view()
        app.run_worker(self.start_recording(), name="start-recording", group="hub-work")

    async def start_recording(self) -> None:
        app = self.app
        try:
            await asyncio.to_thread(app.services.start_recording)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: recording_start_failed", exc, safe=True)
            app.notify(f"Could not start recording: {exc}", severity="error")
        else:
            log.info(fmt_event("hub", "recording_started"))
        app.activity_status = None
        app.refresh_view()

    def action_toggle_mic(self) -> None:
        session = self.session
        if session is not None:
            self._run_live_action(
                lambda: session.toggle("mic"), status="Toggling microphone...", name="toggle-mic"
            )

    def action_toggle_system(self) -> None:
        session = self.session
        if session is not None:
            self._run_live_action(
                lambda: session.toggle("system"),
                status="Toggling system audio...",
                name="toggle-system",
            )

    def _run_live_action(self, action: Callable[[], None], *, status: str, name: str) -> None:
        app = self.app
        if app.activity_status is not None:
            return
        app.activity_status = status
        app.refresh_view()
        app.run_worker(self._perform_live_action(action, name), name=name, group="hub-work")

    async def _perform_live_action(self, action: Callable[[], None], name: str) -> None:
        app = self.app
        try:
            await asyncio.to_thread(action)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: live_action_failed", exc, safe=True, action=name)
            app.notify(f"Could not update the live session: {exc}", severity="error")
        app.activity_status = None
        app.refresh_view()

    def _transcript(self):
        return self.live_view.query_one("#live-transcript")

    def action_scroll_line(self, offset: int) -> None:
        self._transcript().scroll_line(offset)

    def action_scroll_page(self, offset: int) -> None:
        self._transcript().scroll_page(offset)

    def action_scroll_home(self) -> None:
        self._transcript().scroll_top()

    def action_scroll_end(self) -> None:
        self._transcript().scroll_bottom()

    def action_toggle_view(self) -> None:
        self.split = not self.split
        log.info(fmt_event("hub", "live_view_toggled", view="split" if self.split else "mixed"))
        self.app.refresh_view()

    def action_rename_speaker(self) -> None:
        session = self.session
        if session is None:
            return
        speakers = session.speakers
        if not speakers:
            self.app.notify("No speakers are available to rename.")
            return
        self.app.push_screen(
            RenameDialog(speakers),
            lambda result: self._rename_speaker(session, result),
        )

    def _rename_speaker(self, session, value: tuple[str, str] | None) -> None:
        if value is None:
            return
        speaker_id, name = value
        try:
            session.rename(speaker_id, name)
        except ValueError as exc:
            self.app.notify(str(exc))
            return
        self.app.refresh_view()
