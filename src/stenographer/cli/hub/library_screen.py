# SPDX-License-Identifier: GPL-3.0-or-later
"""The Library screen: a table of sessions and file jobs, and one session on the full screen."""

from __future__ import annotations

import asyncio
import itertools
import logging
import math
import pathlib
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, Any, ClassVar

from rich.console import Group
from rich.text import Text
from textual.binding import Binding
from textual.containers import Grid, Horizontal, VerticalScroll
from textual.geometry import Region
from textual.widgets import Input, Rule, Static

from stenographer.cli.hub.dialogs import QuitConfirm
from stenographer.cli.hub.doctor_view import DOCTOR_STATE_GLYPHS
from stenographer.cli.hub.export_dialog import ExportDialog
from stenographer.cli.hub.hub_screen import HubScreen
from stenographer.cli.hub.library_table import GENERATING, LibraryTable, TableRow
from stenographer.cli.hub.rename_dialog import RenameDialog
from stenographer.cli.hub.title_dialog import TitleDialog
from stenographer.cli.hub.transcribe_dialog import TranscribeDialog
from stenographer.cli.hub.widgets.button import HubButton
from stenographer.cli.hub.widgets.clock import Clock
from stenographer.cli.hub.widgets.frame import Frame
from stenographer.cli.hub.widgets.key_hints import KeyHints
from stenographer.cli.hub.widgets.row_input import fit_input_to_row
from stenographer.cli.hub.widgets.speaker_bar import SpeakerBar
from stenographer.cli.hub.widgets.status_token import StatusToken
from stenographer.cli.hub.widgets.transcript_line import TranscriptRows
from stenographer.cli.hub.widgets.update_changed import update_changed
from stenographer.cli.shared.speaker_colors import speaker_color
from stenographer.cli.shared.transcript_scroll import TranscriptScroll
from stenographer.lib.logging.pipeline import fmt_event, log_failure
from stenographer.lib.sessions.jobs import SessionJobs

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.app import ComposeResult

    from stenographer.cli.hub.widgets.row_selected import RowSelected
    from stenographer.lib.sessions.models import SessionDetail, SessionSummary

log = logging.getLogger(__name__)

_FAILED_JOB_STATES = frozenset({"failed", "needs_ffmpeg"})
_FAILED = DOCTOR_STATE_GLYPHS["fail"]
_DIM = StatusToken.TONES["dim"]
_WARN = StatusToken.TONES["warn"]
_DANGER = StatusToken.TONES["danger"]
# Fixed slots: a value changes inside its slot and nothing beside it moves.
_COUNT_SLOT = 3
_SIZE_SLOT = 7
_DUR_SLOT = 8
_STATE_SLOT = 13
_KIND_SLOT = 4
_TALK_TIME_SLOT = 5
_ACTION_GAP = 3
# Buttons of the open session: ``(id, key, label, action, tone)``.
_ACTIONS = (
    ("library-play", "p", "▶ Play", "session_playback", "default"),
    ("library-rename", "r", "Rename…", "session_rename", "default"),
    ("library-rediarize", "d", "Re-diarize", "session_rediarize", "default"),
    ("library-retranscribe", "t", "Re-transcribe", "session_retranscribe", "default"),
    ("library-export", "x", "Export…", "session_export", "default"),
    ("library-delete", "del", "Delete…", "session_delete", "danger"),
)
# The Play label: ``▶ Play`` and ``■ Stop`` have the same width.
_PLAY, _STOP = "▶ Play", "■ Stop"
_POSITION_SLOT = len("00:00:00 / 00:00:00")


ACTIVE_JOB_STATES = frozenset({"queued", "running"})


@dataclass(frozen=True)
class LibraryEntry:
    """A session row (``summary``), a job row (``summary`` is None), or a session row with
    the revision job that writes into it (``job``)."""

    entry_id: str
    summary: SessionSummary | None
    job: Any = None
    job_name: str = ""
    listed_at: datetime | None = None

    @property
    def session_id(self) -> str | None:
        return None if self.summary is None else self.summary.session_id

    @property
    def kind(self) -> str:
        return "file" if self.summary is None else self.summary.kind

    @property
    def job_active(self) -> bool:
        return self.job is not None and self.job.state in ACTIVE_JOB_STATES


def format_size(size: int) -> str:
    """Return ``176 M`` below one gigabyte and ``1.6 G`` above; at most 7 cells to 999.9 G."""
    megabytes = size / 1024**2
    if round(megabytes) < 1024:
        return f"{megabytes:.0f} M"
    return f"{megabytes / 1024:.1f} G"


