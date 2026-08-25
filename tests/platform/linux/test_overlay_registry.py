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

from stenographer.platform.linux.overlay import overlay_backends
from stenographer.platform.linux.overlay_backends.base import BackendUnavailableError
from stenographer.status import Backend, UnavailableReason

_BACKEND_MODULES = {
    Backend.LAYER_SHELL: "stenographer.platform.linux.overlay_backends.wayland",
    Backend.XWAYLAND: "stenographer.platform.linux.overlay_backends.x11",
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
