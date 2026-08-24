# SPDX-License-Identifier: GPL-3.0-or-later
"""``stenographer model download``: fetch the ASR model into the cache."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from stenographer.cli.commands import with_config

if TYPE_CHECKING:
    from stenographer.config import Config


@with_config
def cmd_model_download(args: argparse.Namespace, cfg: Config) -> int:
    from stenographer.transcribe import model

    model.download_model(cfg.asr.model)
    print(f"stenographer: downloaded {cfg.asr.model}")
    return 0
