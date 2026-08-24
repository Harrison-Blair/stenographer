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
import os

import pytest

from stenographer.update_check import (
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
        ("https://github.com/Harrison-Blair/stenographer/releases/tag/v0.12.0", (0, 12, 0)),
        ("https://github.com/Harrison-Blair/stenographer/releases/tag/v0.12.0/", (0, 12, 0)),
    ],
)
def test_parse_release_tag_accepts_tags_and_urls(text, expected):
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


@pytest.mark.parametrize("text", [None, "", "{", "[]", '"v1.2.3"', "null", "not json at all"])
def test_load_record_tolerates_missing_and_corrupt_text(text):
    assert load_record(text) == CheckRecord()


def test_load_record_drops_wrongly_typed_fields():
    text = json.dumps({"checked_at": "yesterday", "latest": 12, "notified_at": [1]})

    assert load_record(text) == CheckRecord()


def test_load_record_keeps_wellformed_fields():
    text = json.dumps({"checked_at": 10, "latest": "v9.9.9", "notified_at": 20.5})

    assert load_record(text) == CheckRecord(checked_at=10.0, latest="v9.9.9", notified_at=20.5)


def test_dump_and_load_round_trip():
    record = CheckRecord(checked_at=1000.0, latest="v0.12.0", notified_at=1000.0)

    assert load_record(dump_record(record)) == record


def test_needs_fetch_is_true_when_never_checked():
    assert needs_fetch(CheckRecord(), 1000.0)


def test_needs_fetch_is_false_within_the_ttl():
    record = CheckRecord(checked_at=1000.0)

    assert not needs_fetch(record, 1000.0 + CHECK_TTL_SECONDS - 1)


def test_needs_fetch_is_true_once_the_ttl_has_elapsed():
    record = CheckRecord(checked_at=1000.0)

    assert needs_fetch(record, 1000.0 + CHECK_TTL_SECONDS)


def test_needs_fetch_is_true_when_the_record_is_from_the_future():
    """A clock correction must not disable the check forever.

    An RTC-less box boots at a bogus far-future time, writes that as
    ``checked_at``, then NTP pulls the clock back. A one-sided window would
    stay inside the TTL for decades.
    """

    record = CheckRecord(checked_at=4_000_000_000.0)

    assert needs_fetch(record, 1_770_000_000.0)


def test_needs_fetch_is_true_for_a_nonfinite_timestamp():
    """``json.loads`` accepts bare ``NaN``; every comparison against it is False."""

    assert needs_fetch(CheckRecord(checked_at=math.nan), 1000.0)


@pytest.mark.parametrize("bogus", [math.inf, -math.inf])
def test_needs_fetch_is_true_for_an_infinite_timestamp(bogus):
    assert needs_fetch(CheckRecord(checked_at=bogus), 1000.0)


def test_evaluate_notifies_despite_a_nonfinite_notified_at():
    record = CheckRecord(checked_at=500.0, latest="v0.12.0", notified_at=math.nan)

    _, message = evaluate(record, "0.11.5", None, 1000.0)

    assert message == notification_message("0.11.5", "v0.12.0")


def test_evaluate_notifies_despite_a_future_notified_at():
    record = CheckRecord(checked_at=500.0, latest="v0.12.0", notified_at=4_000_000_000.0)

    updated, message = evaluate(record, "0.11.5", None, 1000.0)

    assert message == notification_message("0.11.5", "v0.12.0")
    assert updated.notified_at == 1000.0


def test_evaluate_notifies_when_installed_is_behind():
    updated, message = evaluate(CheckRecord(), "0.11.5", "v0.12.0", 1000.0)

    assert updated == CheckRecord(checked_at=1000.0, latest="v0.12.0", notified_at=1000.0)
    assert message == notification_message("0.11.5", "v0.12.0")


def test_evaluate_is_silent_when_versions_match():
    updated, message = evaluate(CheckRecord(), "0.11.5", "v0.11.5", 1000.0)

    assert message is None
    assert updated == CheckRecord(checked_at=1000.0, latest="v0.11.5")


def test_evaluate_is_silent_when_installed_is_ahead():
    """A local dev build is ahead of the newest published tag; that is not news."""

    updated, message = evaluate(CheckRecord(), "0.11.5", "v0.11.0", 1000.0)

    assert message is None
    assert updated.notified_at is None


def test_evaluate_without_a_fetch_keeps_the_cached_tag_and_still_notifies():
    record = CheckRecord(checked_at=500.0, latest="v0.12.0")

    updated, message = evaluate(record, "0.11.5", None, 1000.0)

    assert updated.checked_at == 500.0
    assert updated.latest == "v0.12.0"
    assert updated.notified_at == 1000.0
    assert message == notification_message("0.11.5", "v0.12.0")


def test_evaluate_suppresses_a_repeat_inside_the_notify_floor():
    record = CheckRecord(checked_at=500.0, latest="v0.12.0", notified_at=900.0)

    updated, message = evaluate(record, "0.11.5", None, 900.0 + NOTIFY_FLOOR_SECONDS - 1)

    assert message is None
    assert updated.notified_at == 900.0


def test_evaluate_notifies_again_once_the_floor_has_passed():
    record = CheckRecord(checked_at=500.0, latest="v0.12.0", notified_at=900.0)
    now = 900.0 + NOTIFY_FLOOR_SECONDS

    updated, message = evaluate(record, "0.11.5", None, now)

    assert message == notification_message("0.11.5", "v0.12.0")
    assert updated.notified_at == now


def test_evaluate_is_silent_when_the_installed_version_is_unparseable():
    updated, message = evaluate(CheckRecord(), "0.11.5.dev1+local", "v0.12.0", 1000.0)

    assert message is None
    assert updated.notified_at is None


def test_evaluate_is_silent_when_the_fetched_tag_is_unparseable():
    updated, message = evaluate(CheckRecord(), "0.11.5", "latest", 1000.0)

    assert message is None
    assert updated.latest == "latest"


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


def test_notification_message_can_never_render_a_url():
    """Rendered from the parsed tuple, so even a URL collapses to digits."""

    message = notification_message("0.11.5", f"{TAG_URL}v0.12.0")

    assert "/" not in message
    assert message == notification_message("0.11.5", "v0.12.0")


def test_notification_message_never_shows_the_v_prefix():
    assert "v0.12.0" not in notification_message("0.11.5", "v0.12.0")


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

    if os.environ.get("STENOGRAPHER_INTEGRATION") != "1":
        pytest.skip("integration suite requires STENOGRAPHER_INTEGRATION=1")

    tag = fetch_latest_tag()

    assert tag is not None
    assert parse_release_tag(tag) is not None
    # Pins what no offline test can reach: the redirect target is reduced to a
    # bare tag, not carried through whole. parse_release_tag alone would accept
    # the full URL, so assert the shape directly.
    assert "/" not in tag
    assert tag == tag_from_location(f"{TAG_URL}{tag}")
