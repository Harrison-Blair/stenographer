# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit downloads of the pinned live audio models."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.request import urlopen

from stenographer.lib.live.errors import LiveDownloadError
from stenographer.lib.live.models import LIVE_MODELS, LiveModel

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


def _fetch(url: str, destination: Path) -> None:
    with urlopen(url, timeout=60) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_live_models(
    data_dir: Path,
    *,
    fetch: Callable[[str, Path], None] = _fetch,
    models: Sequence[LiveModel] = LIVE_MODELS,
) -> tuple[str, ...]:
    """Download missing models into ``data_dir/models/live`` and verify each hash."""
    model_dir = data_dir / "models" / "live"
    model_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[str] = []

    for model in models:
        destination = model_dir / model.filename
        if destination.exists():
            if _sha256(destination) != model.sha256:
                raise LiveDownloadError(
                    f"Live model {model.filename} is present with an incorrect SHA-256 hash. "
                    "Remove it and retry."
                )
            continue

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=model_dir,
                prefix=f".{model.filename}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temp_path = Path(temporary.name)
            fetch(model.url, temp_path)
            if _sha256(temp_path) != model.sha256:
                raise LiveDownloadError(
                    f"Downloaded live model {model.filename} failed its SHA-256 check."
                )
            os.replace(temp_path, destination)
            downloaded.append(model.filename)
        except LiveDownloadError:
            raise
        except Exception as exc:
            raise LiveDownloadError(
                f"Could not download live model {model.filename}: {exc}"
            ) from exc
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    return tuple(downloaded)
