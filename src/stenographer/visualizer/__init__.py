# SPDX-License-Identifier: GPL-3.0-or-later
"""Wayland status overlay and microphone spectrum analysis.

The daemon-side :class:`StatusIndicator` owns a small helper process that
renders GTK4 on the layer shell. Audio callback work is limited to copying the
latest mono block into a one-slot queue; FFT analysis and GUI IPC happen on a
dedicated worker thread. If GTK, layer shell, or Wayland is unavailable, the
existing Freedesktop notification backend remains fully functional.
"""

from stenographer.visualizer.indicator import StatusIndicator
from stenographer.visualizer.overlay_app import run_overlay_process

__all__ = ["StatusIndicator", "run_overlay_process"]
