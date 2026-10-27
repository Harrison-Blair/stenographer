# SPDX-License-Identifier: GPL-3.0-or-later
"""The Library screen: saved sessions, and the file transcription sub-view."""

from __future__ import annotations

import asyncio
import logging
import pathlib
from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding

from stenographer.cli.hub.config_dialog import ConfigPrompt
from stenographer.cli.hub.dialogs import QuitConfirm
from stenographer.cli.hub.files_view import FilesPanel
from stenographer.cli.hub.hub_screen import HubScreen
from stenographer.cli.hub.sessions_view import SessionsPanel
from stenographer.lib.logging.pipeline import fmt_event, log_failure

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.app import ComposeResult

log = logging.getLogger(__name__)

_SESSION_ACTIONS = frozenset(
    {
        "session_move",
        "session_playback",
        "session_rediarize",
        "session_retranscribe",
        "session_rename",
        "session_export",
        "session_delete",
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


class LibraryScreen(HubScreen):
    """List saved sessions; ``n`` opens the Files view as a full-body sub-view."""

    SCREEN_NAME = "library"
    SCREEN_TITLE = "Library"
    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        ("up", "session_move(-1)", "Previous session"),
        ("down", "session_move(1)", "Next session"),
        ("p", "session_playback", "Play or stop the session"),
        ("d", "session_rediarize", "Re-diarize the session"),
        ("t", "session_retranscribe", "Re-transcribe the session"),
        ("r", "session_rename", "Rename a speaker"),
        ("x", "session_export", "Export the session"),
        Binding("delete", "session_delete", "Delete the session", key_display="del"),
        ("n", "open_files", "Transcribe a file"),
        ("up", "files_move(-1)", "Previous file, option or job"),
        ("down", "files_move(1)", "Next file, option or job"),
        Binding("tab", "files_next_area", "Change Files panel focus", priority=True),
        ("space", "files_toggle", "Select a file or change an option"),
        ("enter", "files_enter", "Queue files or edit an option"),
        ("o", "files_options", "Edit Files options"),
        ("slash", "files_search", "Search audio files"),
        ("x", "files_cancel", "Cancel the selected job"),
        ("escape", "close_files", "Back to the session list"),
    ]

    def __init__(self, services, *, files_home: pathlib.Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.sessions_panel = SessionsPanel(
            getattr(services, "session_store", None), id="sessions-panel"
        )
        self.files_panel = FilesPanel(
            home=files_home,
            start=getattr(services, "files_start_folder", None),
            id="files-panel",
        )
        self.files_panel.display = False
        self.files_open = False
        self.files_submitting = 0
        self.job_status: str | None = None
        self.loaded = False
        self._pending_speaker_id: str | None = None
        self._pending_delete_session: str | None = None

    def compose_body(self) -> ComposeResult:
        yield self.sessions_panel
        yield self.files_panel

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in _SESSION_ACTIONS:
            return not self.files_open
        if action in _FILES_ACTIONS:
            return self.files_open and (action != "files_next_area" or self.app.screen is self)
        return True

    def refresh_body(self) -> None:
        self.sessions_panel.display = not self.files_open
        self.files_panel.display = self.files_open
        self.sessions_panel.set_job_status(self.job_status)
        if self.files_open:
            self.refresh_files()
        self.app.set_context_card("library", self.sessions_panel.storage_summary(), title="storage")

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
            ("↑↓", "session"),
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
        """Return the number of listed entries, or ``None`` before the first load."""
        return len(self.sessions_panel.summaries) if self.loaded else None

    # Sessions

    def load_sessions(self) -> None:
        self.sessions_panel.set_loading(True)
        self.app.refresh_view()
        self.app.run_worker(self.read_sessions(), group="sessions-list", exclusive=True)

    async def read_sessions(self, select: str | None = None) -> None:
        """Read the list; select ``select`` when it is listed, else keep the selection."""
        app = self.app
        panel = self.sessions_panel
        store = panel.store
        if store is None:
            panel.set_summaries(())
        else:
            try:
                summaries = await asyncio.to_thread(store.list_sessions)
                active_session_id = getattr(app.services, "active_session_id", None)
                if active_session_id is not None:
                    summaries = tuple(
                        summary for summary in summaries if summary.session_id != active_session_id
                    )
            except Exception as exc:
                log_failure(log, logging.ERROR, "hub: sessions_list_failed", exc, safe=True)
                panel.set_error("Could not read saved sessions.")
            else:
                panel.set_summaries(summaries)
        self.loaded = True
        if select is not None and not self.select_session(select):
            app.notify(f"Session {select} was not found.", severity="warning")
        app.refresh_view()
        session_id = panel.selected_session_id
        if session_id is not None and app.screen is self:
            self._load_session_detail(session_id)

    def select_session(self, session_id: str) -> bool:
        """Select a listed session; return false when it is not listed."""
        panel = self.sessions_panel
        index = next(
            (i for i, summary in enumerate(panel.summaries) if summary.session_id == session_id),
            None,
        )
        if index is None:
            return False
        if index != panel.selected_index or panel.detail is None:
            panel.move_selection(index - panel.selected_index)
            if self.is_mounted:
                self._load_session_detail(session_id)
        return True

    def show_session(self, session_id: str) -> None:
        """Select a session; reload the list first when it is not in it."""
        self.close_files_view()
        if not self.select_session(session_id):
            self.app.run_worker(
                self.read_sessions(select=session_id), group="sessions-list", exclusive=True
            )
        self.app.refresh_view()

    def _load_session_detail(self, session_id: str) -> None:
        if self.sessions_panel.store is None or not self.app.is_running:
            return
        self.sessions_panel.set_loading(True)
        self.app.run_worker(
            self._read_session_detail(session_id),
            group="session-detail",
            exclusive=True,
        )

    async def _read_session_detail(self, session_id: str) -> None:
        try:
            detail = await asyncio.to_thread(self.sessions_panel.store.read, session_id)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: session_detail_failed", exc, safe=False)
            self.sessions_panel.set_error("Could not read this session.")
        else:
            self.sessions_panel.set_detail(session_id, detail)
        self.app.refresh_view()

    def action_session_move(self, offset: int) -> None:
        session_id = self.sessions_panel.move_selection(offset)
        self.app.refresh_view()
        if session_id is not None:
            self._load_session_detail(session_id)

    def _selected_session_id(self) -> str | None:
        session_id = self.sessions_panel.selected_session_id
        if session_id is None:
            self.app.notify("Select a saved session first.", severity="warning")
        return session_id

    async def action_session_playback(self) -> None:
        session_id = self._selected_session_id()
        toggle = getattr(self.app.services, "toggle_session_playback", None)
        if session_id is None or toggle is None:
            return
        try:
            await asyncio.to_thread(toggle, session_id)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: session_playback_failed", exc, safe=False)
            self.app.notify("Could not play this session.", severity="error")

    def action_session_rediarize(self) -> None:
        session_id = self._selected_session_id()
        operation = getattr(self.app.services, "rediarize_session", None)
        if session_id is not None and operation is not None:
            self._start_session_job("Re-diarizing", operation, session_id)

    def action_session_retranscribe(self) -> None:
        session_id = self._selected_session_id()
        operation = getattr(self.app.services, "retranscribe_session", None)
        if session_id is not None and operation is not None:
            self._start_session_job("Re-transcribing", operation, session_id)

    def action_session_rename(self) -> None:
        session_id = self._selected_session_id()
        labels = self.sessions_panel.speaker_labels
        if session_id is None or not labels:
            self.app.notify("This session has no speaker to rename.", severity="warning")
            return
        speaker_id = next(iter(labels))
        choices = ", ".join(f"{key} ({value})" for key, value in labels.items())
        self.app.push_screen(
            ConfigPrompt(
                f"Rename a speaker in {session_id}. Enter its ID: {choices}",
                initial=speaker_id,
            ),
            self._select_speaker_to_rename,
        )

    def _select_speaker_to_rename(self, speaker_id: str | None) -> None:
        if speaker_id is None:
            return
        label = self.sessions_panel.speaker_labels.get(speaker_id)
        if label is None:
            self.app.notify("That speaker is not in this session.", severity="warning")
            return
        self._pending_speaker_id = speaker_id
        self.app.push_screen(
            ConfigPrompt(f"New name for {label} ({speaker_id})", initial=label),
            self._rename_speaker,
        )

    def _rename_speaker(self, name: str | None) -> None:
        session_id = self.sessions_panel.selected_session_id
        speaker_id = self._pending_speaker_id
        self._pending_speaker_id = None
        store = self.sessions_panel.store
        if (
            name is None
            or not name.strip()
            or session_id is None
            or speaker_id is None
            or store is None
        ):
            return
        self._start_session_job(
            "Saving speaker name", store.rename_speaker, session_id, speaker_id, name
        )

    def action_session_export(self) -> None:
        session_id = self._selected_session_id()
        if session_id is None or self.sessions_panel.store is None:
            return
        self.app.push_screen(
            ConfigPrompt(
                f"Export {session_id}. Enter format and output folder "
                "(for example: md ~/Documents).",
                initial="md ~/Documents",
            ),
            self._export_session,
        )

    def _export_session(self, value: str | None) -> None:
        session_id = self.sessions_panel.selected_session_id
        store = self.sessions_panel.store
        if value is None or session_id is None or store is None:
            return
        try:
            format_name, output_folder = value.split(maxsplit=1)
        except ValueError:
            self.app.notify(
                "Enter md, jsonl, srt, or txt followed by an output folder.", severity="warning"
            )
            return
        if format_name not in {"md", "jsonl", "srt", "txt"}:
            self.app.notify("Export format must be md, jsonl, srt, or txt.", severity="warning")
            return
        self._start_session_job(
            "Exporting",
            store.export,
            session_id,
            pathlib.Path(output_folder).expanduser(),
            format_name,
        )

    def action_session_delete(self) -> None:
        session_id = self._selected_session_id()
        if session_id is None:
            return
        self._pending_delete_session = session_id
        self.app.push_screen(
            QuitConfirm(f"Delete session {session_id}? This action cannot be undone."),
            self._confirm_session_delete,
        )

    async def _confirm_session_delete(self, confirmed: bool | None) -> None:
        session_id = self._pending_delete_session
        self._pending_delete_session = None
        store = self.sessions_panel.store
        if not confirmed or session_id is None or store is None:
            return
        self._start_session_job("Deleting", store.delete, session_id)

    def _start_session_job(self, status: str, operation: Callable[..., object], *args) -> None:
        if self.job_status is not None:
            self.app.notify("A session job is already running.", severity="warning")
            return
        self.job_status = f"{status} session…"
        self.app.refresh_view()
        self.app.run_worker(
            self._run_session_job(status, operation, args),
            group="session-job",
            exclusive=True,
        )

    async def _run_session_job(
        self, status: str, operation: Callable[..., object], args: tuple[object, ...]
    ) -> None:
        app = self.app
        try:
            result = await asyncio.to_thread(operation, *args)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: session_job_failed", exc, safe=False)
            app.notify(f"{status} failed. Check the application log for details.", severity="error")
        else:
            if status == "Exporting":
                app.notify(f"Exported session to {result}.")
            elif status == "Deleting":
                app.notify("Session deleted.")
            else:
                app.notify(f"{status.removesuffix(' session…')} complete.")
            try:
                summaries = await asyncio.to_thread(self.sessions_panel.store.list_sessions)
            except Exception as exc:
                log_failure(log, logging.ERROR, "hub: sessions_list_failed", exc, safe=True)
                self.sessions_panel.set_error("Could not read saved sessions.")
            else:
                self.sessions_panel.set_summaries(summaries)
                session_id = self.sessions_panel.selected_session_id
                if session_id is not None and app.screen is self:
                    self._load_session_detail(session_id)
        finally:
            self.job_status = None
            if app.is_running:
                app.refresh_view()

    # Files sub-view

    def action_open_files(self) -> None:
        self.files_open = True
        log.info(fmt_event("hub", "library_files_opened"))
        self.app.refresh_view()

    def action_close_files(self) -> None:
        self.close_files_view()
        self.app.refresh_view()

    def close_files_view(self) -> None:
        self.files_open = False

    def refresh_files(self) -> None:
        jobs = getattr(self.app.services, "files_jobs", ())
        if callable(jobs):
            jobs = jobs()
        self.files_panel.set_jobs(tuple(jobs))

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
        app.run_worker(self._submit_files(paths, options), group="files-submit")

    async def _submit_files(
        self, paths: tuple[pathlib.Path, ...], options: dict[str, object]
    ) -> None:
        app = self.app
        submit = getattr(app.services, "submit_file", None)
        if submit is None:
            app.notify("File transcription is not available.", severity="error")
            self.files_submitting = max(0, self.files_submitting - len(paths))
            app.refresh_view()
            return
        for path in paths:
            try:
                await asyncio.to_thread(submit, path, **options)
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
