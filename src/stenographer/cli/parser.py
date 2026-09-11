# SPDX-License-Identifier: GPL-3.0-or-later
"""Root command parser; imports remain lightweight."""

import argparse

from stenographer._version import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.

    Pure: importable and callable with only the stdlib present. No ASR/audio
    imports happen here or at module scope — those belong inside the
    subcommand handlers.
    """
    parser = argparse.ArgumentParser(
        prog="stenographer",
        description="Local, offline push-to-talk dictation.",
    )
    parser.add_argument("--version", action="version", version=__version__)

    subparsers = parser.add_subparsers(dest="command", required=False)

    from stenographer.cli.completion.parser import register as register_completion
    from stenographer.cli.devices.parser import register as register_devices
    from stenographer.cli.doctor.parser import register as register_doctor
    from stenographer.cli.model.parser import register as register_model
    from stenographer.cli.run.parser import register as register_run
    from stenographer.cli.setup.parser import register as register_setup
    from stenographer.cli.sounds.parser import register as register_sounds
    from stenographer.cli.stats.parser import register as register_stats
    from stenographer.cli.transcribe.parser import register as register_transcribe

    register_run(subparsers)
    register_transcribe(subparsers)
    register_model(subparsers)
    register_doctor(subparsers)
    register_devices(subparsers)
    register_setup(subparsers)
    register_sounds(subparsers)
    register_completion(subparsers)
    register_stats(subparsers)
    return parser
