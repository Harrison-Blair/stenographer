# SPDX-License-Identifier: GPL-3.0-or-later
"""Self-update subcommand.

The :func:`check_for_update` and :func:`download_and_install`
functions are pure-Python and unit-testable. The CLI subcommand
in ``stenographer.cli:cmd_update`` wires them together with the
interactive prompt and the daemon stop / start steps.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import pathlib
import shutil
import ssl
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

import certifi
from packaging.version import InvalidVersion, Version

from stenographer import __version__
from stenographer.errors import UpdateError

_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

if TYPE_CHECKING:
    from stenographer.config import UpdateConfig

CHUNK_SIZE = 64 * 1024

_USER_AGENT = f"stenographer/{__version__} (+update)"
_DEFAULT_REPO_PATH = "Harrison-Blair/stenographer"
_DEFAULT_STAGING_PARENT = pathlib.Path("~/.local/share/stenographer/staging")
_DEFAULT_UPDATE_LOCK = pathlib.Path("/dev/null")  # overridden at call time

# Archive suffixes stripped when deriving the sibling .sha256 asset name
# from the asset_pattern output. The CI workflow produces
# "stenographer-<version>-linux-x86_64.sha256" (no .tar.gz in the middle).
_ARCHIVE_SUFFIXES: tuple[str, ...] = (
    ".tar.gz",
    ".tar.bz2",
    ".tar.xz",
    ".tgz",
    ".tbz2",
    ".txz",
    ".zip",
)


def _strip_archive_suffix(name: str) -> str:
    """Return ``name`` with a recognised archive extension removed.

    Falls back to ``os.path.splitext`` (strips the last suffix) for
    extensions not in :data:`_ARCHIVE_SUFFIXES`. Never returns an empty
    string; if ``name`` has no stem, the original is returned verbatim.
    """
    for suffix in _ARCHIVE_SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    stem, _, _ = name.rpartition(".")
    return stem or name


@dataclasses.dataclass(frozen=True)
class UpdateInfo:
    """Result of :func:`check_for_update`."""

    current_version: str
    latest_version: str
    tag_name: str
    asset_url: str
    asset_size: int
    sha256_url: str
    release_notes: str
    prerelease: bool


def _data_dir() -> pathlib.Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    base = pathlib.Path(xdg) if xdg else pathlib.Path.home() / ".local/share"
    return base / "stenographer"


def _runtime_dir() -> pathlib.Path:
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return pathlib.Path(xdg)
    return pathlib.Path(f"/run/user/{os.getuid()}")


def _http_get(url: str, *, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError(f"update: 404 not found: {url}") from exc
        raise UpdateError(f"update: HTTP {exc.code} on {url}") from exc
    except urllib.error.URLError as exc:
        raise UpdateError(f"update: network error on {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise UpdateError(f"update: timed out on {url}") from exc


def _http_get_json(url: str, *, timeout: int) -> object:
    return json.loads(_http_get(url, timeout=timeout))


def _parse_tag(tag_name: str) -> Version:
    raw = tag_name.lstrip("v")
    try:
        return Version(raw)
    except InvalidVersion as exc:
        raise UpdateError(f"update: cannot parse tag {tag_name!r} as a version") from exc


def _pick_release(
    releases: list[dict],
    *,
    channel: str,
    current: Version,
    development: bool = False,
) -> dict | None:
    """Return the highest-version release matching ``channel``.

    ``channel`` is ``"stable"`` (drop ``prerelease``) or ``"latest"``
    (keep all). Returns the raw release dict, or ``None`` if no
    release is newer than ``current`` (i.e. already up to date). Development
    builds instead select the newest matching release regardless of ordering,
    allowing a locally built newer dev version to switch to stable.
    """
    candidates: list[tuple[Version, dict]] = []
    for rel in releases:
        if channel == "stable" and rel.get("prerelease", False):
            continue
        try:
            v = _parse_tag(rel.get("tag_name", ""))
        except UpdateError:
            continue
        if not development and v <= current:
            continue
        candidates.append((v, rel))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    return candidates[-1][1]


def check_for_update(
    cfg: UpdateConfig,
    *,
    current_version: str | None = None,
    prerelease: bool = False,
) -> UpdateInfo | None:
    """Return the highest-version release newer than the running binary.

    Returns ``None`` when already up to date. ``current_version``
    defaults to the package's ``__version__`` and is overridable for
    testing. ``prerelease`` widens the channel to ``"latest"`` for
    this invocation.
    """
    current_str = current_version if current_version is not None else __version__
    try:
        current = Version(current_str)
    except InvalidVersion as exc:
        raise UpdateError(f"update: cannot parse current version {current_str!r}") from exc

    channel = "latest" if prerelease else cfg.channel
    url = f"{cfg.base_url}/repos/{cfg.repo}/releases?per_page=10"
    raw = _http_get_json(url, timeout=cfg.timeout_seconds)
    if not isinstance(raw, list):
        raise UpdateError(f"update: unexpected response shape from {url}: expected a list")
    development = current_str.endswith("-dev")
    chosen = _pick_release(raw, channel=channel, current=current, development=development)
    if chosen is None:
        return None
    tag = chosen.get("tag_name", "")
    raw_version = tag.lstrip("v")
    asset_name = cfg.asset_pattern.format(version=raw_version)
    sha_name = f"{_strip_archive_suffix(asset_name)}.sha256"

    asset = next((a for a in chosen.get("assets", []) if a.get("name") == asset_name), None)
    sha = next((a for a in chosen.get("assets", []) if a.get("name") == sha_name), None)
    if asset is None:
        raise UpdateError(f"update: release {tag} is missing the asset {asset_name!r}")
    if sha is None:
        raise UpdateError(f"update: release {tag} is missing the asset {sha_name!r}")

    return UpdateInfo(
        current_version=current_str,
        latest_version=raw_version,
        tag_name=tag,
        asset_url=asset["browser_download_url"],
        asset_size=int(asset.get("size", 0)),
        sha256_url=sha["browser_download_url"],
        release_notes=chosen.get("body", "") or "",
        prerelease=bool(chosen.get("prerelease", False)),
    )


def _download_to(url: str, dest: pathlib.Path, *, timeout: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with (
            urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp,
            dest.open("wb") as out,
        ):
            while True:
                chunk = resp.read(CHUNK_SIZE)
                if not chunk:
                    break
                out.write(chunk)
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"update: HTTP {exc.code} downloading {url}") from exc
    except urllib.error.URLError as exc:
        raise UpdateError(f"update: network error downloading {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise UpdateError(f"update: timed out downloading {url}") from exc


def _verify_sha256(tarball: pathlib.Path, sha_text: bytes) -> None:
    expected_line = None
    for line in sha_text.decode("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Format: "<hash>  <filename>" or "<hash> *<filename>"
        if "  " in line:
            expected_line = line
            break
        if " *" in line:
            expected_line = line.replace(" *", "  ", 1)
            break
    if expected_line is None:
        raise UpdateError("update: sha256 file is empty or malformed")
    expected_hash = expected_line.split()[0].lower()

    actual = hashlib.sha256()
    with tarball.open("rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            actual.update(chunk)
    actual_hash = actual.hexdigest().lower()
    if actual_hash != expected_hash:
        raise UpdateError(f"update: sha256 mismatch: expected {expected_hash}, got {actual_hash}")


def download_update(
    info: UpdateInfo,
    cfg: UpdateConfig,
    *,
    staging_dir: pathlib.Path | None = None,
) -> pathlib.Path:
    """Download the tarball and verify its SHA-256.

    Returns the path of the downloaded tarball. Leaves the tarball in
    place; :func:`apply_update` is responsible for extraction and the
    atomic swap.
    """
    parent = staging_dir if staging_dir is not None else _data_dir() / "staging"
    parent.mkdir(parents=True, exist_ok=True)
    tarball = parent / f"stenographer-{info.latest_version}.tar.gz"
    _download_to(info.asset_url, tarball, timeout=cfg.timeout_seconds)
    sha_text = _http_get(info.sha256_url, timeout=cfg.timeout_seconds)
    _verify_sha256(tarball, sha_text)
    return tarball


def detect_install_root() -> pathlib.Path:
    """Return the onedir bundle directory containing the running binary.

    Detects a frozen PyInstaller ``--onedir`` bundle by resolving the
    running executable and checking for a sibling ``_internal/``
    directory. Resolving the executable preserves installations whose
    launcher is reached through a symlink outside the bundle. Raises
    :class:`UpdateError` for a wheel / pipx install: swapping out the
    directory containing the console script would clobber unrelated
    files (e.g. ``~/.local/bin``).
    """
    if getattr(sys, "frozen", False):
        install_root = pathlib.Path(sys.executable).resolve().parent
        if (install_root / "_internal").is_dir():
            return install_root
    raise UpdateError(
        "update: self-update is only supported for the onedir binary install; "
        "use pip/pipx to upgrade this installation"
    )


def extract_to_staging(tarball: pathlib.Path, install_root: pathlib.Path) -> pathlib.Path:
    """Extract ``tarball`` to a sibling staging directory.

    The staging directory is ``<install_root>.new.<pid>``. The
    onedir tarball's top-level entry is ``stenographer/``; the
    extracted bundle is at ``<staging>/stenographer``.
    """
    staging = install_root.with_name(f"{install_root.name}.new.{os.getpid()}")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    with tarfile.open(tarball, "r:gz") as tf:
        tf.extractall(staging)
    bundle = staging / "stenographer"
    if not bundle.is_dir():
        raise UpdateError(
            f"update: extracted tarball is missing the 'stenographer/' directory at {staging}"
        )
    return bundle


def _sanity_check_bundle(bundle: pathlib.Path) -> None:
    if not (bundle / "stenographer").is_file():
        raise UpdateError(
            f"update: extracted bundle is missing the launcher at {bundle}/stenographer"
        )


def apply_update(
    bundle: pathlib.Path,
    install_root: pathlib.Path,
) -> None:
    """Swap ``bundle`` over ``install_root`` on the same filesystem.

    ``bundle`` is the extracted onedir directory (containing
    ``_internal/`` and the launcher). ``install_root`` is the existing
    onedir directory being replaced. ``os.replace`` is the only
    operation that is atomic across the swap, but on Linux it cannot
    overwrite a non-empty directory; we therefore do a two-step
    rename (target -> backup, source -> target) which leaves the
    system in either the old state or the new state, never in
    between (modulo crashes between the two renames, in which case
    the backup is restored on the next attempt).
    """
    _sanity_check_bundle(bundle)
    parent = install_root.parent
    if bundle.parent.parent != parent:
        raise UpdateError(
            f"update: staging dir {bundle.parent} is not a sibling of {install_root}; "
            "cross-filesystem rename is not supported"
        )
    backup = install_root.with_name(f"{install_root.name}.old.{os.getpid()}")
    if backup.exists():
        shutil.rmtree(backup)
    os.rename(install_root, backup)
    try:
        os.rename(bundle, install_root)
    except OSError:
        if backup.exists():
            os.rename(backup, install_root)
        raise
    else:
        shutil.rmtree(backup, ignore_errors=True)
        shutil.rmtree(bundle.parent, ignore_errors=True)


def stop_daemon() -> bool:
    """Best-effort ``systemctl --user stop`` of the daemon.

    Returns True if the daemon was running and a stop was issued;
    False if the unit is missing or systemctl is unavailable.
    """
    if shutil.which("systemctl") is None:
        return False
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", "stenographer.service"],
            check=False,
        )
    except OSError:
        return False
    if result.returncode != 0:
        return False
    subprocess.run(
        ["systemctl", "--user", "stop", "stenographer.service"],
        check=False,
    )
    return True


def start_daemon() -> bool:
    """Best-effort ``systemctl --user start`` of the daemon.

    Returns True if the unit was found and a start was issued;
    False if the unit is missing or systemctl is unavailable.
    """
    if shutil.which("systemctl") is None:
        return False
    try:
        result = subprocess.run(
            [
                "systemctl",
                "--user",
                "cat",
                "stenographer.service",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    if result.returncode != 0:
        return False
    start = subprocess.run(
        ["systemctl", "--user", "start", "stenographer.service"],
        check=False,
    )
    return start.returncode == 0


def acquire_update_lock() -> int | None:
    """Acquire an exclusive flock preventing concurrent ``update`` runs.

    Returns the file descriptor (caller closes it) or ``None`` if
    another update is in progress.
    """
    lock_path = _runtime_dir() / "stenographer-update.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    import fcntl

    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    os.write(fd, f"{os.getpid()}\n".encode())
    return fd
