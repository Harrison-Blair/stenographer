# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import contextlib
import logging
import mmap
import os
import selectors

from pywayland import ffi
from pywayland.client import Display
from pywayland.protocol.wayland import WlCompositor, WlOutput, WlShm

from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.lib.logging.pipeline import fmt_event, log_failure
from stenographer.overlay.platform.linux.backends.base import DISPLAY_KEY
from stenographer.overlay.platform.linux.backends.errors import BackendUnavailableError
from stenographer.overlay.platform.linux.backends.global_removal import GlobalRemoval
from stenographer.overlay.platform.linux.backends.helper_backend import HelperBackend
from stenographer.overlay.platform.linux.backends.protocols.fractional_scale_v1 import (
    WpFractionalScaleManagerV1,
)
from stenographer.overlay.platform.linux.backends.protocols.viewporter import WpViewporter
from stenographer.overlay.platform.linux.backends.protocols.wlr_layer_shell_unstable_v1 import (
    ZwlrLayerShellV1,
    ZwlrLayerSurfaceV1,
)
from stenographer.overlay.platform.linux.backends.registry_inventory import RegistryInventory
from stenographer.overlay.platform.linux.backends.shm_buffer import _ShmBuffer
from stenographer.overlay.platform.linux.backends.wayland import (
    callback_is_current,
    choose_scale_plan,
    classify_global_removal,
    flush_wants_write,
)
from stenographer.overlay.platform.linux.backends.wayland_constants import (
    _MAX_IN_FLIGHT_BUFFERS,
    _OPTIONAL_GLOBALS,
    _OUTPUT_INTERFACE,
    log,
)
from stenographer.overlay.protocol.backend import Backend
from stenographer.overlay.protocol.unavailablereason import UnavailableReason
from stenographer.overlay.rendering.constants import CANVAS_HEIGHT, CANVAS_WIDTH
from stenographer.overlay.rendering.render import layer_margin_bottom, premultiplied_argb32


