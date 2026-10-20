# SPDX-License-Identifier: GPL-3.0-or-later
"""Render the saved-session list and selected session detail."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static

from stenographer.lib.sessions.models import SessionDetail, SessionSummary


class SessionsPanel(Vertical):
    """Show storage totals, saved sessions, and the selected transcript."""

    CSS = """
    SessionsPanel {
        width: 1fr;
        height: 1fr;
    }
    #sessions-layout {
        width: 1fr;
        height: 1fr;
        gap: 1;
    }
    #sessions-list-column {
        width: 35%;
        min-width: 24;
        height: 1fr;
    }
    #sessions-storage {
        height: 5;
        border: round #3a4150;
        padding: 0 1;
    }
    #sessions-list-scroll {
        height: 1fr;
        border: round #3a4150;
    }
    #sessions-list {
        height: auto;
        padding: 0 1;
    }
    #sessions-detail-scroll {
        width: 1fr;
        height: 1fr;
        border: round #3a4150;
    }
    #sessions-detail {
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(self, store=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.store = store
        self.summaries: tuple[SessionSummary, ...] = ()
        self.selected_index = 0
        self.detail: SessionDetail | None = None
        self.error: str | None = None
        self.loading = False
        self.job_status: str | None = None

    def render(self) -> Text:
        return Text("")

    def compose(self) -> ComposeResult:
        with Horizontal(id="sessions-layout"):
            with Vertical(id="sessions-list-column"):
                yield Static("", id="sessions-storage", markup=False)
                with VerticalScroll(id="sessions-list-scroll"):
                    yield Static("", id="sessions-list", markup=False)
            with VerticalScroll(id="sessions-detail-scroll"):
                yield Static("", id="sessions-detail", markup=False)

    def on_mount(self) -> None:
        self._refresh_children()

    @property
    def selected_session_id(self) -> str | None:
        if not self.summaries:
            return None
        return self.summaries[self.selected_index].session_id

    @property
    def selected_summary(self) -> SessionSummary | None:
        if not self.summaries:
            return None
        return self.summaries[self.selected_index]

    @property
    def speaker_labels(self) -> dict[str, str]:
        if self.detail is None:
            return {}
        return {
            line.speaker_id: line.label for line in self.detail.lines if line.speaker_id != "you"
        }

    def set_loading(self, loading: bool) -> None:
        self.loading = loading
        self.error = None
        self._refresh_children()

    def set_summaries(self, summaries: tuple[SessionSummary, ...]) -> None:
        selected_id = self.selected_session_id
        self.summaries = summaries
        self.selected_index = next(
            (index for index, summary in enumerate(summaries) if summary.session_id == selected_id),
            0,
        )
        self.detail = None
        self.error = None
        self.loading = False
        self._refresh_children()

    def set_detail(self, session_id: str, detail: SessionDetail) -> None:
        if session_id != self.selected_session_id:
            return
        self.detail = detail
        self.loading = False
        self.error = None
        self._refresh_children()

    def set_error(self, message: str) -> None:
        self.loading = False
        self.error = message
        self._refresh_children()

    def move_selection(self, offset: int) -> str | None:
        if not self.summaries:
            return None
        self.selected_index = (self.selected_index + offset) % len(self.summaries)
        self.detail = None
        self.error = None
        self.loading = True
        self._refresh_children()
        return self.selected_session_id

    def set_job_status(self, status: str | None) -> None:
        self.job_status = status
        self._refresh_children()

    def _refresh_children(self) -> None:
        if not self.is_mounted:
            return
        storage = self.query_one("#sessions-storage", Static)
        listing = self.query_one("#sessions-list", Static)
        detail = self.query_one("#sessions-detail", Static)
        storage.border_title = "storage"
        listing.border_title = "saved"
        total_bytes = sum(summary.audio_size_bytes for summary in self.summaries)
        storage.update(f"{len(self.summaries)} sessions\n{self._format_size(total_bytes)} audio")

        rows = []
        for index, summary in enumerate(self.summaries):
            marker = "▸" if index == self.selected_index else " "
            date = summary.started_at.strftime("%Y-%m-%d %H:%M")
            row = (
                f"{marker} {date}  {self._duration(summary.duration_seconds)}  "
                f"{summary.speaker_count} spk"
            )
            if summary.interrupted:
                row += "  ! interrupted"
            rows.append(row)
        listing.update("\n".join(rows) if rows else "No saved sessions.")

        summary = self.selected_summary
        detail.border_title = summary.session_id if summary is not None else "session"
        if self.error is not None:
            content = self.error
        elif self.loading:
            content = "Loading session…"
        elif self.detail is None:
            content = (
                "No saved sessions." if summary is None else "Select a session to load its detail."
            )
        else:
            content = self._detail_text(self.detail)
        if self.job_status is not None:
            content += f"\n\n{self.job_status}"
        detail.update(content)

    def _detail_text(self, detail: SessionDetail) -> str:
        label_state = "re-labelled" if detail.labels_revised else "live"
        rows = [f"labels: {label_state}"]
        rows.extend(
            f"{label} {self._duration(seconds)}"
            for label, seconds in sorted(detail.talk_time.items())
        )
        for source in ("mic", "system"):
            label = source if source == "mic" else "sys"
            activity = self._activity_bar(detail.activity.get(source, ()))
            rows.append(f"{label}  {activity}")
        rows.append("─" * 40)
        rows.extend(
            f"{self._clock(line.start)}  {line.label}: {line.text.replace(chr(10), ' ')}"
            for line in detail.lines
        )
        return "\n".join(rows)

    @staticmethod
    def _duration(seconds: float) -> str:
        total = max(0, int(seconds))
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    @staticmethod
    def _clock(seconds: float) -> str:
        total = max(0, int(seconds))
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    @staticmethod
    def _format_size(size: int) -> str:
        amount = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if amount < 1024 or unit == "GB":
                return f"{amount:.1f} {unit}"
            amount /= 1024
        return f"{amount:.1f} GB"

    @staticmethod
    def _activity_bar(activity: tuple[float, ...]) -> str:
        if not activity:
            return "no audio"
        glyphs = "▁▂▃▄▅▆▇█"
        peak = max(activity)
        if peak <= 0:
            return glyphs[0] * len(activity)
        count = min(28, len(activity))
        bars = []
        for index in range(count):
            start = index * len(activity) // count
            end = (index + 1) * len(activity) // count
            level = max(activity[start:end])
            glyph_index = min(len(glyphs) - 1, int(level / peak * (len(glyphs) - 1)))
            bars.append(glyphs[glyph_index])
        return "".join(bars)
