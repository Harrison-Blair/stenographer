# SPDX-License-Identifier: GPL-3.0-or-later
"""Private child-mode entry point for the GTK overlay helper process."""

import sys

from stenographer.visualizer.overlay_app import run_overlay_process

if __name__ == "__main__":
    if sys.argv[1:] == ["--child"]:
        raise SystemExit(run_overlay_process())
    raise SystemExit("stenographer.visualizer is an internal module")
