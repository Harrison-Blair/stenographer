# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent native desktop launcher."""

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from stenographer_desktop import main

    sys.exit(main())
