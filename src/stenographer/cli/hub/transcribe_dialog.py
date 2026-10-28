# SPDX-License-Identifier: GPL-3.0-or-later
"""The Transcribe a file dialog of the Library: a file browser and the job options."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import soundfile
from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Input, Label, Static

from stenographer.cli.hub.doctor_view import DOCTOR_STATE_GLYPHS
from stenographer.cli.hub.files_entry import BrowserEntry
from stenographer.cli.hub.widgets.button import HubButton
from stenographer.cli.hub.widgets.dialog import Dialog
from stenographer.cli.hub.widgets.frame import Frame
from stenographer.cli.hub.widgets.selectable_list import SelectableList
from stenographer.cli.hub.widgets.status_token import StatusToken

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from stenographer.cli.hub.widgets.row_selected import RowSelected

AUDIO_SUFFIXES = frozenset(
    {
        ".aac",
        ".flac",
        ".m4a",
        ".mkv",
        ".mp3",
        ".mp4",
        ".ogg",
        ".opus",
        ".wav",
        ".webm",
        ".wma",
    }
)
_COUNT_ERROR = f"{DOCTOR_STATE_GLYPHS['fail']} Speaker count must be auto or a whole number above 0"
_DIM = StatusToken.TONES["dim"]


class TranscribeDialog(Dialog[tuple[Path, dict[str, object]] | None]):
    """Browse folders from the home folder, choose one audio file and its options.

    ``enter`` opens the selected folder or returns ``(path, options)`` for the
    selected file. ``escape`` clears an active search first, then cancels.
    """

    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        ("escape", "cancel", "Clear the search or cancel"),
        ("enter", "transcribe", "Open the folder or transcribe the file"),
        ("up", "move(-1)", "Previous file"),
        ("down", "move(1)", "Next file"),
        ("slash", "search", "Search this folder"),
        ("s", "toggle_speakers", "Separate speakers"),
        ("c", "edit_count", "Speaker count"),
        ("r", "toggle_refine", "Refine text"),
    ]
    # Letters are keys of the dialog until the user focuses an input.
    AUTO_FOCUS = ""
    DEFAULT_CSS = """
    TranscribeDialog > #dialog-frame { width: 80; }
    TranscribeDialog #transcribe-browser { margin-bottom: 1; }
    TranscribeDialog #transcribe-head { height: 1; }
    TranscribeDialog #transcribe-folder { width: 1fr; color: #8b93a1; }
    TranscribeDialog #transcribe-search { width: 1fr; height: 1; padding: 0; border: none; }
    TranscribeDialog #transcribe-list-scroll { height: auto; max-height: 12; }
    TranscribeDialog .transcribe-option { height: 1; }
    TranscribeDialog #transcribe-speakers-row { height: 3; }
    TranscribeDialog #transcribe-speakers-row Label { padding: 1 0 0 2; }
    TranscribeDialog .transcribe-option Label { width: 20; padding: 0 0 0 2; }
    TranscribeDialog #transcribe-speakers, TranscribeDialog #transcribe-refine { width: 14; }
    TranscribeDialog #transcribe-count { width: 12; }
    TranscribeDialog #transcribe-error { height: auto; margin-top: 1; }
    """

    def __init__(self, home: Path | None = None) -> None:
        super().__init__("Transcribe a file")
        home = Path(home or Path.home()).expanduser()
        self.home = home if home.is_dir() else Path.home()
        self.directory = self.home
        self.search_term = ""
        self.entries: tuple[BrowserEntry, ...] = ()
        self.selected_index = 0
        self.diarize = True
        self.refine = False

    def compose_body(self) -> ComposeResult:
        with Frame(id="transcribe-browser"):
            with Horizontal(id="transcribe-head"):
                yield Static("", id="transcribe-folder", markup=False)
                yield Input(placeholder="search this folder", id="transcribe-search")
                yield HubButton("search", key="/", action="search", id="transcribe-search-button")
            with VerticalScroll(id="transcribe-list-scroll", can_focus=False):
                yield SelectableList(id="transcribe-list")
        with Horizontal(classes="transcribe-option", id="transcribe-speakers-row"):
            yield Label("Separate speakers")
            yield HubButton("", key="s", action="toggle_speakers", id="transcribe-speakers")
            yield HubButton(
                "Speaker count", key="c", action="edit_count", id="transcribe-count-button"
            )
            yield Input("auto", id="transcribe-count")
        with Horizontal(classes="transcribe-option"):
            yield Label("Refine text")
            yield HubButton("", key="r", action="toggle_refine", id="transcribe-refine")
        yield Static("", id="transcribe-error", markup=False)

    def buttons(self) -> tuple[tuple[str, str, str], ...]:
        return (("esc", "Cancel", "cancel"), ("enter", "Transcribe", "transcribe"))

    def on_mount(self) -> None:
        self.query_one("#transcribe-search", Input).display = False
        # A focused scroll body would take the arrow keys of the list.
        self.body_widget().can_focus = False
        # The app rules of HubButton outrank dialog CSS; line the buttons up with the input text.
        for button in self.query("#transcribe-speakers-row HubButton"):
            button.styles.margin = (1, 1, 0, 0)
        self._show_error("")
        self._draw_options()
        self._open(self.directory)

    @property
    def selected_entry(self) -> BrowserEntry | None:
        return self.entries[self.selected_index] if self.entries else None

    # Browser

    def _open(self, directory: Path) -> None:
        self.directory = directory
        self.search_term = ""
        search = self.query_one("#transcribe-search", Input)
        search.value = ""
        search.display = False
        self.query_one("#transcribe-folder").display = True
        self._refresh_entries()

    def _refresh_entries(self) -> None:
        directory = self.directory
        try:
            children = tuple(directory.iterdir())
        except OSError:
            children = ()
        needle = self.search_term.casefold()
        found = []
        for path in children:
            if path.name.startswith(".") or needle not in path.name.casefold():
                continue
            try:
                is_dir = path.is_dir()
            except OSError:
                continue
            if not is_dir and path.suffix.lower() not in AUDIO_SUFFIXES:
                continue
            found.append(BrowserEntry(path, is_dir, None if is_dir else self._duration(path)))
        found.sort(key=lambda entry: (not entry.is_dir, entry.path.name.casefold()))
        parent = ()
        if directory != directory.parent:
            parent = (BrowserEntry(directory.parent, True, None),)
        self.entries = (*parent, *found)
        self.selected_index = len(parent) if found else 0
        self._draw_browser()

    @staticmethod
    def _duration(path: Path) -> float | None:
        try:
            info = soundfile.info(str(path))
        except (OSError, RuntimeError, ValueError):
            return None
        if info.samplerate <= 0 or info.frames < 0:
            return None
        return info.frames / info.samplerate

    def _draw_browser(self) -> None:
        try:
            relative = self.directory.relative_to(self.home)
        except ValueError:
            title = str(self.directory)
        else:
            title = "~" if relative == Path(".") else f"~/{relative}"
        self.query_one("#transcribe-folder", Static).update(title)
        rows = []
        for index, entry in enumerate(self.entries):
            if index == 0 and entry.path == self.directory.parent and entry.is_dir:
                rows.append(("..", ""))
            elif entry.is_dir:
                rows.append((f"{entry.path.name}/", ""))
            else:
                duration = entry.duration_seconds
                rows.append((entry.path.name, "" if duration is None else self.clock(duration)))
        if not rows or (len(rows) == 1 and self.entries[0].path == self.directory.parent):
            rows.append((Text("no audio files or folders match", style=_DIM), ""))
        self.query_one("#transcribe-list", SelectableList).set_rows(
            tuple(rows), self.selected_index if self.entries else None
        )
        self._keep_visible()

    def _keep_visible(self) -> None:
        scroll = self.query_one("#transcribe-list-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        if not height:
            return
        top = int(scroll.scroll_y)
        if self.selected_index < top:
            scroll.scroll_to(y=self.selected_index, animate=False)
        elif self.selected_index >= top + height:
            scroll.scroll_to(y=self.selected_index - height + 1, animate=False)

    def action_move(self, offset: int) -> None:
        if self.entries:
            self.selected_index = (self.selected_index + offset) % len(self.entries)
            self._draw_browser()

    def on_row_selected(self, event: RowSelected) -> None:
        event.stop()
        if 0 <= event.index < len(self.entries):
            self.selected_index = event.index
            self._draw_browser()

    def action_search(self) -> None:
        self.query_one("#transcribe-folder").display = False
        search = self.query_one("#transcribe-search", Input)
        search.display = True
        search.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        if event.input.id == "transcribe-search":
            self.search_term = event.value.strip()
            self._refresh_entries()
        elif event.input.id == "transcribe-count":
            self._show_error("")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        if event.input.id == "transcribe-search":
            self.set_focus(None)
        else:
            self.action_transcribe()

    def action_cancel(self) -> None:
        if self.query_one("#transcribe-search", Input).display:
            self.set_focus(None)
            self._open(self.directory)
            return
        super().action_cancel()

    # Options

    def _draw_options(self) -> None:
        for button_id, value in (
            ("#transcribe-speakers", self.diarize),
            ("#transcribe-refine", self.refine),
        ):
            self.query_one(button_id, HubButton).set_label("(●) on" if value else "( ) off")

    def action_toggle_speakers(self) -> None:
        self.diarize = not self.diarize
        self._draw_options()

    def action_toggle_refine(self) -> None:
        self.refine = not self.refine
        self._draw_options()

    def action_edit_count(self) -> None:
        self.query_one("#transcribe-count", Input).focus()

    def _show_error(self, message: str) -> None:
        error = self.query_one("#transcribe-error", Static)
        error.update(Text(message, style=StatusToken.TONES["danger"]))
        error.display = bool(message)

    def _speaker_count(self) -> tuple[bool, int | None]:
        value = self.query_one("#transcribe-count", Input).value.strip().lower()
        if value == "auto":
            return True, None
        if value.isdecimal() and int(value) > 0:
            return True, int(value)
        return False, None

    # Submit

    def action_transcribe(self) -> None:
        entry = self.selected_entry
        if entry is None:
            return
        if entry.is_dir:
            self.set_focus(None)
            self._open(entry.path)
            return
        valid, count = self._speaker_count()
        if not valid:
            self._show_error(_COUNT_ERROR)
            self.query_one("#transcribe-count", Input).focus()
            return
        self.dismiss(
            (entry.path, {"diarize": self.diarize, "speaker_count": count, "refine": self.refine})
        )

    @staticmethod
    def clock(seconds: float) -> str:
        """Return ``m:ss`` or ``h:mm:ss``."""
        total = max(0, int(seconds))
        hours, remainder = divmod(total, 3600)
        minutes, second = divmod(remainder, 60)
        return f"{hours}:{minutes:02d}:{second:02d}" if hours else f"{minutes}:{second:02d}"
