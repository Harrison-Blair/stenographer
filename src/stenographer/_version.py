# SPDX-License-Identifier: GPL-3.0-or-later
"""Generated release build version; release tags remain authoritative."""

# Source and editable checkouts use an explicit non-release placeholder. The
# release workflow replaces this file in each build job with its tag-derived
# version before installing or packaging Stenographer.
__version__ = "0.0.0+source"
