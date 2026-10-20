# SPDX-License-Identifier: GPL-3.0-or-later
"""Prepare and run the interactive hub."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import TYPE_CHECKING

from stenographer.cli.hub.services import HubServices
from stenographer.cli.shared.config import with_config
from stenographer.lib.logging.pipeline import fmt_event, log_failure
from stenographer.lib.platform import current_platform

if TYPE_CHECKING:
    from stenographer.lib.config.models import Config

log = logging.getLogger(__name__)


def _run_app(services: HubServices) -> None:
    from stenographer.cli.hub.app import HubApp

    HubApp(services).run()


@with_config
def cmd_hub(_args: argparse.Namespace, cfg: Config) -> int:
    platform = current_platform()
    services = HubServices(cfg, platform)
    try:
        services.warm_worker()
    except Exception as exc:
        log_failure(log, logging.ERROR, "hub: worker_prewarm_failed", exc, safe=True)
        print(f"stenographer: could not prepare the ASR worker: {exc}", file=sys.stderr)
        return 1

    log.info(fmt_event("hub", "worker_ready"))
    try:
        _run_app(services)
    except KeyboardInterrupt:
        log.info(fmt_event("hub", "interrupted"))
    return 0
