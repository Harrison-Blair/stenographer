# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the real quick-install script, as ``curl | bash`` does, with stub commands.

The stubs replace ``curl`` and ``systemctl``, and ``HOME`` is temporary, so a run
cannot reach the network or the machine's real service. ``tar`` and ``sha256sum``
are real and work on archives built here.
"""

import hashlib
import os
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERSION = "9.9.9"
_INSTALLED_MARKER = f"stenographer stub {VERSION}"
_SETUP_STEP = "stenographer setup --quick"
_CURL = """#!/bin/sh
# Resolving the latest release asks for the effective URL.
case " $* " in
    *" -w "*)
        printf 'https://github.com/Harrison-Blair/stenographer/releases/tag/v%s' "$VERSION"
        exit 0
        ;;
esac
while [ "$#" -gt 1 ]; do
    if [ "$1" = "-o" ]; then output=$2; fi
    shift
done
exec cp "$FIXTURES/${1##*/}" "$output"
"""
# Keeps the service state in a file, as the real manager would across calls.
_SYSTEMCTL = """#!/bin/sh
echo "$*" >> "$SERVICE_LOG"
case "$2" in
    is-active) [ "$(cat "$SERVICE_STATE")" = active ] ;;
    is-enabled)
        cat "$UNIT_STATE" 2>/dev/null || echo not-found
        [ "$(cat "$UNIT_STATE" 2>/dev/null)" = enabled ]
        ;;
    enable) echo enabled > "$UNIT_STATE" ;;
    start) echo active > "$SERVICE_STATE" ;;
    stop) echo stopped > "$SERVICE_STATE" ;;
esac
"""
_RECORDING_INSTALLER = """#!/bin/sh
for option in "$@"; do echo "$option"; done > "$INSTALLER_ARGS"
"""


@dataclass
class Machine:
    tmp_path: Path
    home: Path
    commands: Path
    env: dict[str, str]

    @property
    def launcher(self) -> Path:
        return self.home / ".local/bin/stenographer"

    @property
    def service_state(self) -> str:
        return (self.tmp_path / "service-state").read_text().strip()

    @property
    def unit_state(self) -> str:
        return (self.tmp_path / "unit-state").read_text().strip()

    @property
    def service_calls(self) -> list[str]:
        return (self.tmp_path / "service-log").read_text().splitlines()

    @property
    def installer_args(self) -> list[str]:
        return (self.tmp_path / "installer-args").read_text().splitlines()

    def set_service(self, state: str) -> None:
        (self.tmp_path / "service-state").write_text(f"{state}\n")

    def set_unit(self, state: str) -> None:
        (self.tmp_path / "unit-state").write_text(f"{state}\n")

    def install_old_version(self) -> None:
        binary = self.home / ".local/share/stenographer/stenographer"
        _executable(binary, "#!/bin/sh\necho old\n")
        self.launcher.parent.mkdir(parents=True)
        self.launcher.symlink_to(binary)

    def installed_version(self) -> str:
        return subprocess.run([self.launcher], capture_output=True, text=True).stdout.strip()

    def run(self, *options: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [shutil.which("bash"), "-s", "--", *options],
            input=(ROOT / "scripts/quick-install.sh").read_text(),
            env=self.env,
            capture_output=True,
            text=True,
        )


def _executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(0o755)


def _build_release(fixtures: Path, sdist_tree: Path) -> None:
    bundle_tree = fixtures.parent / "bundle-tree"
    _executable(
        bundle_tree / "stenographer/stenographer",
        f'#!/bin/sh\necho "{_INSTALLED_MARKER}"\n',
    )
    fixtures.mkdir()
    bundle = f"stenographer-{VERSION}-linux-x86_64.tar.gz"
    aarch_bundle = f"stenographer-{VERSION}-linux-aarch64.tar.gz"
    sdist = f"stenographer-{VERSION}.tar.gz"
    with tarfile.open(fixtures / bundle, "w:gz") as archive:
        archive.add(bundle_tree / "stenographer", arcname="stenographer")
    shutil.copy(fixtures / bundle, fixtures / aarch_bundle)
    with tarfile.open(fixtures / sdist, "w:gz") as archive:
        archive.add(sdist_tree, arcname=f"stenographer-{VERSION}")
    (fixtures / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256((fixtures / name).read_bytes()).hexdigest()}  {name}\n"
            for name in (bundle, aarch_bundle, sdist)
        )
    )


def _machine(tmp_path: Path, sdist_tree: Path) -> Machine:
    _build_release(tmp_path / "fixtures", sdist_tree)
    home = tmp_path / "home"
    home.mkdir()
    commands = tmp_path / "commands"
    _executable(commands / "curl", _CURL)
    _executable(commands / "systemctl", _SYSTEMCTL)
    (tmp_path / "service-log").touch()
    temporary = tmp_path / "tmp"
    temporary.mkdir()
    machine = Machine(
        tmp_path=tmp_path,
        home=home,
        commands=commands,
        env={
            "HOME": str(home),
            "PATH": f"{commands}:{os.environ['PATH']}",
            "TMPDIR": str(temporary),
            "VERSION": VERSION,
            "FIXTURES": str(tmp_path / "fixtures"),
            "SERVICE_LOG": str(tmp_path / "service-log"),
            "SERVICE_STATE": str(tmp_path / "service-state"),
            "UNIT_STATE": str(tmp_path / "unit-state"),
            "INSTALLER_ARGS": str(tmp_path / "installer-args"),
        },
    )
    machine.set_service("stopped")
    return machine


@pytest.fixture
def real_installer(tmp_path: Path) -> Machine:
    """A release whose source distribution holds the repository's real install.sh."""

    tree = tmp_path / "sdist-tree"
    for path in ("scripts/install.sh", "scripts/progress.sh", "packaging/stenographer.service"):
        destination = tree / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / path, destination)
    return _machine(tmp_path, tree)


