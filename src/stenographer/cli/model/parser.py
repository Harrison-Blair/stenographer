# SPDX-License-Identifier: GPL-3.0-or-later
"""Register model arguments without runtime dependencies."""

from stenographer.cli.commands.spec import CommandSpec

MODEL_COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec(
        "download",
        handler_module="stenographer.cli.model.download.handler",
        handler_name="cmd_model_download",
        help="Download the ASR model into the cache.",
    ),
)


def register(subparsers) -> None:
    model = subparsers.add_parser("model", help="Manage the ASR model.")
    model_sub = model.add_subparsers(dest="model_command", required=True)
    for spec in MODEL_COMMANDS:
        spec.register(model_sub)
