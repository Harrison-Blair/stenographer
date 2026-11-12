# SPDX-License-Identifier: GPL-3.0-or-later
"""Identical helpers shared by hub tests."""

from textual.geometry import Region
from textual.widgets import Button, Static

from stenographer.cli.hub.app import HubApp
from stenographer.cli.hub.config_view import ConfigEditor
from stenographer.cli.hub.widgets.field import Field
from stenographer.lib.config.defaults import default_toml


def _config_path(tmp_path, content=None):
    path = tmp_path / "config.toml"
    path.write_text(default_toml() if content is None else content, encoding="utf-8")
    return path


def _fields(app) -> list[Field]:
    return list(app.settings_screen.query("#config-rows Field").results(Field))


class IdleServices:
    recording = False
    files_running = False
    session = None


def _screen_text(app: HubApp) -> str:
    return "\n".join(
        "".join(segment.text for segment in strip._segments)
        for strip in app.screen._compositor.render_strips()
    )


def _has_split_header(text: str) -> bool:
    """Return whether a screen row holds only the two column headers of the split transcript."""
    return any(row.replace("│", " ").split() == ["MIC", "SYSTEM"] for row in text.splitlines())


def _speaker_bar(app: HubApp) -> str:
    return str(app.screen.query_one("#speaker-bar", Static).render())


def make_app(tmp_path, services, **kwargs) -> HubApp:
    """Return a hub on ``services``; a config of defaults in ``tmp_path`` backs its editor."""
    if "config_editor" not in kwargs:
        kwargs["config_editor"] = ConfigEditor(_config_path(tmp_path))
    return HubApp(services, **kwargs)


def _scrolls(node, screen) -> bool:
    """Return whether ``node`` scrolls its children up and down."""
    if node is screen:
        return False
    # A ScrollableContainer with overflow-y hidden cannot scroll, so its rows must fit.
    return node.styles.overflow_y in {"auto", "scroll"}


def _layout_problems(app) -> list[str]:
    """Each shown widget outside the screen or its parent, each overlap, each cut label.

    A widget inside a scroll container may leave its parent vertically (it scrolls);
    it must still stay inside it horizontally and must not overlap another widget.
    """
    screen = app.screen
    problems = []
    shown = []
    for widget in screen.query("*"):
        if not widget.display or not widget.region.area:
            continue
        name = widget.id or type(widget).__name__
        region = widget.region
        parent = widget.parent
        scroll = next((node for node in widget.ancestors if _scrolls(node, screen)), None)
        if scroll is not None:
            # Scrolling moves a widget only up and down: its full width must
            # stay inside its parent whether it is scrolled into view or not.
            inside = parent.content_region
            if region.x < inside.x or region.right > inside.right:
                problems.append(f"{name} leaves {parent.id} sideways: {region}")
            view = scroll.content_region
            if region.y >= view.bottom or region.bottom <= view.y:
                continue
            # Only the rows inside the scroll view are on screen.
            top, bottom = max(region.y, view.y), min(region.bottom, view.bottom)
            region = Region(region.x, top, region.width, bottom - top)
        if isinstance(widget, Field) and len(widget.label) > widget.LABEL_WIDTH:
            problems.append(f"{name} cuts its label: {widget.label}")
        if isinstance(widget, Button) and widget.label.cell_length > widget.content_size.width:
            problems.append(f"{name} cuts its label: {widget.label}")
        shown.append((widget, region))
        if not screen.region.contains_region(region):
            problems.append(f"{name} leaves the screen: {region}")
        if parent is screen or scroll is not None:
            continue
        if not parent.content_region.contains_region(region):
            problems.append(f"{name} leaves {parent.id}: {region}")
    for index, (widget, region) in enumerate(shown):
        for other, other_region in shown[index + 1 :]:
            related = widget in other.ancestors or other in widget.ancestors
            if not related and region.overlaps(other_region):
                problems.append(f"{widget.id or widget} overlaps {other.id or other}")
    return problems
