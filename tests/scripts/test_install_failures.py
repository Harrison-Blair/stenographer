# SPDX-License-Identifier: GPL-3.0-or-later
"""Installer failures must preserve a usable existing installation."""

import os
import resource
import shutil
import signal
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _setup(tmp_path):
    project = tmp_path / "project"
    for path in ("scripts/install.sh", "scripts/progress.sh", "packaging/stenographer.service"):
        destination = project / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / path, destination)
    bundle = project / "dist/stenographer"
    bundle.mkdir(parents=True)
    binary = bundle / "stenographer"
    binary.write_text("#!/bin/sh\necho completion\n")
    binary.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    commands = tmp_path / "commands"
    commands.mkdir()
    systemctl = commands / "systemctl"
    systemctl.write_text('#!/bin/sh\necho "$*" >> "$CALLS"\n')
    systemctl.chmod(0o755)
    (tmp_path / "calls").touch()
    env = os.environ | {
        "HOME": str(home),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "PATH": f"{commands}:{os.environ['PATH']}",
        "CALLS": str(tmp_path / "calls"),
    }
    return project, home, commands, env


def test_failed_bundle_copy_preserves_running_installation(tmp_path):
    project, home, commands, env = _setup(tmp_path)
    install = home / ".local/share/stenographer"
    (install / "_internal").mkdir(parents=True)
    (install / "stenographer").write_text("old executable")
    (install / "_internal/library").write_text("old library")
    cp = commands / "cp"
    cp.write_text("#!/bin/sh\nexit 1\n")
    cp.chmod(0o755)

    result = subprocess.run(["bash", "scripts/install.sh", "--verbose"], cwd=project, env=env)

    assert result.returncode != 0
    assert (install / "stenographer").read_text() == "old executable"
    assert (install / "_internal/library").read_text() == "old library"
    assert "stop stenographer.service" not in (tmp_path / "calls").read_text()


def test_failed_unit_write_preserves_existing_unit(tmp_path):
    project, home, _, env = _setup(tmp_path)
    unit = home / ".config/systemd/user/stenographer.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("old unit\n")
    install = tmp_path.joinpath(*(["a" * 100] * 7))

    def limit_file_size():
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024, 1024))

    result = subprocess.run(
        ["bash", "scripts/install.sh", "--verbose", "--install-dir", str(install)],
        cwd=project,
        env=env,
        preexec_fn=limit_file_size,
    )

    assert result.returncode != 0
    assert unit.read_text() == "old unit\n"


def test_failed_bundle_replacement_restores_bundle_and_service(tmp_path):
    project, home, commands, env = _setup(tmp_path)
    install = home / ".local/share/stenenographer"
    (install / "_internal").mkdir(parents=True)
    (install / "stenographer").write_text("old executable")
    (install / "_internal/library").write_text("old library")
    mv = commands / "mv"
    mv.write_text(
        '#!/bin/sh\ncase "$1" in */bundle/stenographer) exit 1;; esac\nexec /bin/mv "$@"\n'
    )
    mv.chmod(0o755)

    result = subprocess.run(
        ["bash", "scripts/install.sh", "--verbose", "--install-dir", str(install)],
        cwd=project,
        env=env,
    )

    assert result.returncode != 0
    assert (install / "stenographer").read_text() == "old executable"
    assert (install / "_internal/library").read_text() == "old library"
    calls = (tmp_path / "calls").read_text()
    assert "stop stenographer.service" in calls
    assert "start stenographer.service" in calls
    assert not list(install.glob(".install.*"))


def test_successful_install_preserves_user_data_and_backs_up_unit(tmp_path):
    project, home, _, env = _setup(tmp_path)
    install = home / ".local/share/stenographer"
    (install / "_internal").mkdir(parents=True)
    (install / "_internal/old").write_text("old library")
    (install / "config.toml").write_text("user data")
    unit = home / ".config/systemd/user/stenographer.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("old unit\n")

    result = subprocess.run(
        ["bash", "scripts/install.sh", "--verbose", "--no-start"], cwd=project, env=env
    )

    assert result.returncode == 0
    assert (install / "config.toml").read_text() == "user data"
    assert not (install / "_internal/old").exists()
    assert (unit.parent / "stenographer.service.bak").read_text() == "old unit\n"
    assert "ExecStart=%h/.local/share/stenographer/stenographer run" in unit.read_text()
    assert not list(install.glob(".install.*"))
