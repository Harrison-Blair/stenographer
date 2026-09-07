# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent optional desktop launcher. Importing this module does not load Qt."""

from __future__ import annotations


def main(argv: list[str] | None = None) -> int:
    import argparse
    import logging
    import os
    from logging.handlers import RotatingFileHandler
    from pathlib import Path

    from stenographer.config import resolve_config_path
    from stenographer.platform import current_platform

    parser = argparse.ArgumentParser(prog="stenographer-ui", description="Stenographer desktop")
    parser.add_argument("--config", type=Path, help="configuration file")
    parser.add_argument("--database", type=Path, help="analytics database")
    parser.add_argument(
        "--smoke-test", action="store_true", help="render and verify with temporary data"
    )
    args = parser.parse_args(argv)
    try:
        from stenographer_desktop.app import run
    except ImportError as exc:
        if exc.name and exc.name.startswith("PySide6"):
            parser.exit(78, "Desktop dependencies unavailable; install stenographer[desktop].\n")
        raise
    if args.smoke_test:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory(prefix="stenographer-desktop-") as temporary:
            root = Path(temporary)
            return run(root / "config.toml", root / "analytics.sqlite3", smoke=True)
    state = current_platform().state_dir(os.environ, Path.home())
    state.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(state / "desktop.log", maxBytes=1048576, backupCount=1)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger = logging.getLogger("stenographer_desktop")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.info("desktop: started")
    try:
        return run(args.config or resolve_config_path(create_parent=False), args.database)
    finally:
        logger.info("desktop: stopped")
        handler.close()
        logger.removeHandler(handler)
