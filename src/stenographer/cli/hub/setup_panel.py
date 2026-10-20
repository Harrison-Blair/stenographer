# SPDX-License-Identifier: GPL-3.0-or-later
"""Render the selected setup step beside the step list."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from stenographer.cli.hub.selection import append_line

if TYPE_CHECKING:
    from stenographer.cli.hub.setup_state import SetupWizard
    from stenographer.lib.config.models import Config


class SetupPanel(Horizontal):
    """Show the setup steps beside the selected step's details."""

    def compose(self) -> ComposeResult:
        yield Static("", id="setup-steps", markup=False)
        with Vertical(id="setup-detail"):
            yield Static("", id="setup-detail-content", markup=False)
            yield Static("", id="setup-test-status", markup=False)

    def refresh_view(self, wizard: SetupWizard, config: Config | None) -> None:
        steps = Text()
        for index, step in enumerate(wizard.steps, 1):
            selected = index - 1 == wizard.index and not wizard.finished
            if selected:
                value = f"{index} {step.title}"
            elif step.step_id in wizard.completed:
                value = f"✓ {index} {step.title}"
            elif step.step_id in wizard.skipped:
                value = f"- {index} {step.title}"
            else:
                value = f"○ {index} {step.title}"
            append_line(steps, value, selectable=True, selected=selected)
        append_line(steps, "")
        append_line(steps, "quick: steps 1-3 only")

        detail = Text()
        test_status = Text()
        if wizard.finished:
            self.query_one("#setup-steps", Static).border_title = "steps"
            self.query_one("#setup-detail", Vertical).border_title = "setup complete"
            append_line(detail, "Setup path complete.")
        else:
            step = wizard.step
            selected = self.query_one("#setup-steps", Static)
            selected.border_title = "steps"
            panel = self.query_one("#setup-detail", Vertical)
            panel.border_title = f"{wizard.index + 1} · {step.title}"
            append_line(detail, step.description)
            if step.step_id == "hotkey":
                hotkey = config.hotkey if config is not None else None
                append_line(detail, "")
                append_line(
                    detail,
                    f"capture target: {hotkey.binding if hotkey is not None else 'not configured'}",
                )
                if detail:
                    detail.append("\n")
                detail.append("mode: ")
                active_mode = hotkey.mode if hotkey is not None else ""
                modes = ("hybrid", "hold", "toggle")
                for index, mode in enumerate(modes):
                    selected_mode = mode == active_mode
                    marker = "●" if selected_mode else "○"
                    style = "bold #5fd7ff" if selected_mode else None
                    gap = "  " if index < len(modes) - 1 else ""
                    detail.append(f"{marker} {mode}{gap}", style=style)
                threshold = (
                    f"{hotkey.hybrid_threshold_seconds:g} s" if hotkey is not None else "unknown"
                )
                append_line(detail, f"hybrid threshold: {threshold}")
                general = hotkey.general_binding if hotkey is not None else "unknown"
                cancel = (hotkey.cancel_binding or "disabled") if hotkey is not None else "unknown"
                device = (hotkey.device or "any keyboard") if hotkey is not None else "unknown"
                append_line(detail, f"general binding: {general}")
                append_line(detail, f"cancel binding: {cancel}")
                append_line(detail, f"device: {device}")
            elif step.config_key is not None and config is not None:
                group, _, key = step.config_key.partition(".")
                value = getattr(getattr(config, group), key)
                shown = "automatic" if value is None else str(value)
                append_line(detail, f"Current {step.config_key}: {shown}")
            append_line(test_status, f"test status: {wizard.last_test or 'not tested'}")
        self.query_one("#setup-steps", Static).update(steps)
        self.query_one("#setup-detail-content", Static).update(detail)
        self.query_one("#setup-test-status", Static).update(test_status)
