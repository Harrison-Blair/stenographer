# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import contextlib
import logging
import threading
import time
from typing import TYPE_CHECKING

import evdev

from stenographer.lib.hotkey.binding import chord_active
from stenographer.lib.hotkey.chord_tracker import ChordTracker
from stenographer.lib.logging.pipeline import fmt_event, log_failure

if TYPE_CHECKING:
    from collections.abc import Callable

from stenographer.lib.platform.linux.hotkey import (
    _REACQUIRE_INTERVAL_SECONDS,
    _RESCAN_INTERVAL_SECONDS,
    auto_detect_paths,
    logger,
)


class EvdevHotkeyListener(ChordTracker):
    """Evdev edge reporter: listens on the configured device or every
    auto-detected keyboard, unioning held keys across HIDs. The device is never
    grabbed: non-chord keys pass through.
    """

    def __init__(
        self,
        *,
        chord: frozenset[int],
        device_path: str | None,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        lock: threading.RLock,
    ) -> None:
        super().__init__(chord=chord, on_start=on_start, on_stop=on_stop, lock=lock)
        self._device_path = device_path
        self._supervisor: threading.Thread | None = None
        self._readers: list[threading.Thread] = []
        self._devices: list[evdev.InputDevice] = []

    def start(self) -> None:
        if self._supervisor is not None:
            return
        self._stop_event.clear()
        self._supervisor = threading.Thread(target=self._run, name="hotkey-listener", daemon=True)
        self._supervisor.start()

    def stop(self, timeout: float = 2.0) -> None:
        with self._transition_lock:
            self._stop_event.set()
        with self._held_lock:
            devices = list(self._devices)
            self._devices.clear()
            self._held_by_device.clear()
            self._held.clear()
        for device in devices:
            with contextlib.suppress(OSError):
                device.close()
        for t in list(self._readers):
            t.join(timeout=timeout)
        if self._supervisor is not None:
            self._supervisor.join(timeout=timeout)
        self._readers = []
        self._supervisor = None
        with self._lock:
            self._active = False

    @property
    def is_running(self) -> bool:
        return self._supervisor is not None and self._supervisor.is_alive()

    def _resolve_paths(self) -> list[str]:
        return [self._device_path] if self._device_path else auto_detect_paths()

    def _run(self) -> None:
        paths = self._resolve_paths()
        while not self._stop_event.is_set():
            devices: list[evdev.InputDevice] = []
            for path in paths:
                with contextlib.suppress(OSError):
                    devices.append(evdev.InputDevice(path))
            if devices:
                for device in devices:
                    logger.info(
                        fmt_event("hotkey", "listening", device=device.path, name=device.name)
                    )
                with self._held_lock:
                    self._held.clear()
                    self._held_by_device = {id(device): set() for device in devices}
                    self._devices = devices
                self._active = False
                self._readers = [self._spawn_reader(d) for d in devices]
                self._supervise()
                for t in list(self._readers):
                    t.join(timeout=0.5)
                if self._stop_event.is_set():
                    return
                logger.warning("hotkey: devices_lost action=redetect")
            else:
                # No target device is currently openable (unplugged, stale
                # explicit path, or a permissions gap). Back off before retrying
                # so an outage cannot busy-loop the daemon: with an explicit
                # hotkey.device, _resolve_paths always yields that path, so
                # _reacquire returns instantly and never blocks.
                logger.debug(
                    "hotkey: no_openable_device retry_seconds=%s",
                    _REACQUIRE_INTERVAL_SECONDS,
                )
                self._stop_event.wait(_REACQUIRE_INTERVAL_SECONDS)
            paths = self._reacquire()
            if not paths:
                logger.error("hotkey: no_readable_device action=listener_exit")
                return

    def _reacquire(self) -> list[str]:
        while not self._stop_event.is_set():
            paths = self._resolve_paths()
            if paths:
                return paths
            self._stop_event.wait(_REACQUIRE_INTERVAL_SECONDS)
        return []

    def _supervise(self) -> None:
        """Wait until every reader dies or stop is requested; while at least one
        reader lives, periodically rescan (auto-detect mode only) to pick up a
        hotplugged keyboard without disturbing an in-flight press.
        """
        next_rescan = time.monotonic() + _RESCAN_INTERVAL_SECONDS
        while not self._stop_event.is_set():
            self._stop_event.wait(0.5)
            self._readers = [t for t in self._readers if t.is_alive()]
            if not self._readers:
                return
            if self._device_path is None and time.monotonic() >= next_rescan:
                self._rescan()
                next_rescan = time.monotonic() + _RESCAN_INTERVAL_SECONDS

    def _rescan(self) -> None:
        with self._held_lock:
            known = {device.path for device in self._devices}
        for path in auto_detect_paths():
            if self._stop_event.is_set() or path in known:
                continue
            try:
                device = evdev.InputDevice(path)
            except OSError as exc:
                log_failure(
                    logger, logging.DEBUG, "hotkey: device_skipped", exc, safe=True, path=path
                )
                continue
            logger.info(fmt_event("hotkey", "hotplug", device=path, name=device.name))
            with self._held_lock:
                if self._stop_event.is_set():
                    device.close()
                    return
                self._devices.append(device)
                self._held_by_device[id(device)] = set()
            self._readers.append(self._spawn_reader(device))

    def _spawn_reader(self, device: evdev.InputDevice) -> threading.Thread:
        t = threading.Thread(
            target=self._reader_loop,
            args=(device,),
            name=f"hotkey-reader:{device.path}",
            daemon=True,
        )
        t.start()
        return t

    def _reader_loop(self, device: evdev.InputDevice) -> None:
        """Feed one device's key events into the shared tracker (see
        ``ChordTracker._key_event``) until the device is lost or stop is requested.
        """
        try:
            for event in device.read_loop():
                if self._stop_event.is_set():
                    return
                if event.type != evdev.ecodes.EV_KEY:
                    continue
                if not self._key_event(id(device), event.code, event.value):
                    return
        except OSError as exc:
            if not self._stop_event.is_set():
                log_failure(
                    logger,
                    logging.WARNING,
                    "hotkey: device_lost",
                    exc,
                    safe=True,
                    device=device.path,
                )
        finally:
            self._device_lost(device)

    def _device_lost(self, device: evdev.InputDevice) -> None:
        """Drop one HID's state and report any resulting falling edge."""
        with self._transition_lock:
            with self._held_lock:
                self._held_by_device.pop(id(device), None)
                self._devices = [opened for opened in self._devices if opened is not device]
                self._rebuild_held()
                is_active = chord_active(self._held, self._chord)
            with contextlib.suppress(OSError):
                device.close()
            if not self._stop_event.is_set():
                self._update(is_active)
