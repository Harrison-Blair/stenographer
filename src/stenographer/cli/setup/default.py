# SPDX-License-Identifier: GPL-3.0-or-later
"""Write defaults without interactive prompts."""

from __future__ import annotations

from typing import TextIO

from stenographer.cli.shared.terminal import open_console, report_save
from stenographer.lib.config.document import ConfigDocument
from stenographer.lib.config.errors import ConfigPersistenceError
from stenographer.lib.config.models import Config


def write_default(
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Write the annotated default configuration, prompting for nothing.

    No terminal gate: nothing is asked. An existing file is replaced through
    the same preservation layer the wizard saves with, so it is backed up
    first and identical bytes are never rewritten.
    """

    from stenographer.lib.config.paths import resolve_config_path

    console = open_console(None, stdout, stderr)
    path = resolve_config_path(create_parent=False)
    try:
        result = ConfigDocument.defaults(path).save(Config.defaults())
    except ConfigPersistenceError as exc:
        console.error(str(exc))
        return 1
    report_save(
        console,
        result,
        saved_prefix="Wrote the default configuration to",
        unchanged_message=f"{result.path} already matches the defaults; no file was written.",
    )
    return 0
