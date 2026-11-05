# SPDX-License-Identifier: GPL-3.0-or-later
"""``stenographer model download``: fetch the ASR model, the refine model, or both.

Two models, two very different transports: the ASR model is built on this
machine from pinned source weights (``lib/transcribe/bark_download.py``), and
the refine model is pulled by the local Ollama server through its own
``/api/pull``. Both stay explicit — nothing here runs
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
from stenographer.lib.transcribe.bark_download import ASR_SIZE_TEXT, MODEL_NAME

if TYPE_CHECKING:
    from stenographer.lib.config.models import Config


#: Shown when the combined offer is declined, so saying no to both is not a
#: dead end for someone who only wanted one of them.
DECLINED_HINT = (
    "Run `stenographer model download --asr` or "
    "`stenographer model download --refine` to fetch just one."
)

_BYTES_PER_GB = 1000**3


def size_phrase(installed_bytes: int | None, approximate_gb: float | None) -> str:
    """Describe a pull's cost from what is actually known about it. PURE.

    Ollama's own reported size wins when the model is already there (the pull
    then costs nothing); otherwise the project's table for a model it names;
    otherwise an honest refusal to guess.
    """

    if installed_bytes is not None:
        return f"already installed, {installed_bytes / _BYTES_PER_GB:.1f} GB"
    if approximate_gb is not None:
        return f"about {approximate_gb:.1f} GB"
    return "size unknown"


def _download_asr() -> int:
    import os
    from pathlib import Path

    from stenographer.lib.live.download import download_live_models
    from stenographer.lib.live.errors import LiveDownloadError
    from stenographer.lib.live.models import VAD_MODEL
    from stenographer.lib.platform import current_platform
    from stenographer.lib.transcribe import bark_download
    from stenographer.lib.transcribe.errors import BarkDownloadError

    data_dir = current_platform().data_dir(os.environ, Path.home())
    try:
        built = bark_download.download_bark_pro(
            data_dir, on_step=lambda line: print(f"stenographer: {line}", flush=True)
        )
    except BarkDownloadError as exc:
        print(f"stenographer: could not install the ASR model: {exc}", file=sys.stderr)
        return 1
    status = "installed" if built else "already present"
    print(f"stenographer: ASR model {status} at {bark_download.model_dir(data_dir)}")
    print(f"stenographer: {bark_download.ATTRIBUTION}")

    vad = (VAD_MODEL,)
    try:
        downloaded = download_live_models(data_dir, models=vad)
    except LiveDownloadError as exc:
        print(f"stenographer: could not download the VAD model: {exc}", file=sys.stderr)
        return 1
    status = "downloaded" if downloaded else "already present"
    print(f"stenographer: VAD model {VAD_MODEL.filename} {status}")
    return 0


def _download_live() -> int:
    import os
    from pathlib import Path

    from stenographer.lib.live.download import download_live_models
    from stenographer.lib.live.errors import LiveDownloadError
    from stenographer.lib.live.models import LIVE_MODELS, live_model_dir
    from stenographer.lib.platform import current_platform

    data_dir = current_platform().data_dir(os.environ, Path.home())
    model_dir = live_model_dir(data_dir)
    print("stenographer: downloading live models...", flush=True)
    for model in LIVE_MODELS:
        try:
            downloaded = download_live_models(data_dir, models=(model,))
        except LiveDownloadError as exc:
            print(f"stenographer: could not download live models: {exc}", file=sys.stderr)
            return 1
        status = "downloaded" if downloaded else "already present"
        print(f"stenographer: live model {model.filename} {status} at {model_dir}", flush=True)
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
    live = args.live
    if live and _download_live():
        return 1
    explicit = live or args.asr or args.refine
    asr, refine = (
        (args.asr, args.refine) if explicit else (True, console.interactive and cfg.refine.enabled)
    )
    if not explicit and refine:
        from stenographer.lib.refine.client import installed_model_bytes
        from stenographer.lib.refine.prompt import APPROXIMATE_MODEL_SIZES_GB

        installed = installed_model_bytes(cfg.refine.host, cfg.refine.model)
        size = size_phrase(installed, APPROXIMATE_MODEL_SIZES_GB.get(cfg.refine.model))
        verb = "verify" if installed is not None else "download"
        console.write("stenographer will:")
        console.write(f"  - download and convert the ASR model {MODEL_NAME} ({ASR_SIZE_TEXT})")
        console.write(
            f"  - {verb} the refine model {cfg.refine.model} ({size}) via {cfg.refine.host}"
        )
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
        failures += _download_asr()
    if refine:
        failures += _pull_refine(cfg)
    return 1 if failures else 0
