# SPDX-License-Identifier: GPL-3.0-or-later
"""The Library screen: saved sessions and file jobs, search, detail, actions and export."""

from __future__ import annotations

import asyncio
import itertools
import logging
import pathlib
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, ClassVar

from rich.console import Group
from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Rule, Static

from stenographer.cli.hub.config_dialog import ConfigPrompt
from stenographer.cli.hub.dialogs import QuitConfirm
from stenographer.cli.hub.export_dialog import ExportDialog
from stenographer.cli.hub.files_view import FilesPanel
from stenographer.cli.hub.hub_screen import HubScreen
from stenographer.cli.hub.library_entry import ACTIVE_JOB_STATES, LibraryEntry
from stenographer.cli.hub.rename_dialog import RenameDialog
from stenographer.cli.hub.widgets.button import HubButton
from stenographer.cli.hub.widgets.frame import Frame
from stenographer.cli.hub.widgets.key_hints import KeyHints
from stenographer.cli.hub.widgets.selectable_list import SelectableList
from stenographer.cli.hub.widgets.sparkline import Sparkline
from stenographer.cli.hub.widgets.status_token import StatusToken
from stenographer.cli.hub.widgets.transcript_line import TranscriptLine
from stenographer.cli.shared.speaker_colors import speaker_color
from stenographer.cli.shared.transcript_scroll import TranscriptScroll
from stenographer.lib.logging.pipeline import fmt_event, log_failure

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.app import ComposeResult

    from stenographer.cli.hub.widgets.row_selected import RowSelected
    from stenographer.lib.sessions.models import SessionDetail, SessionSummary

log = logging.getLogger(__name__)

_LIBRARY_ACTIONS = frozenset(
    {
        "session_move",
        "library_search",
        "clear_search",
        "session_playback",
        "session_rediarize",
        "session_retranscribe",
        "session_rename",
        "session_export",
        "session_delete",
        "scroll_page",
        "scroll_home",
        "scroll_end",
        "open_files",
    }
)
_FILES_ACTIONS = frozenset(
    {
        "files_move",
        "files_next_area",
        "files_toggle",
        "files_enter",
        "files_options",
        "files_search",
        "files_cancel",
        "close_files",
    }
)
_FAILED_JOB_STATES = frozenset({"failed", "needs_ffmpeg"})
_FAILED = "\u00d7"  # the multiplication sign: the failed glyph
_COLUMNS = f"  {'date':<12} {'dur':>7} {'kind':<4} {'spk':>3}  labels"
_DIM = StatusToken.TONES["dim"]
_SPARK_CELLS = 28
# Buttons of the detail: ``(id, key, label, action, tone)``.
_ACTIONS = (
    ("library-play", "p", "▶ Play", "session_playback", "default"),
    ("library-rename", "r", "Rename speaker…", "session_rename", "default"),
    ("library-rediarize", "d", "Re-diarize", "session_rediarize", "default"),
    ("library-retranscribe", "t", "Re-transcribe", "session_retranscribe", "default"),
    ("library-export", "x", "Export…", "session_export", "default"),
    ("library-delete", "del", "Delete…", "session_delete", "danger"),
)


