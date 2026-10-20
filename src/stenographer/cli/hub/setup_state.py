# SPDX-License-Identifier: GPL-3.0-or-later
"""State transitions for the hub setup wizard."""

from __future__ import annotations

from stenographer.cli.hub.setup_wizard import SETUP_STEPS, SetupStep


class SetupWizard:
    """Track the selected setup step and the optional three-step quick path."""

    def __init__(self) -> None:
        self.index = 0
        self.quick = False
        self.finished = False
        self.completed: set[str] = set()
        self.skipped: set[str] = set()
        self.last_test = ""

    @property
    def steps(self) -> tuple[SetupStep, ...]:
        return SETUP_STEPS

    @property
    def step(self) -> SetupStep:
        return SETUP_STEPS[self.index]

    @property
    def will_finish(self) -> bool:
        return self.index == (2 if self.quick else len(SETUP_STEPS) - 1)

    def next(self) -> None:
        self._advance(skipped=False)

    def skip(self) -> None:
        self._advance(skipped=True)

    def back(self) -> None:
        if self.index:
            self.index -= 1
            self.finished = False
        self.last_test = ""

    def start_quick(self) -> None:
        self.quick = True
        self.index = 0
        self.finished = False
        self.completed.clear()
        self.skipped.clear()
        self.last_test = ""

    def record_test(self, result: str) -> None:
        self.last_test = result

    def _advance(self, *, skipped: bool) -> None:
        if self.finished:
            return
        step = self.step
        if skipped:
            self.skipped.add(step.step_id)
        else:
            self.completed.add(step.step_id)
        last_index = 2 if self.quick else len(SETUP_STEPS) - 1
        if self.index == last_index:
            self.finished = True
        else:
            self.index += 1
        self.last_test = ""
