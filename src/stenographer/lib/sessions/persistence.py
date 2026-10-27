# SPDX-License-Identifier: GPL-3.0-or-later
"""Write private session files by atomic replacement."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path


def atomic_write_private(path: Path, content: bytes) -> None:
    temporary: Path | None = None
    try:
        fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary = Path(name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
        temporary = None
    except OSError as exc:
        raise OSError(f"cannot write private file {path}: {exc}") from exc
    finally:
        if temporary is not None:
            with contextlib.suppress(OSError):
                temporary.unlink()


def write_private_temporary(directory: Path, name: str, content: bytes) -> Path:
    """Write content to a private temporary file in directory and return its path."""
    fd, temporary_name = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=directory)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o600)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary
