# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline model-cache probes and explicit model downloads."""

from __future__ import annotations


def is_model_cached(model_id: str) -> bool:
    """True if the model's ``config.json`` is in the local HF cache (no network).

    Delegate cache layout and environment resolution to huggingface_hub so this
    stays aligned with model loading and ``snapshot_download``.
    """
    from huggingface_hub import try_to_load_from_cache

    cached = try_to_load_from_cache(model_id, "config.json")
    return isinstance(cached, str)


def download_model(model_id: str) -> None:
    """Fetch the model into the local HF cache using the fixed allow-list."""
    from huggingface_hub import snapshot_download

    snapshot_download(
        model_id,
        allow_patterns=[
            "*.json",
            "model.bin",
            "tokenizer.json",
            "vocabulary.*",
            "preprocessor_config.json",
        ],
    )
