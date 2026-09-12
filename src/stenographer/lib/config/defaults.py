# SPDX-License-Identifier: GPL-3.0-or-later
"""Render the annotated default document with host guidance."""

from __future__ import annotations

from stenographer.lib.config.constants import DEFAULT_SOUND_PACK
from stenographer.lib.refine.prompt import DEFAULT_MODEL as DEFAULT_REFINE_MODEL


def default_toml() -> str:
    """The annotated default config, with the host's ``hotkey.device`` comment.

    The template is the data file ``assets/default_config.toml.in`` (the
    ``.in`` suffix marks it as a ``str.format`` template, not loadable TOML),
    read at write time rather than at import: what a hotkey device *is*
    differs per host, so the ``{hotkey_device_comment}`` placeholder comes
    from ``HostGuidance`` and the core never spells a device-node
    convention; ``{sound_pack}`` is ``DEFAULT_SOUND_PACK``, and the two
    ``{refine_*}`` placeholders keep the template and :class:`RefineConfig`
    from drifting apart when the benchmark picks a different default model.
    """

    from importlib.resources import files

    from stenographer.lib.config.models import RefineConfig
    from stenographer.lib.platform import current_platform

    template = files("stenographer").joinpath("assets", "default_config.toml.in")
    return template.read_text(encoding="utf-8").format(
        hotkey_device_comment=current_platform().guidance().hotkey_device_comment,
        sound_pack=DEFAULT_SOUND_PACK,
        refine_host=RefineConfig().host,
        refine_model=DEFAULT_REFINE_MODEL,
    )
