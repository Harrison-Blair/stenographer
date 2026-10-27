# SPDX-License-Identifier: GPL-3.0-or-later
"""Render the saved-session list and selected session detail."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Rule, Static

from stenographer.cli.hub.selection import append_line
from stenographer.lib.sessions.models import SessionDetail, SessionSummary


class SessionsPanel(Vertical):
    """Show storage totals, saved sessions, and the selected transcript."""

    DEFAULT_CSS = """
    SessionsPanel {
        width: 1fr;
        height: 1fr;
    }
    #sessions-layout {
        width: 1fr;
        height: 1fr;
    }
    #sessions-list-column {
        width: 35%;
        min-width: 24;
        height: 1fr;
        margin-right: 1;
    }
    #sessions-list-scroll {
        height: 1fr;
        border: round #3a4150;
    }
    #sessions-list {
        height: auto;
        padding: 0 1;
        text-wrap: nowrap;
        text-overflow: ellipsis;
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
    #sessions-detail-rule {
        width: 1fr;
        height: 1;
        margin: 0 1;
        color: #3a4150;
    }
    #sessions-transcript {
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
            with Vertical(id="sessions-list-column"), VerticalScroll(id="sessions-list-scroll"):
                yield Static("", id="sessions-list", markup=False)
            with VerticalScroll(id="sessions-detail-scroll"):
                with Horizontal(id="sessions-detail-header"):
                    yield Static("", id="sessions-detail-title", markup=False)
                    yield Static("", id="sessions-detail-labels", markup=False)
                yield Static("", id="sessions-detail", markup=False)
                yield Rule(id="sessions-detail-rule")
                yield Static("", id="sessions-transcript", markup=False)

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

    def storage_summary(self) -> str:
        total_bytes = sum(summary.audio_size_bytes for summary in self.summaries)
        count = len(self.summaries)
        text = f"{count} {'entry' if count == 1 else 'entries'}\n"
        text += f"{self._format_size(total_bytes)} audio"
        if self.store is not None:
            text += f"\n\n{self.store.root}"
        return text

    def _refresh_children(self) -> None:
        if not self.is_mounted:
            return
        listing_panel = self.query_one("#sessions-list-scroll", VerticalScroll)
        detail_panel = self.query_one("#sessions-detail-scroll", VerticalScroll)
        listing = self.query_one("#sessions-list", Static)
        detail = self.query_one("#sessions-detail", Static)
        detail_title = self.query_one("#sessions-detail-title", Static)
        detail_labels = self.query_one("#sessions-detail-labels", Static)
        detail_rule = self.query_one("#sessions-detail-rule", Rule)
        transcript = self.query_one("#sessions-transcript", Static)
        listing_panel.border_title = "saved"

        rows = Text()
        for index, summary in enumerate(self.summaries):
            date = summary.started_at.strftime("%Y-%m-%d %H:%M")
            row = f"{date}  {self._duration(summary.duration_seconds)}  {summary.speaker_count} spk"
            if summary.interrupted:
                row += " ! int."
            append_line(rows, row, selectable=True, selected=index == self.selected_index)
        listing.update(rows if rows else "No saved sessions.")

        summary = self.selected_summary
        detail_panel.border_title = ""
        detail_title.update(summary.session_id if summary is not None else "session")
        detail_labels.update("")
        if self.error is not None:
            content = self.error
        elif self.loading:
            content = "Loading session…"
        elif self.detail is None:
            content = (
                "No saved sessions." if summary is None else "Select a session to load its detail."
            )
        else:
            detail_title.update(self.detail.summary.session_id)
            detail_labels.update(self._label_status(self.detail))
            content = self._detail_summary_text(self.detail)
            transcript.update(self._transcript_text(self.detail))
        detail_rule.display = self.detail is not None
        transcript.display = self.detail is not None
        if self.detail is None:
            transcript.update("")
        if self.job_status is not None:
            if isinstance(content, Text):
                content.append(f"\n\n{self.job_status}")
            else:
                content += f"\n\n{self.job_status}"
        detail.update(content)

    @staticmethod
    def _label_status(detail: SessionDetail) -> str:
        state = "re-labelled at stop" if detail.labels_revised else "live"
        return f"labels: {state}"

    @staticmethod
    def _speaker_colors(detail: SessionDetail) -> dict[str, str]:
        palette = ("#ffaf5f", "#c6a8ff", "#6ee69a")
        labels = list(detail.talk_time)
        for line in detail.lines:
            if line.label not in labels:
                labels.append(line.label)
        labels.sort(key=lambda label: (label.casefold() != "you", label.casefold()))
        colors = {}
        speaker_index = 0
        for label in labels:
            if label.casefold() == "you":
                colors[label] = "#5fd7ff"
            else:
                colors[label] = palette[speaker_index % len(palette)]
                speaker_index += 1
        return colors

    def _detail_summary_text(self, detail: SessionDetail) -> Text:
        colors = self._speaker_colors(detail)
        rows = Text()
        talk_labels = [label for label in colors if label in detail.talk_time]
        for index, label in enumerate(talk_labels):
            if index:
                rows.append("  ")
            rows.append(
                f"{label} {self._duration(detail.talk_time[label])}",
                style=f"bold {colors[label]}",
            )
        rows.append("\n")
        for source, label, color in (
            ("mic", "mic", "#5fd7ff"),
            ("system", "sys", "#ffaf5f"),
        ):
            rows.append(f"{label}  ", style="dim")
            rows.append(self._activity_bar(detail.activity.get(source, ())), style=color)
            rows.append("\n")
        return rows

    def _transcript_text(self, detail: SessionDetail) -> Text:
        colors = self._speaker_colors(detail)
        rows = Text()
        for index, line in enumerate(detail.lines):
            if index:
                rows.append("\n")
            rows.append(f"{self._clock(line.start)}  ", style="dim")
            rows.append(line.label, style=f"bold {colors[line.label]}")
            rows.append(f"  {line.text.replace(chr(10), ' ')}")
        return rows

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
