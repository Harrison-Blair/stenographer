# SPDX-License-Identifier: GPL-3.0-or-later
"""The Transcribe a file dialog of the Library: a file browser and the job options."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import soundfile
from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Input, Label, Static

from stenographer.cli.hub.widgets.button import HubButton
from stenographer.cli.hub.widgets.clock import Clock
from stenographer.cli.hub.widgets.dialog import Dialog
from stenographer.cli.hub.widgets.frame import Frame
from stenographer.cli.hub.widgets.row_input import fit_input_to_row
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
_DIM = StatusToken.TONES["dim"]


@dataclass(frozen=True)
class BrowserEntry:
    """One visible directory or audio file."""

    path: Path
    is_dir: bool
    duration_seconds: float | None


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
        ("r", "toggle_refine", "Refine text"),
    ]
    # Letters are keys of the dialog until the user focuses an input.
    AUTO_FOCUS = ""
    DEFAULT_CSS = """
    TranscribeDialog > #dialog-frame { width: 80; }
    TranscribeDialog #transcribe-browser { margin-bottom: 1; }
    TranscribeDialog #transcribe-head { height: 1; }
    TranscribeDialog #transcribe-folder { width: 1fr; color: #8b93a1; }
    TranscribeDialog #transcribe-search { width: 1fr; }
    TranscribeDialog #transcribe-list-scroll { height: auto; max-height: 12; }
    TranscribeDialog .transcribe-option { height: 1; }
    TranscribeDialog .transcribe-option Label { width: 20; padding: 0 0 0 2; }
    TranscribeDialog #transcribe-speakers, TranscribeDialog #transcribe-refine { width: 14; }
    """

    def __init__(self, home: Path | None = None) -> None:
        super().__init__("Transcribe a file")
        home = Path(home or Path.home()).expanduser()
        self.home = home if home.is_dir() else Path.home()
        self.directory = self.home
        self.search_term = ""
        self.entries: tuple[BrowserEntry, ...] = ()
        self.selected_index = 0
        self.browser_error = ""
        self.diarize = True
        self.refine = False

    def compose_body(self) -> ComposeResult:
        with Frame(id="transcribe-browser"):
            with Horizontal(id="transcribe-head"):
                yield Static("", id="transcribe-folder", markup=False)
                yield Input(placeholder="search", id="transcribe-search")
                yield HubButton("search", key="/", action="search", id="transcribe-search-button")
            with VerticalScroll(id="transcribe-list-scroll", can_focus=False):
                yield SelectableList(id="transcribe-list")
        with Horizontal(classes="transcribe-option"):
            yield Label("Separate speakers")
            yield HubButton("", key="s", action="toggle_speakers", id="transcribe-speakers")
        with Horizontal(classes="transcribe-option"):
            yield Label("Refine text")
            yield HubButton("", key="r", action="toggle_refine", id="transcribe-refine")

    def buttons(self) -> tuple[tuple[str, str, str], ...]:
        return (("esc", "Cancel", "cancel"), ("enter", "Transcribe", "transcribe"))

    def on_mount(self) -> None:
        search = self.query_one("#transcribe-search", Input)
        fit_input_to_row(search)
        search.display = False
        # A focused scroll body would take the arrow keys of the list.
        self.body_widget().can_focus = False
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
        self.browser_error = ""
        try:
            children = tuple(directory.iterdir())
        except OSError as exc:
            children = ()
            self.browser_error = f"Cannot read folder: {exc.strerror or str(exc)}"
        needle = self.search_term.casefold()
        found = []
        for path in children:
            if needle not in path.name.casefold():
                continue
            try:
                is_dir = path.is_dir()
            except OSError:
                continue
            if not is_dir and path.name.startswith(".") and not needle.startswith("."):
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
                rows.append((entry.path.name, "" if duration is None else Clock.duration(duration)))
        if self.browser_error:
            rows.append((Text(self.browser_error, style=_DIM), ""))
        elif not rows or (len(rows) == 1 and self.entries[0].path == self.directory.parent):
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
        self.search_term = event.value.strip()
        self._refresh_entries()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.set_focus(None)

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

    # Submit

    def action_transcribe(self) -> None:
        entry = self.selected_entry
        if entry is None:
            return
        if entry.is_dir:
            self.set_focus(None)
            self._open(entry.path)
            return
        self.dismiss((entry.path, {"diarize": self.diarize, "refine": self.refine}))
