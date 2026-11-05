# SPDX-License-Identifier: GPL-3.0-or-later
"""Identical helpers shared by hub tests."""

from textual.widgets import Static

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


def _card(app: HubApp) -> str:
    return str(app.screen.query_one("#sidebar-card", Static).render())


def make_app(tmp_path, services, **kwargs) -> HubApp:
    """Return a hub on ``services``; a config of defaults in ``tmp_path`` backs its editor."""
    if "config_editor" not in kwargs:
        kwargs["config_editor"] = ConfigEditor(_config_path(tmp_path))
    return HubApp(services, **kwargs)
