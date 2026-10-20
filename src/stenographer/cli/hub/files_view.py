# SPDX-License-Identifier: GPL-3.0-or-later
"""Render the file browser, transcription options, queue, and preview."""

from __future__ import annotations

from pathlib import Path

import soundfile
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static

from stenographer.cli.hub.files_entry import BrowserEntry
from stenographer.cli.hub.selection import append_line

_FORMATS = ("md", "jsonl", "srt", "txt")
_AUDIO_SUFFIXES = {
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
_OPTION_NAMES = ("diarize", "speaker count", "refine", "output format", "output folder")


class FilesPanel(Vertical):
    """Hold Files-section navigation state and render its panels."""

    DEFAULT_CSS = """
    FilesPanel {
        width: 1fr;
        height: 1fr;
    }
    #files-main {
        width: 1fr;
        height: 3fr;
        min-height: 8;
    }
    #files-browser-scroll {
        width: 1fr;
        height: 1fr;
        border: round #3a4150;
        margin-right: 1;
    }
    #files-browser {
        height: auto;
        padding: 0 1;
    }
    #files-right {
        width: 1fr;
        height: 1fr;
    }
    #files-options-scroll, #files-queue-scroll {
        height: 1fr;
        border: round #3a4150;
    }
    #files-options-scroll {
        margin-bottom: 1;
    }
    #files-options, #files-queue {
        height: auto;
        padding: 0 1;
    }
    #files-preview-scroll {
        width: 1fr;
        height: 2fr;
        min-height: 6;
        border: round #3a4150;
    }
    #files-preview {
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        *,
        home: Path | None = None,
        output_folder: Path | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.home = Path(home or Path.home()).expanduser()
        if not self.home.is_dir():
            self.home = Path.home()
        self.directory = self.home
        self.output_folder = Path(output_folder or self.home / ".local/share/stenographer/files")
        self.diarize = True
        self.speaker_count: int | None = None
        self.refine = False
        self.output_format = "md"
        self.search_term = ""
        self.entries: tuple[BrowserEntry, ...] = ()
        self.selected_entry_index = 0
        self.selected_paths: dict[Path, None] = {}
        self.focus_area = "browser"
        self.options_open = False
        self.selected_option_index = 0
        self.jobs: tuple[object, ...] = ()
        self.selected_job_index = 0
        self._browser_text = ""
        self._options_text = ""
        self._queue_text = ""
        self._preview_text = Text()
        self._refresh_entries()
        self._build_text()

    def compose(self) -> ComposeResult:
        with Horizontal(id="files-main"):
            with VerticalScroll(id="files-browser-scroll", can_focus=False):
                yield Static("", id="files-browser", markup=False)
            with Vertical(id="files-right"):
                with VerticalScroll(id="files-options-scroll", can_focus=False):
                    yield Static("", id="files-options", markup=False)
                with VerticalScroll(id="files-queue-scroll", can_focus=False):
                    yield Static("", id="files-queue", markup=False)
        with VerticalScroll(id="files-preview-scroll", can_focus=False):
            yield Static("", id="files-preview", markup=False)

    def on_mount(self) -> None:
        self.query_one("#files-options-scroll", VerticalScroll).border_title = "options"
        self.query_one("#files-queue-scroll", VerticalScroll).border_title = "queue"
        self.query_one("#files-preview-scroll", VerticalScroll).border_title = "preview"
        self._update_text()

    @property
    def selected_entry(self) -> BrowserEntry | None:
        if not self.entries:
            return None
        return self.entries[self.selected_entry_index]

    @property
    def selected_job(self):
        if not self.jobs:
            return None
        return self.jobs[self.selected_job_index]

    @property
    def selected_option(self) -> str:
        return _OPTION_NAMES[self.selected_option_index]

    def _refresh_entries(self) -> None:
        try:
            children = tuple(self.directory.iterdir())
        except OSError:
            children = ()
        entries = []
        if self.directory != self.directory.parent:
            entries.append(BrowserEntry(self.directory.parent, True, None))
        for path in children:
            try:
                is_dir = path.is_dir()
            except OSError:
                continue
            if not is_dir and path.suffix.lower() not in _AUDIO_SUFFIXES:
                continue
            if self.search_term and self.search_term.casefold() not in path.name.casefold():
                continue
            entries.append(BrowserEntry(path, is_dir, None if is_dir else self._duration(path)))
        start = 1 if self.directory != self.directory.parent else 0
        entries[start:] = sorted(
            entries[start:], key=lambda entry: (not entry.is_dir, entry.path.name.casefold())
        )
        self.entries = tuple(entries)
        self.selected_entry_index = min(self.selected_entry_index, max(0, len(self.entries) - 1))
        if len(self.entries) > 1 and self.entries[0].path == self.directory.parent:
            self.selected_entry_index = max(1, self.selected_entry_index)

    @staticmethod
    def _duration(path: Path) -> float | None:
        try:
            info = soundfile.info(str(path))
        except (OSError, RuntimeError, ValueError):
            return None
        if info.samplerate <= 0 or info.frames < 0:
            return None
        return info.frames / info.samplerate

    def set_search(self, term: str) -> None:
        self.search_term = term.strip()
        self.selected_entry_index = 0
        self._refresh_entries()
        self._update_text()

    def refresh_display(self) -> None:
        self._update_text()

    def move_selection(self, offset: int) -> None:
        if self.focus_area == "browser":
            if self.entries:
                self.selected_entry_index = (self.selected_entry_index + offset) % len(self.entries)
        elif self.focus_area == "queue":
            if self.jobs:
                self.selected_job_index = (self.selected_job_index + offset) % len(self.jobs)
        else:
            self.selected_option_index = (self.selected_option_index + offset) % len(_OPTION_NAMES)
        self._update_text()

    def cycle_focus(self) -> None:
        areas = ("browser", "queue", "options")
        self.focus_area = areas[(areas.index(self.focus_area) + 1) % len(areas)]
        self.options_open = self.focus_area == "options"
        self._update_text()

    def toggle_options(self) -> None:
        self.options_open = not self.options_open
        self.focus_area = "options" if self.options_open else "browser"
        self._update_text()

    def toggle_selected_file(self) -> None:
        entry = self.selected_entry
        if entry is None or entry.is_dir:
            return
        if entry.path in self.selected_paths:
            del self.selected_paths[entry.path]
        else:
            self.selected_paths[entry.path] = None
        self._update_text()

    def enter(self) -> tuple[Path, ...]:
        if self.focus_area != "browser":
            return ()
        if self.selected_paths:
            paths = tuple(self.selected_paths)
            self.selected_paths.clear()
            self._update_text()
            return paths
        entry = self.selected_entry
        if entry is None:
            return ()
        if entry.is_dir:
            self.directory = entry.path
            self.search_term = ""
            self.selected_entry_index = 0
            self._refresh_entries()
            self._update_text()
            return ()
        self._update_text()
        return (entry.path,)

    def set_jobs(self, jobs: tuple[object, ...]) -> None:
        selected_id = getattr(self.selected_job, "id", None)
        new_job_added = len(jobs) > len(self.jobs)
        self.jobs = jobs
        if jobs and new_job_added:
            self.selected_job_index = len(jobs) - 1
        elif jobs:
            self.selected_job_index = next(
                (
                    index
                    for index, job in enumerate(jobs)
                    if getattr(job, "id", None) == selected_id
                ),
                len(jobs) - 1,
            )
        else:
            self.selected_job_index = 0
        self._update_text()

    def display_text(self) -> str:
        """Return all panel content for tests and accessible text views."""
        return "\n".join(
            (
                self._browser_text.plain,
                self._options_text.plain,
                self._queue_text.plain,
                self._preview_text.plain,
            )
        )

    def _update_text(self) -> None:
        self._build_text()
        if not self.is_mounted or not self.app.is_running:
            return
        browser_panel = self.query_one("#files-browser-scroll", VerticalScroll)
        try:
            relative_directory = self.directory.relative_to(self.home)
        except ValueError:
            browser_panel.border_title = str(self.directory)
        else:
            browser_panel.border_title = (
                "~" if relative_directory == Path(".") else f"~/{relative_directory}"
            )
        preview_panel = self.query_one("#files-preview-scroll", VerticalScroll)
        job = self.selected_job
        if job is None:
            result_name = ""
        else:
            output_path = getattr(job, "output_path", None)
            path = getattr(getattr(job, "options", None), "path", Path("file"))
            result_name = Path(output_path).stem if output_path is not None else path.stem
        preview_panel.border_title = "preview" if not result_name else f"preview · {result_name}"
        self.query_one("#files-browser", Static).update(self._browser_text)
        self.query_one("#files-options", Static).update(self._options_text)
        self.query_one("#files-queue", Static).update(self._queue_text)
        self.query_one("#files-preview", Static).update(self._preview_text)

    def _build_text(self) -> None:
        self._browser_text = self._render_browser()
        self._options_text = self._render_options()
        self._queue_text = self._render_queue()
        self._preview_text = self._render_preview()

    def _render_browser(self) -> Text:
        rows = Text()
        if self.search_term:
            append_line(rows, f"search: {self.search_term}")
        if self.selected_paths:
            append_line(rows, f"selected: {len(self.selected_paths)} file(s)")
        if not any(entry.path != self.directory.parent for entry in self.entries):
            append_line(rows, "No matching audio files or folders.")
        for index, entry in enumerate(self.entries):
            selected = "[x]" if entry.path in self.selected_paths else "[ ]"
            name = ".." if entry.path == self.directory.parent and entry.is_dir else entry.path.name
            if entry.is_dir:
                value = f"     {name}/"
            else:
                duration = (
                    ""
                    if entry.duration_seconds is None
                    else self._format_clock(entry.duration_seconds)
                )
                value = f"{selected} {name:<28} {duration}"
            append_line(
                rows,
                value,
                selectable=True,
                selected=self.focus_area == "browser" and index == self.selected_entry_index,
            )
        append_line(rows, "")
        append_line(rows, "/ search · enter queue/open · space select")
        return rows

    def _render_options(self) -> Text:
        rows = Text()
        speaker_count = self.speaker_count if self.speaker_count is not None else "auto"
        diarize_marker = "x" if self.diarize else " "
        refine_marker = "x" if self.refine else " "
        diarize_choice = f"[{diarize_marker}] diarize"
        refine_choice = f"[{refine_marker}] cleanup pass"
        option_rows = (
            f"speakers      {diarize_choice}   count {speaker_count}",
            f"refine        {refine_choice}",
            f"output        {' · '.join(_FORMATS)}",
            f"save to       {self.output_folder}",
        )
        for row_index, option in enumerate(option_rows):
            if row_index == 0:
                selected = self.selected_option_index in {0, 1}
            else:
                selected = self.selected_option_index == row_index + 1
            selected = self.focus_area == "options" and selected
            line_start = len(rows.plain) + (1 if rows else 0) + 2
            append_line(rows, option, selectable=True, selected=selected)
            if row_index == 0:
                choice_start = line_start + len("speakers      ")
                rows.stylize("#5fd7ff", choice_start, choice_start + len(diarize_choice))
                count_start = line_start + option.index(str(speaker_count))
                rows.stylize("#5fd7ff", count_start, count_start + len(str(speaker_count)))
            elif row_index == 1:
                choice_start = line_start + len("refine        ")
                rows.stylize("#5fd7ff", choice_start, choice_start + len(refine_choice))
            elif row_index == 2:
                format_start = line_start + len("output        ")
                active_start = format_start + sum(
                    len(value) + 3 for value in _FORMATS[: _FORMATS.index(self.output_format)]
                )
                rows.stylize(
                    "bold #5fd7ff",
                    active_start,
                    active_start + len(self.output_format),
                )
        if self.options_open:
            append_line(rows, "enter/space edit · o close")
        else:
            append_line(rows, "o edit options")
        return rows

    def _render_queue(self) -> Text:
        rows = Text()
        if not self.jobs:
            append_line(rows, "No queued jobs.")
        for index, job in enumerate(self.jobs):
            options = getattr(job, "options", None)
            path = getattr(options, "path", Path("file"))
            progress = getattr(job, "progress", None)
            stage = getattr(progress, "stage", "transcribe")
            percent = min(100, max(0, int(getattr(progress, "percent", 0))))
            eta = getattr(progress, "eta_seconds", None)
            eta_text = "—" if eta is None else self._format_clock(eta)
            state = getattr(job, "state", "queued")
            append_line(
                rows,
                path.name,
                selectable=True,
                selected=self.focus_area == "queue" and index == self.selected_job_index,
            )
            if rows:
                rows.append("\n")
            rows.append(self._progress_bar(percent), style="bold #5fd7ff")
            rows.append(f" {percent}%  eta {eta_text}")
            diarize = getattr(options, "diarize", True)
            append_line(rows, self._render_stages(stage, state, diarize))
            error = getattr(job, "error", None)
            if error:
                append_line(rows, f"  {error}")
        return rows

    @staticmethod
    def _progress_bar(percent: int) -> str:
        width = 12
        filled = round(width * percent / 100)
        return f"▕{'█' * filled}{'·' * (width - filled)}▏"

    @staticmethod
    def _render_stages(stage: str, state: str, diarize: bool) -> str:
        stages = ("transcribe", "diarize", "save")
        try:
            current_index = stages.index(stage)
        except ValueError:
            current_index = 0
        rendered = []
        for index, name in enumerate(stages):
            if name == "diarize" and not diarize:
                marker = "—"
            elif state == "completed" or (state == "running" and index < current_index):
                marker = "✓"
            elif state == "running" and index == current_index:
                marker = "…"
            else:
                marker = ""
            rendered.append(f"{name} {marker}".rstrip())
        return " · ".join(rendered)

    def _render_preview(self) -> Text:
        rows = Text()
        job = self.selected_job
        if job is None:
            rows.append("Queue a file to preview its transcript.")
            return rows
        progress = getattr(job, "progress", None)
        lines = getattr(progress, "completed_lines", ())
        if not lines:
            rows.append("Transcript preview will appear here.")
        for line in lines[-8:]:
            if rows:
                rows.append("\n")
            rows.append(f"{self._format_timestamp(line.start)}  ")
            rows.append(f"{line.label}\u00a0", style="bold #5fd7ff")
            rows.append(f" {line.text.replace(chr(10), ' ')}")
        output_path = getattr(job, "output_path", None)
        if output_path is not None:
            if rows:
                rows.append("\n")
            rows.append(f"saved: {Path(output_path).name}")
        return rows

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        total = max(0, int(seconds))
        hours, remainder = divmod(total, 3600)
        minutes, second = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{second:02d}"

    @staticmethod
    def _format_clock(seconds: float) -> str:
        total = max(0, int(seconds))
        if total >= 3600:
            hours, remainder = divmod(total, 3600)
            minutes, seconds = divmod(remainder, 60)
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        minutes, remainder = divmod(total, 60)
        return f"{minutes}:{remainder:02d}"
