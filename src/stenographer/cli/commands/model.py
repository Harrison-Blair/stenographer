# SPDX-License-Identifier: GPL-3.0-or-later
"""``stenographer model download``: fetch the ASR model into the cache."""

from __future__ import annotations

import argparse

from stenographer.cli import _fatal


def cmd_model_download(args: argparse.Namespace) -> int:
    from stenographer import config
    from stenographer.transcribe import model

    try:
        cfg = config.load_or_default()
    except config.ConfigError as exc:
        return _fatal(str(exc))

    model.download_model(cfg.asr.model)
    print(f"stenographer: downloaded {cfg.asr.model}")
    return 0
