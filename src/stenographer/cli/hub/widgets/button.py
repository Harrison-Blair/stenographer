# SPDX-License-Identifier: GPL-3.0-or-later
"""A one-row button that prints its key and runs the action of that key."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Button as TextualButton


class HubButton(TextualButton):
    """Print ``[key] label`` on one row; a click runs the bound action.

    The action is the action name of the key binding. A click runs it on the
    nearest ancestor (or the app) that defines ``action_<name>``, so the click
    and the key always do the same thing. A tab button has no key.
    """

    # The app stylesheet includes these rules after the shared transparent
    # rules, because app CSS outranks a widget's default CSS.
    # The app stylesheet includes these rules after the shared transparent
    # rules: app CSS outranks widget default CSS, and the ``-hub`` class
    # matches the specificity of the shared ``Button.-style-default`` rules.
    APP_CSS = """
    HubButton.-hub, HubButton.-hub:hover, HubButton.-hub:focus, HubButton.-hub.-active {
        width: auto;
        min-width: 0;
        height: 1;
        padding: 0 1;
        margin: 0 1 0 0;
        border: none;
        text-wrap: nowrap;
        text-overflow: ellipsis;
        text-style: none;
        color: ansi_default;
    }
    HubButton.-hub.-tone-primary { color: #5fd7ff; }
    HubButton.-hub.-tone-record, HubButton.-hub.-tone-danger { color: #ff875f; }
    HubButton.-hub:hover {
        color: #5fd7ff;
        text-style: bold;
    }
    HubButton.-hub.-tab, HubButton.-hub.-tab:hover {
        height: 2;
        border: round #3a4150;
        border-bottom: none;
        color: #8b93a1;
    }
    HubButton.-hub.-tab.-selected, HubButton.-hub.-tab.-selected:hover {
        border: round #5fd7ff;
        border-bottom: none;
        color: #5fd7ff;
        text-style: bold;
    }
    HubButton.-hub:disabled { color: #8b93a1; }
    """

    def __init__(
        self,
        label: str | Text,
        *,
        key: str | None = None,
        action: str | None = None,
        tone: str = "default",
        **kwargs,
    ) -> None:
        self.key = key
        self.action_name = action
        super().__init__(self.label_text(label, key), **kwargs)
        self.can_focus = False
        self.add_class("-hub", f"-tone-{tone}")

    @staticmethod
    def label_text(label: str | Text, key: str | None) -> Text:
        """Return the printed label with the key in brackets, as plain text."""
        text = label.copy() if isinstance(label, Text) else Text(label)
        return text if key is None else Text(f"[{key}] ").append_text(text)

    def set_label(self, label: str | Text) -> None:
        """Change the label and keep the key."""
        self.label = self.label_text(label, self.key)
        self.refresh(layout=True)

    async def on_button_pressed(self, event: TextualButton.Pressed) -> None:
        if self.action_name is None:
            return
        event.stop()
        name = self.action_name.partition("(")[0]
        for node in self.ancestors_with_self:
            if callable(getattr(node, f"action_{name}", None)):
                await self.app.run_action(self.action_name, node)
                return
