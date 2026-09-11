# SPDX-License-Identifier: GPL-3.0-or-later
"""Combine required host capabilities and optional display availability."""

from dataclasses import fields

from stenographer.cli.shared.capabilities import Capabilities
from stenographer.lib.diagnostics.capabilities import probe as probe_core
from stenographer.overlay.capabilities.probe import probe_overlay


def probe(cfg) -> Capabilities:
    """Collect independent library and overlay results for terminal workflows."""
    core = probe_core(cfg)
    return Capabilities(
        **{field.name: getattr(core, field.name) for field in fields(core)},
        overlay=probe_overlay(cfg.feedback.overlay),
    )
