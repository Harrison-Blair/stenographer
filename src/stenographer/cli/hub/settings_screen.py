# SPDX-License-Identifier: GPL-3.0-or-later
"""The Settings screen: a tab row, the one-page settings and the Checks tab."""

from __future__ import annotations

import asyncio
import datetime
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Click
from textual.widgets import Input, Static

from stenographer.cli.hub.checks_tab import ChecksTab
from stenographer.cli.hub.choice_dialog import ChoiceDialog
from stenographer.cli.hub.config_dialog import ConfigPrompt
from stenographer.cli.hub.dialogs import QuitConfirm
from stenographer.cli.hub.doctor_view import DOCTOR_STATE_GLYPHS
from stenographer.cli.hub.hub_screen import HubScreen
from stenographer.cli.hub.vocabulary_dialog import VocabularyDialog
from stenographer.cli.hub.widgets.button import HubButton
from stenographer.cli.hub.widgets.field import Field
from stenographer.cli.hub.widgets.row_input import fit_input_to_row
from stenographer.cli.hub.widgets.status_token import StatusToken
from stenographer.cli.hub.widgets.update_changed import update_changed
from stenographer.lib.config.errors import ConfigError, ConfigPersistenceError

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from stenographer.cli.hub.config_view import ConfigEditor

# The one settings page: six groups of dotted keys, in order.
SETTINGS_GROUPS = (
    (
        "Keys",
        ("hotkey.binding", "hotkey.general_binding", "hotkey.cancel_binding", "hotkey.mode"),
    ),
    (
        "Audio",
        ("audio.input_device", "feedback.volume", "feedback.sound_pack", "feedback.overlay"),
    ),
    ("Text", ("refine.vocabulary", "delivery.copy_original", "delivery.restore_clipboard")),
    ("Refine", ("refine.enabled", "refine.host", "refine.model")),
    ("Recording", ("live.diarize_mic", "feedback.spectrum_floor_dbfs")),
    ("System", ("analytics.enabled", "asr.idle_unload_seconds")),
)
SETTINGS_KEYS = tuple(key for _group, keys in SETTINGS_GROUPS for key in keys)
# The first three groups fill the left column of the wide page.
_LEFT_GROUPS = 3
TABS = (("settings", "Settings"), ("checks", "Checks"))
_CONFIG_ACTIONS = frozenset(
    {
        "previous_key",
        "next_key",
        "edit_key",
        "toggle_key",
        "undo",
        "reset_key",
        "search",
        "save",
        "discard_all",
        "escape",
        "tab_row",
    }
)
# Buttons with a key leave the tab row first when it is too narrow, in this order.
_DROPPABLE_BUTTONS = ("#config-reset", "#config-undo")
_ACCENT_BOLD = "bold #5fd7ff"
_DIM = "#8b93a1"
_DEFAULT_DEVICE = {"audio.input_device": "Default input"}
# Fixed slots: the unsaved count of the message line and the count beside Save.
_UNSAVED_SLOT = 20
_COUNT_SLOT = 10
_WIDE_COLUMNS = 120
_MEDIUM_COLUMNS = 80


def settings_tier(width: int) -> str:
    """Return ``wide``, ``medium`` or ``narrow`` for a terminal width.

    The hub tier classes replace this once they exist.
    """
    if width >= _WIDE_COLUMNS:
        return "wide"
    return "medium" if width >= _MEDIUM_COLUMNS else "narrow"


def _count_text(count: int) -> str:
    return f"{count} change{'' if count == 1 else 's'}"


class SettingRow(Field):
    """A settings row whose label column holds the longest setting name."""

    LABEL_WIDTH = 22


# The input of a number or text row starts at the control column: dot slot, gap, label, gap.
_CONTROL_WIDTH = 30
_CONTROL_OFFSET = 2 + 1 + SettingRow.LABEL_WIDTH + 1


