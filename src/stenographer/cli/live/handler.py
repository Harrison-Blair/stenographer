# SPDX-License-Identifier: GPL-3.0-or-later
"""Start a configured live session and its terminal interface."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from stenographer.cli.shared.config import with_config
from stenographer.lib.live.live_session import LiveSession
from stenographer.lib.live.models import LIVE_MODELS
from stenographer.lib.logging.pipeline import fmt_event, log_failure
from stenographer.lib.platform import current_platform

if TYPE_CHECKING:
    from stenographer.lib.config.models import Config

log = logging.getLogger(__name__)


def _run_app(session: LiveSession) -> None:
    from stenographer.cli.live.app import LiveApp

    LiveApp(session).run()


@with_config
def cmd_live(args: argparse.Namespace, cfg: Config) -> int:
    platform = current_platform()
    data_dir = platform.data_dir(os.environ, Path.home())
    model_dir = data_dir / "models" / "live"
    missing = [
        model.filename for model in LIVE_MODELS if not (model_dir / model.filename).is_file()
    ]
    if missing:
        print(
            "stenographer: live voice models are missing; run `stenographer model download --live` "
            f"(missing: {', '.join(missing)})",
            file=sys.stderr,
        )
        return 1

    session = LiveSession(
        cfg,
        mic=args.mic,
        system=args.system,
        device=args.device,
        diarize_mic=cfg.live.diarize_mic if args.diarize_mic is None else args.diarize_mic,
        platform=platform,
    )
    print("stenographer: loading model for live ASR...", flush=True)
    try:
        session.start()
    except Exception as exc:
        log_failure(log, logging.ERROR, "live: model_load_failed", exc, safe=True)
        print(f"stenographer: could not load live ASR model: {exc}", file=sys.stderr)
        session.stop()
        return 1

    log.info(fmt_event("live", "started", mic=int(args.mic), system=int(args.system)))
    try:
        _run_app(session)
    except KeyboardInterrupt:
        log.info(fmt_event("live", "interrupted"))
    finally:
        session.stop()
    relabel_error = getattr(session, "relabel_error", None)
    if relabel_error:
        print(f"stenographer: speaker relabel failed: {relabel_error}", file=sys.stderr)
    print(f"stenographer: session saved at {session.path}")
    return 0
