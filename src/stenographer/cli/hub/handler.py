# SPDX-License-Identifier: GPL-3.0-or-later
"""Prepare and run the interactive hub."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager

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


@contextmanager
def _terminal_only_for_app() -> Iterator[None]:
    """Keep every writer but the app off the terminal, and restore them after.

    The logging stderr sink, ASR workers, ``pw-play``, host commands, and native
    libraries all write to file descriptors 1 and 2, so those point at the null
    device while the app runs. Textual draws through ``sys.__stderr__`` and ends
    with its crash report on ``sys.stderr``; both get private terminal streams.
    """
    originals = (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__)
    sys.stdout.flush()
    sys.stderr.flush()
    app_stdout = open(  # noqa: SIM115
        os.dup(1), "w", encoding=sys.stdout.encoding, errors=sys.stdout.errors, buffering=1
    )
    app_stderr = open(  # noqa: SIM115
        os.dup(2), "w", encoding=sys.stderr.encoding, errors=sys.stderr.errors, buffering=1
    )
    null = os.open(os.devnull, os.O_WRONLY)
    os.dup2(null, 1)
    os.dup2(null, 2)
    os.close(null)
    sys.stdout = sys.__stdout__ = app_stdout
    sys.stderr = sys.__stderr__ = app_stderr
    try:
        yield
    finally:
        sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__ = originals
        app_stdout.flush()
        app_stderr.flush()
        os.dup2(app_stdout.fileno(), 1)
        os.dup2(app_stderr.fileno(), 2)
        app_stdout.close()
        app_stderr.close()


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
        with _terminal_only_for_app():
            _run_app(services, config_editor)
    except KeyboardInterrupt:
        log.info(fmt_event("hub", "interrupted"))
    return 0
