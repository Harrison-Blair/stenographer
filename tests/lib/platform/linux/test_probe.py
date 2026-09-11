# SPDX-License-Identifier: GPL-3.0-or-later
"""The Linux host probes, run for real against this machine.

Every probe here is read-only: ``os.access`` on /dev/uinput, the group
database, a Wayland/X registry look, and two ``systemctl --user`` *queries*
(``is-enabled`` / ``is-active``). Nothing is opened, written, or restarted —
``restart_service()`` is never called from the unit suite.
"""

from __future__ import annotations

import grp
import os
import pathlib
import shutil

from stenographer.lib.platform.host_probe import HostProbe
from stenographer.lib.platform.linux.clipboard import probe_clipboard
from stenographer.lib.platform.linux.cues import detect_player
from stenographer.lib.platform.linux.probe import (
    in_input_group,
    probe_host,
    service_status,
    uinput_writable,
)

# `systemctl --user is-enabled` answers with one of these, or nothing at all
# for a unit that was never installed.
_ENABLED_STATES = {
    "enabled",
    "enabled-runtime",
    "linked",
    "linked-runtime",
    "alias",
    "masked",
    "masked-runtime",
    "static",
    "indirect",
    "disabled",
    "generated",
    "transient",
    "bad",
}

_ACTIVE_STATES = {
    "active",
    "reloading",
    "inactive",
    "failed",
    "activating",
    "deactivating",
    "unknown",
    "maintenance",
}


def test_uinput_writability_is_a_plain_bool_about_a_node_that_may_not_exist():
    result = uinput_writable()
    assert result is True or result is False
    if not pathlib.Path("/dev/uinput").exists():
        # A node that is not there can never be writable; doctor must say so
        # rather than trip over the missing path.
        assert result is False


def test_input_group_membership_is_reported_as_a_plain_bool():
    """Membership, not merely a readable group database.

    A host whose group table has no ``input`` entry must read as False (the
    ``KeyError`` branch) instead of raising into doctor's capability table.

    The membership assertion below restates the rule the function applies, so
    it is a consistency and type guard only: it would not catch an inverted
    policy. What it does catch is a raise, a non-bool, and the missing-group
    branch. The load-bearing probe test is the ``probe_host`` composition below.
    """
    result = in_input_group()
    assert result is True or result is False
    try:
        input_gid = grp.getgrnam("input").gr_gid
    except KeyError:
        assert result is False
    else:
        assert result is (os.geteuid() == 0 or input_gid in os.getgroups())


def test_service_status_answers_with_systemd_vocabulary_or_nothing():
    """A real read-only query pair against the user manager.

    ``is-enabled`` prints nothing for a unit that was never installed, and an
    unreachable user manager yields (None, None); anything else must be a
    stripped, non-empty systemd state word, because doctor prints it verbatim.
    """
    enabled, active = service_status()
    if shutil.which("systemctl") is None:
        assert (enabled, active) == (None, None)
        return
    for value, vocabulary in ((enabled, _ENABLED_STATES), (active, _ACTIVE_STATES)):
        if value is None:
            continue
        assert value == value.strip() != ""
        assert value in vocabulary, value


def test_probe_host_composes_the_platform_half_of_the_doctor_report():
    """Each probe must land in its own HostProbe field.

    A transposed pair here (uinput into hotkey_access_ok, say) would make
    doctor blame the wrong capability and print the wrong fix hint.
    """
    # Sampled once, against expectations computed once: the host is not asked
    # the same question twice, so a service that starts or stops mid-test
    # cannot fail this.
    expected_injector = uinput_writable()
    expected_hotkey = in_input_group()
    expected_clipboard_ok, expected_backend = probe_clipboard()
    expected_player = detect_player()

    probe = probe_host()

    assert isinstance(probe, HostProbe)
    assert probe.key_injector_ok is expected_injector
    assert probe.hotkey_access_ok is expected_hotkey
    assert probe.clipboard_ok is expected_clipboard_ok
    assert probe.clipboard_backend == expected_backend
    assert probe.cue_player == expected_player
    # The systemd pair is live state, so it is held to its vocabulary rather
    # than to a second query: the two vocabularies barely overlap, so a
    # transposed pair still fails here.
    assert probe.service_enabled is None or probe.service_enabled in _ENABLED_STATES
    assert probe.service_active is None or probe.service_active in _ACTIVE_STATES


def test_service_status_is_unknown_where_systemd_is_not_installed(tmp_path, monkeypatch):
    # No systemctl at all (a non-systemd host): doctor must report "unknown"
    # for both halves rather than failing to run the query.
    monkeypatch.setenv("PATH", str(tmp_path))
    assert service_status() == (None, None)


def test_service_status_is_unknown_when_the_query_cannot_run(tmp_path, monkeypatch):
    """A systemctl that is found but cannot be executed must not crash doctor.

    The stub is executable yet not a program, so the real spawn raises OSError
    — the same shape as a systemctl that cannot reach the user manager.
    """
    broken = tmp_path / "systemctl"
    broken.write_text("this is not an executable\n")
    broken.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert shutil.which("systemctl") == str(broken)
    assert service_status() == (None, None)
