# SPDX-License-Identifier: GPL-3.0-or-later
"""Ordered table of public subcommands; order here is help order."""

from __future__ import annotations

from collections.abc import Iterable

from stenographer.cli.commands.spec import CommandSpec

COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec(
        "run",
        handler_module="stenographer.cli.run.handler",
        handler_name="cmd_run",
        help="Run the dictation daemon.",
    ),
    CommandSpec(
        "transcribe",
        handler_module="stenographer.cli.transcribe.handler",
        handler_name="cmd_transcribe",
        parser_module="stenographer.cli.transcribe.parser",
    ),
    CommandSpec(
        "model",
        handler_module="stenographer.cli.model.handler",
        handler_name="cmd_model",
        parser_module="stenographer.cli.model.parser",
    ),
    CommandSpec(
        "doctor",
        handler_module="stenographer.cli.doctor.handler",
        handler_name="cmd_doctor",
        help="Probe required capabilities.",
    ),
    CommandSpec(
        "devices",
        handler_module="stenographer.cli.devices.handler",
        handler_name="cmd_devices",
        help="List audio input devices.",
    ),
    CommandSpec(
        "setup",
        handler_module="stenographer.cli.setup.handler",
        handler_name="cmd_setup",
        parser_module="stenographer.cli.setup.parser",
    ),
    CommandSpec(
        "sounds",
        handler_module="stenographer.cli.sounds.handler",
        handler_name="cmd_sounds",
        parser_module="stenographer.cli.sounds.parser",
    ),
    CommandSpec(
        "completion",
        handler_module="stenographer.cli.completion.handler",
        handler_name="cmd_completion",
        parser_module="stenographer.cli.completion.parser",
    ),
    CommandSpec(
        "stats",
        handler_module="stenographer.cli.stats.handler",
        handler_name="cmd_stats",
        parser_module="stenographer.cli.stats.parser",
    ),
)


def resolve_command(specs: Iterable[CommandSpec], name: str) -> CommandSpec:
    """Return the spec named ``name`` or raise ``LookupError``.

    argparse already rejects names outside its ``choices``, so a miss here
    means the table and the parser disagree — a programming error worth a
    loud failure rather than a silent fallback.
    """
    for spec in specs:
        if spec.name == name:
            return spec
    raise LookupError(f"no registered command named {name!r}")