class LibraryScreen(HubScreen):
    """List recordings, file sessions and unfinished file jobs; open one on the full screen.

    The table and the open session are two views of one screen. The keys of the actions
    act on the selected entry in both views. ``n`` opens the Transcribe a file dialog;
    its job shows in the table at once.
    """

    SCREEN_TITLE = "Library"
    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        ("up", "library_move(-1)", "Previous entry, or scroll the session up"),
        ("down", "library_move(1)", "Next entry, or scroll the session down"),
        ("enter", "open_session", "Open the session"),
        Binding(
            "escape", "library_back", "Back to the table, or clear the search", key_display="esc"
        ),
        ("slash", "library_search", "Search titles and transcripts"),
        ("p", "session_playback", "Play or stop the session"),
        ("e", "session_title", "Edit the title"),
        ("g", "session_generate_title", "Generate a title"),
        ("r", "session_rename", "Rename a speaker"),
        ("d", "session_rediarize", "Re-diarize the session"),
        ("t", "session_retranscribe", "Re-transcribe the session"),
        ("x", "session_export", "Export the session"),
        Binding(
            "delete", "session_delete", "Delete the session or cancel its job", key_display="del"
        ),
        ("pageup", "scroll_page(-1)", "Page up"),
        ("pagedown", "scroll_page(1)", "Page down"),
        ("home", "scroll_home", "First entry, or the transcript start"),
        ("end", "scroll_end", "Last entry, or the transcript end"),
        ("n", "transcribe_file", "Transcribe a file"),
    ]
    DEFAULT_CSS = """
    LibraryScreen .library-view { height: 1fr; }
    LibraryScreen #library-session { display: none; }
    LibraryScreen.-open #library-session { display: block; }
    LibraryScreen.-open #library-table-view { display: none; }
    LibraryScreen #library-search-row { height: 1; }
    LibraryScreen #library-search { width: 1fr; }
    LibraryScreen #library-head-gap { width: 1fr; }
    LibraryScreen #library-count { width: auto; color: #8b93a1; }
    LibraryScreen #library-columns { height: 1; }
    LibraryScreen #library-list-scroll { height: 1fr; scrollbar-gutter: stable; }
    LibraryScreen #library-session-head { height: 1; }
    LibraryScreen #library-session-meta { width: 1fr; text-align: right; }
    LibraryScreen #library-title-row { height: 1; }
    LibraryScreen #library-detail-title {
        width: 1fr;
        text-style: bold;
        color: ansi_default;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    LibraryScreen #library-actions {
        height: auto;
        grid-rows: 1;
        grid-columns: auto;
    }
    LibraryScreen #library-rule { margin: 0; color: #3a4150; }
    LibraryScreen #library-transcript { height: 1fr; }
    LibraryScreen .library-hints { height: 1; }
    """

    def __init__(self, services, *, files_home: pathlib.Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.store = getattr(services, "session_store", None)
        self.files_home = files_home
        self.files_submitting = 0
        self.loaded = False
        self.summaries: tuple[SessionSummary, ...] = ()
        self.entries: tuple[LibraryEntry, ...] = ()
        self.detail: SessionDetail | None = None
        self.search_query = ""
        self.opened = False
        self._open_after_select = False
        self._all_count = 0
        self._list_error: str | None = None
        self._selected_id: str | None = None
        self._detail_id: str | None = None
        self._detail_error: str | None = None
        self._search_matches: tuple[str, frozenset[str]] | None = None
        self._job_targets: dict[str, tuple[str, str] | None] = {}
        self._job_listed_at: dict[str, datetime] = {}
        self._job_states: dict[str, str] = {}
        self._job_owners: dict[str, tuple[str, str]] = {}
        self._session_work: dict[str, str] = {}
        # The sessions whose title the model works on, as the last poll read them.
        self._generating: frozenset[str] = frozenset()
        self._titles_stored = 0
        self._removed_jobs: set[str] = set()
        self._owner_ids = itertools.count(1)
        self._pending_select: str | None = None
        self._follow_select: str | None = None
        self._list_running = False
        self._list_again = False
        self._watch_key: object = None
        self._poll_key: object = None
        self._rows_key: object = None
        self._row_in_view: int | None = None
        self._transcript_key: object = None
        self._actions_key: object = None
        self._play_timer = None
        self._rows = TranscriptRows()

    def compose_body(self) -> ComposeResult:
        with Frame(id="library-table-view", classes="library-view"):
            with Horizontal(id="library-search-row"):
                yield HubButton(
                    "search", key="/", action="library_search", id="library-search-button"
                )
                yield Input(placeholder="search", id="library-search")
                yield HubButton(
                    "+ Transcribe a file…",
                    key="n",
                    action="transcribe_file",
                    tone="primary",
                    id="library-transcribe",
                )
                yield Static("", id="library-head-gap", markup=False)
                yield Static("", id="library-count", markup=False)
            yield Static("", id="library-columns", markup=False)
            with VerticalScroll(id="library-list-scroll", can_focus=False):
                yield LibraryTable(id="library-list")
            yield KeyHints(footer=False, id="library-list-hints", classes="library-hints")
        with Frame(id="library-session", classes="library-view"):
            with Horizontal(id="library-session-head"):
                yield HubButton(
                    "← Library",
                    key="esc",
                    action="library_back",
                    tone="primary",
                    tight=True,
                    id="library-back",
                )
                yield Static("", id="library-session-meta", markup=False)
            with Horizontal(id="library-title-row"):
                yield Static("", id="library-detail-title", markup=False)
                yield HubButton(
                    "Edit title…",
                    key="e",
                    action="session_title",
                    tight=True,
                    id="library-title-button",
                )
                yield HubButton(
                    "Generate title",
                    key="g",
                    action="session_generate_title",
                    tight=True,
                    id="library-generate-button",
                )
            yield SpeakerBar(id="library-speakers")
            with Grid(id="library-actions"):
                for button_id, key, label, action, tone in _ACTIONS:
                    yield HubButton(
                        label, key=key, action=action, tone=tone, tight=True, id=button_id
                    )
            yield Rule(id="library-rule")
            yield TranscriptScroll(id="library-transcript", can_focus=False)

    def on_mount(self) -> None:
        search = self.query_one("#library-search", Input)
        fit_input_to_row(search)
        search.display = False
        # Inline: the app rules of HubButton outrank screen CSS.
        self.query_one("#library-title-button", HubButton).styles.margin = (0, 0, 0, 2)
        self.query_one("#library-generate-button", HubButton).styles.margin = (0, 0, 0, 2)
        self.query_one("#library-list-hints", KeyHints).set_hints(
            ("↑↓", "select"), ("enter", "open"), ("PgUp/Dn", "page")
        )
        self.set_interval(0.1, self.poll_jobs)

    def footer_hints(self) -> tuple[tuple[str, str], ...]:
        if self.typing:
            return (("enter", "keep"), ("esc", "clear"))
        if self.opened:
            entry = self.selected_entry
            delete = "cancel job" if entry is not None and entry.job_active else "delete"
            return (
                ("esc", "back"),
                ("p", "play"),
                ("e", "title"),
                ("g", "generate"),
                ("r", "rename"),
                ("d", "re-diarize"),
                ("t", "re-transcribe"),
                ("x", "export"),
                ("del", delete),
                ("↑↓", "line"),
                ("PgUp/Dn", "page"),
            )
        return (
            ("enter", "open"),
            ("n", "transcribe"),
            ("/", "search"),
            ("p", "play"),
            ("e", "title"),
            ("g", "generate"),
            ("r", "rename"),
            ("d", "re-diarize"),
            ("t", "re-transcribe"),
            ("x", "export"),
            ("del", "delete"),
        )

    @property
    def entry_count(self) -> int | None:
        """Return the number of entries without the search, or ``None`` before the first load."""
        return self._all_count if self.loaded else None

    @property
    def selected_id(self) -> str | None:
        return self._selected_id

    def entry(self, entry_id: str) -> LibraryEntry | None:
        return next((entry for entry in self.entries if entry.entry_id == entry_id), None)

    @property
    def selected_entry(self) -> LibraryEntry | None:
        return None if self._selected_id is None else self.entry(self._selected_id)

    # Views

    def action_open_session(self) -> None:
        if self.selected_entry is None:
            return
        self._set_opened(True)

    def action_library_back(self) -> None:
        if self.opened:
            self._set_opened(False)
        else:
            self.action_clear_search()

    def _set_opened(self, opened: bool) -> None:
        if opened == self.opened:
            return
        self.opened = opened
        self.set_class(opened, "-open")
        self._row_in_view = None
        self._rows_key = None
        self.app.refresh_view()
        # The view that shows gets its widths in the next layout.
        self.call_after_refresh(self._fit_after_layout)

    def action_library_move(self, offset: int) -> None:
        if self.opened:
            self._transcript().scroll_line(offset)
        else:
            self.action_session_move(offset)

    def action_scroll_page(self, offset: int) -> None:
        if self.opened:
            super().action_scroll_page(offset)
        else:
            page = max(1, self.query_one("#library-list-scroll").size.height // 2)
            self._move_to(offset * page, clamp=True)

    def action_scroll_home(self) -> None:
        if self.opened:
            super().action_scroll_home()
        elif self.entries:
            self.select_entry(self.entries[0].entry_id)

    def action_scroll_end(self) -> None:
        if self.opened:
            super().action_scroll_end()
        elif self.entries:
            self.select_entry(self.entries[-1].entry_id)

    def _transcript(self) -> TranscriptScroll:
        return self.query_one("#library-transcript", TranscriptScroll)

    # Drawing

    def refresh_body(self) -> None:
        self._draw_head()
        if self.opened:
            self._draw_session()
        else:
            self._draw_list()

    def _draw_head(self) -> None:
        total = sum(summary.audio_size_bytes for summary in self.summaries)
        count = f"{self._all_count:>{_COUNT_SLOT}}"
        size = f"{format_size(total):>{_SIZE_SLOT}}"
        # An open search takes the free cells of the row; the medium tier then drops the words.
        searching = self._search_shown
        short = self.tier == "narrow" or (searching and self.tier == "medium")
        text = f"{count} · {size}" if short else f"{count} entries · {size} audio"
        self.query_one("#library-head-gap").display = not searching
        update_changed(self.query_one("#library-count", Static), text)
        transcribe = self.query_one("#library-transcribe", HubButton)
        label = "+ Transcribe…" if self.tier == "narrow" else "+ Transcribe a file…"
        if transcribe.label.plain != HubButton.label_text(label, "n").plain:
            transcribe.set_label(label)

    def _draw_list(self) -> None:
        tier = self.tier
        table = self.query_one("#library-list", LibraryTable)
        width = table.size.width
        rows = tuple(self._table_row(entry) for entry in self.entries)
        index = next(
            (i for i, entry in enumerate(self.entries) if entry.entry_id == self._selected_id),
            None,
        )
        query = self.search_query.strip()
        searching = bool(query) and (
            self._search_matches is None or self._search_matches[0] != query
        )
        message = self._list_error or ("Searching…" if searching else "")
        if not message and not rows:
            message = "No matches." if query else "No saved sessions."
            index = None
        message_text = Text(message, style=_DIM) if message else None
        update_changed(
            self.query_one("#library-columns", Static), LibraryTable.heading(tier, width)
        )
        key = (rows, index, tier, message)
        if key != self._rows_key:
            self._rows_key = key
            table.set_rows(rows, index, tier=tier, message=message_text)
            if index is not None and index != self._row_in_view:
                # Only a move scrolls: a job's progress changes its row text, not the selection.
                self.call_after_refresh(self._show_row, index)
            self._row_in_view = index

    def _show_row(self, index: int) -> None:
        self.query_one("#library-list-scroll", VerticalScroll).scroll_to_region(
            Region(0, index * 2, 1, 2), animate=False, immediate=True
        )

    def on_resize(self) -> None:
        # HubScreen.on_resize redraws first; the heading and the buttons then fit the
        # widths of the new layout.
        self.call_after_refresh(self._fit_after_layout)

    def _fit_after_layout(self) -> None:
        if self.opened:
            self._fit_actions()
        else:
            table = self.query_one("#library-list", LibraryTable)
            update_changed(
                self.query_one("#library-columns", Static),
                LibraryTable.heading(self.tier, table.size.width),
            )
            # A new height can leave the selected entry below or above the view.
            if table.selected_index is not None:
                self._show_row(table.selected_index)

    def _when(self, entry: LibraryEntry) -> datetime:
        if entry.summary is not None:
            return entry.summary.started_at.astimezone()
        return (self._job_listed_at.get(entry.job.id) or datetime.now(UTC)).astimezone()

    def _duration(self, entry: LibraryEntry) -> Text:
        """Return the job's ``queued`` or percent, else the duration of the session."""
        job = entry.job
        if entry.job_active:
            value = "queued" if job.state == "queued" else f"{job.progress.percent}%"
            return Text(value, style=_WARN)
        if entry.summary is None:
            return Text("—", style=_DIM)
        return Text(Clock.duration(max(0, entry.summary.duration_seconds)))

    def _title(self, entry: LibraryEntry) -> str | None:
        """Return the title; a file entry without one shows its file name."""
        summary = entry.summary
        if summary is None:
            return entry.job_name
        if summary.title is not None:
            return summary.title
        return summary.source_name if summary.kind == "file" else None

    def _is_generating(self, entry: LibraryEntry) -> bool:
        return entry.session_id is not None and entry.session_id in self._generating

    def _table_row(self, entry: LibraryEntry) -> TableRow:
        summary = entry.summary
        size = (
            Text(format_size(summary.audio_size_bytes))
            if summary is not None
            else Text("—", style=_DIM)
        )
        return TableRow(
            date=f"{self._when(entry):%d %b %H:%M}",
            dur=self._duration(entry),
            kind=entry.kind,
            speakers=summary.speakers if summary is not None else (),
            title=self._title(entry),
            size=size,
            state=self._state_word(entry),
            glyph=self._state_glyph(entry),
            generating=self._is_generating(entry),
        )

    def _state_word(self, entry: LibraryEntry) -> Text:
        """Return the state word of the wide table and the open session; a fault has its glyph.

        A job's ``queued`` or percent shows in the duration slot, not here.
        """
        summary = entry.summary
        job = entry.job
        if summary is None:
            if job.state in _FAILED_JOB_STATES:
                return Text(f"{_FAILED} failed", style=_DANGER)
            return Text("transcribe" if entry.job_active else job.state, style=_WARN)
        if entry.job_active:
            return Text("re-transcribe", style=_WARN)
        work = self._session_work.get(summary.session_id)
        if work is not None:
            return Text(work, style=_WARN)
        if summary.interrupted:
            return Text("! interrupted", style=_DANGER)
        # A Transcribe a file job on the saved audio of a session stores this method.
        if summary.label_state == "file-transcribe":
            return Text("re-transcribe")
        return Text(summary.label_state)

    @staticmethod
    def _state_glyph(entry: LibraryEntry) -> Text:
        """Return the glyph of an interrupted session or a failed job, else nothing."""
        if entry.summary is None:
            failed = entry.job.state in _FAILED_JOB_STATES
            return Text(_FAILED if failed else "", style=f"bold {_DANGER}")
        return Text("!" if entry.summary.interrupted else "", style=f"bold {_DANGER}")

    # The open session

    def _draw_session(self) -> None:
        entry = self.selected_entry
        if entry is None:
            return
        detail = self.detail if entry.summary is not None else None
        update_changed(self.query_one("#library-session-meta", Static), self._session_meta(entry))
        title = self._title(entry)
        if self._is_generating(entry):
            title_text = Text(GENERATING, style=_DIM)
        else:
            title_text = Text(title) if title is not None else Text("—", style=_DIM)
        update_changed(self.query_one("#library-detail-title", Static), title_text)
        speakers = self.query_one("#library-speakers", SpeakerBar)
        items = self._speaker_items(detail) if detail is not None else ()
        speakers.set_items(items, speakers=len(items), max_rows=self._speaker_rows_allowed())
        self._draw_buttons(entry)
        self._draw_transcript(entry, detail)

    def _speaker_rows_allowed(self) -> int:
        """Return one row in a short or narrow terminal, else two (as on Record)."""
        return 1 if self.app.size.height < 28 or self.tier == "narrow" else 2

    def _session_meta(self, entry: LibraryEntry) -> Text:
        """Return ``state · date · duration · kind · size``; each changing value has a slot."""
        summary = entry.summary
        dur = self._duration(entry)
        dur = Text(" " * max(0, _DUR_SLOT - dur.cell_len)).append_text(dur)
        sep = Text(" · ", style=_DIM)
        when = self._when(entry)
        if self.tier == "narrow":
            text = self._state_glyph(entry)
            text.pad_left(1 - text.cell_len)
            return Text.assemble(text, " ", f"{when:%d %b %H:%M}", sep, dur)
        state = self._state_word(entry)
        state.pad_left(_STATE_SLOT - state.cell_len)
        date = f"{when:%d %b %Y %H:%M}" if self.tier == "wide" else f"{when:%d %b %H:%M}"
        size = format_size(summary.audio_size_bytes) if summary is not None else "—"
        return Text.assemble(
            state,
            sep,
            date,
            sep,
            dur,
            sep,
            f"{entry.kind:<{_KIND_SLOT}}",
            sep,
            f"{size:>{_SIZE_SLOT}}",
        )

    def _speaker_items(self, detail: SessionDetail) -> tuple[Text, ...]:
        ids = self._speaker_ids(detail)
        items: list[Text] = []
        for label in detail.summary.speakers:
            speaker_id = ids[label]
            color = speaker_color(
                speaker_id, tuple(ids.values()), source=self._source_of(detail, label)
            )
            item = Text()
            item.append(label, style=f"bold {color}")
            item.append(f" {Clock.talk_time(max(0, detail.talk_time[label])):>{_TALK_TIME_SLOT}}")
            items.append(item)
        return tuple(items)

    @staticmethod
    def _speaker_ids(detail: SessionDetail) -> dict[str, str]:
        ids: dict[str, str] = {}
        for line in detail.lines:
            ids.setdefault(line.label, line.speaker_id)
        return ids

    @staticmethod
    def _source_of(detail: SessionDetail, label: str) -> str | None:
        return next((line.source for line in detail.lines if line.label == label), None)

    def _play_label(self, entry: LibraryEntry) -> str:
        """Return ``▶ Play`` or ``■ Stop`` and, in the wide and medium tiers, the position."""
        summary = entry.summary
        if summary is None:
            return _PLAY if self.tier == "narrow" else f"{_PLAY} {'':{_POSITION_SLOT}}"
        playback = self._playback()
        playing = playback is not None and playback[0] == summary.session_id
        label = _STOP if playing else _PLAY
        if self.tier == "narrow":
            return label
        duration = max(0.0, summary.duration_seconds)
        position = min(playback[1], duration) if playing else 0.0
        return f"{label} {Clock.format(position)} / {Clock.format(duration)}"

    def _playback(self) -> tuple[str, float] | None:
        playback = getattr(self.app.services, "session_playback", None)
        return playback() if playback is not None else None

    def _draw_buttons(self, entry: LibraryEntry) -> None:
        session_id = entry.session_id
        busy = session_id is not None and self.app.is_busy(session_id)
        none = session_id is None
        loaded = not none and self._detail_id == session_id and self.detail is not None
        titling = busy or self._is_generating(entry)
        rediarize_off = none or entry.kind == "file" or self._rediarize_refusal(entry) is not None
        if entry.job_active:
            delete = ("Cancel job…", False)
        elif none:
            delete = ("Remove", False)
        else:
            delete = ("Delete…", busy)
        states = {
            "library-play": (self._play_label(entry), none),
            "library-rename": ("Rename…", none or busy or not loaded),
            "library-rediarize": ("Re-diarize", rediarize_off or busy),
            "library-retranscribe": ("Re-transcribe", none or busy),
            "library-export": ("Export…", none),
            "library-delete": delete,
            "library-title-button": (
                "Title…" if self.tier == "narrow" else "Edit title…",
                none or titling,
            ),
            "library-generate-button": ("Generate title", none or titling),
        }
        for button_id, (label, disabled) in states.items():
            button = self.query_one(f"#{button_id}", HubButton)
            if button.label.plain != HubButton.label_text(label, button.key).plain:
                button.set_label(label)
            button.disabled = disabled
        # The narrow tier has no room for it on the title row; ``g`` still acts.
        self.query_one("#library-generate-button").display = self.tier != "narrow"
        self._fit_actions()

    def _fit_actions(self) -> None:
        """Put the buttons in the fewest rows that fit: one row in the narrow tier, else two.

        The buttons that do not fit hide from the end; their keys still act.
        """
        grid = self.query_one("#library-actions", Grid)
        width = grid.content_size.width
        buttons = list(grid.query(HubButton).results(HubButton))
        widths = [button.label.cell_length for button in buttons]
        key = (width, tuple(widths), self.tier)
        # No width yet, or the size line below 60x16: the next resize or open fits again.
        if not width or key == self._actions_key:
            return
        self._actions_key = key
        rows = 1 if self.tier == "narrow" else 2
        shown, columns = self._action_grid(widths, width, rows)
        grid.styles.grid_size_columns = columns
        # Explicit widths: an ``auto`` column does not count the margin of its button.
        # The last column has no gap after it.
        cells = self._column_cells(widths[:shown], columns)
        grid.styles.grid_columns = " ".join(
            str(cell + (_ACTION_GAP if column < columns - 1 else 0))
            for column, cell in enumerate(cells)
        )
        for index, button in enumerate(buttons):
            button.display = index < shown
            last = index % columns == columns - 1
            # Inline: the app rules of HubButton outrank screen CSS.
            button.styles.margin = (0, 0 if last else _ACTION_GAP, 0, 0)

    @staticmethod
    def _action_grid(widths: list[int], width: int, rows: int) -> tuple[int, int]:
        """Return how many buttons show and in how many columns: most buttons, fewest rows."""
        for shown in range(len(widths), 0, -1):
            for columns in range(shown, 0, -1):
                if math.ceil(shown / columns) > rows:
                    break
                cells = LibraryScreen._column_cells(widths[:shown], columns)
                if sum(cells) + _ACTION_GAP * (columns - 1) <= width:
                    return shown, columns
        return 1, 1

    @staticmethod
    def _column_cells(widths: list[int], columns: int) -> list[int]:
        return [max(widths[column::columns]) for column in range(columns)]

    def _draw_transcript(self, entry: LibraryEntry, detail: SessionDetail | None) -> None:
        if entry.summary is None:
            job = entry.job
            lines = tuple(job.progress.completed_lines)
            message = (
                f"{_FAILED} {job.error or 'failed'}" if job.state in _FAILED_JOB_STATES else ""
            )
        elif detail is not None:
            lines = detail.lines
            message = "This session has no transcript lines."
        else:
            lines = ()
            message = self._detail_error or "Loading…"
        key = (lines, message)
        if key == self._transcript_key:
            return
        self._transcript_key = key
        ids = tuple(dict.fromkeys(line.speaker_id for line in lines))
        rows: list = self._rows.rows(lines, ids)
        failed = entry.summary is None and entry.job.state in _FAILED_JOB_STATES
        if message and (not rows or failed):
            rows.insert(0, Text(message, style=_DIM))
        self._transcript().update_content(Group(*rows))

    # Play position

    def _follow_playback(self) -> None:
        """Redraw the Play position while a player runs; stop the timer when none runs."""
        if self._playback() is None:
            if self._play_timer is not None:
                self._play_timer.stop()
                self._play_timer = None
        elif self._play_timer is None:
            self._play_timer = self.set_interval(0.25, self._follow_playback)
        if self.opened and self.selected_entry is not None and self.app.is_running:
            self._draw_buttons(self.selected_entry)

    # Loading

    def load_sessions(self, select: str | None = None) -> None:
        """Read the list again off the event loop; select ``select`` when it is listed."""
        if select is not None:
            self._pending_select = select
        if self._list_running:
            self._list_again = True
            return
        self._list_running = True
        self.app.run_worker(self._read_list, group="library-list")

    async def _read_list(self) -> None:
        app = self.app
        store = self.store
        query = self.search_query.strip()
        unknown = tuple(job for job in self._jobs() if job.id not in self._job_targets)

        def read():
            summaries = store.list_sessions() if store is not None else ()
            matches = frozenset(store.search(query)) if store is not None and query else None
            targets = {job.id: self._revision_target(job.options.path) for job in unknown}
            return summaries, matches, targets

        try:
            summaries, matches, targets = await asyncio.to_thread(read)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: sessions_list_failed", exc, safe=True)
            self._list_error = "Could not read saved sessions."
            summaries, matches, targets = (), None, {}
        else:
            self._list_error = None
        finally:
            self._list_running = False
        active = getattr(app.services, "active_session_id", None)
        self.summaries = tuple(s for s in summaries if s.session_id != active)
        if matches is not None:
            self._search_matches = (query, matches)
        for job_id, target in targets.items():
            self._job_targets.setdefault(job_id, target)
        self.loaded = True
        select, self._pending_select = self._pending_select, None
        self._rebuild()
        opening, self._open_after_select = self._open_after_select, False
        if select is not None:
            if self.select_entry(select):
                if opening:
                    self._set_opened(True)
            else:
                app.notify(f"Session {select} was not found.", severity="warning")
        self._load_detail()
        app.refresh_view()
        if self._list_again or query != self.search_query.strip():
            self._list_again = False
            self.load_sessions()

    def _revision_target(self, path) -> tuple[str, str] | None:
        return self.store.revision_target(path) if self.store is not None else None

    def _jobs(self) -> tuple:
        jobs = getattr(self.app.services, "files_jobs", ())
        return tuple(jobs() if callable(jobs) else jobs)

    def _rebuild(self) -> None:
        """Make the entries from the sessions, the jobs and the search; keep the selection."""
        now = datetime.now(UTC)
        job_rows: list[LibraryEntry] = []
        revisions: dict[str, object] = {}
        for job in self._jobs():
            self._job_listed_at.setdefault(job.id, now)
            if job.id not in self._job_targets:
                continue
            target = self._job_targets[job.id]
            state = job.state
            if target is not None:
                if state in ACTIVE_JOB_STATES:
                    revisions.setdefault(target[0], job)
                continue
            if state in ACTIVE_JOB_STATES or (
                state in _FAILED_JOB_STATES and job.id not in self._removed_jobs
            ):
                job_rows.append(
                    LibraryEntry(
                        f"job:{job.id}",
                        None,
                        job=job,
                        job_name=job.options.path.name,
                        listed_at=self._job_listed_at[job.id],
                    )
                )
        entries = list(reversed(job_rows))
        for summary in self.summaries:
            job = revisions.get(summary.session_id)
            entries.append(
                LibraryEntry(
                    summary.session_id,
                    summary,
                    job=job,
                    job_name=job.options.path.name if job is not None else "",
                )
            )
        self._all_count = len(entries)
        needle_query = self.search_query.strip()
        needle = needle_query.casefold()
        if needle:
            # Until the search of this query returns, only job source names match.
            found = self._search_matches
            matches = found[1] if found is not None and found[0] == needle_query else frozenset()
            entries = [
                entry
                for entry in entries
                if (entry.job is not None and needle in entry.job_name.casefold())
                or entry.entry_id in matches
            ]
        self.entries = tuple(entries)
        if self._follow_select is not None and self.entry(self._follow_select) is not None:
            self._selected_id, self._follow_select = self._follow_select, None
        if self.entry(self._selected_id or "") is None:
            self._selected_id = self.entries[0].entry_id if self.entries else None
            # The open session is gone, for example deleted: show the table.
            if self.opened and self.is_mounted:
                self._set_opened(False)

    def _load_detail(self) -> None:
        entry = self.selected_entry
        session_id = entry.session_id if entry is not None else None
        if session_id is None:
            self.detail = None
            self._detail_id = None
            return
        if session_id == self._detail_id or self.store is None or not self.app.is_running:
            return
        self._detail_id = session_id
        self.detail = None
        self._detail_error = None
        self.app.run_worker(
            partial(self._read_detail, session_id), group="library-detail", exclusive=True
        )

    async def _read_detail(self, session_id: str) -> None:
        try:
            detail = await asyncio.to_thread(self.store.read, session_id)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: session_detail_failed", exc, safe=True)
            if session_id == self._detail_id:
                self._detail_error = "Could not read this session."
        else:
            if session_id == self._detail_id:
                self.detail = detail
        self.app.refresh_view()

    def _reload_detail(self) -> None:
        self._detail_id = None
        self._load_detail()

    # Jobs

    def poll_jobs(self) -> None:
        """Follow file jobs and titles: release sessions, keep rows current, reload on an end."""
        # Without a session store there is no session to title.
        reload = self.store is not None and self._follow_titles()
        for job in self._jobs():
            state = job.state
            if job.id not in self._job_targets:
                reload = True
            if self._job_states.get(job.id) != state:
                previous = self._job_states.get(job.id)
                self._job_states[job.id] = state
                if previous is not None and state not in ACTIVE_JOB_STATES:
                    self._job_ended(job)
                    reload = True
            owner = self._job_owners.get(job.id)
            if owner is not None and state not in ACTIVE_JOB_STATES:
                del self._job_owners[job.id]
                self.app.release_session(*owner)
                reload = True
        services = self.app.services
        last_saved = getattr(services, "last_saved", None)
        watch = (
            tuple(session.path.name for session in getattr(services, "stopping_sessions", ())),
            last_saved.path.name if last_saved is not None else None,
        )
        if watch != self._watch_key:
            reload = reload or self._watch_key is not None
            self._watch_key = watch
        if reload:
            self.load_sessions()
        elif self.loaded and self.app.current_mode == "library":
            # Other changes draw through refresh_view; only a job or a busy mark changes alone.
            entry = self.selected_entry
            key = (
                tuple((job.id, job.state, job.progress) for job in self._jobs()),
                self._generating,
                entry is not None
                and entry.session_id is not None
                and self.app.is_busy(entry.session_id),
            )
            if key == self._poll_key:
                return
            self._poll_key = key
            self._rebuild()
            self._load_detail()
            self.refresh_body()

    def _job_ended(self, job) -> None:
        target = self._job_targets.get(job.id)
        name = job.options.path.name
        if job.state == "completed" and job.session_id is not None:
            if self._selected_id == f"job:{job.id}":
                # Select the session when a reload lists it.
                self._follow_select = job.session_id
            self.app.services.titles.generate_auto(job.session_id)
            if target is not None and target[0] == self._detail_id:
                self._detail_id = None
            log.info(fmt_event("hub", "library_job_saved", job_id=job.id))
        elif job.state in _FAILED_JOB_STATES and target is not None:
            self.app.notify(f"The file job for {name} failed: {job.error}", severity="error")

    def submit_file(self, path, **options):
        """Queue one file job; a job that revises a session holds that session until it ends.

        Call it off the event loop: it reads the file system. It returns the job, or ``None``
        when the session is busy (the notice ``session busy`` shows).
        """
        app = self.app
        submit = getattr(app.services, "submit_file", None)
        if submit is None:
            raise RuntimeError("file transcription is not available")
        target = self._revision_target(path)
        owner = None
        if target is not None:
            owner = (target[0], f"file-job-{next(self._owner_ids)}")
            if not app.try_acquire_session(*owner):
                app.notify("session busy", severity="warning")
                return None
        try:
            job = submit(path, **options)
        except BaseException:
            if owner is not None:
                app.release_session(*owner)
            raise
        self._job_targets[job.id] = target
        if owner is not None:
            self._job_owners[job.id] = owner
        return job

    # Selection

    def select_entry(self, entry_id: str) -> bool:
        """Select a listed entry; return false when it is not listed."""
        if self.entry(entry_id) is None:
            return False
        if entry_id != self._selected_id:
            self._selected_id = entry_id
            if self.is_mounted:
                self._load_detail()
                self.app.refresh_view()
        return True

    def show_session(self, session_id: str) -> None:
        """Select and open a session; reload the list first when it is not in it.

        A kept search could hide the session, so it is cleared first.
        """
        if self.is_mounted and (self.search_query or self._search_shown):
            self.action_clear_search()
        if self.select_entry(session_id):
            self._set_opened(True)
        else:
            self._open_after_select = True
            self.load_sessions(select=session_id)
        self.app.refresh_view()

    def action_session_move(self, offset: int) -> None:
        self._move_to(offset)

    def _move_to(self, offset: int, *, clamp: bool = False) -> None:
        """Select the entry ``offset`` rows away; it wraps around unless ``clamp``."""
        if not self.entries:
            return
        index = next(
            (i for i, entry in enumerate(self.entries) if entry.entry_id == self._selected_id), 0
        )
        count = len(self.entries)
        target = min(max(index + offset, 0), count - 1) if clamp else (index + offset) % count
        self.select_entry(self.entries[target].entry_id)

    def on_row_selected(self, event: RowSelected) -> None:
        if event.control.id != "library-list":
            return
        event.stop()
        if 0 <= event.index < len(self.entries):
            self.select_entry(self.entries[event.index].entry_id)

    # Search

    def action_library_search(self) -> None:
        if self.opened:
            return
        search = self.query_one("#library-search", Input)
        search.display = True
        self.query_one("#library-search-button", HubButton).set_label("")
        search.focus()

    @property
    def _search_shown(self) -> bool:
        return self.query_one("#library-search", Input).display

    def action_clear_search(self) -> None:
        search = self.query_one("#library-search", Input)
        had_query = bool(self.search_query)
        self.search_query = ""
        search.value = ""
        search.display = False
        self.query_one("#library-search-button", HubButton).set_label("search")
        self.set_focus(None)
        if had_query:
            self._search_matches = None
            self._rebuild()
            self.app.refresh_view()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "library-search":
            return
        event.stop()
        self.search_query = event.value
        self._rebuild()
        self.app.refresh_view()
        self.load_sessions()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "library-search":
            event.stop()
            self.set_focus(None)

    # Actions

    def _selected_session(self) -> LibraryEntry | None:
        entry = self.selected_entry
        if entry is None or entry.summary is None:
            self.app.notify("Select a saved session first.", severity="warning")
            return None
        return entry

    def action_session_playback(self) -> None:
        entry = self._selected_session()
        toggle = getattr(self.app.services, "toggle_session_playback", None)
        if entry is None or toggle is None:
            return
        self.app.run_worker(partial(self._play, toggle, entry.entry_id), group="library-play")

    async def _play(self, toggle: Callable[..., None], session_id: str) -> None:
        app = self.app

        def report_failure(status: int) -> None:
            app.notify(f"Playback failed: player exit status {status}.", severity="error")

        try:
            await asyncio.to_thread(toggle, session_id, on_failure=report_failure)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: session_playback_failed", exc, safe=True)
            self.app.notify(f"Could not play this session: {exc}", severity="error")
        if app.is_running:
            self._follow_playback()

    def _rediarize_refusal(self, entry: LibraryEntry) -> str | None:
        """Why Re-diarize cannot run on *entry*, once its detail is loaded."""
        if self._detail_id != entry.session_id or self.detail is None:
            return None
        return SessionJobs.rediarize_refusal(self.detail)

    def action_session_rediarize(self) -> None:
        entry = self._selected_session()
        if entry is None:
            return
        refusal = (
            "Re-diarize is not available for a file session: use Re-transcribe."
            if entry.kind == "file"
            else self._rediarize_refusal(entry)
        )
        if refusal is not None:
            self.app.notify(refusal, severity="warning")
            return
        self._start_job("Re-diarize", entry.entry_id, self.app.services.session_jobs.rediarize)

    def action_session_retranscribe(self) -> None:
        entry = self._selected_session()
        if entry is not None:
            self._start_job(
                "Re-transcribe", entry.entry_id, self.app.services.session_jobs.retranscribe
            )

    async def _run_session_job(
        self,
        label: str,
        operation: Callable[..., object],
        session_id: str,
        owner: str,
        *,
        notice: bool = True,
    ) -> object:
        app = self.app
        try:
            result = await asyncio.to_thread(operation, session_id)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: session_job_failed", exc, safe=True)
            app.notify(f"{label} failed: {exc}", severity="error")
            result = None
        else:
            if label == "Delete":
                saved = getattr(app.services, "last_saved", None)
                if saved is not None and saved.path.name == session_id:
                    app.services.last_saved = None
            if notice:
                app.notify(f"{label} complete.")
        finally:
            app.release_session(session_id, owner)
            self._session_work.pop(session_id, None)
            self._reload_detail()
            self.load_sessions()
            if app.is_running:
                app.refresh_view()
        return result

    def action_session_rename(self) -> None:
        app = self.app
        entry = self._selected_session()
        if entry is None:
            return
        if app.is_busy(entry.entry_id):
            app.notify("session busy", severity="warning")
            return
        detail = self.detail if self._detail_id == entry.entry_id else None
        if detail is None:
            app.notify(self._detail_error or "Loading session…", severity="warning")
            return
        speakers = tuple(self._speaker_ids(detail).items())
        if not speakers:
            app.notify("This session has no speaker to rename.", severity="warning")
            return
        app.push_screen(
            RenameDialog(tuple((speaker_id, label) for label, speaker_id in speakers)),
            partial(self._rename, entry.entry_id),
        )

    def _rename(self, session_id: str, value: tuple[str, str] | None) -> None:
        if value is None or self.store is None:
            return
        self._start_job("Rename", session_id, self.store.rename_label, *value)

    def _start_job(
        self,
        label: str,
        session_id: str,
        operation: Callable[..., object],
        *args,
        notice: bool = True,
    ) -> None:
        app = self.app
        owner = f"{label.lower()}-{next(self._owner_ids)}"
        if not app.try_acquire_session(session_id, owner):
            app.notify("session busy", severity="warning")
            return
        self._session_work[session_id] = label.lower()
        app.run_worker(
            partial(
                self._run_session_job,
                label,
                lambda sid: operation(sid, *args),
                session_id,
                owner,
                notice=notice,
            ),
            group="library-session-job",
        )
        app.refresh_view()

    def action_session_title(self) -> None:
        app = self.app
        entry = self._selected_session()
        if entry is None or self.store is None:
            return
        if self._title_busy(entry.entry_id):
            app.notify("session busy", severity="warning")
            return
        app.push_screen(
            TitleDialog(entry.summary.title or ""), partial(self._save_title, entry.entry_id)
        )

    def _save_title(self, session_id: str, title: str | None) -> None:
        if title is None or self.store is None:
            return
        self._start_job("Title", session_id, self.store.set_title, title, notice=False)

    def _title_busy(self, session_id: str) -> bool:
        """Whether a job holds the session or the model works on its title."""
        return self.app.is_busy(session_id) or session_id in self.app.services.titles.generating

    def action_session_generate_title(self) -> None:
        app = self.app
        entry = self._selected_session()
        if entry is None or self.store is None:
            return
        if self._title_busy(entry.entry_id):
            app.notify("session busy", severity="warning")
            return
        summary = entry.summary
        if summary.title is not None and summary.title_source != "model":
            app.push_screen(
                QuitConfirm(
                    "Replace the title you typed with a generated title?",
                    confirm="Generate",
                    cancel="Keep",
                ),
                partial(self._generate_title, entry.entry_id, summary.title),
            )
        else:
            self._generate_title(entry.entry_id, None, True)

    def _generate_title(self, session_id: str, replace: str | None, confirmed: bool | None) -> None:
        """Queue ``g``; ``replace`` is the typed title that the user agreed to replace."""
        if not confirmed:
            return
        app = self.app
        titles = app.services.titles
        if app.is_busy(session_id) or not titles.generate(session_id, replace=replace):
            app.notify("session busy", severity="warning")
            return
        self._generating = titles.generating
        app.refresh_view()

    def _follow_titles(self) -> bool:
        """Show the notices of ``g`` and the new generating set; true when a title was stored."""
        titles = self.app.services.titles
        for message, severity in titles.take_notices():
            self.app.notify(message, severity=severity)
        self._generating = titles.generating
        # A count, not the generating set: a title stored between two polls still counts.
        stored = titles.stored
        changed = stored != self._titles_stored
        self._titles_stored = stored
        return changed

    def action_session_export(self) -> None:
        entry = self._selected_session()
        if entry is None or self.store is None:
            return

        async def export(format_name: str, folder: pathlib.Path) -> pathlib.Path:
            try:
                path = await asyncio.to_thread(
                    self.store.export, entry.entry_id, folder, format_name
                )
            except Exception as exc:
                log_failure(log, logging.ERROR, "hub: session_export_failed", exc, safe=True)
                raise
            log.info(fmt_event("hub", "session_exported", format=format_name))
            return path

        self.app.push_screen(ExportDialog(entry.entry_id, export))

    def action_session_delete(self) -> None:
        app = self.app
        entry = self.selected_entry
        if entry is None:
            app.notify("Select an entry first.", severity="warning")
            return
        if entry.job_active:
            app.push_screen(
                QuitConfirm(
                    f"Cancel the file job for {entry.job_name}?",
                    confirm="Cancel job",
                    cancel="Keep job",
                ),
                partial(self._cancel_job, entry.job),
            )
        elif entry.summary is None:
            self._removed_jobs.add(entry.job.id)
            self._rebuild()
            app.refresh_view()
        elif app.is_busy(entry.entry_id):
            app.notify("session busy", severity="warning")
        else:
            app.push_screen(
                QuitConfirm(
                    f"Delete session {entry.entry_id}? This action cannot be undone.",
                    confirm="Delete",
                    cancel="Keep",
                ),
                partial(self._delete, entry.entry_id),
            )

    def _cancel_job(self, job, confirmed: bool | None) -> None:
        if not confirmed:
            return
        app = self.app
        cancel = getattr(app.services, "cancel_file", None)
        try:
            cancelled = cancel(job) if cancel is not None else job.cancel()
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: file_cancel_failed", exc, safe=True)
            app.notify("Could not cancel this file job.", severity="error")
            return
        log.info(fmt_event("hub", "files_job_cancel_requested", job_id=job.id))
        if not cancelled:
            app.notify("This file job has already finished.", severity="warning")

    def _delete(self, session_id: str, confirmed: bool | None) -> None:
        if confirmed and self.store is not None:
            self._start_job("Delete", session_id, self._delete_session)

    def _delete_session(self, session_id: str) -> None:
        """Stop the player of this session, then delete it; runs off the event loop."""
        self.app.services.stop_session_playback(session_id)
        self.store.delete(session_id)

    # Transcript scroll

    def action_transcribe_file(self) -> None:
        if self.app.config_editor.read_only:
            self.app.notify(
                "Fix the invalid configuration before transcribing files.", severity="error"
            )
            return
        log.info(fmt_event("hub", "library_transcribe_opened"))
        self.app.push_screen(TranscribeDialog(self.files_home), self._queue_file)

    def _queue_file(self, result: tuple[pathlib.Path, dict[str, object]] | None) -> None:
        if result is None:
            return
        app = self.app
        if app.config_editor.read_only:
            app.notify("Fix the invalid configuration before transcribing files.", severity="error")
            return
        path, options = result
        self.files_submitting += 1
        log.info(fmt_event("hub", "files_queue_requested", count=1))
        app.run_worker(partial(self._submit_file, path, options), group="files-submit")

    async def _submit_file(self, path: pathlib.Path, options: dict[str, object]) -> None:
        app = self.app
        try:
            job = await asyncio.to_thread(self.submit_file, path, **options)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: file_submit_failed", exc, safe=True)
            app.notify("Could not queue this file.", severity="error")
            job = None
        finally:
            self.files_submitting -= 1
        if job is None or not app.is_running:
            return
        # The job was queued when it was submitted, so the poll sees its end even when it ends
        # before the next poll.
        self._job_states.setdefault(job.id, "queued")
        target = self._job_targets.get(job.id)
        if self.search_query:
            self.action_clear_search()
        self._rebuild()
        self.select_entry(target[0] if target is not None else f"job:{job.id}")
        app.refresh_view()

    @property
    def files_running(self) -> bool:
        return self.files_submitting > 0 or bool(getattr(self.app.services, "files_running", False))
