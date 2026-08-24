# SPDX-License-Identifier: GPL-3.0-or-later
"""Native layer-shell display backend for the isolated overlay helper.

The backend supplies only layer-shell primitives to ``HelperBackend``: registry
inventory and hotplug classification, surface creation with its bufferless
initial commit, scale selection, ``wl_shm`` buffer management, and the
non-blocking flush toggling the loop's write interest.  Lifecycle policy, the
selector loop, the loading-frame timer, and the frame request are shared (see
``base.py``); the pure helpers at the top make each decision testable without a
compositor.
"""

from __future__ import annotations

import contextlib
import errno
import mmap
import os
import selectors
from dataclasses import dataclass
from enum import StrEnum

from pywayland import ffi
from pywayland.client import Display
from pywayland.protocol.wayland import WlCompositor, WlOutput, WlShm

from stenographer.overlay.render import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    layer_margin_bottom,
    premultiplied_argb32,
)
from stenographer.platform.linux.overlay_backends.base import (
    DISPLAY_KEY,
    BackendUnavailableError,
    HelperBackend,
)
from stenographer.platform.linux.overlay_backends.protocols.fractional_scale_v1 import (
    WpFractionalScaleManagerV1,
)
from stenographer.platform.linux.overlay_backends.protocols.viewporter import WpViewporter
from stenographer.platform.linux.overlay_backends.protocols.wlr_layer_shell_unstable_v1 import (
    ZwlrLayerShellV1,
    ZwlrLayerSurfaceV1,
)
from stenographer.status import Backend, OverlayState, UnavailableReason

REQUIRED_GLOBALS = ("wl_compositor", "wl_shm", "zwlr_layer_shell_v1")
_OPTIONAL_GLOBALS = ("wp_fractional_scale_manager_v1", "wp_viewporter")
_REQUIRED_VERSIONS = {"wl_compositor": 3, "wl_shm": 1, "zwlr_layer_shell_v1": 1}
_MAX_IN_FLIGHT_BUFFERS = 3
_OUTPUT_INTERFACE = "wl_output"


@dataclass(frozen=True, slots=True)
class _Global:
    name: int
    interface: str
    version: int


class GlobalRemoval(StrEnum):
    """What losing one advertised global means for a running surface."""

    IGNORE = "ignore"
    LOST = "lost"
    OUTPUT = "output"


def classify_global_removal(interface: str | None) -> GlobalRemoval:
    """Classify a ``global_remove`` by interface without touching the display.

    Losing a required global is unrecoverable; losing an output only matters
    when the surface had entered it. Anything else is a hotplug detail.
    """
    if interface is None:
        return GlobalRemoval.IGNORE
    if interface in REQUIRED_GLOBALS:
        return GlobalRemoval.LOST
    if interface == _OUTPUT_INTERFACE:
        return GlobalRemoval.OUTPUT
    return GlobalRemoval.IGNORE


def flush_wants_write(result: int, error_number: int) -> bool:
    """Classify one ``wl_display_flush`` result. PURE.

    A short flush on a full socket is normal back-pressure and asks the loop
    for write interest; any other failure is a lost connection.
    """
    if result >= 0:
        return False
    if error_number in {errno.EAGAIN, errno.EWOULDBLOCK}:
        return True
    raise RuntimeError("Wayland display flush failed")


class RegistryInventory:
    """Pure global-registry inventory used by probing and hotplug handling."""

    def __init__(self) -> None:
        self._by_name: dict[int, _Global] = {}

    def add(self, name: int, interface: str, version: int) -> None:
        self._by_name[name] = _Global(name, interface, version)

    def remove(self, name: int) -> _Global | None:
        return self._by_name.pop(name, None)

    def get(self, interface: str) -> _Global | None:
        return next((item for item in self._by_name.values() if item.interface == interface), None)

    def version(self, interface: str) -> int:
        item = self.get(interface)
        return item.version if item is not None else 0

    def missing_required(self) -> tuple[str, ...]:
        return tuple(
            interface
            for interface in REQUIRED_GLOBALS
            if self.version(interface) < _REQUIRED_VERSIONS[interface]
        )

    def values(self) -> tuple[_Global, ...]:
        return tuple(self._by_name.values())


