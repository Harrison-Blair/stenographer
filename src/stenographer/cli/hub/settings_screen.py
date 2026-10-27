# SPDX-License-Identifier: GPL-3.0-or-later
"""The Settings screen: a tab bar, the config tabs and the Checks tab."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from stenographer.cli.hub.checks_tab import ChecksTab
from stenographer.cli.hub.config_dialog import ConfigPrompt
from stenographer.cli.hub.hub_screen import HubScreen
from stenographer.cli.hub.widgets.button import HubButton
from stenographer.cli.hub.widgets.status_token import StatusToken
from stenographer.lib.config.errors import ConfigError

if TYPE_CHECKING:
    from textual.app import ComposeResult

# Tab mapping of README §4.6; a pattern ending in ".*" matches a whole group.
SETTINGS_TABS = (
    (
        "general",
        "General",
        (
            "hotkey.*",
            "feedback.volume",
            "feedback.mute",
            "feedback.overlay",
            "feedback.sound_pack",
            "feedback.update_check",
            "feedback.log_level",
            "delivery.*",
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
    {"previous_key", "next_key", "edit_key", "undo", "reset_key", "search", "save"}
)


class SettingsScreen(HubScreen):
    """Edit the configuration by tab; the Checks tab runs the system checks."""

    SCREEN_NAME = "settings"
    SCREEN_TITLE = "Settings"
    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        ("left", "move_tab(-1)", "Previous tab"),
        ("right", "move_tab(1)", "Next tab"),
        ("up", "previous_key", "Previous setting"),
        ("down", "next_key", "Next setting"),
        ("enter", "edit_key", "Edit the setting"),
        ("u", "undo", "Undo the last change"),
        Binding("shift+d", "reset_key", "Reset the setting to its default", key_display="D"),
        ("slash", "search", "Search setting names"),
        ("ctrl+s", "save", "Save changes"),
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
        padding: 1 2;
        border: round #3a4150;
        overflow-y: auto;
    }
    SettingsScreen #section-content {
        height: auto;
    }
    SettingsScreen #config-selected-help {
        dock: bottom;
        height: auto;
        margin-top: 1;
        display: none;
    }
    """

    def __init__(self, checks_tab: ChecksTab, **kwargs) -> None:
        super().__init__(**kwargs)
        self.checks_tab = checks_tab
        self.tab = "general"
        self.check_badge: tuple[int, str] | None = None

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
            yield Static("", id="section-content", markup=False)
            yield Static("", id="config-selected-help", markup=False)
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
        editor = self.app.config_editor
        keys = editor.all_keys if editor is not None else ()
        return tuple(key for key in keys if self._tab_of_or_none(key) == tab)

    def _tab_of_or_none(self, dotted_key: str) -> str | None:
        try:
            return self.tab_of(dotted_key)
        except KeyError:
            return None

    def select_tab(self, tab: str) -> None:
        """Show one tab; unsaved changes stay."""
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

    def refresh_body(self) -> None:
        app = self.app
        editor = app.config_editor
        self.query_one("#tab-checks", HubButton).set_label(self.tab_label("checks"))
        if self.tab == "checks":
            self.checks_tab.refresh_view()
            app.set_context_card("settings", self.checks_tab.summary_card(), title="checks")
            return
        content = self.query_one("#section-content", Static)
        selected_help = self.query_one("#config-selected-help", Static)
        if editor is None:
            content.update("Configuration settings will appear here.")
            selected_help.display = False
            return
        if editor.shown_keys is None and not editor.read_only:
            editor.show_keys(self.tab_keys(self.tab))
        content.update(editor.render())
        selected_help.update(editor.render_selected_help())
        selected_help.display = not editor.read_only and editor.selected_key is not None
        app.set_context_card("settings", self._config_card(), title="config")

    def _config_card(self) -> Text:
        editor = self.app.config_editor
        count = editor.unsaved_change_count
        suffix = "" if count == 1 else "s"
        card = Text(f"{editor.path.name}\n")
        card.append(
            f"● {count} unsaved change{suffix}" if count else "0 unsaved changes",
            style=StatusToken.TONES["warn"] if count else StatusToken.TONES["dim"],
        )
        return card

    def footer_hints(self) -> tuple[tuple[str, str], ...]:
        if self.tab == "checks":
            return (("←→", "tab"), *self.checks_tab.footer_hints(), ("1 2 3", "screens"))
        return (
            ("←→", "tab"),
            ("↑↓", "row"),
            ("enter", "edit"),
            ("u", "undo"),
            ("D", "reset"),
            ("ctrl+s", "save"),
            ("/", "search"),
            ("1 2 3", "screens"),
        )

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
        if self.app.config_editor is not None:
            self.app.config_editor.move_key(offset)
            self.app.refresh_view()

    def action_edit_key(self) -> None:
        editor = self.app.config_editor
        if editor is None:
            return
        key = editor.selected_key
        if key is None or editor.read_only:
            return
        value = editor.value(key)
        if value is None:
            initial = ""
        elif isinstance(value, tuple):
            initial = ", ".join(map(str, value))
        else:
            initial = str(value)
        self.app.push_screen(
            ConfigPrompt(f"Edit {key}", initial=initial),
            lambda result: self._apply_edit(key, result),
        )

    def _apply_edit(self, key: str, value: str | None) -> None:
        editor = self.app.config_editor
        if value is None or editor is None:
            return
        try:
            editor.edit(key, value)
        except (ValueError, TypeError, ConfigError) as exc:
            self.app.notify(str(exc), severity="error")
        self.app.refresh_view()

    def action_undo(self) -> None:
        editor = self.app.config_editor
        if editor is not None and editor.undo():
            self.app.refresh_view()

    def action_reset_key(self) -> None:
        editor = self.app.config_editor
        if editor is None:
            return
        key = editor.selected_key
        if key is not None and not editor.read_only:
            try:
                editor.reset(key)
            except (ValueError, TypeError, ConfigError) as exc:
                self.app.notify(str(exc), severity="error")
            self.app.refresh_view()

    def action_search(self) -> None:
        editor = self.app.config_editor
        if editor is None or editor.read_only:
            return
        self.app.push_screen(
            ConfigPrompt("Search configuration keys", initial=""),
            self._search,
        )

    def _search(self, term: str | None) -> None:
        editor = self.app.config_editor
        if editor is None:
            return
        if term is not None and not editor.search(term):
            self.app.notify(f"No configuration keys match {term!r}.", severity="warning")
        self.app.refresh_view()

    def action_save(self) -> None:
        self.app.save_config()
