# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn one ``[stenographer.refine]`` section into the refiner to use.

The one place that knows a disabled stage is a :class:`NullRefiner` rather than
``None``, so the daemon, ``transcribe --refine``, and any future caller cannot
disagree about it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from stenographer.lib.refine.null_refiner import NullRefiner
from stenographer.lib.refine.ollama_refiner import OllamaRefiner
from stenographer.lib.refine.policy import keep_alive_for

if TYPE_CHECKING:
    from stenographer.lib.config.models import RefineConfig
    from stenographer.lib.refine.text_refiner import TextRefiner


def build_refiner(
    cfg: RefineConfig,
    *,
    idle_unload_seconds: int,
    enabled: bool | None = None,
) -> TextRefiner:
    """Build the configured refiner.

    *enabled* overrides ``cfg.enabled`` for the one caller that opts in per
    invocation (``transcribe --refine``), which deliberately does not inherit
    the daemon's setting.
    """

    active = cfg.enabled if enabled is None else enabled
    if not active or not cfg.model.strip() or not cfg.host.strip():
        return NullRefiner()
    return OllamaRefiner(
        host=cfg.host,
        model=cfg.model,
        min_words=cfg.min_words,
        structured_output=cfg.structured_output,
        keep_alive=keep_alive_for(idle_unload_seconds),
    )
