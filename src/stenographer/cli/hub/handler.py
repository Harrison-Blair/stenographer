# SPDX-License-Identifier: GPL-3.0-or-later
"""Prepare and run the interactive hub."""

from __future__ import annotations

import argparse
import logging
import sys

from stenographer.cli.hub.config_view import ConfigEditor
from stenographer.cli.hub.services import HubServices
from stenographer.lib.config.errors import ConfigError
from stenographer.lib.config.models import Config
from stenographer.lib.config.paths import load_or_default, resolve_config_path
from stenographer.lib.logging.pipeline import apply_stderr_level, fmt_event, log_failure
from stenographer.lib.platform import current_platform

log = logging.getLogger(__name__)


def _run_app(services: HubServices, config_editor: ConfigEditor) -> None:
    from stenographer.cli.hub.app import HubApp

    HubApp(services, config_editor=config_editor).run()


def cmd_hub(_args: argparse.Namespace) -> int:
    path = resolve_config_path()
    try:
        cfg = load_or_default()
    except ConfigError:
        cfg = Config.defaults()
    config_editor = ConfigEditor(path)
    if not config_editor.read_only:
        apply_stderr_level(cfg.feedback.log_level)
    platform = current_platform()
    services = HubServices(cfg, platform)
    if not config_editor.read_only:
        try:
            services.warm_worker()
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: worker_prewarm_failed", exc, safe=True)
            print(f"stenographer: could not prepare the ASR worker: {exc}", file=sys.stderr)
            return 1
        log.info(fmt_event("hub", "worker_ready"))
    try:
        _run_app(services, config_editor)
    except KeyboardInterrupt:
        log.info(fmt_event("hub", "interrupted"))
    return 0
