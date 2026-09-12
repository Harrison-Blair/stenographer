# SPDX-License-Identifier: GPL-3.0-or-later
"""The benchmark's prompt constants are the implementation's, verbatim.

``scripts/refine_bench.py`` is where a prompt change is measured, and
``stenographer.lib.refine.prompt`` is where the measured result is shipped.
The prompt module says the two must stay identical; editing either alone
silently un-tunes the feature, so this is the check that catches it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from stenographer.lib.refine.prompt import FEW_SHOT_EXAMPLES, SYSTEM_PROMPT

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "refine_bench.py"


def _load_bench():
    spec = importlib.util.spec_from_file_location("refine_bench", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_system_prompt_is_shipped_verbatim():
    assert _load_bench().SYSTEM_PROMPT == SYSTEM_PROMPT


def test_the_few_shot_examples_are_shipped_verbatim():
    assert _load_bench().FEW_SHOT == FEW_SHOT_EXAMPLES
