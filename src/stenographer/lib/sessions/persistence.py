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