class SettingsScreen(HubScreen):
    """Edit the configuration on one page; the Checks tab runs the system checks.

    Each config row is a ``Field``. ``●`` marks a row whose draft value
    differs from the saved file. The line under the tabs shows the unsaved
    count and one message: the newest backup, the default of the selected
    row, or why the config refused a value. A number or text row edits in an
    input in the row; while it has focus, letters go to it and only
    ``escape``, ``enter``, ``tab`` and ``ctrl+s`` act.
    """

    SCREEN_TITLE = "Settings"
    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        ("left", "move_tab(-1)", "Previous tab"),
        ("right", "move_tab(1)", "Next tab"),
        ("up", "previous_key", "Previous setting"),
        ("down", "next_key", "Next setting"),
        ("enter", "edit_key", "Edit the setting"),
        ("space", "toggle_key", "Toggle the setting"),
        ("u", "undo", "Undo the last change"),
        Binding("shift+d", "reset_key", "Reset the setting to its default", key_display="D"),
        ("slash", "search", "Search setting names"),
        ("ctrl+s", "save", "Save changes"),
        Binding("escape", "escape", "Close the input or the search", show=False),
        Binding("tab", "tab_row", "Keep the input and select the next setting", show=False),
    ]
    DEFAULT_CSS = """
    SettingsScreen #settings-panel {
        height: 1fr;
        border: round #3a4150;
        padding: 0 1;
    }
    SettingsScreen #settings-tabs {
        height: 1;
    }
    SettingsScreen #settings-tabs-gap {
        width: 1fr;
        min-width: 1;
    }
    SettingsScreen #config-count {
        width: 10;
        text-align: right;
    }
    SettingsScreen #config-body {
        height: 1fr;
    }
    SettingsScreen #config-summary {
        height: 1;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    SettingsScreen #config-search {
        height: 1;
        color: #8b93a1;
        display: none;
    }
    SettingsScreen #config-rule {
        height: 1;
        border-top: solid #3a4150;
    }
    SettingsScreen #config-rows {
        height: 1fr;
    }
    SettingsScreen .config-columns {
        height: auto;
    }
    SettingsScreen .config-column {
        width: 1fr;
        height: auto;
    }
    SettingsScreen .config-column.-right {
        margin-left: 4;
    }
    SettingsScreen .config-group {
        height: 1;
        color: #8b93a1;
        text-style: bold;
    }
    SettingsScreen .config-group.-spaced {
        margin-top: 1;
    }
    SettingsScreen #config-hint {
        height: 1;
        color: #8b93a1;
        text-align: right;
    }
    """

    def __init__(self, checks_tab: ChecksTab, **kwargs) -> None:
        super().__init__(**kwargs)
        self.checks_tab = checks_tab
        self.tab = "settings"
        self.editing: str | None = None
        self.row_error: tuple[str, str] | None = None
        self._rows: dict[str, Field] = {}
        self._row_signature: tuple[object, ...] | None = None
        self._shown_selection: str | None = None
        self._device_labels: dict[str, dict[str, str]] = {}

    def compose_body(self) -> ComposeResult:
        with Vertical(id="settings-panel"):
            with Horizontal(id="settings-tabs"):
                for name, _label in TABS:
                    yield HubButton(
                        self.tab_label(name),
                        action=f"select_tab('{name}')",
                        tight=True,
                        id=f"tab-{name}",
                    )
                yield Static("", id="settings-tabs-gap")
                yield HubButton("Undo", key="u", action="undo", tight=True, id="config-undo")
                yield HubButton(
                    "Reset row", key="D", action="reset_key", tight=True, id="config-reset"
                )
                yield HubButton(
                    "Discard all", action="discard_all", tight=True, id="config-discard"
                )
                yield HubButton(
                    "Save",
                    key="ctrl+s",
                    action="save",
                    tone="primary",
                    tight=True,
                    id="config-save",
                )
                yield Static("", id="config-count", markup=False)
            with Vertical(id="config-body"):
                yield Static("", id="config-summary", markup=False)
                yield Static("", id="config-search", markup=False)
                yield Static("", id="config-rule")
                yield VerticalScroll(id="config-rows")
                yield Static(
                    "↑↓ select · ←→ tab · enter edit · space toggle", id="config-hint", markup=False
                )
            yield self.checks_tab

    def on_mount(self) -> None:
        editor = self.app.config_editor
        if editor.shown_keys is None:
            editor.show_keys(SETTINGS_KEYS)
        self._sync_tab_widgets()

    @property
    def tier(self) -> str:
        return settings_tier(self.app.size.width)

    def on_resize(self) -> None:
        if self.ready:
            self.app.refresh_view()

    def select_tab(self, tab: str) -> None:
        """Show one tab; unsaved changes stay."""
        if not self._commit_input():
            return
        self.tab = tab
        if self.ready:
            self._sync_tab_widgets()
        checks = self.checks_tab
        if tab == "checks" and checks.report is None and not checks.checking:
            checks.run_checks()
        self.app.refresh_view()

    def _sync_tab_widgets(self) -> None:
        config_tab = self.tab != "checks"
        self.checks_tab.display = not config_tab
        self.query_one("#config-body").display = config_tab
        for name, _label in TABS:
            self.query_one(f"#tab-{name}", HubButton).set_label(self.tab_label(name))
        if config_tab:
            self.set_focus(None)
        else:
            self.checks_tab.focus()

    def tab_label(self, tab: str) -> Text:
        """Return the printed tab label: ``▶`` marks the active tab, not colour alone.

        Each other tab keeps two blank cells there, so a tab change moves no tab.
        """
        selected = tab == self.tab
        label = Text("▶ " if selected else "  ", style=_ACCENT_BOLD if selected else "")
        label.append(dict(TABS)[tab], style=_ACCENT_BOLD if selected else "")
        report = self.checks_tab.report
        if tab == "checks" and report is not None and (report.warn_count or report.fail_count):
            count = report.warn_count + report.fail_count
            tone = "danger" if report.fail_count else "warn"
            label.append(" ")
            label.append(f"●{count}", style=StatusToken.TONES[tone])
        return label

    def open_setting(self, dotted_key: str) -> None:
        """Show the Settings tab with the row of a dotted key selected."""
        self.select_tab("settings")
        editor = self.app.config_editor
        if editor.search_term or editor.shown_keys != SETTINGS_KEYS:
            editor.show_keys(SETTINGS_KEYS)
        editor.select(dotted_key)
        self.app.refresh_view()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in _CONFIG_ACTIONS:
            return self.tab != "checks"
        return True

    # Drawing

    def refresh_body(self) -> None:
        app = self.app
        self.query_one("#tab-checks", HubButton).set_label(self.tab_label("checks"))
        editor = app.config_editor
        config_tab = self.tab != "checks"
        tier = self.tier
        for selector in ("#config-undo", "#config-reset", "#config-discard", "#config-save"):
            self.query_one(selector).display = config_tab and not editor.read_only
        count_slot = self.query_one("#config-count", Static)
        count_slot.display = config_tab and not editor.read_only and tier == "wide"
        if not config_tab:
            self.checks_tab.refresh_view()
            return
        if editor.shown_keys is None and not editor.read_only:
            editor.show_keys(SETTINGS_KEYS)
        self._sync_rows(editor, tier)
        summary = self.query_one("#config-summary", Static)
        summary.display = not editor.read_only
        search = self.query_one("#config-search", Static)
        search.display = bool(editor.search_term)
        self.query_one("#config-hint").display = tier == "wide"
        if editor.read_only:
            return
        self._fit_tab_row(tier)
        search.update(f"search: {editor.search_term} · esc clears")
        self._update_rows(editor)
        count = editor.unsaved_change_count
        update_changed(count_slot, _count_text(count) if count else "")
        update_changed(summary, self._config_summary(editor, tier))

    def _fit_tab_row(self, tier: str) -> None:
        """Hide the buttons that have a key, Reset row first, until the tab row fits."""
        gap = 3 if tier == "wide" else 2
        row = self.query_one("#settings-tabs")
        shown = list(row.query(HubButton))
        for button in shown:
            button.styles.margin = (0, 0 if button.id == "config-save" else gap, 0, 0)
        for selector in _DROPPABLE_BUTTONS:
            self.query_one(selector).display = True
        width = row.content_size.width or self.app.size.width
        count = _COUNT_SLOT if self.query_one("#config-count").display else 0
        needed = (
            count
            + 1
            + sum(
                button.label.cell_length + (0 if button.id == "config-save" else gap)
                for button in shown
            )
        )
        for selector in _DROPPABLE_BUTTONS:
            if needed <= width:
                break
            button = self.query_one(selector, HubButton)
            button.display = False
            needed -= button.label.cell_length + gap

    def _sync_rows(self, editor: ConfigEditor, tier: str) -> None:
        """Mount the group heads and one Field per shown key when the page changes."""
        if editor.read_only:
            signature: tuple[object, ...] = (id(editor), editor.error_text())
        else:
            signature = (id(editor), editor.visible_keys, editor.search_term, tier)
        if signature == self._row_signature:
            return
        self._row_signature = signature
        reopen = None
        if self.editing is not None and self.editing in editor.visible_keys:
            typed = self.query_one("#config-input", Input)
            reopen = (self.editing, typed.value, typed.cursor_position, self.row_error)
        self._close_input()
        container = self.query_one("#config-rows", VerticalScroll)
        container.remove_children()
        self._rows = {}
        self._shown_selection = None
        if editor.read_only:
            container.mount(Static(editor.error_text(), id="config-message", markup=False))
            return
        shown = set(editor.visible_keys)
        groups = []
        for index, (group, keys) in enumerate(SETTINGS_GROUPS):
            rows = [key for key in keys if key in shown]
            if not rows:
                continue
            head = Static(group.upper(), markup=False)
            head.add_class("config-group", f"group-{group.lower()}")
            widgets: list[Static] = [head]
            for key in rows:
                field = SettingRow(editor.label(key), "")
                self._rows[key] = field
                widgets.append(field)
            groups.append((index, widgets))
        if tier == "wide":
            left = [group for group in groups if group[0] < _LEFT_GROUPS]
            right = [group for group in groups if group[0] >= _LEFT_GROUPS]
            container.mount(
                Horizontal(
                    Vertical(*self._spaced(left, spaced=True), classes="config-column"),
                    Vertical(*self._spaced(right, spaced=True), classes="config-column -right"),
                    classes="config-columns",
                )
            )
        else:
            container.mount_all(self._spaced(groups, spaced=tier == "medium"))
        if reopen is not None:
            self.call_after_refresh(self._reopen_input, editor, *reopen)

    def _reopen_input(
        self, editor: ConfigEditor, key: str, text: str, cursor: int, error: tuple[str, str] | None
    ) -> None:
        """Put back an input that a row rebuild closed, with its typed text and refusal."""
        self.row_error = error
        self.run_worker(self._open_input(editor, key, text=text, cursor=cursor))

    @staticmethod
    def _spaced(groups: list[tuple[int, list[Static]]], *, spaced: bool) -> list[Static]:
        """Join groups into one list; ``spaced`` leaves an empty line above each later head."""
        widgets: list[Static] = []
        for position, (_index, members) in enumerate(groups):
            if spaced and position:
                members[0].add_class("-spaced")
            widgets.extend(members)
        return widgets

    def _update_rows(self, editor: ConfigEditor) -> None:
        selected = editor.selected_key
        for key, field in self._rows.items():
            focused = key == selected
            field.set_value(
                self._control(editor, key, focused), changed=editor.is_changed(key), focused=focused
            )
        if selected != self._shown_selection and selected in self._rows:
            self._shown_selection = selected
            self.query_one("#config-rows", VerticalScroll).scroll_to_widget(
                self._rows[selected], animate=False
            )

    def _control(self, editor: ConfigEditor, key: str, focused: bool) -> Text:
        style = _ACCENT_BOLD if focused else ""
        kind = editor.kind(key)
        value = editor.value(key)
        if kind == "toggle":
            return Text("(●) on" if value else "( ) off", style=style)
        if kind == "number":
            text = Text(str(value), style=style)
            unit = editor.unit(key)
            if unit:
                text.append(f" {unit}", style=_DIM)
            return text
        if kind == "list":
            terms = self._value_text(editor, key, value)
            return Text(f"[enter] Edit list… {terms}", style=style or "#5fd7ff")
        text = self._value_text(editor, key, value)
        if kind in {"choice", "device"}:
            text = f"{text} ▾"
        return Text(text, style=style, no_wrap=True, overflow="ellipsis")

    def _value_text(self, editor: ConfigEditor, key: str, value: object) -> str:
        if editor.kind(key) == "list":
            return f"{len(value)} {'term' if len(value) == 1 else 'terms'}"
        if editor.kind(key) == "device":
            if value is None:
                return _DEFAULT_DEVICE[key]
            return self._device_labels.get(key, {}).get(str(value), str(value))
        if value is None:
            return "(none)"
        return editor.format_value(value)

    def _config_summary(self, editor: ConfigEditor, tier: str) -> Text:
        """Return the message line: file, unsaved count slot and one message."""
        count = editor.unsaved_change_count
        summary = Text("" if tier == "narrow" else f"{editor.path.name} · ", no_wrap=True)
        unsaved = f"● {count} unsaved {_count_text(count)[len(str(count)) + 1 :]}"
        summary.append(
            (unsaved if count else unsaved[2:]).ljust(_UNSAVED_SLOT),
            style=StatusToken.TONES["warn"] if count else StatusToken.TONES["dim"],
        )
        summary.append("· ", style=StatusToken.TONES["dim"])
        summary.append_text(self._message(editor))
        return summary

    def _message(self, editor: ConfigEditor) -> Text:
        """Return the refusal of an input, else the default of the selected row, else the backup."""
        if self.row_error is not None:
            key, reason = self.row_error
            glyph = DOCTOR_STATE_GLYPHS["fail"]
            return Text(f"{glyph} {editor.label(key)} {reason}", style=StatusToken.TONES["danger"])
        key = editor.selected_key
        if key is not None and editor.value(key) != editor.default(key):
            default = self._value_text(editor, key, editor.default(key))
            return Text(f"default {default}", style=StatusToken.TONES["dim"])
        message = Text("backups ")
        backups = editor.backups()
        if not backups:
            message.append("none yet", style=StatusToken.TONES["dim"])
            return message
        newest = backups[-1]
        message.append(f"{newest.name} · ")
        try:
            stamp = datetime.datetime.fromtimestamp(newest.stat().st_mtime).strftime("%H:%M")
        except OSError:
            stamp = "—"
        message.append(f"last {stamp}", style=StatusToken.TONES["dim"])
        return message

    def footer_hints(self) -> tuple[tuple[str, str], ...]:
        if self.typing:
            return (("enter", "keep"), ("esc", "cancel"), ("tab", "next row"), ("ctrl+s", "save"))
        if self.tab == "checks":
            return (("←→", "tab"), *self.checks_tab.footer_hints())
        return (
            ("enter", "edit"),
            ("space", "toggle"),
            ("ctrl+s", "save"),
            ("u", "undo"),
            ("D", "reset"),
            ("/", "search"),
            ("←→", "tab"),
            ("↑↓", "row"),
        )

    # Device lists

    def list_devices(self) -> list[tuple[str, str]]:
        """Return ``(value, label)`` of each microphone the sound server lists."""
        return self.app.services.input_devices()

    # Actions

    def _editor(self) -> ConfigEditor | None:
        editor = self.app.config_editor
        return None if editor.read_only else editor

    def action_move_tab(self, offset: int) -> None:
        names = [name for name, _label in TABS]
        self.select_tab(names[(names.index(self.tab) + offset) % len(names)])

    def action_select_tab(self, tab: str) -> None:
        self.select_tab(tab)

    def action_previous_key(self) -> None:
        self._move_key(-1)

    def action_next_key(self) -> None:
        self._move_key(1)

    def _move_key(self, offset: int) -> None:
        editor = self._editor()
        if editor is not None:
            self.row_error = None
            editor.move_key(offset)
            self.app.refresh_view()

    async def action_edit_key(self) -> None:
        editor = self._editor()
        key = editor.selected_key if editor is not None else None
        if editor is None or key is None:
            return
        kind = editor.kind(key)
        if kind == "toggle":
            self._apply(key, not editor.value(key))
        elif kind == "choice":
            self._open_choice(editor, key)
        elif kind == "device":
            self.app.run_worker(
                self._open_devices(editor, key), group="settings-devices", exclusive=True
            )
        elif kind == "list":
            self.app.push_screen(
                VocabularyDialog(editor.value(key), editor.check_vocabulary),
                lambda terms: terms is not None and self._apply(key, terms),
            )
        else:
            await self._open_input(editor, key)

    def action_toggle_key(self) -> None:
        editor = self._editor()
        key = editor.selected_key if editor is not None else None
        if key is not None and editor.kind(key) == "toggle":
            self._apply(key, not editor.value(key))

    def _open_choice(self, editor: ConfigEditor, key: str) -> None:
        values = editor.choices(key)
        current = values.index(str(editor.value(key)))
        self.app.push_screen(
            ChoiceDialog(editor.label(key), values, current),
            lambda index: index is not None and self._apply(key, values[index]),
        )

    async def _open_devices(self, editor: ConfigEditor, key: str) -> None:
        devices = list(await asyncio.to_thread(self.list_devices))
        # The user may have moved on during the enumeration; a late dialog would edit a hidden row.
        if self.app.screen is not self or editor.selected_key != key:
            return
        self._device_labels[key] = dict(devices)
        options: list[tuple[str | None, str]] = [(None, _DEFAULT_DEVICE[key]), *devices]
        current = editor.value(key)
        if current is not None and str(current) not in self._device_labels[key]:
            options.append((str(current), str(current)))
        values = [value for value, _label in options]
        self.app.push_screen(
            ChoiceDialog(
                editor.label(key),
                tuple(label for _value, label in options),
                values.index(None if current is None else str(current)),
            ),
            lambda index: index is not None and self._apply(key, values[index]),
        )

    def _apply(self, key: str, value: object) -> bool:
        editor = self._editor()
        if editor is None:
            return False
        try:
            editor.set_value(key, value)
        except (ConfigError, ConfigPersistenceError) as exc:
            self.row_error = (key, self._reason(exc))
            self.app.notify(str(exc), severity="error")
            return False
        finally:
            self.app.refresh_view()
        self.row_error = None
        return True

    @staticmethod
    def _reason(exc: Exception) -> str:
        """Return the words of a rejection for the ``\N{MULTIPLICATION SIGN}`` line of its row."""
        return exc.reason if isinstance(exc, ConfigError) else str(exc)

    async def _open_input(
        self, editor: ConfigEditor, key: str, *, text: str | None = None, cursor: int | None = None
    ) -> None:
        field = self._rows.get(key)
        if field is None:
            return
        value = editor.value(key)
        if text is not None:
            initial = text
        elif value is None:
            initial = ""
        elif isinstance(value, tuple):
            initial = ", ".join(map(str, value))
        else:
            initial = str(value)
        input_type = "text"
        if editor.kind(key) == "number":
            input_type = "integer" if isinstance(editor.default(key), int) else "number"
        editor_input = Input(
            initial, type=input_type, compact=True, select_on_focus=False, id="config-input"
        )
        fit_input_to_row(editor_input)
        editor_input.styles.width = max(1, min(_CONTROL_WIDTH, field.size.width - _CONTROL_OFFSET))
        editor_input.styles.margin = (0, 0, 0, _CONTROL_OFFSET)
        self.editing = key
        self.app.refresh_view()
        await field.mount(editor_input)
        editor_input.focus()
        editor_input.cursor_position = len(initial) if cursor is None else cursor

    def _close_input(self) -> None:
        self.editing = None
        self.row_error = None
        for editor_input in self.query("#config-input"):
            editor_input.remove()
        if self.tab != "checks" and self.ready:
            self.set_focus(None)

    def _commit_input(self) -> bool:
        """Keep the value typed in the row input; false leaves the input open."""
        key = self.editing
        editor = self._editor()
        if key is None or editor is None:
            return True
        value = self.query_one("#config-input", Input).value
        try:
            editor.edit(key, value)
        except (ValueError, TypeError, ConfigError, ConfigPersistenceError) as exc:
            reason = self._reason(exc)
            if isinstance(exc, ValueError) and editor.kind(key) == "number":
                reason = "enter a number"
            self.row_error = (key, reason)
            self.app.notify(str(exc), severity="error")
            self.app.refresh_view()
            return False
        self._close_input()
        self.app.refresh_view()
        return True

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "config-input":
            event.stop()
            self._commit_input()

    def on_click(self, event: Click) -> None:
        field = event.widget
        if not isinstance(field, Field) or field not in self._rows.values():
            return
        editor = self._editor()
        if editor is None or self.editing is not None:
            return
        key = next(key for key, row in self._rows.items() if row is field)
        if editor.selected_key == key:
            self.run_worker(self.action_edit_key(), group="settings-edit")
        else:
            editor.select(key)
            self.app.refresh_view()

    def action_escape(self) -> None:
        if self.editing is not None:
            self._close_input()
            self.app.refresh_view()
            return
        editor = self._editor()
        if editor is not None and editor.clear_search():
            editor.show_keys(SETTINGS_KEYS)
            self.app.refresh_view()

    def action_tab_row(self) -> None:
        if self.editing is not None and not self._commit_input():
            return
        self._move_key(1)

    def action_undo(self) -> None:
        editor = self._editor()
        if editor is not None and editor.undo():
            self.app.refresh_view()

    def action_reset_key(self) -> None:
        editor = self._editor()
        key = editor.selected_key if editor is not None else None
        if key is not None:
            self._apply(key, editor.default(key))

    def action_search(self) -> None:
        if self._editor() is None:
            return
        self.app.push_screen(ConfigPrompt("Search setting names", initial=""), self._search)

    def _search(self, term: str | None) -> None:
        editor = self._editor()
        if editor is None or term is None:
            return
        if not editor.search(term):
            self.app.notify(f"No settings match {term!r}.", severity="warning")
            editor.show_keys(SETTINGS_KEYS)
        self.app.refresh_view()

    def action_discard_all(self) -> None:
        editor = self._editor()
        if editor is None or not editor.dirty:
            return
        count = editor.unsaved_change_count
        self.app.push_screen(
            QuitConfirm(
                f"Discard {count} unsaved change{'' if count == 1 else 's'}?",
                confirm="Discard all",
                cancel="Keep",
            ),
            self._discard_all,
        )

    def _discard_all(self, confirmed: bool | None) -> None:
        editor = self._editor()
        if confirmed and editor is not None:
            editor.discard()
            self.app.refresh_view()

    def action_save(self) -> None:
        if self.editing is not None and not self._commit_input():
            return
        self.app.save_config()
