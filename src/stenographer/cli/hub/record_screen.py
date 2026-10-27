# SPDX-License-Identifier: GPL-3.0-or-later
"""The Record screen: REC panel, spectrum meters, transcript and speakers card."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, ClassVar

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from stenographer.cli.hub.device_dialog import DeviceDialog
from stenographer.cli.hub.hub_screen import HubScreen
from stenographer.cli.hub.rename_dialog import RenameDialog
from stenographer.cli.hub.widgets.button import HubButton
from stenographer.cli.hub.widgets.clock import Clock
from stenographer.cli.hub.widgets.frame import Frame
from stenographer.cli.hub.widgets.key_hints import KeyHints
from stenographer.cli.hub.widgets.spectrum_meter import SpectrumMeter
from stenographer.cli.hub.widgets.status_token import StatusToken
from stenographer.cli.hub.widgets.transcript_line import TranscriptLine
from stenographer.cli.shared.speaker_colors import speaker_color
from stenographer.cli.shared.transcript_scroll import TranscriptScroll
from stenographer.lib.logging.pipeline import fmt_event, log_failure
from stenographer.lib.sessions.reader import session_started_at

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy as np
    from textual import events
    from textual.app import ComposeResult

log = logging.getLogger(__name__)

_IDLE_TEXT = {"mic": "not recording", "system": "captures the default output mix"}
_SYSTEM_DEVICE = "default output"
_STATE_TOKENS = {
    "idle": ("○", "READY", "dim"),
    "recording": ("●", "REC", "danger"),
    "paused": ("Ⅱ", "PAUSED", "warn"),
    "saved": ("■", "SAVED", "ok"),
}
_RECORD_HINTS = (("m", "mic"), ("s", "system"), ("v", "view"))


class RecordScreen(HubScreen):
    """Record, pause, stop and save; watch the meters and the transcript; rename speakers."""

    SCREEN_NAME = "record"
    SCREEN_TITLE = "Record"
    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        Binding("space", "record_toggle", "Record, pause or resume"),
        Binding("enter", "stop", "Stop and save"),
        ("o", "open_library", "Open the saved session in Library"),
        ("d", "choose_device", "Input device for the next recording"),
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
    RecordScreen #record-body { height: 1fr; }
    RecordScreen #record-top { height: 14; }
    RecordScreen #rec-panel {
        width: 1fr;
        min-width: 28;
        height: 13;
        margin-right: 1;
    }
    RecordScreen #rec-info { height: 1fr; color: #8b93a1; }
    RecordScreen #rec-panel HubButton { margin-top: 0; }
    RecordScreen #mic-column { width: 43; margin-right: 1; }
    RecordScreen #system-column { width: 43; }
    RecordScreen #device-button { margin-left: 1; }
    RecordScreen #transcript-frame { height: 1fr; }
    RecordScreen #transcript-head { height: 1; }
    RecordScreen #transcript-title { width: 1fr; text-style: bold; }
    RecordScreen #transcript { height: 1fr; }
    RecordScreen #transcript-hints { height: 1; }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.split = False
        self.meters = {
            "mic": SpectrumMeter("mic", "Default input", id="mic-meter"),
            "system": SpectrumMeter("system", _SYSTEM_DEVICE, id="system-meter"),
        }
        self._state_shown: str | None = None
        self._metered = None
        self._remove_listener: Callable[[], None] | None = None
        self._meter_states: dict[str, tuple[str, str]] = {}
        self._session_devices: dict[str, str] = {}
        self._saved_at: dict[str, datetime] = {}
        self._saved_lines: tuple[str, tuple] | None = None
        self._transcript_key: object = None

    def compose_body(self) -> ComposeResult:
        yield Static("", id="section-content", markup=False)
        with Vertical(id="record-body"):
            with Horizontal(id="record-top"):
                with Frame(id="rec-panel", variant="record"):
                    yield Static("", id="rec-state", markup=False)
                    yield Clock(id="rec-clock")
                    yield Static("", id="rec-info", markup=False)
                    yield HubButton(
                        "● Record",
                        key="space",
                        action="record_toggle",
                        tone="record",
                        id="rec-primary",
                    )
                    yield HubButton("", key="space", action="record_toggle", id="rec-secondary")
                with Vertical(id="mic-column"):
                    yield self.meters["mic"]
                    yield HubButton(
                        "change device…", key="d", action="choose_device", id="device-button"
                    )
                with Vertical(id="system-column"):
                    yield self.meters["system"]
            with Frame(id="transcript-frame", variant="fill"):
                with Horizontal(id="transcript-head"):
                    yield Static("", id="transcript-title", markup=False)
                    yield HubButton("", key="v", action="toggle_view", id="view-button")
                yield TranscriptScroll(id="transcript", can_focus=False)
                yield KeyHints(footer=False, id="transcript-hints")

    # State

    @property
    def session(self):
        services = self.app.services
        return getattr(services, "session", None) if services.recording else None

    @property
    def saved_session(self):
        return getattr(self.app.services, "last_saved", None)

    def record_state(self) -> str:
        services = self.app.services
        if services.recording:
            session = getattr(services, "session", None)
            return "paused" if session is not None and session.paused else "recording"
        return "saved" if self.saved_session is not None else "idle"

    def _stopping(self, session) -> bool:
        return any(item is session for item in getattr(self.app.services, "stopping_sessions", ()))

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        state = self.record_state()
        if action == "stop":
            return state in {"recording", "paused"}
        if action == "choose_device":
            return state in {"idle", "saved"}
        if action == "open_library":
            return state == "saved"
        return True

    # Drawing

    def refresh_body(self) -> None:
        app = self.app
        state = self.record_state()
        if state != self._state_shown:
            self._state_shown = state
            self.refresh_bindings()
        activity = self.query_one("#section-content", Static)
        activity.update(app.activity_status or "")
        activity.display = app.activity_status is not None
        self.query_one("#record-body").display = app.activity_status is None

        live = self.session
        self._attach_meters(live)
        shown = live if live is not None else self.saved_session if state == "saved" else None
        lines = self._lines(shown)
        speakers = self._speaker_rows(shown, lines)
        self._draw_rec_panel(state, shown)
        self._draw_meters(state, live)
        self._draw_transcript(state, shown, lines, speakers)
        app.set_context_card("record", self._speakers_card(shown, speakers), title="speakers")

    def footer_hints(self) -> tuple[tuple[str, str], ...]:
        state = self.record_state()
        if state in {"recording", "paused"}:
            space = "resume" if state == "paused" else "pause"
            items = (("enter", "stop & save"), ("space", space), *_RECORD_HINTS, ("r", "rename"))
        elif state == "saved":
            items = (
                ("space", "record again"),
                ("o", "open in Library"),
                ("d", "device"),
                *_RECORD_HINTS,
                ("r", "rename"),
            )
        else:
            items = (("space", "record"), ("d", "device"), *_RECORD_HINTS)
        return (*items, ("1 2 3", "screens"))

    def _draw_rec_panel(self, state: str, session) -> None:
        self.query_one("#rec-state", Static).update(StatusToken.text(*_STATE_TOKENS[state]))
        clock = self.query_one("#rec-clock", Clock)
        clock.set_seconds(session.elapsed_seconds if session is not None else 0)
        clock.set_tone("saved" if state == "saved" else "record")
        if state == "idle":
            info = f"mic · {self.mic_device()}"
        elif state == "saved":
            session_id = session.path.name
            saved_at = self._saved_at.get(session_id)
            info = f"saved {saved_at:%H:%M}\n{session_id}" if saved_at else session_id
        else:
            started = session_started_at(session.path.name) if session is not None else None
            info = f"started {started.astimezone():%H:%M}" if started else "started"
        self.query_one("#rec-info", Static).update(info)

        primary = self.query_one("#rec-primary", HubButton)
        secondary = self.query_one("#rec-secondary", HubButton)
        if state in {"recording", "paused"}:
            self._set_button(primary, "enter", "■ Stop & save", "stop")
            resume = state == "paused"
            self._set_button(
                secondary, "space", "▶ Resume" if resume else "Ⅱ Pause", "record_toggle"
            )
        elif state == "saved":
            self._set_button(primary, "space", "● Record again", "record_toggle")
            self._set_button(secondary, "o", "Open in Library", "open_library")
        else:
            self._set_button(primary, "space", "● Record", "record_toggle")
        secondary.display = state != "idle"
        self.query_one("#device-button").visible = state in {"idle", "saved"}

    @staticmethod
    def _set_button(button: HubButton, key: str, label: str, action: str) -> None:
        if (button.key, button.action_name, str(button.label)) == (
            key,
            action,
            str(HubButton.label_text(label, key)),
        ):
            return
        button.key = key
        button.action_name = action
        button.set_label(label)

    def _draw_meters(self, state: str, session) -> None:
        services = self.app.services
        sources = getattr(services, "next_sources", {"mic": True, "system": True})
        speech = getattr(session, "speech_detected", {}) if session is not None else {}
        for source, meter in self.meters.items():
            if session is not None:
                current = session.source_states.get(source, "off")
                wanted = {"on": ("on", ""), "paused": ("idle", "paused")}.get(current, ("off", ""))
            else:
                wanted = ("idle", _IDLE_TEXT[source]) if sources.get(source) else ("off", "")
            if self._meter_states.get(source) != wanted:
                self._meter_states[source] = wanted
                meter.set_state(wanted[0], idle_text=wanted[1])
            heard = bool(speech.get(source, False))
            if meter.model.speech != heard:
                meter.set_speech(heard)
        device = self._session_devices.get(session.path.name) if session is not None else None
        device = device or self.mic_device()
        if self.meters["mic"].model.device != device:
            self.meters["mic"].set_device(device)

    def _draw_transcript(self, state: str, session, lines: tuple, speakers: tuple) -> None:
        count = len(speakers)
        title = f"transcript · {count} {'speaker' if count == 1 else 'speakers'}"
        relabeling = state == "saved" and self._stopping(session)
        if relabeling:
            title += " · relabeling…"
        self.query_one("#transcript-title", Static).update(title)
        view = "▶ mixed  split" if not self.split else "mixed  ▶ split"
        self._set_button(self.query_one("#view-button", HubButton), "v", view, "toggle_view")
        follow = ("End", "follow") if state in {"recording", "paused"} else ("Home/End", "top/end")
        self.query_one("#transcript-hints", KeyHints).set_hints(
            ("↑↓", "line"), ("PgUp/Dn", "page"), follow
        )

        marker = self._marker(session, lines) if state == "saved" else None
        if state == "idle":
            message = "Press space to start recording."
        elif state in {"recording", "paused"}:
            message = "Recording is active. Change screens without stopping it."
        else:
            message = ""
        key = (lines, speakers, self.split, marker, message)
        if key == self._transcript_key:
            return
        self._transcript_key = key
        speaker_ids = tuple(speaker_id for speaker_id, _label, _seconds in speakers)
        layout = "split" if self.split else "mixed"
        rows: list = []
        if self.split:
            header = Table.grid(padding=(0, 1), expand=True)
            header.add_column(width=8)
            header.add_column(ratio=1)
            header.add_column(ratio=1)
            header.add_row(
                "",
                Text("MIC · what you said", style="bold #5fd7ff"),
                Text("SYSTEM · everyone else", style="bold #ffaf5f"),
            )
            rows.append(header)
        for line in lines:
            color = speaker_color(line.speaker_id, speaker_ids, source=line.source)
            rows.append(
                TranscriptLine(
                    line.start,
                    line.label,
                    line.text,
                    color=color,
                    source=line.source,
                    layout=layout,
                ).row()
            )
        if marker is not None:
            rows.append(Text(f"── {marker} ──", style="#6ee69a", no_wrap=True))
        if not lines and message:
            rows.append(Text(message))
        self.query_one("#transcript", TranscriptScroll).update_content(Group(*rows))

    def _lines(self, session) -> tuple:
        if session is None:
            return ()
        if self._saved_lines is not None and self._saved_lines[0] == session.path.name:
            lines = self._saved_lines[1]
        else:
            lines = session.lines
        return tuple(sorted(lines, key=lambda line: line.start))

    @staticmethod
    def _speaker_rows(session, lines: tuple) -> tuple[tuple[str, str, float], ...]:
        """Return ``(speaker_id, label, talk seconds)`` in first-line order."""
        labels: dict[str, str] = {}
        seconds: dict[str, float] = {}
        for line in lines:
            labels[line.speaker_id] = line.label
            seconds[line.speaker_id] = seconds.get(line.speaker_id, 0.0) + max(
                0.0, line.end - line.start
            )
        if session is not None:
            for speaker_id, label in getattr(session, "speakers", ()):
                labels.setdefault(speaker_id, label)
        return tuple(
            (speaker_id, label, seconds.get(speaker_id, 0.0))
            for speaker_id, label in labels.items()
        )

    @staticmethod
    def _marker(session, lines: tuple) -> str:
        parts = [f"saved · {len(lines)} {'phrase' if len(lines) == 1 else 'phrases'}"]
        for name in ("mic.flac", "system.flac"):
            try:
                size = (session.path / name).stat().st_size
            except OSError:
                continue
            megabytes = size / 1024**2
            parts.append(
                f"{name} {megabytes:.1f} MB" if megabytes < 10 else f"{name} {megabytes:.0f} MB"
            )
        return " · ".join(parts)

    def _speakers_card(self, session, speakers: tuple) -> Text:
        card = Text()
        speaker_ids = tuple(speaker_id for speaker_id, _label, _seconds in speakers)
        for speaker_id, label, seconds in speakers:
            if card:
                card.append("\n")
            color = speaker_color(
                speaker_id, speaker_ids, source="mic" if speaker_id == "you" else None
            )
            card.append(f"{label[:14]:<14}", style=f"bold {color}")
            whole = int(seconds)
            card.append(f" {whole // 60}:{whole % 60:02d}")
        if not card:
            card.append("no speakers yet", style="#8b93a1")
        failed = getattr(session, "failed_phrase_count", 0) if session is not None else 0
        if failed:
            noun = "phrase" if failed == 1 else "phrases"
            card.append(f"\n! {failed} {noun} failed", style="#ffaf5f")
        card.append("\n\n[r] Rename…")
        saved = self.record_state() == "saved" and session is not None
        if saved and self.app.is_busy(session.path.name):
            card.append(" busy", style="#8b93a1")
        return card

    def mic_device(self) -> str:
        label = getattr(self.app.services, "next_device_label", None)
        if label:
            return label
        device = self.app.current_config().audio.input_device
        return str(device) if device else "Default input"

    # Meters

    def _attach_meters(self, session) -> None:
        if session is self._metered:
            return
        self._detach_meters()
        self._metered = session
        if session is None:
            return
        self._session_devices[session.path.name] = self.mic_device()
        add_listener = getattr(session, "add_block_listener", None)
        if add_listener is not None:
            self._remove_listener = add_listener(self._on_block)

    def _detach_meters(self) -> None:
        remove, self._remove_listener = self._remove_listener, None
        self._metered = None
        if remove is not None:
            remove()

    def _on_block(self, source: str, samples: np.ndarray) -> None:
        meter = self.meters.get(source)
        if meter is not None:
            meter.feed(samples)

    # Actions

    def action_record_toggle(self) -> None:
        app = self.app
        if app.activity_status is not None:
            return
        if app.services.recording:
            session = getattr(app.services, "session", None)
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

    def action_stop(self) -> None:
        app = self.app
        begin_stop = getattr(app.services, "begin_stop", None)
        if app.activity_status is not None or begin_stop is None:
            return
        session = begin_stop()
        if session is None:
            return
        self._detach_meters()
        session_id = session.path.name
        owner = f"stop-{session_id}"
        app.try_acquire_session(session_id, owner)
        self._saved_at[session_id] = datetime.now()
        self._saved_lines = None
        log.info(fmt_event("hub", "recording_stopping"))
        app.run_worker(self._finish_stop(session, owner), name=owner, group="record-stop")
        app.refresh_view()

    async def _finish_stop(self, session, owner: str) -> None:
        app = self.app
        try:
            await asyncio.to_thread(app.services.finish_stop, session)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: recording_stop_failed", exc, safe=True)
            app.notify(f"Could not save the recording: {exc}", severity="error")
        else:
            log.info(fmt_event("hub", "recording_saved"))
        finally:
            app.release_session(session.path.name, owner)
            self._transcript_key = None
            app.refresh_view()

    def action_open_library(self) -> None:
        session = self.saved_session
        if session is not None and not self.app.services.recording:
            self.app.show_library(session.path.name)

    def action_choose_device(self) -> None:
        if self.app.services.recording or self.app.activity_status is not None:
            return
        self.app.run_worker(self._open_device_dialog(), name="device-list", group="device-list")

    async def _open_device_dialog(self) -> None:
        app = self.app
        services = app.services
        devices = await asyncio.to_thread(services.input_devices)
        setting = app.current_config().audio.input_device
        dialog = DeviceDialog(
            devices,
            setting=str(setting) if setting else "Default input",
            current=services.next_device,
        )
        app.push_screen(dialog, self._choose_device)

    def _choose_device(self, choice: tuple[str | None, str | None] | None) -> None:
        if choice is None:
            return
        self.app.services.choose_device(*choice)
        log.info(fmt_event("hub", "device_chosen", setting=choice[0] is None))
        self.app.refresh_view()

    def action_toggle_mic(self) -> None:
        self._toggle_source("mic", "Toggling microphone...")

    def action_toggle_system(self) -> None:
        self._toggle_source("system", "Toggling system audio...")

    def _toggle_source(self, source: str, status: str) -> None:
        services = self.app.services
        session = self.session
        if session is not None:
            self._run_live_action(
                lambda: session.toggle(source), status=status, name=f"toggle-{source}"
            )
        elif not services.recording and hasattr(services, "toggle_next_source"):
            services.toggle_next_source(source)
            self.app.refresh_view()

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

    def _transcript(self) -> TranscriptScroll:
        return self.query_one("#transcript", TranscriptScroll)

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

    # Rename

    def on_click(self, event: events.Click) -> None:
        if event.widget is not None and event.widget.id == "sidebar-card":
            self.action_rename_speaker()

    def action_rename_speaker(self) -> None:
        app = self.app
        live = self.session
        if live is not None:
            speakers = live.speakers
            if not speakers:
                app.notify("No speakers are available to rename.")
                return
            app.push_screen(RenameDialog(speakers), lambda result: self._rename_live(live, result))
            return
        saved = self.saved_session
        if saved is None or self.record_state() != "saved":
            return
        session_id = saved.path.name
        if app.is_busy(session_id):
            app.notify("session busy")
            return
        speakers = tuple(
            (speaker_id, label)
            for speaker_id, label, _seconds in self._speaker_rows(None, self._lines(saved))
        )
        if not speakers:
            app.notify("No speakers are available to rename.")
            return
        app.push_screen(
            RenameDialog(speakers),
            lambda result: self._rename_saved(session_id, result),
        )

    def _rename_live(self, session, value: tuple[str, str] | None) -> None:
        if value is None:
            return
        speaker_id, name = value
        try:
            session.rename(speaker_id, name)
        except ValueError as exc:
            self.app.notify(str(exc))
            return
        self.app.refresh_view()

    def _rename_saved(self, session_id: str, value: tuple[str, str] | None) -> None:
        if value is None:
            return
        self.app.run_worker(self._write_rename(session_id, *value), name=f"rename-{session_id}")

    async def _write_rename(self, session_id: str, speaker_id: str, name: str) -> None:
        app = self.app
        owner = f"rename-{session_id}"
        if not app.try_acquire_session(session_id, owner):
            app.notify("session busy")
            return
        store = app.services.session_store
        try:
            await asyncio.to_thread(store.rename_speaker, session_id, speaker_id, name)
            detail = await asyncio.to_thread(store.read, session_id)
        except (OSError, ValueError, RuntimeError) as exc:
            log_failure(log, logging.ERROR, "hub: speaker_rename_failed", exc, safe=True)
            app.notify(f"Could not rename the speaker: {exc}", severity="error")
        else:
            self._saved_lines = (session_id, detail.lines)
            log.info(fmt_event("hub", "speaker_renamed", session_id=session_id))
        finally:
            app.release_session(session_id, owner)
            app.refresh_view()
