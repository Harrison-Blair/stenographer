# SPDX-License-Identifier: GPL-3.0-or-later
"""Register model arguments without runtime dependencies."""

from stenographer.cli.commands.spec import CommandSpec

MODEL_COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec(
        "download",
        handler_module="stenographer.cli.model.download.handler",
        handler_name="cmd_model_download",
        parser_module="stenographer.cli.model.download.parser",
    ),
)


def register(subparsers) -> None:
    model = subparsers.add_parser("model", help="Manage the ASR and refine models.")
    model_sub = model.add_subparsers(dest="model_command", required=True)
    for spec in MODEL_COMMANDS:
        spec.register(model_sub)
