# SPDX-License-Identifier: GPL-3.0-or-later
"""Capability-gated daemon startup and process cleanup."""

from __future__ import annotations

import contextlib
import logging
import sys
from typing import TYPE_CHECKING

from stenographer.cli.run.banner import _log_banner
from stenographer.lib.contracts.null_status_sink import NullStatusSink
from stenographer.lib.contracts.status_sink import StatusSink
from stenographer.lib.daemon.daemon import Daemon
from stenographer.lib.logging.pipeline import log_failure
from stenographer.lib.platform import current_platform
from stenographer.lib.platform.errors import SingleInstanceLockError

if TYPE_CHECKING:
    from stenographer.lib.config.models import Config

log = logging.getLogger("stenographer.lib.daemon")


def _startup_failure(status: StatusSink, message: str, code: int) -> int:
    """Report a startup bail-out on stderr and hand back its exit code.

    Any overlay opened before the failure is closed first, so a rejected start
    never strands a helper process.
    """
    with contextlib.suppress(Exception):
        status.close()
    print(f"stenographer: {message}", file=sys.stderr)
    return code


def run(cfg: Config) -> int:
    """Build and run the daemon. Returns the process exit code."""
    from stenographer.cli.shared.capabilities import REQUIRED, missing_required, probe
    from stenographer.lib.config.paths import resolve_config_path
    from stenographer.lib.hotkey.errors import BindingError

    plat = current_platform()
    status: StatusSink = NullStatusSink()
    caps = probe(cfg)
    _log_banner(cfg, plat, caps, resolve_config_path(create_parent=False))
    if missing_required(caps):
        from stenographer.cli.doctor.report import format_required_capabilities

        missing = set(missing_required(caps))
        guidance = plat.guidance()
        lines = format_required_capabilities(caps, guidance)
        details = [line for name, line in zip(REQUIRED, lines, strict=True) if name in missing]
        return _startup_failure(
            status, "required capabilities unavailable:\n" + "\n".join(details), 78
        )

    if cfg.feedback.overlay:
        try:
            from stenographer.overlay.supervision.overlay_supervisor import OverlaySupervisor

            status = OverlaySupervisor(cfg.feedback.spectrum_floor_dbfs)
        except Exception as exc:
            log_failure(log, logging.WARNING, "overlay: unavailable", exc, safe=True)

    log.info("deliver: configured clipboard_backend=%s", caps.clipboard_backend)
    try:
        daemon = Daemon.build(
            cfg, clipboard_backend=caps.clipboard_backend, status=status, platform=plat
        )
    except BindingError as exc:
        return _startup_failure(status, str(exc), 78)

    lock = plat.single_instance_lock()
    try:
        acquired = lock.acquire()
    except SingleInstanceLockError as exc:
        return _startup_failure(status, str(exc), 78)
    if not acquired:
        return _startup_failure(status, "another instance is already running.", 1)

    def _handler(reason: str) -> None:
        log.info("stop: requested reason=%s", reason)
        daemon.request_stop()

    plat.install_stop_handlers(_handler)

    try:
        daemon.run()
    except KeyboardInterrupt:
        pass
    finally:
        daemon.stop()
        with contextlib.suppress(Exception):
            status.close()
        lock.release()
    return 0