class LayerShellBackend(HelperBackend):
    """One-display, one-surface-at-a-time layer-shell client."""

    backend = Backend.LAYER_SHELL

    def __init__(self) -> None:
        super().__init__()
        if not os.environ.get("WAYLAND_DISPLAY"):
            raise BackendUnavailableError(UnavailableReason.NO_WAYLAND_DISPLAY)

        self._display = Display()
        try:
            self._display.connect()
        except Exception as exc:
            # ``from None`` on the wire: the parent gets the fixed reason only.
            log_failure(log, logging.INFO, "overlay_helper: wayland_connect_failed", exc, safe=True)
            raise BackendUnavailableError(UnavailableReason.WAYLAND_CONNECT_FAILED) from None

        self._inventory = RegistryInventory()
        self._registry = self._display.get_registry()
        self._registry.dispatcher["global"] = self._on_global
        self._registry.dispatcher["global_remove"] = self._on_global_remove
        self._initialized = False
        self._lost = False

        self._compositor = None
        self._compositor_version = 0
        self._shm = None
        self._layer_shell = None
        self._layer_shell_version = 0
        self._fractional_manager = None
        self._viewporter = None
        self._outputs: dict[int, tuple[object, int]] = {}
        self._output_scales: dict[object, int] = {}
        self._entered_outputs: set[object] = set()

        self._surface = None
        self._layer_surface = None
        self._fractional_scale = None
        self._viewport = None
        self._configured = False
        self._preferred_scale_120: int | None = None
        self._buffers: dict[int, _ShmBuffer] = {}
        self._render_pending = False

        try:
            self._roundtrip()
            missing = self._inventory.missing_required()
            if missing:
                log.info(
                    fmt_event(
                        "overlay_helper", "wayland_globals_missing", missing="|".join(missing)
                    )
                )
                raise BackendUnavailableError(UnavailableReason.REQUIRED_GLOBALS_MISSING)
            self._bind_globals()
            self._initialized = True
            self._roundtrip()
        except BackendUnavailableError:
            self.close()
            raise
        except Exception as exc:
            self.close()
            log_failure(log, logging.INFO, "overlay_helper: wayland_setup_failed", exc, safe=True)
            raise BackendUnavailableError(UnavailableReason.WAYLAND_CONNECT_FAILED) from None

    def _on_global(self, _registry, name: int, interface: str, version: int) -> None:
        self._inventory.add(name, interface, version)
        if self._initialized and interface == _OUTPUT_INTERFACE:
            self._bind_output(name, version)

    def _on_global_remove(self, _registry, name: int) -> None:
        item = self._inventory.remove(name)
        removal = classify_global_removal(None if item is None else item.interface)
        if removal is GlobalRemoval.LOST:
            log.info(fmt_event("overlay_helper", "display_lost", at="global_remove"))
            self._lost = True
            return
        if removal is not GlobalRemoval.OUTPUT:
            return
        assert item is not None
        output_entry = self._outputs.pop(item.name, None)
        if output_entry is None:
            return
        output, bound_version = output_entry
        was_entered = output in self._entered_outputs
        self._entered_outputs.discard(output)
        self._output_scales.pop(output, None)
        self._release_output(output, bound_version)
        if was_entered and self._visible:
            try:
                state = self._state
                self._destroy_surface()
                self._create_surface(state)
            except Exception as exc:
                self._display_lost(exc, "output_removed")

    def _bind_globals(self) -> None:
        compositor = self._inventory.get("wl_compositor")
        shm = self._inventory.get("wl_shm")
        layer_shell = self._inventory.get("zwlr_layer_shell_v1")
        assert compositor is not None and shm is not None and layer_shell is not None
        self._compositor_version = min(compositor.version, 4)
        self._compositor = self._registry.bind(
            compositor.name, WlCompositor, self._compositor_version
        )
        self._shm = self._registry.bind(shm.name, WlShm, 1)
        self._layer_shell_version = min(layer_shell.version, 5)
        self._layer_shell = self._registry.bind(
            layer_shell.name, ZwlrLayerShellV1, self._layer_shell_version
        )

        fractional = self._inventory.get(_OPTIONAL_GLOBALS[0])
        viewporter = self._inventory.get(_OPTIONAL_GLOBALS[1])
        if fractional is not None and viewporter is not None:
            self._fractional_manager = self._registry.bind(
                fractional.name, WpFractionalScaleManagerV1, 1
            )
            self._viewporter = self._registry.bind(viewporter.name, WpViewporter, 1)

        for item in self._inventory.values():
            if item.interface == _OUTPUT_INTERFACE:
                self._bind_output(item.name, item.version)

    def _bind_output(self, name: int, advertised_version: int) -> None:
        if name in self._outputs:
            return
        bound_version = min(advertised_version, 3)
        output = self._registry.bind(name, WlOutput, bound_version)
        output.dispatcher["scale"] = self._on_output_scale
        self._outputs[name] = output, bound_version
        self._output_scales[output] = 1

    def _roundtrip(self) -> None:
        if self._display.roundtrip() < 0:
            raise RuntimeError("Wayland display roundtrip failed")

    def _on_output_scale(self, output, factor: int) -> None:
        if output not in self._output_scales:
            return
        try:
            old_scale = self._integer_scale()
            self._output_scales[output] = max(1, factor)
            if output in self._entered_outputs and self._integer_scale() != old_scale:
                self._present_if_configured()
        except Exception as exc:
            self._display_lost(exc, "output_scale")

    def _on_surface_enter(self, _surface, output) -> None:
        if not callback_is_current(_surface, self._surface) or output not in self._output_scales:
            return
        try:
            old_scale = self._integer_scale()
            self._entered_outputs.add(output)
            if self._integer_scale() != old_scale:
                self._present_if_configured()
        except Exception as exc:
            self._display_lost(exc, "surface_enter")

    def _on_surface_leave(self, _surface, output) -> None:
        if not callback_is_current(_surface, self._surface) or output not in self._output_scales:
            return
        try:
            old_scale = self._integer_scale()
            self._entered_outputs.discard(output)
            if self._integer_scale() != old_scale:
                self._present_if_configured()
        except Exception as exc:
            self._display_lost(exc, "surface_leave")

    def _display_lost(self, exc: Exception, where: str) -> None:
        """Mark the connection unusable and say which callback found it out.

        Every one of these fires from a Wayland dispatcher, where raising would
        unwind through the C event loop; the loop checks ``_lost`` on its next
        turn instead. Logging is what keeps that from being a silent death.
        """
        self._lost = True
        log_failure(log, logging.WARNING, "overlay_helper: display_lost", exc, safe=True, at=where)

    def _integer_scale(self) -> int:
        return max(
            (self._output_scales.get(output, 1) for output in self._entered_outputs),
            default=1,
        )

    def _on_fractional_scale(self, _fractional_scale, scale: int) -> None:
        if not callback_is_current(_fractional_scale, self._fractional_scale):
            return
        if scale <= 0 or scale == self._preferred_scale_120:
            return
        try:
            self._preferred_scale_120 = scale
            self._present_if_configured()
        except Exception as exc:
            self._display_lost(exc, "fractional_scale")

    def _on_configure(self, layer_surface, serial: int, _width: int, _height: int) -> None:
        if not callback_is_current(layer_surface, self._layer_surface):
            return
        try:
            layer_surface.ack_configure(serial)
            self._configured = True
            self._present_if_configured()
        except Exception as exc:
            self._display_lost(exc, "configure")

    def _on_layer_closed(self, _layer_surface) -> None:
        if callback_is_current(_layer_surface, self._layer_surface):
            log.info(fmt_event("overlay_helper", "display_lost", at="layer_closed"))
            self._lost = True

    def _draw(self) -> None:
        if self._surface is None:
            # NULL output deliberately lets the compositor pick the recently
            # interacted output at each hidden-to-visible transition.
            self._create_surface(self._state)
        else:
            self._present_if_configured()

    def _repaint(self) -> None:
        self._present_if_configured()

    def _teardown(self) -> None:
        self._destroy_surface()

    def _create_surface(self, state: OverlayState) -> None:
        assert self._compositor is not None and self._layer_shell is not None
        logical_frame = self._frame(state)
        margin_bottom = layer_margin_bottom(
            canvas_height=logical_frame.height,
            pill_bottom=logical_frame.pill_bounds[3],
        )
        surface = self._compositor.create_surface()
        surface.dispatcher["enter"] = self._on_surface_enter
        surface.dispatcher["leave"] = self._on_surface_leave
        region = self._compositor.create_region()
        surface.set_input_region(region)
        region.destroy()

        layer_surface = self._layer_shell.get_layer_surface(
            surface,
            None,
            ZwlrLayerShellV1.layer.overlay,
            "stenographer-lifecycle",
        )
        layer_surface.dispatcher["configure"] = self._on_configure
        layer_surface.dispatcher["closed"] = self._on_layer_closed
        layer_surface.set_size(logical_frame.width, logical_frame.height)
        layer_surface.set_anchor(ZwlrLayerSurfaceV1.anchor.bottom)
        layer_surface.set_exclusive_zone(0)
        layer_surface.set_keyboard_interactivity(ZwlrLayerSurfaceV1.keyboard_interactivity.none)
        layer_surface.set_margin(0, 0, margin_bottom, 0)

        self._surface = surface
        self._layer_surface = layer_surface
        self._configured = False
        self._preferred_scale_120 = None
        if self._fractional_manager is not None and self._viewporter is not None:
            self._fractional_scale = self._fractional_manager.get_fractional_scale(surface)
            self._fractional_scale.dispatcher["preferred_scale"] = self._on_fractional_scale
            self._viewport = self._viewporter.get_viewport(surface)

        # Layer-shell requires this bufferless initial commit.  The configure
        # handler acknowledges its serial before the first frame is attached.
        surface.commit()

    def _present_if_configured(self) -> None:
        if not self._configured or self._surface is None or not self._visible:
            return
        if len(self._buffers) >= _MAX_IN_FLIGHT_BUFFERS:
            self._render_pending = True
            return
        plan = choose_scale_plan(
            integer_scale=self._integer_scale(),
            preferred_scale_120=(self._preferred_scale_120 if self._viewport is not None else None),
        )
        frame = self._frame(self._state, scale=plan.render_scale)
        buffer = self._create_buffer(
            premultiplied_argb32(frame.image),
            width=frame.width,
            height=frame.height,
            stride=frame.stride,
        )
        self._surface.set_buffer_scale(plan.buffer_scale)
        if self._viewport is not None:
            if plan.viewport_destination is None:
                self._viewport.set_destination(-1, -1)
            else:
                self._viewport.set_destination(*plan.viewport_destination)
        self._surface.attach(buffer, 0, 0)
        if self._compositor_version >= 4:
            self._surface.damage_buffer(0, 0, frame.width, frame.height)
        else:
            self._surface.damage(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT)
        self._surface.commit()
        self._render_pending = False

    def _create_buffer(self, pixels: bytes, *, width: int, height: int, stride: int):
        assert self._shm is not None
        size = stride * height
        if len(pixels) != size:
            raise ValueError("overlay frame byte size does not match its geometry")
        fd = os.memfd_create("stenographer-overlay", os.MFD_CLOEXEC)
        mapping = None
        pool = None
        try:
            os.ftruncate(fd, size)
            mapping = mmap.mmap(fd, size, flags=mmap.MAP_SHARED, prot=mmap.PROT_WRITE)
            mapping[:] = pixels
            pool = self._shm.create_pool(fd, size)
            proxy = pool.create_buffer(0, width, height, stride, WlShm.format.argb8888)
            key = id(proxy)
            self._buffers[key] = _ShmBuffer(proxy, mapping)
            proxy.dispatcher["release"] = lambda _proxy: self._release_buffer(key)
            mapping = None
            return proxy
        finally:
            if pool is not None:
                with contextlib.suppress(Exception):
                    pool.destroy()
            if mapping is not None:
                mapping.close()
            os.close(fd)

    def _release_buffer(self, key: int) -> None:
        buffer = self._buffers.pop(key, None)
        if buffer is not None:
            buffer.close()
        if self._render_pending:
            try:
                self._present_if_configured()
            except Exception as exc:
                self._display_lost(exc, "buffer_release")

    def _drop_buffers(self) -> None:
        buffers, self._buffers = self._buffers, {}
        for buffer in buffers.values():
            buffer.close()

    def _destroy_surface(self) -> None:
        surface, self._surface = self._surface, None
        layer_surface, self._layer_surface = self._layer_surface, None
        fractional_scale, self._fractional_scale = self._fractional_scale, None
        viewport, self._viewport = self._viewport, None
        self._configured = False
        self._render_pending = False
        self._preferred_scale_120 = None
        self._entered_outputs.clear()
        if surface is not None:
            with contextlib.suppress(Exception):
                surface.attach(None, 0, 0)
                surface.commit()
        for proxy in (fractional_scale, viewport, layer_surface, surface):
            if proxy is not None:
                with contextlib.suppress(Exception):
                    proxy.destroy()

    def _display_fd(self) -> int:
        return self._display.get_fd()

    def _before_select(self, selector: selectors.BaseSelector) -> None:
        want_write = self._flush_display()
        selector.modify(
            self._display_fd(),
            selectors.EVENT_READ | (selectors.EVENT_WRITE if want_write else 0),
            DISPLAY_KEY,
        )

    def _on_display_readable(self, mask: int) -> None:
        if mask & selectors.EVENT_READ:
            self._display.read()
            self._display.dispatch(block=False)
        if mask & selectors.EVENT_WRITE:
            self._flush_display()

    def _after_events(self) -> None:
        if self._lost:
            raise RuntimeError("layer-shell backend was closed")

    def _flush_display(self) -> bool:
        return flush_wants_write(self._display.flush(), ffi.errno)

    @staticmethod
    def _release_output(output, bound_version: int) -> None:
        with contextlib.suppress(Exception):
            if bound_version >= 3:
                output.release()
            else:
                output.destroy()

    def _close(self) -> None:
        self._destroy_surface()
        for output, bound_version in tuple(self._outputs.values()):
            self._release_output(output, bound_version)
        self._outputs.clear()
        for proxy in (
            self._fractional_manager,
            self._viewporter,
            self._shm,
            self._compositor,
            self._registry,
        ):
            if proxy is not None:
                with contextlib.suppress(Exception):
                    proxy.destroy()
        if self._layer_shell is not None:
            with contextlib.suppress(Exception):
                if self._layer_shell_version >= 3:
                    self._layer_shell.destroy()
                else:
                    self._layer_shell._destroy()
        with contextlib.suppress(Exception):
            self._display.flush()
        with contextlib.suppress(Exception):
            self._display.disconnect()
        self._drop_buffers()