@dataclass(frozen=True, slots=True)
class ScalePlan:
    """Renderer scale and Wayland surface mapping for one frame."""

    render_scale: float
    buffer_scale: int
    viewport_destination: tuple[int, int] | None


def choose_scale_plan(*, integer_scale: int, preferred_scale_120: int | None = None) -> ScalePlan:
    """Select fractional scaling only when a valid preferred scale is present."""
    integer_scale = max(1, integer_scale)
    if preferred_scale_120 is not None and preferred_scale_120 > 0:
        return ScalePlan(
            render_scale=preferred_scale_120 / 120,
            buffer_scale=1,
            viewport_destination=(CANVAS_WIDTH, CANVAS_HEIGHT),
        )
    return ScalePlan(float(integer_scale), integer_scale, None)


def callback_is_current(callback_proxy: object, current_proxy: object | None) -> bool:
    """Accept an event only when it belongs to the current surface epoch."""
    return current_proxy is not None and callback_proxy is current_proxy


@dataclass(slots=True)
class _ShmBuffer:
    proxy: object
    mapping: mmap.mmap

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.proxy.destroy()
        with contextlib.suppress(BufferError, OSError):
            self.mapping.close()


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
        except Exception:
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
            if self._inventory.missing_required():
                raise BackendUnavailableError(UnavailableReason.REQUIRED_GLOBALS_MISSING)
            self._bind_globals()
            self._initialized = True
            self._roundtrip()
        except BackendUnavailableError:
            self.close()
            raise
        except Exception:
            self.close()
            raise BackendUnavailableError(UnavailableReason.WAYLAND_CONNECT_FAILED) from None

    def _on_global(self, _registry, name: int, interface: str, version: int) -> None:
        self._inventory.add(name, interface, version)
        if self._initialized and interface == _OUTPUT_INTERFACE:
            self._bind_output(name, version)

    def _on_global_remove(self, _registry, name: int) -> None:
        item = self._inventory.remove(name)
        removal = classify_global_removal(None if item is None else item.interface)
        if removal is GlobalRemoval.LOST:
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
            except Exception:
                self._lost = True

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
        except Exception:
            self._lost = True

    def _on_surface_enter(self, _surface, output) -> None:
        if not callback_is_current(_surface, self._surface) or output not in self._output_scales:
            return
        try:
            old_scale = self._integer_scale()
            self._entered_outputs.add(output)
            if self._integer_scale() != old_scale:
                self._present_if_configured()
        except Exception:
            self._lost = True

    def _on_surface_leave(self, _surface, output) -> None:
        if not callback_is_current(_surface, self._surface) or output not in self._output_scales:
            return
        try:
            old_scale = self._integer_scale()
            self._entered_outputs.discard(output)
            if self._integer_scale() != old_scale:
                self._present_if_configured()
        except Exception:
            self._lost = True

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
        except Exception:
            self._lost = True

    def _on_configure(self, layer_surface, serial: int, _width: int, _height: int) -> None:
        if not callback_is_current(layer_surface, self._layer_surface):
            return
        try:
            layer_surface.ack_configure(serial)
            self._configured = True
            self._present_if_configured()
        except Exception:
            self._lost = True

    def _on_layer_closed(self, _layer_surface) -> None:
        if callback_is_current(_layer_surface, self._layer_surface):
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
            except Exception:
                self._lost = True

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


__all__ = [
    "REQUIRED_GLOBALS",
    "GlobalRemoval",
    "LayerShellBackend",
    "RegistryInventory",
    "ScalePlan",
    "callback_is_current",
    "choose_scale_plan",
    "classify_global_removal",
    "flush_wants_write",
]
