# SPDX-License-Identifier: GPL-3.0-or-later
"""Register model arguments without runtime dependencies."""


def register(subparsers) -> None:
    model = subparsers.add_parser("model", help="Manage the ASR model.")
    model_sub = model.add_subparsers(dest="model_command", required=True)
    from stenographer.cli.model.download.parser import register as register_download

    register_download(model_sub)
