# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
import time
from dataclasses import replace
from typing import TYPE_CHECKING

from stenographer.lib.logging.pipeline import (
    fmt_event,
    log_failure,
    set_utterance,
)

if TYPE_CHECKING:
    from stenographer.lib.config.models import AsrConfig

log = logging.getLogger(__name__)


_JOIN_SECONDS = 2.0


def _child_main(cfg: AsrConfig, request_q, response_q, log_q, log_level: int) -> None:
    """Spawn entry (module-level, picklable). Load and decode one request at a
    time, staying healthy after a caught error. The model is built lazily on the
    first load request so the child inherits the local-cache-only load."""
    from stenographer.lib.logging.pipeline import configure_worker_logging
    from stenographer.lib.transcribe.model import Model
    from stenographer.lib.transcribe.worker_policy import classify_error, error_is_safe_to_render

    configure_worker_logging(log_q, log_level)
    model = None
    while True:
        message = request_q.get()
        if message[0] == "stop":
            return
        # Every request carries the parent's utterance id so the child's own
        # ``asr:`` lines interleave with the daemon's under the same utt=N.
        set_utterance(message[-1])
        if message[0] == "load":
            try:
                if model is None:
                    model = Model(cfg)
            except Exception as exc:
                # A model-load failure names paths and library complaints, not
                # anything derived from audio: its text may be rendered.
                log_failure(
                    log, logging.ERROR, "asr: job_failed", exc, safe=True, phase="model_load"
                )
                kind, detail = classify_error(exc)
                response_q.put(("error", kind, detail))
                continue
            log.info(
                fmt_event(
                    "worker",
                    "child_started",
                    model=cfg.model,
                    compute_type=cfg.compute_type,
                    cpu_threads=model.cpu_threads,
                )
            )
            response_q.put(("model_ready",))
            continue

        phase = "decode"
        try:
            if model is None:
                raise RuntimeError("decode requested before model load")
            samples = message[1]
            inference_started_at = time.perf_counter()
            result = model.transcribe(samples)
            result = replace(
                result, inference_ms=(time.perf_counter() - inference_started_at) * 1000
            )
        except Exception as exc:
            # Report and stay alive; native segfaults are handled by the parent
            # liveness poll, not here.
            log_failure(
                log,
                logging.ERROR,
                "asr: job_failed",
                exc,
                safe=error_is_safe_to_render(exc),
                phase=phase,
            )
            kind, detail = classify_error(exc)
            response_q.put(("error", kind, detail))
            continue
        response_q.put(("ok", result))
