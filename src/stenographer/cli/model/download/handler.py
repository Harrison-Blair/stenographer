# SPDX-License-Identifier: GPL-3.0-or-later
"""``stenographer model download``: fetch the ASR model, the refine model, or both.

Two models, two very different transports: the ASR weights come from the
Hugging Face cache API, and the refine model is pulled by the local Ollama
server through its own ``/api/pull``. Both stay explicit — nothing here runs
without the user having typed this command, and the no-flag form additionally
states the sizes and asks before it starts, when refine is enabled and there
is a terminal to ask on.

``--asr`` and ``--refine`` select one. With neither flag, only the ASR model
is fetched when there is no terminal to prompt on, or when refine has been
explicitly turned off (``refine.enabled = false``), so an existing script —
or a user who opted out of refine — keeps doing exactly what it did before.
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from stenographer.cli.shared.config import with_config

if TYPE_CHECKING:
    from stenographer.lib.config.models import Config

#: What the ASR default weighs; the cache API cannot say before downloading.
ASR_SIZE_TEXT = "about 1.6 GB"

#: Shown when the combined offer is declined, so saying no to both is not a
#: dead end for someone who only wanted one of them.
DECLINED_HINT = (
    "Run `stenographer model download --asr` or "
    "`stenographer model download --refine` to fetch just one."
)

_BYTES_PER_GB = 1000**3

#: How :func:`size_phrase` opens when the pull would cost nothing.
_INSTALLED_PREFIX = "already installed"


def size_phrase(installed_bytes: int | None, approximate_gb: float | None) -> str:
    """Describe a pull's cost from what is actually known about it. PURE.

    Ollama's own reported size wins when the model is already there (the pull
    then costs nothing); otherwise the project's table for a model it names;
    otherwise an honest refusal to guess.
    """

    if installed_bytes is not None:
        return f"{_INSTALLED_PREFIX}, {installed_bytes / _BYTES_PER_GB:.1f} GB"
    if approximate_gb is not None:
        return f"about {approximate_gb:.1f} GB"
    return "size unknown"


def refine_size_phrase(cfg: Config) -> str:
    """Size the refine pull, asking the configured Ollama host first."""

    from stenographer.lib.refine.client import installed_model_bytes
    from stenographer.lib.refine.prompt import APPROXIMATE_MODEL_SIZES_GB

    return size_phrase(
        installed_model_bytes(cfg.refine.host, cfg.refine.model),
        APPROXIMATE_MODEL_SIZES_GB.get(cfg.refine.model),
    )


def plan_lines(cfg: Config, *, asr: bool, refine: bool, refine_size: str | None) -> list[str]:
    """Render what the command is about to do, with sizes. PURE.

    A model Ollama already has costs nothing to "pull", so it is listed as a
    check rather than under a download heading: telling someone a 7 GB download
    is about to start when it is not is how a confirm prompt stops being read.
    """

    lines: list[str] = []
    if asr:
        lines.append(f"download the ASR model {cfg.asr.model} ({ASR_SIZE_TEXT})")
    if refine:
        size = refine_size or "size unknown"
        verb = "verify" if size.startswith(_INSTALLED_PREFIX) else "download"
        lines.append(f"{verb} the refine model {cfg.refine.model} ({size}) via {cfg.refine.host}")
    return lines


def selection(
    args: argparse.Namespace, *, interactive: bool, refine_enabled: bool
) -> tuple[bool, bool]:
    """Decide which models this invocation covers. PURE.

    Neither flag means "both" only where there is a terminal to confirm on and
    refine has not been explicitly turned off; a piped or scripted run keeps
    the historical ASR-only behaviour rather than silently starting a second
    multi-gigabyte download, and an explicit `refine.enabled = false` is
    respected the same way. An explicit `--refine` flag still forces the pull
    regardless of `refine.enabled` — it is a deliberate opt-in.
    """

    asr = bool(getattr(args, "asr", False))
    refine = bool(getattr(args, "refine", False))
    if asr or refine:
        return asr, refine
    return True, interactive and refine_enabled


def _download_asr(cfg: Config) -> int:
    from stenographer.lib.transcribe import download as model

    model.download_model(cfg.asr.model)
    print(f"stenographer: downloaded {cfg.asr.model}")
    return 0


def _pull_refine(cfg: Config) -> int:
    from stenographer.lib.refine.client import pull_model
    from stenographer.lib.refine.errors import RefineError

    def report(line: str) -> None:
        print(f"stenographer: {cfg.refine.model}: {line}")

    try:
        pull_model(cfg.refine.host, cfg.refine.model, on_progress=report)
    except RefineError as exc:
        print(f"stenographer: could not pull {cfg.refine.model}: {exc}", file=sys.stderr)
        return 1
    print(f"stenographer: pulled {cfg.refine.model}")
    return 0


@with_config
def cmd_model_download(args: argparse.Namespace, cfg: Config) -> int:
    from stenographer.cli.shared.terminal import ask_yes_no, open_console

    console = open_console(None, None, None)
    asr, refine = selection(
        args, interactive=console.interactive, refine_enabled=cfg.refine.enabled
    )
    explicit = bool(getattr(args, "asr", False) or getattr(args, "refine", False))
    if not explicit:
        lines = plan_lines(
            cfg,
            asr=asr,
            refine=refine,
            refine_size=refine_size_phrase(cfg) if refine else None,
        )
        if refine:
            console.write("stenographer will:")
            for line in lines:
                console.write(f"  - {line}")
            try:
                # Default to declining: a multi-gigabyte download must never be
                # one stray Enter away from starting.
                if not ask_yes_no(console, "Continue?", default=False):
                    console.write("Nothing was downloaded.")
                    console.write(DECLINED_HINT)
                    return 0
            except (EOFError, KeyboardInterrupt):
                console.write()
                console.error("download cancelled")
                return 130
    failures = 0
    if asr:
        failures += _download_asr(cfg)
    if refine:
        failures += _pull_refine(cfg)
    return 1 if failures else 0
