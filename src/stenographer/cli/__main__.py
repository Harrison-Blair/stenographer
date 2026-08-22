# SPDX-License-Identifier: GPL-3.0-or-later
"""Module-execution shim: ``python -m stenographer.cli`` (incl. the private _overlay re-exec)."""

import sys

from stenographer.cli import main

if __name__ == "__main__":
    sys.exit(main())