class LibraryScreen(HubScreen):
    """List recordings, file sessions and unfinished file jobs; act on the selected entry.

    ``n`` opens the temporary Files view as a full-body sub-view.
    """

    SCREEN_NAME = "library"
    SCREEN_TITLE = "Library"
    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        ("up", "session_move(-1)", "Previous entry"),
        ("down", "session_move(1)", "Next entry"),
        ("slash", "library_search", "Search titles and transcripts"),
        ("escape", "clear_search", "Clear the search"),
        ("p", "session_playback", "Play or stop the session"),
        ("r", "session_rename", "Rename a speaker"),
        ("d", "session_rediarize", "Re-diarize the session"),
        ("t", "session_retranscribe", "Re-transcribe the session"),
        ("x", "session_export", "Export the session"),
        Binding(
            "delete", "session_delete", "Delete the session or cancel its job", key_display="del"
        ),
        ("pageup", "scroll_page(-1)", "Scroll transcript up one page"),
        ("pagedown", "scroll_page(1)", "Scroll transcript down one page"),
        ("home", "scroll_home", "Scroll to transcript start"),
        ("end", "scroll_end", "Scroll to transcript end"),
        ("n", "open_files", "Transcribe a file"),
        ("up", "files_move(-1)", "Previous file, option or job"),
        ("down", "files_move(1)", "Next file, option or job"),
        Binding("tab", "files_next_area", "Change Files panel focus", priority=True),
        ("space", "files_toggle", "Select a file or change an option"),
        ("enter", "files_enter", "Queue files or edit an option"),
        ("o", "files_options", "Edit Files options"),
        ("slash", "files_search", "Search audio files"),
        ("x", "files_cancel", "Cancel the selected job"),
        ("escape", "close_files", "Back to the Library list"),
    ]
    DEFAULT_CSS = """
    LibraryScreen #library-body { height: 1fr; }
    LibraryScreen #library-list-frame {
        width: 1fr;
        height: 1fr;
        margin-right: 1;
    }
    LibraryScreen #library-detail-frame { width: 1fr; height: 1fr; }
    LibraryScreen #library-search-row { height: 1; }
    LibraryScreen #library-search {
        width: 1fr;
        height: 1;
        padding: 0;
        border: none;
    }
    LibraryScreen #library-transcribe { margin-bottom: 1; }
    LibraryScreen #library-columns { height: 1; color: #8b93a1; }
    LibraryScreen #library-list-scroll { height: 1fr; }
    LibraryScreen #library-detail-head { height: 1; }
    LibraryScreen #library-detail-title { width: 1fr; text-style: bold; }
    LibraryScreen #library-detail-state { width: auto; }
    LibraryScreen #library-speakers { height: auto; }
    LibraryScreen .library-actions { height: 1; }
    LibraryScreen #library-actions-0 { margin-top: 1; }
    LibraryScreen #library-action-help { height: auto; color: #8b93a1; }
    LibraryScreen #library-rule { margin: 0; color: #3a4150; }
    LibraryScreen #library-transcript { height: 1fr; }
    LibraryScreen .library-hints { height: 1; }
    """

    def __init__(self, services, *, files_home: pathlib.Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.store = getattr(services, "session_store", None)
        self.files_panel = FilesPanel(
            home=files_home,
            start=getattr(services, "files_start_folder", None),
            id="files-panel",
        )
        self.files_panel.display = False
        self.files_open = False
        self.files_submitting = 0
        self.loaded = False
        self.summaries: tuple[SessionSummary, ...] = ()
        self.entries: tuple[LibraryEntry, ...] = ()
        self.detail: SessionDetail | None = None
        self.search_query = ""
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
        self._removed_jobs: set[str] = set()
        self._owner_ids = itertools.count(1)
        self._pending_select: str | None = None
        self._follow_select: str | None = None
        self._list_running = False
        self._list_again = False
        self._watch_key: object = None
        self._rows_key: object = None
        self._transcript_key: object = None

    def compose_body(self) -> ComposeResult:
        with Horizontal(id="library-body"):
            with Frame(id="library-list-frame", variant="fill"):
                with Horizontal(id="library-search-row"):
                    yield HubButton(
                        "search titles and transcripts",
                        key="/",
                        action="library_search",
                        id="library-search-button",
                    )
                    yield Input(placeholder="search titles and transcripts", id="library-search")
                yield HubButton(
                    "+ Transcribe a file…",
                    key="n",
                    action="open_files",
                    tone="primary",
                    id="library-transcribe",
                )
                yield Static(_COLUMNS, id="library-columns", markup=False)
                with Vertical(id="library-list-scroll"):
                    yield SelectableList(id="library-list")
                yield KeyHints(footer=False, id="library-list-hints", classes="library-hints")
            with Frame(id="library-detail-frame", variant="fill"):
                with Horizontal(id="library-detail-head"):
                    yield Static("", id="library-detail-title", markup=False)
                    yield Static("", id="library-detail-state", markup=False)
                yield Static("", id="library-speakers", markup=False)
                yield Sparkline("mic", label_after=False, width=_SPARK_CELLS, id="library-mic")
                yield Sparkline(
                    "sys", label_after=False, width=_SPARK_CELLS, color="#ffaf5f", id="library-sys"
                )
                # Two buttons per row, so each ``busy`` word stays visible.
                for row in range(0, len(_ACTIONS), 2):
                    with Horizontal(id=f"library-actions-{row}", classes="library-actions"):
                        for button_id, key, label, action, tone in _ACTIONS[row : row + 2]:
                            yield HubButton(label, key=key, action=action, tone=tone, id=button_id)
                yield Static("", id="library-action-help", markup=False)
                yield Rule(id="library-rule")
                yield TranscriptScroll(id="library-transcript", can_focus=False)
                yield KeyHints(footer=False, id="library-detail-hints", classes="library-hints")
        yield self.files_panel

    def on_mount(self) -> None:
        self.query_one("#library-search", Input).display = False
        self.query_one("#library-list-hints", KeyHints).set_hints(
            ("↑↓", "select"), ("del", "delete")
        )
        self.query_one("#library-detail-hints", KeyHints).set_hints(
            ("PgUp/Dn", "page"), ("Home/End", "top/end")
        )
        # The app rules of HubButton outrank screen CSS; the action rows need tight buttons.
        for button in self.query(".library-actions HubButton"):
            button.styles.padding = 0
        self.set_interval(0.1, self.poll_jobs)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in _LIBRARY_ACTIONS:
            return not self.files_open
        if action in _FILES_ACTIONS:
            return self.files_open and (action != "files_next_area" or self.app.screen is self)
        return True

    def footer_hints(self) -> tuple[tuple[str, str], ...]:
        if self.files_open:
            return (
                ("↑↓", "move"),
                ("tab", "focus"),
                ("/", "search"),
                ("enter", "queue"),
                ("space", "select"),
                ("o", "options"),
                ("x", "cancel"),
                ("esc", "back"),
                ("1 2 3", "screens"),
            )
        return (
            ("n", "transcribe file"),
            ("/", "search"),
            ("p", "play"),
            ("r", "rename"),
            ("d", "re-diarize"),
            ("t", "re-transcribe"),
            ("x", "export"),
            ("del", "delete"),
            ("1 2 3", "screens"),
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

    # Drawing

    def refresh_body(self) -> None:
        self.query_one("#library-body").display = not self.files_open
        self.files_panel.display = self.files_open
        if self.files_open:
            self.refresh_files()
        else:
            self._draw_list()
            self._draw_detail()
        self.app.set_context_card("library", self._storage_card(), title="storage")

    def _storage_card(self) -> str:
        count = self._all_count
        total = sum(summary.audio_size_bytes for summary in self.summaries)
        text = f"{count} {'entry' if count == 1 else 'entries'}\n{self._format_size(total)} audio"
        if self.store is not None:
            text += f"\n\n{self.store.root}"
        return text

    def _draw_list(self) -> None:
        rows = tuple((self._row_text(entry), "") for entry in self.entries)
        index = next(
            (i for i, entry in enumerate(self.entries) if entry.entry_id == self._selected_id),
            None,
        )
        if not rows:
            message = self._list_error or (
                "No matches." if self.search_query.strip() else "No saved sessions."
            )
            rows = ((Text(message, style=_DIM), ""),)
            index = None
        key = (tuple(row[0].plain for row in rows), index)
        if key != self._rows_key:
            self._rows_key = key
            self.query_one("#library-list", SelectableList).set_rows(rows, index)

    def _row_text(self, entry: LibraryEntry) -> Text:
        summary = entry.summary
        job = entry.job
        if summary is not None:
            when = summary.started_at.astimezone()
            dur = self._duration(summary.duration_seconds)
            spk = str(summary.speaker_count)
        else:
            when = (self._job_listed_at.get(job.id) or datetime.now(UTC)).astimezone()
            dur = "—"
            spk = "—"
        dur_style = None
        if entry.job_active:
            dur = "queued" if job.state == "queued" else f"{job.progress.percent}%"
            dur_style = StatusToken.TONES["warn"]
        text = Text(f"{when:%d %b %H:%M} ")
        text.append(f"{dur:>7}", style=dur_style)
        text.append(f" {entry.kind:<4} {spk:>3}  ")
        if summary is None:
            if job.state in _FAILED_JOB_STATES:
                danger = StatusToken.TONES["danger"]
                text.append(f"{_FAILED} failed · {entry.job_name}", style=danger)
            else:
                text.append(entry.job_name)
        elif summary.kind == "file":
            text.append(summary.source_name or "file")
        elif summary.interrupted:
            text.append("! interrupted", style=StatusToken.TONES["danger"])
        else:
            text.append(summary.label_state)
        return text

    def _draw_detail(self) -> None:
        entry = self.selected_entry
        title, state = self._detail_head(entry)
        self.query_one("#library-detail-title", Static).update(title)
        self.query_one("#library-detail-state", Static).update(state)
        detail = self.detail if entry is not None and entry.summary is not None else None
        recording = detail is not None and detail.summary.kind == "rec"
        speakers = self.query_one("#library-speakers", Static)
        speakers.update(self._speakers_text(detail) if detail is not None else "")
        speakers.display = detail is not None
        for spark_id, source in (("#library-mic", "mic"), ("#library-sys", "system")):
            spark = self.query_one(spark_id, Sparkline)
            spark.display = recording
            if recording:
                spark.set_values(self._resample(detail.activity.get(source, ())))
        self._draw_buttons(entry)
        self._draw_transcript(entry, detail)

    def _detail_head(self, entry: LibraryEntry | None) -> tuple[str, Text]:
        if entry is None:
            return ("No entry selected." if not self.entries else "", Text(""))
        job = entry.job
        summary = entry.summary
        if summary is None:
            when = (self._job_listed_at.get(job.id) or datetime.now(UTC)).astimezone()
            title = f"{when:%d %b %Y · %H:%M} · file · {entry.job_name}"
            return title, self._job_state(job)
        when = summary.started_at.astimezone()
        title = f"{when:%d %b %Y · %H:%M} · {self._duration(summary.duration_seconds)} · "
        title += "file" if summary.kind == "file" else "recording"
        if entry.job_active:
            state = self._job_state(job)
            state.append(f" · {entry.job_name}", style=_DIM)
        elif summary.interrupted:
            state = StatusToken.text("!", "interrupted", "danger")
        elif summary.label_state == "live":
            state = Text("live labels", style=_DIM)
        else:
            state = Text(summary.label_state, style=StatusToken.TONES["ok"])
        return title, state

    @staticmethod
    def _job_state(job) -> Text:
        if job.state == "queued":
            return StatusToken.text("◌", "queued", "warn")
        if job.state == "running":
            return StatusToken.text("▶", f"transcribing {job.progress.percent}%", "warn")
        if job.state in _FAILED_JOB_STATES:
            return StatusToken.text(_FAILED, "failed", "danger")
        return StatusToken.text("■", job.state, "dim")

    def _speakers_text(self, detail: SessionDetail) -> Text:
        ids = self._speaker_ids(detail)
        text = Text()
        for label, seconds in detail.talk_time.items():
            if text:
                text.append("   ")
            speaker_id = ids.get(label, label)
            color = speaker_color(
                speaker_id, tuple(ids.values()), source=self._source_of(detail, label)
            )
            text.append(label, style=f"bold {color}")
            text.append(f" {self._duration(seconds)}")
        return text or Text("no speakers", style=_DIM)

    @staticmethod
    def _speaker_ids(detail: SessionDetail) -> dict[str, str]:
        ids: dict[str, str] = {}
        for line in detail.lines:
            ids.setdefault(line.label, line.speaker_id)
        return ids

    @staticmethod
    def _source_of(detail: SessionDetail, label: str) -> str | None:
        return next((line.source for line in detail.lines if line.label == label), None)

    def _draw_buttons(self, entry: LibraryEntry | None) -> None:
        session_id = entry.session_id if entry is not None else None
        busy = session_id is not None and self.app.is_busy(session_id)
        labels: dict[str, tuple[str, bool]] = {}
        for button_id, _key, label, _action, _tone in _ACTIONS:
            labels[button_id] = (label, session_id is None)
        if session_id is not None:
            for button_id in ("library-rename", "library-rediarize", "library-retranscribe"):
                if busy:
                    labels[button_id] = (f"{labels[button_id][0]} · busy", True)
            if entry.kind == "file":
                labels["library-rediarize"] = ("Re-diarize", True)
            if entry.job_active:
                labels["library-delete"] = ("Cancel job… · delete busy", False)
            elif busy:
                labels["library-delete"] = ("Delete… · busy", True)
        elif entry is not None:
            labels["library-delete"] = (
                ("Cancel job…", False) if entry.job_active else ("Remove", False)
            )
        help_line = self.query_one("#library-action-help", Static)
        help_line.update(
            "d re-diarize: use Re-transcribe" if entry and entry.kind == "file" else ""
        )
        help_line.display = entry is not None and entry.kind == "file"
        for button_id, (label, disabled) in labels.items():
            button = self.query_one(f"#{button_id}", HubButton)
            if str(button.label) != str(HubButton.label_text(label, button.key)):
                button.set_label(label)
            button.disabled = disabled

    def _draw_transcript(self, entry: LibraryEntry | None, detail: SessionDetail | None) -> None:
        if entry is not None and entry.summary is None:
            job = entry.job
            lines = tuple(job.progress.completed_lines)
            message = (
                f"{_FAILED} {job.error or 'failed'}"
                if job.state in _FAILED_JOB_STATES
                else "Finished lines show here while the job runs."
            )
        elif detail is not None:
            lines = detail.lines
            message = "This session has no transcript lines."
        else:
            lines = ()
            message = self._detail_error or ("Loading…" if entry is not None else "")
        key = (lines, message)
        if key == self._transcript_key:
            return
        self._transcript_key = key
        ids = tuple(dict.fromkeys(line.speaker_id for line in lines))
        rows: list = [
            TranscriptLine(
                line.start,
                line.label,
                line.text,
                color=speaker_color(line.speaker_id, ids, source=line.source),
                source=line.source,
            ).row()
            for line in lines
        ]
        if not rows and message:
            rows.append(Text(message, style=_DIM))
        self.query_one("#library-transcript", TranscriptScroll).update_content(Group(*rows))

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
        if select is not None and not self.select_entry(select):
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
        """Follow file jobs: release their sessions, keep rows current, reload on an end."""
        reload = False
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
        elif self.loaded and self.app.current_mode == "library" and not self.files_open:
            self._rebuild()
            self._load_detail()
            self._draw_list()
            self._draw_detail()

    def _job_ended(self, job) -> None:
        target = self._job_targets.get(job.id)
        name = job.options.path.name
        if job.state == "completed" and job.session_id is not None:
            if self._selected_id == f"job:{job.id}":
                # Select the session when a reload lists it.
                self._follow_select = job.session_id
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

    def select_session(self, session_id: str) -> bool:
        """Select a listed session by its ID (Record ``o``); false when it is not listed."""
        return self.select_entry(session_id)

    def show_session(self, session_id: str) -> None:
        """Select a session; reload the list first when it is not in it."""
        self.close_files_view()
        if not self.select_session(session_id):
            self.load_sessions(select=session_id)
        self.app.refresh_view()

    def action_session_move(self, offset: int) -> None:
        if not self.entries:
            return
        index = next(
            (i for i, entry in enumerate(self.entries) if entry.entry_id == self._selected_id), 0
        )
        self.select_entry(self.entries[(index + offset) % len(self.entries)].entry_id)

    def on_row_selected(self, event: RowSelected) -> None:
        if event.control.id != "library-list":
            return
        event.stop()
        if 0 <= event.index < len(self.entries):
            self.select_entry(self.entries[event.index].entry_id)

    # Search

    def action_library_search(self) -> None:
        search = self.query_one("#library-search", Input)
        search.display = True
        self.query_one("#library-search-button", HubButton).set_label("")
        search.focus()

    def action_clear_search(self) -> None:
        search = self.query_one("#library-search", Input)
        had_query = bool(self.search_query)
        self.search_query = ""
        search.value = ""
        search.display = False
        self.query_one("#library-search-button", HubButton).set_label(
            "search titles and transcripts"
        )
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

    async def _play(self, toggle: Callable[[str], None], session_id: str) -> None:
        try:
            await asyncio.to_thread(toggle, session_id)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: session_playback_failed", exc, safe=True)
            self.app.notify(f"Could not play this session: {exc}", severity="error")

    def action_session_rediarize(self) -> None:
        entry = self._selected_session()
        if entry is None:
            return
        if entry.kind == "file":
            self.app.notify(
                "Re-diarize is not available for a file session: use Re-transcribe.",
                severity="warning",
            )
            return
        self._start_session_job("Re-diarize", "rediarize_session", entry.entry_id)

    def action_session_retranscribe(self) -> None:
        entry = self._selected_session()
        if entry is not None:
            self._start_session_job("Re-transcribe", "retranscribe_session", entry.entry_id)

    def _start_session_job(self, label: str, method: str, session_id: str) -> None:
        app = self.app
        operation = getattr(app.services, method, None)
        if operation is None:
            return
        owner = f"{method}-{next(self._owner_ids)}"
        if not app.try_acquire_session(session_id, owner):
            app.notify("session busy", severity="warning")
            return
        app.run_worker(
            partial(self._run_session_job, label, operation, session_id, owner),
            group="library-session-job",
        )
        app.refresh_view()

    async def _run_session_job(
        self, label: str, operation: Callable[..., object], session_id: str, owner: str
    ) -> object:
        app = self.app
        try:
            result = await asyncio.to_thread(operation, session_id)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: session_job_failed", exc, safe=True)
            app.notify(f"{label} failed: {exc}", severity="error")
            result = None
        else:
            app.notify(f"{label} complete.")
        finally:
            app.release_session(session_id, owner)
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
        speakers = tuple(self._speaker_ids(detail).items()) if detail is not None else ()
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
        self._start_store_job("Rename", session_id, self.store.rename_speaker, *value)

    def _start_store_job(
        self, label: str, session_id: str, operation: Callable[..., object], *args
    ) -> None:
        app = self.app
        owner = f"{label.lower()}-{next(self._owner_ids)}"
        if not app.try_acquire_session(session_id, owner):
            app.notify("session busy", severity="warning")
            return
        app.run_worker(
            partial(
                self._run_session_job, label, lambda sid: operation(sid, *args), session_id, owner
            ),
            group="library-session-job",
        )
        app.refresh_view()

    def action_session_export(self) -> None:
        entry = self._selected_session()
        if entry is None or self.store is None:
            return
        self.app.push_screen(ExportDialog(entry.entry_id), partial(self._export, entry.entry_id))

    def _export(self, session_id: str, value: tuple[str, pathlib.Path] | None) -> None:
        if value is not None:
            self.app.run_worker(partial(self._write_export, session_id, *value))

    async def _write_export(self, session_id: str, format_name: str, folder: pathlib.Path) -> None:
        app = self.app
        try:
            path = await asyncio.to_thread(self.store.export, session_id, folder, format_name)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: session_export_failed", exc, safe=True)
            app.notify(f"Could not export this session: {exc}", severity="error")
        else:
            log.info(fmt_event("hub", "session_exported", format=format_name))
            app.notify(f"Exported to {path}")

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
            self._start_store_job("Delete", session_id, self.store.delete)

    # Transcript scroll

    def _transcript(self) -> TranscriptScroll:
        return self.query_one("#library-transcript", TranscriptScroll)

    def action_scroll_page(self, offset: int) -> None:
        self._transcript().scroll_page(offset)

    def action_scroll_home(self) -> None:
        self._transcript().scroll_top()

    def action_scroll_end(self) -> None:
        self._transcript().scroll_bottom()

    # Files sub-view (temporary; task 201 replaces it)

    def action_open_files(self) -> None:
        self.files_open = True
        log.info(fmt_event("hub", "library_files_opened"))
        self.app.refresh_view()

    def action_close_files(self) -> None:
        self.close_files_view()
        self.load_sessions()
        self.app.refresh_view()

    def close_files_view(self) -> None:
        self.files_open = False

    def refresh_files(self) -> None:
        self.files_panel.set_jobs(self._jobs())

    @property
    def files_running(self) -> bool:
        return self.files_submitting > 0 or bool(getattr(self.app.services, "files_running", False))

    def action_files_move(self, offset: int) -> None:
        self.files_panel.move_selection(offset)

    def action_files_next_area(self) -> None:
        self.files_panel.cycle_focus()
        log.info(fmt_event("hub", "files_focus_changed", area=self.files_panel.focus_area))

    def action_files_options(self) -> None:
        self.files_panel.toggle_options()
        log.info(fmt_event("hub", "files_options_toggled", open=self.files_panel.options_open))

    def action_files_toggle(self) -> None:
        panel = self.files_panel
        if panel.focus_area == "options":
            self._edit_files_option()
        elif panel.focus_area == "browser":
            panel.toggle_selected_file()
            log.info(fmt_event("hub", "files_selection_changed", count=len(panel.selected_paths)))

    def action_files_enter(self) -> None:
        if self.files_panel.focus_area == "options":
            self._edit_files_option()
        else:
            self._queue_selected_files()

    def action_files_search(self) -> None:
        self.app.push_screen(
            ConfigPrompt("Search audio files", initial=self.files_panel.search_term),
            self._search_files,
        )

    def _search_files(self, term: str | None) -> None:
        if term is not None:
            self.files_panel.set_search(term)
            log.info(fmt_event("hub", "files_search_updated", active=bool(term.strip())))

    def _edit_files_option(self) -> None:
        panel = self.files_panel
        option = panel.selected_option
        log.info(fmt_event("hub", "files_option_edit_started", option=option.replace(" ", "_")))
        if option == "diarize":
            panel.diarize = not panel.diarize
            panel.refresh_display()
        elif option == "refine":
            panel.refine = not panel.refine
            panel.refresh_display()
        elif option == "speaker count":
            count = "auto" if panel.speaker_count is None else str(panel.speaker_count)
            self.app.push_screen(
                ConfigPrompt("Speaker count (auto or a positive number)", initial=count),
                self._set_file_speaker_count,
            )

    def _set_file_speaker_count(self, value: str | None) -> None:
        if value is None:
            return
        normalized = value.strip().lower()
        try:
            count = None if normalized == "auto" else int(normalized)
            if count is not None and count < 1:
                raise ValueError
        except ValueError:
            self.app.notify("Speaker count must be auto or a positive number.", severity="warning")
            return
        self.files_panel.speaker_count = count
        self.files_panel.refresh_display()
        log.info(fmt_event("hub", "files_speaker_count_changed", automatic=count is None))

    def _queue_selected_files(self) -> None:
        app = self.app
        selected = self.files_panel.selected_entry
        paths = self.files_panel.enter()
        if not paths:
            if selected is not None and selected.is_dir:
                log.info(fmt_event("hub", "files_directory_opened"))
            return
        if app.config_editor is not None and app.config_editor.read_only:
            app.notify("Fix the invalid configuration before transcribing files.", severity="error")
            return
        options = {
            "diarize": self.files_panel.diarize,
            "speaker_count": self.files_panel.speaker_count,
            "refine": self.files_panel.refine,
        }
        self.files_submitting += len(paths)
        log.info(fmt_event("hub", "files_queue_requested", count=len(paths)))
        app.refresh_view()
        app.run_worker(partial(self._submit_files, paths, options), group="files-submit")

    async def _submit_files(
        self, paths: tuple[pathlib.Path, ...], options: dict[str, object]
    ) -> None:
        app = self.app
        for path in paths:
            try:
                await asyncio.to_thread(self.submit_file, path, **options)
            except Exception as exc:
                log_failure(log, logging.ERROR, "hub: file_submit_failed", exc, safe=True)
                app.notify("Could not queue this file.", severity="error")
            finally:
                self.files_submitting = max(0, self.files_submitting - 1)
                self.refresh_files()
        if app.is_running:
            app.refresh_view()

    def action_files_cancel(self) -> None:
        app = self.app
        if self.files_panel.focus_area != "queue":
            app.notify("Focus the queue to select a Files job.", severity="warning")
            return
        job = self.files_panel.selected_job
        if job is None:
            app.notify("Select a Files job first.", severity="warning")
            return
        cancel = getattr(app.services, "cancel_file", None)
        try:
            cancelled = cancel(job) if cancel is not None else job.cancel()
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: file_cancel_failed", exc, safe=True)
            app.notify("Could not cancel this Files job.", severity="error")
            return
        log.info(
            fmt_event("hub", "files_job_cancel_requested", job_id=getattr(job, "id", "unknown"))
        )
        if not cancelled:
            app.notify("This Files job has already finished.", severity="warning")
        self.refresh_files()

    # Formats

    @staticmethod
    def _duration(seconds: float) -> str:
        total = max(0, int(seconds))
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    @staticmethod
    def _format_size(size: int) -> str:
        amount = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if amount < 1024 or unit == "GB":
                return f"{amount:.1f} {unit}"
            amount /= 1024
        return f"{amount:.1f} GB"

    @staticmethod
    def _resample(activity: tuple[float, ...]) -> tuple[float, ...]:
        """Return at most ``_SPARK_CELLS`` values: the peak of each equal slice."""
        count = min(_SPARK_CELLS, len(activity))
        return tuple(
            max(activity[index * len(activity) // count : (index + 1) * len(activity) // count])
            for index in range(count)
        )
