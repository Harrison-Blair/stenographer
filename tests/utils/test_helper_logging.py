# SPDX-License-Identifier: GPL-3.0-or-later
"""The overlay helper's own log file: where it lands and how it is capped.

These write real files under ``tmp_path`` — the point is the file, and a mocked
handler would prove nothing about which path was opened — but they touch no
device, no display, and no child process.
"""

from __future__ import annotations

from io import StringIO

from stenographer.utils.logging_setup import (
    _HELPER_MAX_BYTES,
    cap_helper_log,
    helper_log_path,
    setup_helper_logging,
    shutdown_logging,
)


def _helper_state(tmp_path):
    return {"XDG_STATE_HOME": str(tmp_path)}, tmp_path / "stenographer"


def test_the_helper_writes_its_own_file_and_never_the_daemons(tmp_path):
    """The daemon owns ``stenographer.log`` and its rotation; the helper cannot.

    Seen to FAIL against the pre-``setup_helper_logging`` helper, which had no
    logger at all: ``overlay-helper.log`` was never created.
    """

    env, state = _helper_state(tmp_path)
    try:
        logger = setup_helper_logging(env=env, home=tmp_path, stderr=StringIO())
        logger.info("overlay_helper: backend_selected backend=layer-shell")
    finally:
        shutdown_logging()

    assert (
        (state / "overlay-helper.log")
        .read_text(encoding="utf-8")
        .endswith("overlay_helper: backend_selected backend=layer-shell\n")
    )
    assert not list(tmp_path.rglob("stenographer.log*"))


def test_an_unopenable_helper_file_degrades_to_stderr(tmp_path):
    blocked = tmp_path / "occupied"
    blocked.write_text("not a directory", encoding="utf-8")
    stream = StringIO()
    try:
        logger = setup_helper_logging(
            env={"XDG_STATE_HOME": str(blocked)}, home=tmp_path, stderr=stream
        )
        logger.info("overlay_helper: ready backend=xwayland")
    finally:
        shutdown_logging()

    assert "logging: helper_file_unavailable" in stream.getvalue()
    assert "overlay_helper: ready backend=xwayland" in stream.getvalue()


def test_an_oversized_log_is_rolled_aside_once_before_anything_opens_it(tmp_path):
    """One startup check, not a RotatingFileHandler.

    Two descriptors append to this file — the helper's handler and the stderr
    the transport hands the child — so a rotation *while it is open* would
    leave one of them writing to an unlinked inode. Seen to FAIL with
    ``cap_helper_log``'s body replaced by ``return``: no ``.1`` appeared.
    """

    env, state = _helper_state(tmp_path)
    state.mkdir(parents=True)
    path = helper_log_path(env, tmp_path)
    path.write_bytes(b"x" * _HELPER_MAX_BYTES)

    cap_helper_log(path)

    assert (state / "overlay-helper.log.1").stat().st_size == _HELPER_MAX_BYTES
    assert not path.exists()


def test_a_log_within_budget_is_left_alone(tmp_path):
    """Seen to FAIL with the ``st_size < _HELPER_MAX_BYTES`` check removed,
    which rolled a one-line log aside on every single start.
    """
    env, state = _helper_state(tmp_path)
    state.mkdir(parents=True)
    path = helper_log_path(env, tmp_path)
    path.write_bytes(b"x" * (_HELPER_MAX_BYTES - 1))

    cap_helper_log(path)

    assert path.stat().st_size == _HELPER_MAX_BYTES - 1
    assert not (state / "overlay-helper.log.1").exists()


def test_capping_a_missing_log_is_not_an_error(tmp_path):
    cap_helper_log(tmp_path / "nowhere" / "overlay-helper.log")


def test_the_childs_inherited_stderr_is_never_renamed_out_from_under_it(tmp_path):
    """The spawned helper must not cap the file its own stderr already holds.

    The parent caps, then opens the stderr descriptor and spawns; the child
    would otherwise cap the same path a second time and rename that inode to
    ``.1``, sending every later byte of backend chatter into a file the next
    start overwrites. Seen to FAIL with the ``_stderr_targets`` guard removed:
    ``.1`` appeared and the inherited stream no longer wrote to the live log.
    """

    env, state = _helper_state(tmp_path)
    state.mkdir(parents=True)
    path = helper_log_path(env, tmp_path)
    path.write_bytes(b"x" * _HELPER_MAX_BYTES)

    with path.open("a", encoding="utf-8") as inherited:
        try:
            logger = setup_helper_logging(env=env, home=tmp_path, stderr=inherited)
            logger.info("overlay_helper: ready backend=layer-shell")
        finally:
            shutdown_logging()
        inherited.write("library chatter\n")

    assert not (state / "overlay-helper.log.1").exists()
    assert "library chatter" in path.read_text(encoding="utf-8")


def test_a_standalone_helper_still_caps_because_its_stderr_is_elsewhere(tmp_path):
    env, state = _helper_state(tmp_path)
    state.mkdir(parents=True)
    path = helper_log_path(env, tmp_path)
    path.write_bytes(b"x" * _HELPER_MAX_BYTES)

    try:
        setup_helper_logging(env=env, home=tmp_path, stderr=StringIO())
    finally:
        shutdown_logging()

    assert (state / "overlay-helper.log.1").stat().st_size == _HELPER_MAX_BYTES


def test_logging_setup_never_raises_out_of_the_helper(tmp_path):
    """A helper that cannot open its log must still go on to serve the protocol.

    Seen to FAIL with the catch narrowed back to ``(OSError, ValueError)``:
    the platform's refusal propagated and the helper died before replying.
    """

    class _NoStateDir:
        def state_dir(self, env, home):
            raise RuntimeError("this host has no state directory")

    import stenographer.utils.logging_setup as module

    original = module.current_platform
    module.current_platform = lambda: _NoStateDir()
    stream = StringIO()
    try:
        logger = setup_helper_logging(env={}, home=tmp_path, stderr=stream)
        logger.info("overlay_helper: ready backend=xwayland")
    finally:
        module.current_platform = original
        shutdown_logging()

    assert "logging: helper_file_unavailable" in stream.getvalue()
    assert "overlay_helper: ready backend=xwayland" in stream.getvalue()
