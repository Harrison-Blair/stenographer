# SPDX-License-Identifier: GPL-3.0-or-later
"""Capability-gated daemon startup and process cleanup."""

from __future__ import annotations

import contextlib
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from stenographer.cli.run.banner import _log_banner
from stenographer.lib.contracts.null_status_sink import NullStatusSink
from stenographer.lib.contracts.status_sink import StatusSink
from stenographer.lib.daemon.daemon import Daemon
from stenographer.lib.logging.pipeline import log_failure
from stenographer.lib.platform import current_platform
from stenographer.lib.platform.errors import SingleInstanceLockError

if TYPE_CHECKING:
    from stenographer.cli.shared.capabilities import Capabilities
    from stenographer.lib.config.models import Config

log = logging.getLogger("stenographer.lib.daemon")


def startup_clipboard_backend(caps: Capabilities) -> str | None:
    """Gate daemon startup on the capability requirements and reuse its backend name. PURE."""
    from stenographer.lib.diagnostics.capabilities import missing_required

    if missing_required(caps):
        return None
    return caps.clipboard_backend


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
    from stenographer.cli.shared.capability_probe import probe
    from stenographer.lib.config.paths import resolve_config_path
    from stenographer.lib.hotkey.errors import BindingError

    plat = current_platform()
    status: StatusSink = NullStatusSink()
    caps = probe(cfg)
    _log_banner(cfg, plat, caps, resolve_config_path(create_parent=False))
    clipboard_backend = startup_clipboard_backend(caps)
    if clipboard_backend is None:
        return _startup_failure(
            status, "required capabilities unavailable; run `stenographer doctor`", 78
        )

    if cfg.feedback.overlay:
        try:
            from stenographer.overlay.supervision.overlay_supervisor import OverlaySupervisor

            status = OverlaySupervisor(cfg.feedback.spectrum_floor_dbfs)
        except Exception as exc:
            log_failure(log, logging.WARNING, "overlay: unavailable", exc, safe=True)

    log.info("deliver: configured clipboard_backend=%s", clipboard_backend)
    try:
        daemon = Daemon.build(
            cfg, clipboard_backend=clipboard_backend, status=status, platform=plat
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
        try:
            daemon._recorder.prepare()
        except Exception as exc:
            log_failure(
                log,
                logging.WARNING,
                "recorder: startup_prepare_failed",
                exc,
                safe=True,
                recovery="next_keypress",
            )
        if cfg.feedback.update_check:
            try:
                from stenographer._version import __version__
                from stenographer.lib.updates.notice import start_background_check

                log.debug("update_check: enabled")
                start_background_check(
                    __version__,
                    plat.state_dir(os.environ, Path.home()),
                    daemon._notifier,
                )
            except Exception as exc:
                log_failure(log, logging.DEBUG, "update_check: not_started", exc, safe=True)
        daemon.run()
    except KeyboardInterrupt:
        pass
    finally:
        daemon.stop()
        with contextlib.suppress(Exception):
            status.close()
        lock.release()
    return 0
