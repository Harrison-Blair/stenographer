# SPDX-License-Identifier: GPL-3.0-or-later
"""Textual interface for a live audio session."""

from __future__ import annotations

import asyncio
import math
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from stenographer.cli.live.rename_dialog import RenameDialog
from stenographer.cli.shared.no_background_css import NO_BACKGROUND_CSS
from stenographer.lib.live.live_session import LiveSession
from stenographer.lib.live.transcript_line import TranscriptLine


class LiveApp(App[None]):
    """Display session status, transcript lines, and live controls."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("space", "toggle_pause", "Pause / resume"),
        ("m", "toggle_mic", "Microphone"),
        ("s", "toggle_system", "System audio"),
        ("r", "rename", "Rename speaker"),
        ("q", "stop", "Stop and save"),
        ("ctrl+c", "stop", "Stop and save"),
    ]
    CSS = (
        NO_BACKGROUND_CSS
        + """
    #status {
        height: auto;
        min-height: 2;
        padding: 0 1;
    }
    #transcript-scroll {
        height: 1fr;
        padding: 1 2;
    }
    #transcript {
        width: 1fr;
    }
    #key-hints {
        height: 1;
        padding: 0 1;
    }
    """
    )

    def __init__(self, session: LiveSession) -> None:
        super().__init__(ansi_color=True)
        self._session = session
        self._session.subscribe(self._receive_line)
        self._stop_requested = False

    def compose(self) -> ComposeResult:
        yield Static("", id="status", markup=False)
        with VerticalScroll(id="transcript-scroll"):
            yield Static("", id="transcript", markup=False)
        yield Static(
            "space pause/resume   m mic   s system   r rename   q stop/save · q again skip relabel",
            id="key-hints",
        )

    def on_mount(self) -> None:
        self._session.start()
        self.set_interval(0.1, self._refresh_status)
        self._refresh_status()
        self._refresh_transcript()

    def action_toggle_pause(self) -> None:
        if self._session.paused:
            self._session.resume()
        else:
            self._session.pause()
        self._refresh_status()

    def action_toggle_mic(self) -> None:
        self._session.toggle("mic")
        self._refresh_status()

    def action_toggle_system(self) -> None:
        self._session.toggle("system")
        self._refresh_status()

    def action_rename(self) -> None:
        speakers = self._session.speakers
        if not speakers:
            self.notify("No speakers are available to rename.")
            return
        self.push_screen(RenameDialog(speakers), self._rename_speaker)

    def action_stop(self) -> None:
        if self._stop_requested:
            self._session.skip_relabel()
            self.notify("Skipping speaker relabeling.")
            return
        self._stop_requested = True
        self._refresh_status()
        self.run_worker(self._finish_stop(), name="stop-live", group="live-stop")

    async def _finish_stop(self) -> None:
        await asyncio.to_thread(self._session.stop)
        if self._session.relabel_error:
            self.notify(f"Speaker relabeling failed: {self._session.relabel_error}")
        self.exit()

    def _rename_speaker(self, value: tuple[str, str] | None) -> None:
        if value is None:
            return
        speaker_id, name = value
        try:
            self._session.rename(speaker_id, name)
        except ValueError as exc:
            self.notify(str(exc))
            return
        self._refresh_transcript()

    def _receive_line(self, _line: TranscriptLine) -> None:
        self.call_from_thread(self._refresh_transcript)

    def _refresh_transcript(self) -> None:
        rendered = "\n".join(
            f"{self._format_time(line.start)}  {line.label}  {line.text}"
            for line in self._session.lines
        )
        self.query_one("#transcript", Static).update(rendered)

    def _refresh_status(self) -> None:
        elapsed = max(0, int(self._session.elapsed_seconds))
        state = "Saving..." if self._stop_requested else "PAUSED" if self._session.paused else "REC"
        parts = [f"{state} {self._format_time(elapsed)}"]
        for key, source in (("m", "mic"), ("s", "system")):
            source_state = self._session.source_states[source].upper()
            level = self._session.levels_dbfs[source]
            meter = self._format_meter(level, self._session.meter_floor_dbfs)
            level_text = "-inf" if not math.isfinite(level) else f"{level:.0f}"
            reason = self._session.source_reasons[source]
            detail = f"{key} {source_state} [{meter} {level_text} dBFS]"
            if reason:
                detail += f" ({reason})"
            parts.append(detail)
        parts.append(
            f"{self._session.model_name}  queue {self._session.queue_depth}  "
            f"failed phrases {self._session.failed_phrase_count}"
        )
        if self._session.relabel_status:
            parts.append(self._session.relabel_status)
        self.query_one("#status", Static).update("  |  ".join(parts))

    @staticmethod
    def _format_time(seconds: float | int) -> str:
        whole_seconds = max(0, int(seconds))
        hours, remainder = divmod(whole_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    @staticmethod
    def _format_meter(level_dbfs: float, floor_dbfs: float = -70.0) -> str:
        filled = (
            0
            if not math.isfinite(level_dbfs)
            else min(5, max(0, int((level_dbfs - floor_dbfs) / (-10.0 - floor_dbfs) * 5)))
        )
        return "█" * filled + "·" * (5 - filled)
