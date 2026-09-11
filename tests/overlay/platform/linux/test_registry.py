# SPDX-License-Identifier: GPL-3.0-or-later
"""A partial install is its own overlay failure, not a missing compositor.

The two are fixed by different things — reinstall versus start a session — so
``doctor`` must not conflate them. Blocking the backend modules in
``sys.modules`` is the same technique ``test_core_isolation`` uses, and it
needs neither pywayland nor python-xlib to be installed.
"""

from __future__ import annotations

import sys

import pytest

from stenographer.overlay.platform.linux.backends.errors import BackendUnavailableError
from stenographer.overlay.platform.linux.registry import overlay_backends
from stenographer.overlay.protocol.backend import Backend
from stenographer.overlay.protocol.unavailablereason import UnavailableReason

_BACKEND_MODULES = {
    Backend.LAYER_SHELL: "stenographer.overlay.platform.linux.backends.layer_shell_backend",
    Backend.XWAYLAND: "stenographer.overlay.platform.linux.backends.x11_overlay_backend",
}


@pytest.mark.parametrize("backend", sorted(_BACKEND_MODULES, key=lambda item: item.value))
def test_an_unimportable_backend_reports_the_dependency_reason(backend, monkeypatch):
    """Seen to FAIL against the pre-split probes, which caught ``Exception``
    around the import and the probe together and returned the generic
    ``BACKENDS_UNAVAILABLE`` for both.
    """

    monkeypatch.setitem(sys.modules, _BACKEND_MODULES[backend], None)
    spec = next(item for item in overlay_backends() if item.backend is backend)

    assert spec.probe() is UnavailableReason.BACKEND_DEPENDENCY_MISSING


def test_a_blocked_import_never_raises_out_of_a_probe(monkeypatch):
    for module in _BACKEND_MODULES.values():
        monkeypatch.setitem(sys.modules, module, None)

    assert all(spec.probe() is not None for spec in overlay_backends())


@pytest.mark.parametrize("backend", sorted(_BACKEND_MODULES, key=lambda item: item.value))
def test_an_unimportable_backend_constructs_the_same_reason_it_probes(backend, monkeypatch):
    """Otherwise doctor and the running helper describe one install differently.

    Seen to FAIL with the construct guard removed: a bare ``ImportError``
    carries no ``reason``, so the helper folded it to ``backends_unavailable``
    while the probe beside it said ``backend_dependency_missing``.
    """

    monkeypatch.setitem(sys.modules, _BACKEND_MODULES[backend], None)
    spec = next(item for item in overlay_backends() if item.backend is backend)

    with pytest.raises(BackendUnavailableError) as caught:
        spec.construct()
    assert caught.value.reason is UnavailableReason.BACKEND_DEPENDENCY_MISSING
    assert caught.value.reason is spec.probe()


@pytest.mark.parametrize(
    ("backend", "dependency", "variable", "reason"),
    [
        (
            Backend.LAYER_SHELL,
            "pywayland",
            "WAYLAND_DISPLAY",
            UnavailableReason.NO_WAYLAND_DISPLAY,
        ),
        (Backend.XWAYLAND, "Xlib", "DISPLAY", UnavailableReason.NO_X_DISPLAY),
    ],
)
def test_a_missing_session_variable_is_reported_as_a_missing_display(
    backend, dependency, variable, reason, monkeypatch
):
    """``doctor`` on a headless machine must say which session is absent, not
    that the install is broken — the two have different fixes.

    Each backend skips only on its own dependency: a machine with just one of
    them installed still proves the other half.
    """
    pytest.importorskip(dependency)
    monkeypatch.delenv(variable, raising=False)
    spec = next(item for item in overlay_backends() if item.backend is backend)

    assert spec.probe() is reason
