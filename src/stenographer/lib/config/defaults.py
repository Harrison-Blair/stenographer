# SPDX-License-Identifier: GPL-3.0-or-later
"""Render the annotated default document with host guidance."""

from __future__ import annotations


def default_toml() -> str:
    """The annotated default config.

    The template is the data file ``assets/default_config.toml.in``, read at
    write time rather than at import.
    """

    from importlib.resources import files

    template = files("stenographer").joinpath("assets", "default_config.toml.in")
    return template.read_text(encoding="utf-8")