@pytest.fixture
def recording_installer(tmp_path: Path) -> Machine:
    """A release whose install.sh only records the options it receives."""

    tree = tmp_path / "sdist-tree"
    _executable(tree / "scripts/install.sh", _RECORDING_INSTALLER)
    return _machine(tmp_path, tree)


def test_a_running_service_restarts_on_the_new_version(real_installer: Machine) -> None:
    real_installer.install_old_version()
    real_installer.set_service("active")

    result = real_installer.run()

    assert result.returncode == 0, result.stderr
    assert real_installer.service_state == "active"
    calls = real_installer.service_calls
    assert calls.index("--user stop stenographer.service") < calls.index(
        "--user start stenographer.service"
    )
    assert real_installer.installed_version() == _INSTALLED_MARKER
    assert _SETUP_STEP not in result.stdout


def test_a_stopped_service_stays_stopped_after_an_update(real_installer: Machine) -> None:
    real_installer.install_old_version()

    result = real_installer.run()

    assert result.returncode == 0, result.stderr
    assert real_installer.service_state == "stopped"
    assert "--user start stenographer.service" not in real_installer.service_calls
    assert real_installer.installed_version() == _INSTALLED_MARKER
    assert _SETUP_STEP not in result.stdout


def test_a_new_install_stays_stopped_and_prints_the_setup_step(real_installer: Machine) -> None:
    result = real_installer.run()

    assert result.returncode == 0, result.stderr
    assert real_installer.service_state == "stopped"
    assert "--user start stenographer.service" not in real_installer.service_calls
    assert real_installer.unit_state == "enabled"
    assert real_installer.launcher.is_symlink()
    assert _SETUP_STEP in result.stdout


def test_running_again_repairs_an_installation(real_installer: Machine) -> None:
    real_installer.install_old_version()
    (real_installer.home / ".local/share/stenographer/stenographer").write_text("damaged")

    result = real_installer.run()

    assert result.returncode == 0, result.stderr
    assert real_installer.installed_version() == _INSTALLED_MARKER
    assert _SETUP_STEP not in result.stdout


def test_a_disabled_service_stays_disabled_and_stopped(real_installer: Machine) -> None:
    real_installer.install_old_version()
    real_installer.set_unit("disabled")

    result = real_installer.run()

    assert result.returncode == 0, result.stderr
    assert real_installer.unit_state == "disabled"
    assert real_installer.service_state == "stopped"
    assert "--user enable stenographer.service" not in real_installer.service_calls
    assert real_installer.installed_version() == _INSTALLED_MARKER


def test_a_running_disabled_service_restarts_and_stays_disabled(real_installer: Machine) -> None:
    real_installer.install_old_version()
    real_installer.set_service("active")
    real_installer.set_unit("disabled")

    result = real_installer.run()

    assert result.returncode == 0, result.stderr
    assert real_installer.unit_state == "disabled"
    assert real_installer.service_state == "active"
    calls = real_installer.service_calls
    assert calls.index("--user stop stenographer.service") < calls.index(
        "--user start stenographer.service"
    )
    assert real_installer.installed_version() == _INSTALLED_MARKER


def test_an_enabled_service_stays_enabled(real_installer: Machine) -> None:
    real_installer.install_old_version()
    real_installer.set_unit("enabled")

    result = real_installer.run()

    assert result.returncode == 0, result.stderr
    assert real_installer.unit_state == "enabled"
    assert real_installer.service_state == "stopped"


@pytest.mark.parametrize(
    ("service", "options", "expected"),
    [
        ("stopped", [], ["--no-start", "--no-enable"]),
        ("stopped", ["--no-enable"], ["--no-enable", "--no-start"]),
        ("active", ["--no-start"], ["--no-start", "--no-enable"]),
    ],
)
def test_install_options_for_a_disabled_service(
    recording_installer: Machine, service: str, options: list[str], expected: list[str]
) -> None:
    recording_installer.set_service(service)
    recording_installer.set_unit("disabled")

    result = recording_installer.run(*options)

    assert result.returncode == 0, result.stderr
    assert recording_installer.installer_args == expected
    assert "--user start stenographer.service" not in recording_installer.service_calls


@pytest.mark.parametrize(
    ("service", "options", "expected"),
    [
        ("active", [], []),
        ("active", ["--verbose"], ["--verbose"]),
        ("active", ["--no-start"], ["--no-start"]),
        ("stopped", [], ["--no-start"]),
        ("stopped", ["--verbose"], ["--verbose", "--no-start"]),
        ("stopped", ["--no-start"], ["--no-start"]),
        ("stopped", ["--no-enable"], ["--no-enable", "--no-start"]),
    ],
)
def test_install_options_follow_the_service_state(
    recording_installer: Machine, service: str, options: list[str], expected: list[str]
) -> None:
    recording_installer.set_service(service)

    result = recording_installer.run(*options)

    assert result.returncode == 0, result.stderr
    assert recording_installer.installer_args == expected


def test_a_missing_systemctl_counts_as_not_running(recording_installer: Machine) -> None:
    tools = recording_installer.tmp_path / "tools-only"
    tools.mkdir()
    for tool in ("cp", "grep", "gzip", "mkdir", "mktemp", "rm", "sha256sum", "tar", "uname", "wc"):
        (tools / tool).symlink_to(shutil.which(tool))
    (tools / "curl").symlink_to(recording_installer.commands / "curl")
    recording_installer.env["PATH"] = str(tools)

    result = recording_installer.run()

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert recording_installer.installer_args == ["--no-start"]
