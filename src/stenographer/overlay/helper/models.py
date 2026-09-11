# SPDX-License-Identifier: GPL-3.0-or-later
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class HelperControlState:
    ready: bool = False
    unavailable: bool = False
    lost: bool = False

    @property
    def expected_exit(self) -> bool:
        return self.unavailable


@dataclass(frozen=True)
class HelperControlTransition:
    state: HelperControlState
    event: Literal["ready", "unavailable", "backend_lost"]
    value: str
    stop: bool = False
