# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure tests for the notice-only update check.

Everything here is either the pure decision half (parse/load/dump/needs_fetch/
evaluate) or :func:`run_check` driven with an injected clock, an injected
fetch, a real ``tmp_path`` state directory, and a recording notifier. Nothing
mocks urllib, threads, or the desktop notifier: the recording notifier is a
test double of the ``Notifier`` Protocol, not a stand-in for an OS call.

The one network test is marked ``integration`` and skipped without
STENOGRAPHER_INTEGRATION=1.
"""

from __future__ import annotations

import json
import math

import pytest

from stenographer.lib.updates.notice import (
    CHECK_TTL_SECONDS,
    LATEST_RELEASE_URL,
    NOTIFY_FLOOR_SECONDS,
    RECORD_FILENAME,
    USER_AGENT,
    CheckRecord,
    build_request,
    dump_record,
    evaluate,
    fetch_latest_tag,
    load_record,
    needs_fetch,
    notification_message,
    parse_release_tag,
    run_check,
    start_background_check,
    tag_from_location,
)

TAG_URL = "https://github.com/Harrison-Blair/stenographer/releases/tag/"


class RecordingNotifier:
    """A ``Notifier`` double that keeps what it was asked to show."""

    def __init__(self) -> None:
        self.infos: list[str] = []
        self.errors: list[str] = []

    def info(self, message: str) -> None:
        self.infos.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("v1.2.3", (1, 2, 3)),
        ("1.2.3", (1, 2, 3)),
        ("v0.11.5", (0, 11, 5)),
    ],
)
def test_parse_release_tag_accepts_tags(text, expected):
    assert parse_release_tag(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "latest",
        "v1.2",
        "1.2.3.4",
        "v01.2.3",
        "v1.02.3",
        "v1.2.3-rc1",
        "v1.2.3rc1",
        "version 1.2.3",
        "vv1.2.3",
    ],
)
def test_parse_release_tag_rejects_anything_else(text):
    assert parse_release_tag(text) is None


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "{",
        "[]",
        '"v1.2.3"',
        "null",
        "not json at all",
        json.dumps({"checked_at": "yesterday", "latest": 12, "notified_at": [1]}),
    ],
)
def test_load_record_tolerates_missing_and_corrupt_text(text):
    assert load_record(text) == CheckRecord()


def test_load_record_keeps_wellformed_fields():
    text = json.dumps({"checked_at": 10, "latest": "v9.9.9", "notified_at": 20.5})

    assert load_record(text) == CheckRecord(checked_at=10.0, latest="v9.9.9", notified_at=20.5)


def test_dump_and_load_round_trip():
    record = CheckRecord(checked_at=1000.0, latest="v0.12.0", notified_at=1000.0)

    assert load_record(dump_record(record)) == record


@pytest.mark.parametrize(
    ("checked_at", "now", "expected"),
    [
        (None, 1000.0, True),
        (1000.0, 1000.0 + CHECK_TTL_SECONDS - 1, False),
        (1000.0, 1000.0 + CHECK_TTL_SECONDS, True),
        # An RTC-less box can record a far-future time before NTP corrects it.
        (4_000_000_000.0, 1_770_000_000.0, True),
        # json.loads accepts NaN, and comparisons with it are false.
        (math.nan, 1000.0, True),
        (math.inf, 1000.0, True),
        (-math.inf, 1000.0, True),
    ],
)
def test_needs_fetch(checked_at, now, expected):
    assert needs_fetch(CheckRecord(checked_at=checked_at), now) is expected


@pytest.mark.parametrize(
    ("record", "installed", "fetched", "now", "expected_record", "notifies"),
    [
        (
            CheckRecord(500.0, "v0.12.0", math.nan),
            "0.11.5",
            None,
            1000.0,
            CheckRecord(500.0, "v0.12.0", 1000.0),
            True,
        ),
        (
            CheckRecord(500.0, "v0.12.0", 4_000_000_000.0),
            "0.11.5",
            None,
            1000.0,
            CheckRecord(500.0, "v0.12.0", 1000.0),
            True,
        ),
        (
            CheckRecord(),
            "0.11.5",
            "v0.12.0",
            1000.0,
            CheckRecord(latest="v0.12.0", notified_at=1000.0),
            True,
        ),
        (CheckRecord(), "0.11.5", "v0.11.5", 1000.0, CheckRecord(latest="v0.11.5"), False),
        # A local dev build ahead of the published tag is not news.
        (CheckRecord(), "0.11.5", "v0.11.0", 1000.0, CheckRecord(latest="v0.11.0"), False),
        (
            CheckRecord(500.0, "v0.12.0"),
            "0.11.5",
            None,
            1000.0,
            CheckRecord(500.0, "v0.12.0", 1000.0),
            True,
        ),
        (
            CheckRecord(500.0, "v0.12.0", 900.0),
            "0.11.5",
            None,
            900.0 + NOTIFY_FLOOR_SECONDS - 1,
            CheckRecord(500.0, "v0.12.0", 900.0),
            False,
        ),
        (
            CheckRecord(500.0, "v0.12.0", 900.0),
            "0.11.5",
            None,
            900.0 + NOTIFY_FLOOR_SECONDS,
            CheckRecord(500.0, "v0.12.0", 900.0 + NOTIFY_FLOOR_SECONDS),
            True,
        ),
        (
            CheckRecord(),
            "0.11.5.dev1+local",
            "v0.12.0",
            1000.0,
            CheckRecord(latest="v0.12.0"),
            False,
        ),
        (CheckRecord(), "0.11.5", "latest", 1000.0, CheckRecord(latest="latest"), False),
    ],
)
def test_evaluate(record, installed, fetched, now, expected_record, notifies):
    updated, message = evaluate(record, installed, fetched, now)

    assert updated == expected_record
    assert message == (
        notification_message(installed, expected_record.latest) if notifies else None
    )


def test_notification_message_is_exact():
    assert notification_message("0.11.5", "v0.12.0") == (
        "Stenographer 0.12.0 is available (installed 0.11.5). "
        "Re-run the quick install command from the README to update."
    )


def test_tag_from_location_accepts_the_real_redirect_shape():
    assert tag_from_location(f"{TAG_URL}v0.11.5") == "v0.11.5"


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/Harrison-Blair/stenographer/releases/tag/v0.12.0",
        "https://github.com/someone-else/stenographer/releases/tag/v0.12.0",
        "https://example.com/releases/tag/v0.12.0",
        "https://github.com/Harrison-Blair/stenographer/releases/latest",
        f"{TAG_URL}not-a-tag",
        "v0.12.0",
    ],
)
def test_tag_from_location_rejects_anything_but_our_release_tag_url(url):
    """A redirect we did not expect must never reach the notification text."""

    assert tag_from_location(url) is None


def test_build_request_is_a_bare_head_with_our_user_agent():
    """AGENTS calls the request metadata-only: HEAD, no query string, no extras."""

    request = build_request()

    assert request.get_method() == "HEAD"
    assert request.full_url == LATEST_RELEASE_URL
    assert request.headers == {"User-agent": USER_AGENT}


def test_run_check_writes_the_record_and_notifies_once(tmp_path):
    notifier = RecordingNotifier()

    run_check(
        "0.11.5",
        tmp_path,
        notifier,
        now=lambda: 1000.0,
        fetch=lambda: "v9.9.9",
    )

    assert notifier.infos == [notification_message("0.11.5", "v9.9.9")]
    assert notifier.errors == []
    written = (tmp_path / RECORD_FILENAME).read_text(encoding="utf-8")
    assert load_record(written) == CheckRecord(
        checked_at=1000.0, latest="v9.9.9", notified_at=1000.0
    )


def test_run_check_creates_a_missing_state_directory(tmp_path):
    state_dir = tmp_path / "missing" / "state"
    notifier = RecordingNotifier()

    run_check("0.11.5", state_dir, notifier, now=lambda: 1000.0, fetch=lambda: "v9.9.9")

    assert (state_dir / RECORD_FILENAME).exists()


def test_run_check_stays_silent_when_the_fetch_fails(tmp_path):
    """A failed attempt still spends the TTL, or every start would refetch."""

    notifier = RecordingNotifier()

    run_check("0.11.5", tmp_path, notifier, now=lambda: 1000.0, fetch=lambda: None)

    assert notifier.infos == []
    written = (tmp_path / RECORD_FILENAME).read_text(encoding="utf-8")
    assert load_record(written) == CheckRecord(checked_at=1000.0)


def test_run_check_keeps_the_cached_tag_when_a_later_fetch_fails(tmp_path):
    """The attempt is recorded, the known tag survives, and the notice still fires."""

    (tmp_path / RECORD_FILENAME).write_text(
        dump_record(CheckRecord(checked_at=1000.0, latest="v9.9.9")), encoding="utf-8"
    )
    notifier = RecordingNotifier()
    later = 1000.0 + CHECK_TTL_SECONDS + 1

    run_check("0.11.5", tmp_path, notifier, now=lambda: later, fetch=lambda: None)

    written = load_record((tmp_path / RECORD_FILENAME).read_text(encoding="utf-8"))
    assert written.checked_at == later
    assert written.latest == "v9.9.9"
    assert notifier.infos == [notification_message("0.11.5", "v9.9.9")]


def test_run_check_does_not_refetch_inside_the_ttl(tmp_path):
    (tmp_path / RECORD_FILENAME).write_text(
        dump_record(CheckRecord(checked_at=1000.0, latest="v9.9.9")), encoding="utf-8"
    )
    notifier = RecordingNotifier()

    def refuse() -> str | None:
        raise AssertionError("fetched inside the TTL")

    run_check("0.11.5", tmp_path, notifier, now=lambda: 1001.0, fetch=refuse)

    assert notifier.infos == [notification_message("0.11.5", "v9.9.9")]
    # No attempt was made, so the window must not be pushed forward: a
    # frequently restarted daemon would otherwise never refetch.
    written = load_record((tmp_path / RECORD_FILENAME).read_text(encoding="utf-8"))
    assert written.checked_at == 1000.0


def test_run_check_notifies_even_when_the_record_file_cannot_be_read(tmp_path):
    """An unreadable record is an empty record; the notice must not depend on state."""

    (tmp_path / RECORD_FILENAME).mkdir()
    notifier = RecordingNotifier()

    run_check("0.11.5", tmp_path, notifier, now=lambda: 1000.0, fetch=lambda: "v9.9.9")

    assert notifier.infos == [notification_message("0.11.5", "v9.9.9")]


def test_run_check_survives_a_notifier_that_raises(tmp_path):
    class BrokenNotifier(RecordingNotifier):
        def info(self, message: str) -> None:
            raise RuntimeError("no notification daemon")

    run_check("0.11.5", tmp_path, BrokenNotifier(), now=lambda: 1000.0, fetch=lambda: "v9.9.9")

    assert (tmp_path / RECORD_FILENAME).exists()


def test_start_background_check_runs_off_a_daemon_thread(tmp_path):
    """``daemon=True`` is load-bearing: a non-daemon thread delays shutdown."""

    notifier = RecordingNotifier()

    thread = start_background_check("0.11.5", tmp_path, notifier, fetch=lambda: "v9.9.9")
    thread.join(timeout=5)

    assert thread.daemon is True
    assert thread.name == "update-check"
    assert not thread.is_alive()
    assert notifier.infos == [notification_message("0.11.5", "v9.9.9")]
    assert (tmp_path / RECORD_FILENAME).exists()


@pytest.mark.integration
def test_fetch_latest_tag_returns_a_parseable_tag():
    """The real redirect: one HEAD to GitHub, tag only, no download."""

    tag = fetch_latest_tag()

    assert tag is not None
    assert parse_release_tag(tag) is not None
    # Pins what no offline test can reach: the redirect target is reduced to a
    # bare tag, not carried through whole.
    assert "/" not in tag
    assert tag == tag_from_location(f"{TAG_URL}{tag}")
