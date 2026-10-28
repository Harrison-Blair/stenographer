# SPDX-License-Identifier: GPL-3.0-or-later
"""The Settings screen: a tab bar, the config tabs and the Checks tab."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Click
from textual.widgets import Input, Rule, Static

from stenographer.cli.hub.checks_tab import ChecksTab
from stenographer.cli.hub.choice_dialog import ChoiceDialog
from stenographer.cli.hub.config_dialog import ConfigPrompt
from stenographer.cli.hub.dialogs import QuitConfirm
from stenographer.cli.hub.doctor_view import DOCTOR_STATE_GLYPHS
from stenographer.cli.hub.hub_screen import HubScreen
from stenographer.cli.hub.vocabulary_dialog import VocabularyDialog
from stenographer.cli.hub.widgets.button import HubButton
from stenographer.cli.hub.widgets.field import Field
from stenographer.cli.hub.widgets.status_token import StatusToken
from stenographer.lib.config.errors import ConfigError, ConfigPersistenceError

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from stenographer.cli.hub.config_view import ConfigEditor

# A rule between groups of rows; it matches no key.
DIVIDER = "---"
# Tab mapping of README §4.6; a pattern ending in ".*" matches a whole group.
SETTINGS_TABS = (
    (
        "general",
        "General",
        (
            "hotkey.*",
            DIVIDER,
            "feedback.volume",
            "feedback.mute",
            "feedback.overlay",
            "feedback.sound_pack",
            "feedback.update_check",
            "feedback.log_level",
            DIVIDER,
            "delivery.*",
            DIVIDER,
            "analytics.*",
        ),
    ),
    (
        "audio",
        "Audio",
        (
            "audio.input_device",
            "audio.min_speech_rms",
            "audio.max_recording_seconds",
            "feedback.spectrum_floor_dbfs",
        ),
    ),
    (
        "recognition",
        "Recognition",
        (
            "asr.idle_unload_seconds",
            "asr.cpu_threads",
            "refine.vocabulary",
            DIVIDER,
            "refine.enabled",
            "refine.host",
            "refine.model",
            "refine.min_words",
            "refine.structured_output",
        ),
    ),
    ("live", "Live", ("live.diarize_mic",)),
    ("checks", "Checks", ()),
)
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
_ACCENT_BOLD = "bold #5fd7ff"
_DIM = "#8b93a1"
_DEFAULT_DEVICE = {"audio.input_device": "Default input", "hotkey.device": "Default device"}
# The control column of a settings row is wider than the Field default, so
# "[enter] Edit list… 200 terms" fits. Its left edge: dot slot, gap, label, gap.
_CONTROL_WIDTH = 30
_CONTROL_OFFSET = 2 + 1 + Field.LABEL_WIDTH + 1


class SettingsScreen(HubScreen):
    """Edit the configuration by tab; the Checks tab runs the system checks.

    Each config row is a ``Field``. ``●`` marks a row whose draft value
    differs from the saved file. A number or text row edits in an input in
    the row; while it has focus, letters go to it and only ``escape``,
    ``enter``, ``tab`` and ``ctrl+s`` act.
    """

    SCREEN_NAME = "settings"
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
    SettingsScreen #settings-tabs {
        height: 2;
        padding: 0 1;
    }
    SettingsScreen #settings-tabs-hint {
        width: 1fr;
        height: 2;
        content-align: right bottom;
        color: #8b93a1;
    }
    SettingsScreen #config-body {
        height: 1fr;
        border: round #3a4150;
    }
    SettingsScreen #config-search {
        height: 1;
        padding: 0 2;
        color: #8b93a1;
        display: none;
    }
    SettingsScreen #config-rows {
        height: 1fr;
        padding: 1 2 0 2;
    }
    SettingsScreen #config-rows Field {
        margin-bottom: 1;
    }
    SettingsScreen #config-rows Rule {
        margin: 0 0 1 0;
        color: #3a4150;
    }
    SettingsScreen #config-actions {
        height: 2;
        padding: 0 2;
        border-top: solid #3a4150;
    }
    SettingsScreen #config-applies {
        width: 1fr;
        content-align: right top;
        color: #8b93a1;
    }
    """

    def __init__(self, checks_tab: ChecksTab, **kwargs) -> None:
        super().__init__(**kwargs)
        self.checks_tab = checks_tab
        self.tab = "general"
        self.check_badge: tuple[int, str] | None = None
        self.editing: str | None = None
        self.row_error: tuple[str, str] | None = None
        self._rows: dict[str, Field] = {}
        self._row_signature: tuple[object, ...] | None = None
        self._shown_selection: str | None = None
        self._device_labels: dict[str, dict[str, str]] = {}

    def compose_body(self) -> ComposeResult:
        with Horizontal(id="settings-tabs"):
            for name, _label, _keys in SETTINGS_TABS:
                tab = HubButton(
                    self.tab_label(name), action=f"select_tab('{name}')", id=f"tab-{name}"
                )
                tab.add_class("-tab")
                yield tab
            yield Static("←→ tab", id="settings-tabs-hint", markup=False)
        with Vertical(id="config-body"):
            yield Static("", id="config-search", markup=False)
            yield VerticalScroll(id="config-rows")
            with Horizontal(id="config-actions"):
                yield HubButton(
                    self._save_label(0),
                    key="ctrl+s",
                    action="save",
                    tone="primary",
                    id="config-save",
                )
                yield HubButton("Undo", key="u", action="undo", id="config-undo")
                yield HubButton("Reset row", key="D", action="reset_key", id="config-reset")
                yield HubButton("Discard all", action="discard_all", id="config-discard")
                yield Static("applies to new sessions and jobs", id="config-applies", markup=False)
        yield self.checks_tab

    def on_mount(self) -> None:
        editor = self.app.config_editor
        if self.tab != "checks" and editor is not None and editor.shown_keys is None:
            editor.show_keys(self.tab_keys(self.tab))
        self._sync_tab_widgets()

    @staticmethod
    def tab_of(dotted_key: str) -> str:
        """Return the tab that holds a dotted config key."""
        group = dotted_key.partition(".")[0]
        for name, _label, patterns in SETTINGS_TABS:
            if dotted_key in patterns or f"{group}.*" in patterns:
                return name
        raise KeyError(dotted_key)

    def tab_keys(self, tab: str) -> tuple[str, ...]:
        """Return the keys of a tab in the order of its mapping."""
        return tuple(key for key in self._tab_layout(tab) if key != DIVIDER)

    def _tab_layout(self, tab: str) -> tuple[str, ...]:
        editor = self.app.config_editor
        keys = editor.all_keys if editor is not None else ()
        patterns = next(patterns for name, _label, patterns in SETTINGS_TABS if name == tab)
        layout: list[str] = []
        for pattern in patterns:
            if pattern == DIVIDER:
                layout.append(DIVIDER)
            elif pattern.endswith(".*"):
                layout.extend(key for key in keys if key.startswith(pattern[:-1]))
            elif pattern in keys:
                layout.append(pattern)
        return tuple(layout)

    def select_tab(self, tab: str) -> None:
        """Show one tab; unsaved changes stay."""
        self._close_input()
        self.tab = tab
        editor = self.app.config_editor
        if tab != "checks" and editor is not None:
            editor.show_keys(self.tab_keys(tab))
        if self.ready:
            self._sync_tab_widgets()
        checks = self.checks_tab
        if tab == "checks" and checks.report is None and not checks.checking:
            checks.run_checks()
        self.app.refresh_view()

    def _sync_tab_widgets(self) -> None:
        self.checks_tab.display = self.tab == "checks"
        self.query_one("#config-body").display = self.tab != "checks"
        for name, _label, _keys in SETTINGS_TABS:
            tab = self.query_one(f"#tab-{name}", HubButton)
            tab.set_class(name == self.tab, "-selected")
            tab.set_label(self.tab_label(name))
        if self.tab == "checks":
            self.checks_tab.focus()
        else:
            self.set_focus(None)

    def tab_label(self, tab: str) -> Text:
        """Return the printed tab label: ``▶`` marks the active tab without colour.

        Each other tab keeps two blank cells there, so a tab change moves no tab.
        """
        label = Text("▶ " if tab == self.tab else "  ")
        label.append(next(text for name, text, _keys in SETTINGS_TABS if name == tab))
        if tab == "checks" and self.check_badge is not None:
            count, tone = self.check_badge
            label.append(" ")
            label.append(f"●{count}", style=StatusToken.TONES[tone])
        return label

    def open_setting(self, dotted_key: str) -> None:
        """Select the tab of a dotted key and its row."""
        self.select_tab(self.tab_of(dotted_key))
        self.app.config_editor.select(dotted_key)
        self.app.refresh_view()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in _CONFIG_ACTIONS:
            return self.tab != "checks"
        return True

    # Drawing

    def refresh_body(self) -> None:
        app = self.app
        self.query_one("#tab-checks", HubButton).set_label(self.tab_label("checks"))
        if self.tab == "checks":
            self.checks_tab.refresh_view()
            app.set_context_card(
                "settings",
                self.checks_tab.summary_card(),
                title="checks",
                buttons=(("Run again", "r", self.checks_tab.action_run_checks),),
            )
            return
        editor = app.config_editor
        if editor is not None and editor.shown_keys is None and not editor.read_only:
            editor.show_keys(self.tab_keys(self.tab))
        self._sync_rows(editor)
        actions = self.query_one("#config-actions")
        actions.display = editor is not None and not editor.read_only
        search = self.query_one("#config-search", Static)
        search.display = editor is not None and bool(editor.search_term)
        if editor is None or editor.read_only:
            return
        search.update(f"search: {editor.search_term} · esc clears")
        self._update_rows(editor)
        count = editor.unsaved_change_count
        self.query_one("#config-save", HubButton).set_label(self._save_label(count))
        app.set_context_card("settings", self._config_card(editor), title="config")

    def _sync_rows(self, editor: ConfigEditor | None) -> None:
        """Mount one Field per visible key when the visible keys change."""
        if editor is None:
            signature: tuple[object, ...] = (None, "Configuration settings will appear here.")
        elif editor.read_only:
            signature = (id(editor), editor.error_text())
        else:
            signature = (id(editor), editor.visible_keys, editor.search_term)
        if signature == self._row_signature:
            return
        self._row_signature = signature
        self._close_input()
        container = self.query_one("#config-rows", VerticalScroll)
        container.remove_children()
        self._rows = {}
        self._shown_selection = None
        if editor is None or editor.read_only:
            container.mount(Static(str(signature[1]), id="config-message", markup=False))
            return
        layout = editor.visible_keys if editor.search_term else self._tab_layout(self.tab)
        widgets = []
        for key in layout:
            if key == DIVIDER:
                if widgets:
                    widgets.append(Rule())
                continue
            field = Field(editor.label(key), "")
            field.CONTROL_WIDTH = _CONTROL_WIDTH
            self._rows[key] = field
            widgets.append(field)
        container.mount_all(widgets)

    def _update_rows(self, editor: ConfigEditor) -> None:
        selected = editor.selected_key
        for key, field in self._rows.items():
            focused = key == selected
            help_text = editor.help(key)
            if self.row_error is not None and key == self.row_error[0]:
                help_text = f"{DOCTOR_STATE_GLYPHS['fail']} {self.row_error[1]}"
                if key == self.editing:
                    help_text += " · esc cancels"
            elif key == self.editing:
                help_text = "editing · enter keeps · esc cancels"
            elif focused and editor.kind(key) != "list":
                help_text += f" · default {self._value_text(editor, key, editor.default(key))}"
            field.help_text = help_text
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
            return Text("(●) on" if value else "( ) off", style=style, justify="right")
        if kind == "number":
            text = Text(str(value), style=style, justify="right")
            unit = editor.unit(key)
            if unit:
                text.append(f" {unit}", style=_DIM)
            return text
        if kind == "list":
            count = len(value)
            noun = "term" if count == 1 else "terms"
            return Text(
                f"[enter] Edit list… {count} {noun}", style=style or "#5fd7ff", justify="right"
            )
        text = self._value_text(editor, key, value)
        if kind in {"choice", "device"}:
            return Text(f"{text} ▾", style=style, justify="right")
        return Text(text, style=style)

    def _value_text(self, editor: ConfigEditor, key: str, value: object) -> str:
        if editor.kind(key) == "device":
            if value is None:
                return _DEFAULT_DEVICE[key]
            return self._device_labels.get(key, {}).get(str(value), str(value))
        if editor.kind(key) == "list":
            return f"{len(value)} terms"
        if value is None:
            return "(none)"
        return editor.format_value(value)

    @staticmethod
    def _save_label(count: int) -> str:
        return f"Save {count} change{'' if count == 1 else 's'}"

    def _config_card(self, editor: ConfigEditor) -> Text:
        count = editor.unsaved_change_count
        suffix = "" if count == 1 else "s"
        card = Text(f"{editor.path.name}\n")
        card.append(
            f"● {count} unsaved change{suffix}" if count else "0 unsaved changes",
            style=StatusToken.TONES["warn"] if count else StatusToken.TONES["dim"],
        )
        card.append("\n\nbackups\n")
        backups = editor.backups()
        if not backups:
            card.append("none yet", style=StatusToken.TONES["dim"])
            return card
        newest = backups[-1]
        card.append(f"{newest.name}\n")
        try:
            stamp = datetime.datetime.fromtimestamp(newest.stat().st_mtime).strftime("%H:%M")
        except OSError:
            stamp = "—"
        card.append(f"last {stamp}", style=StatusToken.TONES["dim"])
        return card

    def footer_hints(self) -> tuple[tuple[str, str], ...]:
        if self.tab == "checks":
            return (("←→", "tab"), *self.checks_tab.footer_hints(), ("1 2 3", "screens"))
        return (
            ("←→", "tab"),
            ("↑↓", "row"),
            ("enter", "edit"),
            ("space", "toggle"),
            ("u", "undo"),
            ("D", "reset"),
            ("ctrl+s", "save"),
            ("/", "search"),
            ("1 2 3", "screens"),
        )

    # Device lists

    def list_devices(self, dotted_key: str) -> list[tuple[str, str]]:
        """Return ``(value, label)`` of each device the sound or input server lists."""
        if dotted_key == "audio.input_device":
            from stenographer.lib.audio.probe import input_device_choices, query_devices

            return input_device_choices(query_devices().devices)
        from stenographer.lib.platform import current_platform

        return current_platform().hotkey_devices()

    # Actions

    def _editor(self) -> ConfigEditor | None:
        editor = self.app.config_editor
        if editor is None or editor.read_only:
            return None
        return editor

    def action_move_tab(self, offset: int) -> None:
        names = [name for name, _label, _keys in SETTINGS_TABS]
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
            self._open_devices(editor, key)
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

    def _open_devices(self, editor: ConfigEditor, key: str) -> None:
        devices = list(self.list_devices(key))
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

    async def _open_input(self, editor: ConfigEditor, key: str) -> None:
        field = self._rows.get(key)
        if field is None:
            return
        value = editor.value(key)
        if value is None:
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
        # Inline styles: the app stylesheet gives each Input a border, and a
        # row input stays on the one line of its row.
        editor_input.styles.border = ("none", "black")
        editor_input.styles.height = 1
        editor_input.styles.padding = 0
        editor_input.styles.width = _CONTROL_WIDTH
        editor_input.styles.margin = (0, 0, 0, _CONTROL_OFFSET)
        self.editing = key
        self.app.refresh_view()
        await field.mount(editor_input)
        editor_input.focus()
        editor_input.cursor_position = len(initial)

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
            editor.show_keys(self.tab_keys(self.tab))
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
            editor.show_keys(self.tab_keys(self.tab))
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
