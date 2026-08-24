# SPDX-License-Identifier: GPL-3.0-or-later
"""Linux overlay helper backends: layer-shell, XWayland, vendored protocols.

Stdlib-only and importable on every OS: the modules inside pull in PyWayland or
python-xlib, so they are reached lazily through
``stenographer.platform.linux.overlay.overlay_backends()`` and never imported
here.
"""
