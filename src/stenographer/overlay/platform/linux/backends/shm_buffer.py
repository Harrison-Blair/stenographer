# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import contextlib
import mmap
from dataclasses import dataclass


@dataclass(slots=True)
class _ShmBuffer:
    proxy: object
    mapping: mmap.mmap

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.proxy.destroy()
        with contextlib.suppress(BufferError, OSError):
            self.mapping.close()
