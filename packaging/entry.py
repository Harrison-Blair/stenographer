# SPDX-License-Identifier: GPL-3.0-or-later
"""PyInstaller entry stub.

The spec points here instead of at ``src/stenographer/cli`` on purpose:
importing the package keeps the real modules under
``_internal/stenographer/``, so package-anchored asset resolution in
``delivery/feedback.py`` works frozen without any ``sys._MEIPASS``
special-casing.
"""

import sys

if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    from stenographer.cli import main

    sys.exit(main())
