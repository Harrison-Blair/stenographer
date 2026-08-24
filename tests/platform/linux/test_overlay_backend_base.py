# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure scaffolding shared by both helper-side overlay backends."""

from __future__ import annotations

import ast
import pathlib

import pytest

from stenographer.platform.linux.overlay_backends import base
from stenographer.platform.linux.overlay_backends.base import (
    BackendUnavailableError,
    next_timeout,
    probe_backend,
)
from stenographer.status import Backend, UnavailableReason


def test_no_pending_deadline_blocks_the_selector_indefinitely() -> None:
    assert next_timeout() is None
    assert next_timeout(None, None) is None


def test_the_earliest_deadline_wins_and_a_due_one_is_not_mistaken_for_idle() -> None:
    assert next_timeout(0.75, None, 0.1) == 0.1
    assert next_timeout(None, 0.0, 2.5) == 0.0


def test_probe_translates_a_fixed_reason_and_never_leaves_a_connection_open() -> None:
    closed = []

    class _Unusable:
        def __init__(self) -> None:
            raise BackendUnavailableError(UnavailableReason.NO_X_DISPLAY)

        def close(self) -> None:  # pragma: no cover - never constructed
            closed.append("unusable")

    class _Usable:
        def close(self) -> None:
            closed.append("usable")

    assert probe_backend(_Unusable) is UnavailableReason.NO_X_DISPLAY
    assert probe_backend(_Usable) is None
    assert closed == ["usable"]


def test_probe_lets_an_unexpected_construction_failure_reach_the_registry() -> None:
    class _Broken:
        def __init__(self) -> None:
            raise RuntimeError("generated bindings missing")

        def close(self) -> None:  # pragma: no cover - never constructed
            raise AssertionError

    try:
        probe_backend(_Broken)
    except RuntimeError:
        return
    raise AssertionError("probe swallowed a non-reason failure")


def test_the_fixed_reason_is_the_whole_error_text() -> None:
    error = BackendUnavailableError(UnavailableReason.REQUIRED_GLOBALS_MISSING)

    assert error.reason is UnavailableReason.REQUIRED_GLOBALS_MISSING
    assert str(error) == "required_wayland_globals_missing"


def _self_calls(source: str, method: str) -> set[str]:
    """Names the given base method invokes as ``self.<name>(...)``."""
    tree = ast.parse(source)
    body = next(
        node
        for cls in ast.walk(tree)
        if isinstance(cls, ast.ClassDef) and cls.name == "HelperBackend"
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == method
    )
    return {
        node.func.attr
        for node in ast.walk(body)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "self"
    }


def test_every_hook_the_shared_loop_calls_exists_on_the_base() -> None:
    """A hook the loop calls but never declares raises only at runtime.

    Seen to FAIL with ``_after_events`` declared on the Wayland backend but
    absent from the base: the XWayland helper reached its first state message
    and died with AttributeError, which no unit test could have caught.
    """
    source = pathlib.Path(base.__file__).read_text(encoding="utf-8")
    called = set()
    for method in ("run", "_dispatch", "_select_timeout", "_on_timers", "close", "_frame"):
        called |= _self_calls(source, method)

    missing = sorted(name for name in called if not hasattr(base.HelperBackend, name))

    assert called, "the loop was expected to delegate to hooks"
    assert not missing, missing


def test_both_backends_implement_every_display_specific_hook() -> None:
    pytest.importorskip("pywayland")
    pytest.importorskip("Xlib")
    from stenographer.platform.linux.overlay_backends.wayland import LayerShellBackend
    from stenographer.platform.linux.overlay_backends.x11 import X11OverlayBackend

    required = ("_display_fd", "_draw", "_teardown", "_on_display_readable", "_close")
    for backend in (LayerShellBackend, X11OverlayBackend):
        inherited = [
            name for name in required if getattr(backend, name) is getattr(base.HelperBackend, name)
        ]
        assert not inherited, (backend.__name__, inherited)
        assert isinstance(backend.backend, Backend)
