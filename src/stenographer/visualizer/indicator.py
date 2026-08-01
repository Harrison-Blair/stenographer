# SPDX-License-Identifier: GPL-3.0-or-later
"""Status HUD that prefers the overlay and falls back to notifications."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from stenographer.notification import DesktopNotification
from stenographer.visualizer.overlay_client import LayerShellOverlay
from stenographer.visualizer.spectrum import SpectrumAnalyzer

if TYPE_CHECKING:
    import pathlib

    import numpy as np

    from stenographer.config import VisualizerConfig
    from stenographer.live import Preview


class StatusIndicator:
    """Prefer the spectrum overlay and transparently fall back to notify-send."""

    def __init__(
        self,
        *,
        cfg: VisualizerConfig,
        icon_path: pathlib.Path | None = None,
        font_path: pathlib.Path | None = None,
    ) -> None:
        self._desktop = DesktopNotification(icon_path=icon_path)
        self._state_lock = threading.RLock()
        self._desktop_visible = False
        self._fallback_show: Callable[[], None] | None = None
        self._fallback_replayed = False
        self._closed = False
        self._analyzer = SpectrumAnalyzer(
            band_count=cfg.frequency_bands,
            min_frequency=cfg.min_frequency,
            max_frequency=cfg.max_frequency,
            on_levels=self._show_levels,
        )
        self._overlay = (
            LayerShellOverlay(
                cfg,
                icon_path=icon_path,
                font_path=font_path,
                on_unavailable=self._overlay_unavailable,
            )
            if cfg.enabled
            else None
        )

    @staticmethod
    def overlay_probe() -> bool:
        return LayerShellOverlay.probe()

    def show_startup(self, binding: str) -> None:
        with self._state_lock:
            self._show_overlay_or_desktop(
                "ready",
                5000,
                lambda: self._desktop.show_startup(binding),
            )

    def show_listening(self) -> None:
        with self._state_lock:
            shown = self._show_overlay_or_desktop(
                "listening",
                0,
                self._desktop.show_listening,
            )
            self._analyzer.set_active(shown)

    def show_transcribing(self) -> None:
        with self._state_lock:
            self._analyzer.set_active(False)
            self._show_overlay_or_desktop(
                "transcribing",
                0,
                self._desktop.show_transcribing,
            )

    def show_model_loading(self) -> None:
        with self._state_lock:
            shown = self._show_overlay_or_desktop(
                "loading",
                0,
                self._desktop.show_model_loading,
            )
            self._analyzer.set_active(shown)

    def show_model_unloaded(self) -> None:
        with self._state_lock:
            self._analyzer.set_active(False)
            self._show_overlay_or_desktop(
                "unloaded",
                5000,
                self._desktop.show_model_unloaded,
            )

    def show_update_available(self, version: str) -> None:
        with self._state_lock:
            self._analyzer.set_active(False)
            self._show_overlay_or_desktop(
                "update_available",
                10000,
                lambda: self._desktop.show_update_available(version),
                label=f"Release v{version} available",
            )

    def publish_audio(self, samples: np.ndarray, sample_rate: int) -> None:
        self._analyzer.submit(samples, sample_rate)

    def show_preview(self, preview: Preview) -> None:
        """Update only the GTK overlay; transcript text is never notified."""
        if self._overlay is not None:
            self._overlay.show_preview(preview)

    def clear_preview(self) -> None:
        if self._overlay is not None:
            self._overlay.clear_preview()

    def hide(self) -> None:
        with self._state_lock:
            self._fallback_show = None
            self._fallback_replayed = False
            self._analyzer.set_active(False)
            if self._overlay is not None:
                self._overlay.hide()
            if self._desktop_visible:
                self._desktop.hide()
                self._desktop_visible = False

    def flush(self, timeout: float = 5.0) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            self._fallback_show = None
        self._analyzer.close()
        if self._overlay is not None:
            self._overlay.close()
        self._desktop.flush(timeout=timeout)

    def _show_levels(self, levels: list[float]) -> None:
        if self._overlay is not None:
            self._overlay.show_levels(levels)

    def _show_overlay_or_desktop(
        self,
        state: str,
        timeout_ms: int,
        desktop_show: Callable[[], None],
        *,
        label: str | None = None,
    ) -> bool:
        self._fallback_show = desktop_show
        self._fallback_replayed = False
        if self._overlay is not None and self._overlay.show_state(
            state,
            timeout_ms=timeout_ms,
            label=label,
        ):
            if self._desktop_visible:
                self._desktop.hide()
                self._desktop_visible = False
            return True
        if not self._fallback_replayed:
            desktop_show()
        self._desktop_visible = True
        return False

    def _overlay_unavailable(self) -> None:
        """Replay the latest state if asynchronous overlay startup/I/O fails."""
        with self._state_lock:
            if self._closed or self._fallback_show is None or self._fallback_replayed:
                return
            self._analyzer.set_active(False)
            self._fallback_show()
            self._fallback_replayed = True
            self._desktop_visible = True
