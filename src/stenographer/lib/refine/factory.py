# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn one ``[stenographer.refine]`` section into the refiner to use."""

from __future__ import annotations

from typing import TYPE_CHECKING

from stenographer.lib.refine.ollama_refiner import OllamaRefiner

if TYPE_CHECKING:
    from collections.abc import Callable

    from stenographer.lib.config.models import RefineConfig

#: Shorter utterances are delivered without a refine.
MIN_WORDS = 10


def build_refiner(
    cfg: RefineConfig,
    *,
    idle_unload_seconds: int,
    enabled: bool | None = None,
    on_model_loading: Callable[[], None] | None = None,
    on_model_loading_finished: Callable[[], None] | None = None,
) -> OllamaRefiner | None:
    """Build the configured refiner.

    *enabled* overrides ``cfg.enabled`` for the one caller that opts in per
    invocation (``transcribe --refine``), which deliberately does not inherit
    the daemon's setting.
    """

    active = cfg.enabled if enabled is None else enabled
    if not active or not cfg.model.strip() or not cfg.host.strip():
        return None
    return OllamaRefiner(
        host=cfg.host,
        model=cfg.model,
        min_words=MIN_WORDS,
        keep_alive=-1 if idle_unload_seconds <= 0 else int(idle_unload_seconds),
        vocabulary=cfg.vocabulary,
        on_model_loading=on_model_loading,
        on_model_loading_finished=on_model_loading_finished,
    )
