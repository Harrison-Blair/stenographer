# SPDX-License-Identifier: GPL-3.0-or-later
"""Notice-only "update available" check.

This module never updates anything: it compares the installed version against
the newest published release tag and, when the installed build is behind, hands
one sentence to the platform ``Notifier``. Updating stays a deliberate act by
the user.

The network cost is one metadata-only HTTPS HEAD to the ``releases/latest``
URL, which redirects to the tag; nothing is downloaded and no payload is read.
It runs off the hot path in a daemon thread (:func:`start_background_check`)
and is never joined, so a slow or unreachable network cannot delay the daemon.
Every failure is swallowed at DEBUG — a missing notice is not an error. The
result is cached in the state directory for :data:`CHECK_TTL_SECONDS`, and
:data:`NOTIFY_FLOOR_SECONDS` keeps a crash-looping daemon from re-notifying.

``feedback.update_check = false`` disables the check entirely.

The decision half (:func:`evaluate`) is pure and clock-injected; only
:func:`fetch_latest_tag` touches the network.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import ssl
    import urllib.request
    from collections.abc import Callable
    from pathlib import Path

    from stenographer.platform.base import Notifier

log = logging.getLogger(__name__)

CHECK_TTL_SECONDS = 24 * 3600
NOTIFY_FLOOR_SECONDS = 3600
FETCH_TIMEOUT_SECONDS = 5.0
LATEST_RELEASE_URL = "https://github.com/Harrison-Blair/stenographer/releases/latest"
TAG_URL_PREFIX = "https://github.com/Harrison-Blair/stenographer/releases/tag/"
RECORD_FILENAME = "update-check.json"
USER_AGENT = "stenographer-update-check"

# Same shape as scripts/release_guard.py: plain X.Y.Z, no leading zeros.
_TAG_RE = re.compile(r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


@dataclasses.dataclass(frozen=True)
class CheckRecord:
    """What the last check learned, persisted between daemon runs."""

    checked_at: float | None = None
    latest: str | None = None
    notified_at: float | None = None


def _last_segment(text: str) -> str:
    return text.rstrip("/").rsplit("/", 1)[-1]


def parse_release_tag(text: str) -> tuple[int, int, int] | None:
    """``"v1.2.3"``, ``"1.2.3"`` or a URL ending in one, else ``None``."""

    if not text:
        return None
    match = _TAG_RE.fullmatch(_last_segment(text))
    if match is None:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def load_record(text: str | None) -> CheckRecord:
    """Read a persisted record; anything unreadable is an empty record."""

    if not text:
        return CheckRecord()
    try:
        data = json.loads(text)
    except ValueError:
        return CheckRecord()
    if not isinstance(data, dict):
        return CheckRecord()
    latest = data.get("latest")
    return CheckRecord(
        checked_at=_optional_float(data.get("checked_at")),
        latest=latest if isinstance(latest, str) else None,
        notified_at=_optional_float(data.get("notified_at")),
    )


def dump_record(record: CheckRecord) -> str:
    return json.dumps(dataclasses.asdict(record))


def _within(elapsed: float, window: float) -> bool:
    """Two-sided on purpose: a one-sided window never expires.

    A box with no RTC boots with a far-future clock, writes that timestamp, and
    then gets corrected by NTP; a one-sided ``elapsed < window`` would then be
    true forever and silently disable the check for good. Out of range — in
    either direction, NaN included — means stale, which self-heals on the next
    run because the record is rewritten with the current clock.
    """

    return 0 <= elapsed < window


def needs_fetch(record: CheckRecord, now: float) -> bool:
    return record.checked_at is None or not _within(now - record.checked_at, CHECK_TTL_SECONDS)


def notification_message(installed: str, latest: str) -> str:
    """Render from the *parsed* tuple: no raw fetched string reaches the notice.

    ``latest`` must already satisfy :func:`parse_release_tag` — ``evaluate`` is
    the only caller and gates on exactly that.
    """

    number = ".".join(str(part) for part in parse_release_tag(latest))
    return (
        f"Stenographer {number} is available (installed {installed}). "
        "Re-run the quick install command from the README to update."
    )


def evaluate(
    record: CheckRecord, installed: str, fetched: str | None, now: float
) -> tuple[CheckRecord, str | None]:
    """Fold one (possibly absent) fetch into a new record and an optional notice."""

    if fetched is None:
        updated = record
    else:
        updated = dataclasses.replace(record, latest=fetched, checked_at=now)

    latest = updated.latest
    latest_version = parse_release_tag(latest) if latest else None
    installed_version = parse_release_tag(installed)
    if latest_version is None or installed_version is None:
        return updated, None
    if latest_version <= installed_version:
        return updated, None
    if record.notified_at is not None and _within(now - record.notified_at, NOTIFY_FLOOR_SECONDS):
        return updated, None
    return dataclasses.replace(updated, notified_at=now), notification_message(installed, latest)


def tag_from_location(url: str) -> str | None:
    """The tag a redirect landed on, or ``None`` if it is not our release URL.

    Pinning the prefix keeps a redirect we did not expect from ever reaching
    the notification text, and pairs with rendering the message from the parsed
    tuple: two independent reasons a URL cannot be displayed to the user.
    """

    if not url.startswith(TAG_URL_PREFIX):
        return None
    segment = _last_segment(url)
    return segment if parse_release_tag(segment) is not None else None


def build_request() -> urllib.request.Request:
    """The one request this module ever makes. Pure: it performs no I/O."""

    import urllib.request

    return urllib.request.Request(
        LATEST_RELEASE_URL, method="HEAD", headers={"User-Agent": USER_AGENT}
    )


def _ssl_context() -> ssl.SSLContext:
    import ssl

    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def fetch_latest_tag() -> str | None:
    """One HEAD to the latest-release URL; the redirect target carries the tag."""

    import urllib.request

    try:
        with urllib.request.urlopen(
            build_request(), timeout=FETCH_TIMEOUT_SECONDS, context=_ssl_context()
        ) as response:
            resolved = response.geturl()
    except Exception:
        log.debug("update_check: fetch_failed", exc_info=True)
        return None
    tag = tag_from_location(resolved)
    if tag is None:
        log.debug("update_check: unexpected_redirect_target")
    return tag


def run_check(
    installed: str,
    state_dir: Path,
    notifier: Notifier,
    *,
    now: Callable[[], float] = time.time,
    fetch: Callable[[], str | None] = fetch_latest_tag,
) -> None:
    """The whole check, start to notice. Never raises: it runs unsupervised."""

    try:
        path = state_dir / RECORD_FILENAME
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            text = None
        record = load_record(text)
        moment = now()
        attempted = needs_fetch(record, moment)
        fetched = fetch() if attempted else None
        updated, message = evaluate(record, installed, fetched, moment)
        if attempted and fetched is None:
            # A completed round-trip that yielded no usable tag (error page,
            # prerelease) still spends the TTL; otherwise every daemon start
            # would make a fresh request forever. This cannot live in
            # ``evaluate``, whose ``fetched is None`` branch also means "no
            # fetch was attempted" — stamping there would push the window
            # forward on restarts that never touched the network.
            updated = dataclasses.replace(updated, checked_at=moment)
        log.debug(
            "update_check: evaluated installed=%s latest=%s fetched=%s notify=%s",
            installed,
            updated.latest,
            fetched is not None,
            message is not None,
        )
        try:
            state_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(dump_record(updated), encoding="utf-8")
        except OSError:
            log.debug("update_check: record_not_written", exc_info=True)
        if message is not None:
            notifier.info(message)
    except Exception:
        log.debug("update_check: failed", exc_info=True)


def start_background_check(
    installed: str,
    state_dir: Path,
    notifier: Notifier,
    *,
    fetch: Callable[[], str | None] = fetch_latest_tag,
) -> threading.Thread:
    """Run :func:`run_check` in a daemon thread; never joined.

    ``daemon=True`` is load-bearing: a non-daemon thread blocked on a slow HEAD
    would hold up daemon shutdown.
    """

    thread = threading.Thread(
        target=run_check,
        args=(installed, state_dir, notifier),
        kwargs={"fetch": fetch},
        daemon=True,
        name="update-check",
    )
    thread.start()
    return thread
