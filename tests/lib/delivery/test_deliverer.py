# SPDX-License-Identifier: GPL-3.0-or-later
"""Delivery policy: copy → confirm → release-guard → paste chord.

The keyboard, the clipboard writer and the release wait are constructor
collaborators (``Deliverer`` calls that dependency wiring, not test mocking),
so the real policy runs here against recording stand-ins. The clipboard and
/dev/uinput themselves are exercised by the integration smoke suite.
"""

from __future__ import annotations

import logging

import pytest

from stenographer.lib.delivery.deliverer import Deliverer
from stenographer.lib.platform.clipboard_snapshot import ClipboardSnapshot

CANARY = "supercalifragilisticexpialidocious"


class RecordingKeyboard:
    """A key injector that records chords instead of emitting them."""

    def __init__(self) -> None:
        self.chords = 0
        self.closed = 0

    def send_chord(self) -> None:
        self.chords += 1

    def close(self) -> None:
        self.closed += 1


class RecordingClipboard:
    """A clipboard writer that records the text and reports a fixed verdict."""

    def __init__(self, *, result: bool = True, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.texts: list[str] = []

    def __call__(self, text: str) -> bool:
        self.texts.append(text)
        if self.error is not None:
            raise self.error
        return self.result


def _deliverer(
    *,
    copy: RecordingClipboard | None = None,
    keyboard: RecordingKeyboard | None = None,
    wait_released=None,
) -> tuple[Deliverer, RecordingClipboard, RecordingKeyboard]:
    copy = copy if copy is not None else RecordingClipboard()
    keyboard = keyboard if keyboard is not None else RecordingKeyboard()
    return Deliverer(keyboard=keyboard, copy=copy, wait_released=wait_released), copy, keyboard


def test_empty_text_is_not_delivered_and_leaves_no_side_effects():
    deliverer, copy, keyboard = _deliverer()

    assert deliverer.deliver("") is False
    assert copy.texts == []
    assert keyboard.chords == 0
    assert deliverer.last_timings is None


def test_cancellation_before_copy_never_touches_the_clipboard():
    deliverer, copy, keyboard = _deliverer()

    assert deliverer.deliver("hello ", cancelled=lambda: True) is False
    assert copy.texts == []
    assert keyboard.chords == 0
    assert deliverer.last_timings is None


def test_failed_copy_never_sends_the_chord():
    # A chord after a failed copy pastes whatever the clipboard held before.
    deliverer, copy, keyboard = _deliverer(copy=RecordingClipboard(result=False))

    assert deliverer.deliver("hello ") is False
    assert copy.texts == ["hello "]
    assert keyboard.chords == 0
    timings = deliverer.last_timings
    assert timings is not None
    assert timings.copied is False
    assert timings.chord_sent is False
    assert timings.copy_ms >= 0.0
    assert timings.release_wait_ms is None
    assert timings.release_timeout is None


def test_raising_copy_propagates_but_still_measures_the_attempt():
    deliverer, _copy, keyboard = _deliverer(
        copy=RecordingClipboard(error=RuntimeError("clipboard owner vanished"))
    )

    with pytest.raises(RuntimeError):
        deliverer.deliver("hello ")

    assert keyboard.chords == 0
    timings = deliverer.last_timings
    assert timings is not None
    assert timings.copied is False
    assert timings.chord_sent is False
    assert timings.copy_ms >= 0.0


def test_successful_delivery_copies_confirms_then_sends_one_chord():
    events: list[str] = []

    class OrderedClipboard(RecordingClipboard):
        def __call__(self, text: str) -> bool:
            events.append("copy")
            return super().__call__(text)

    class OrderedKeyboard(RecordingKeyboard):
        def send_chord(self) -> None:
            events.append("chord")
            super().send_chord()

    def wait_released() -> bool:
        events.append("wait")
        return True

    copy = OrderedClipboard()
    keyboard = OrderedKeyboard()
    deliverer = Deliverer(keyboard=keyboard, copy=copy, wait_released=wait_released)

    assert deliverer.deliver("hello ", on_copied=lambda: events.append("on_copied")) is True
    assert events == ["copy", "on_copied", "wait", "chord"]
    assert copy.texts == ["hello "]
    assert keyboard.chords == 1
    timings = deliverer.last_timings
    assert timings is not None
    assert timings.copied is True
    assert timings.chord_sent is True
    assert timings.release_timeout is False
    assert timings.release_wait_ms is not None


def test_delivery_without_a_release_wait_leaves_release_measurements_unknown():
    deliverer, _copy, keyboard = _deliverer()

    assert deliverer.deliver("hello ") is True
    assert keyboard.chords == 1
    timings = deliverer.last_timings
    assert timings is not None
    assert timings.release_wait_ms is None
    assert timings.release_timeout is None
    assert timings.chord_sent is True


def test_release_wait_timeout_proceeds_and_says_why(caplog):
    deliverer, _copy, keyboard = _deliverer(wait_released=lambda: False)

    with caplog.at_level(logging.WARNING, logger="stenographer.lib.delivery.deliverer"):
        assert deliverer.deliver("hello ") is True

    assert keyboard.chords == 1
    timings = deliverer.last_timings
    assert timings is not None
    assert timings.release_timeout is True
    assert timings.chord_sent is True
    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 1
    assert "deliver: binding_still_held" in messages[0]
    assert "action=proceed" in messages[0]
    assert "reason=copy_already_confirmed" in messages[0]


def test_release_wait_success_is_not_reported_as_a_timeout(caplog):
    deliverer, _copy, _keyboard = _deliverer(wait_released=lambda: True)

    with caplog.at_level(logging.WARNING, logger="stenographer.lib.delivery.deliverer"):
        assert deliverer.deliver("hello ") is True

    assert caplog.records == []
    assert deliverer.last_timings is not None
    assert deliverer.last_timings.release_timeout is False


def test_cancellation_after_the_copy_keeps_the_clipboard_but_skips_the_chord():
    # The transcript stays recoverable from the clipboard; only the paste is
    # abandoned, so the cancelled utterance cannot type into the cursor.
    verdicts = iter([False, True])
    deliverer, copy, keyboard = _deliverer()

    assert deliverer.deliver("hello ", cancelled=lambda: next(verdicts)) is False
    assert copy.texts == ["hello "]
    assert keyboard.chords == 0
    timings = deliverer.last_timings
    assert timings is not None
    assert timings.copied is True
    assert timings.chord_sent is False


def test_raising_release_wait_propagates_with_the_wait_measured():
    def wait_released() -> bool:
        raise RuntimeError("listener gone")

    deliverer, _copy, keyboard = _deliverer(wait_released=wait_released)

    with pytest.raises(RuntimeError):
        deliverer.deliver("hello ")

    assert keyboard.chords == 0
    timings = deliverer.last_timings
    assert timings is not None
    assert timings.copied is True
    assert timings.release_wait_ms is not None
    assert timings.release_timeout is None
    assert timings.chord_sent is False


def test_a_second_delivery_replaces_the_previous_timings():
    deliverer, _copy, _keyboard = _deliverer()
    deliverer.deliver("hello ")

    assert deliverer.deliver("") is False
    assert deliverer.last_timings is None


def test_close_releases_the_injected_keyboard():
    deliverer, _copy, keyboard = _deliverer()

    deliverer.close()

    assert keyboard.closed == 1


# --- original copy and clipboard restore ---------------------------------


SEED = ClipboardSnapshot(mime="text/plain;charset=utf-8", data=b"previous item")


class RecordingRestore:
    """A clipboard restorer that records each snapshot and reports a verdict."""

    def __init__(self, *, result: bool = True, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.snapshots: list[ClipboardSnapshot] = []

    def __call__(self, snapshot: ClipboardSnapshot) -> bool:
        self.snapshots.append(snapshot)
        if self.error is not None:
            raise self.error
        return self.result


def _restoring(
    *,
    copy: RecordingClipboard | None = None,
    keyboard: RecordingKeyboard | None = None,
    snapshot: ClipboardSnapshot | None = SEED,
    restore: RecordingRestore | None = None,
    events: list[str] | None = None,
):
    copy = copy if copy is not None else RecordingClipboard()
    keyboard = keyboard if keyboard is not None else RecordingKeyboard()
    restore = restore if restore is not None else RecordingRestore()
    events = events if events is not None else []
    sleeps: list[float] = []

    def read() -> ClipboardSnapshot | None:
        events.append("snapshot")
        return snapshot

    def sleep(seconds: float) -> None:
        events.append("sleep")
        sleeps.append(seconds)

    deliverer = Deliverer(
        keyboard=keyboard,
        copy=copy,
        read=read,
        restore=restore,
        restore_delay=0.5,
        sleep=sleep,
    )
    return deliverer, copy, keyboard, restore, sleeps


def test_the_original_is_copied_before_the_refined_text_then_the_chord():
    events: list[str] = []

    class OrderedClipboard(RecordingClipboard):
        def __call__(self, text: str) -> bool:
            events.append(f"copy:{text}")
            return super().__call__(text)

    class OrderedKeyboard(RecordingKeyboard):
        def send_chord(self) -> None:
            events.append("chord")
            super().send_chord()

    deliverer, _copy, keyboard, _restore, _sleeps = _restoring(
        copy=OrderedClipboard(), keyboard=OrderedKeyboard(), events=events
    )

    assert deliverer.deliver("refined ", original="original ") is True
    assert events == ["snapshot", "copy:original ", "copy:refined ", "chord"]
    assert keyboard.chords == 1
    timings = deliverer.last_timings
    assert timings is not None
    assert timings.original_copied is True
    assert timings.original_copy_ms is not None
    assert timings.snapshot_ms is not None
    assert timings.chord_sent is True


def test_a_failed_original_copy_still_delivers_the_refined_text(caplog):
    class FirstFails(RecordingClipboard):
        def __call__(self, text: str) -> bool:
            super().__call__(text)
            return len(self.texts) > 1

    deliverer, copy, keyboard, _restore, _sleeps = _restoring(copy=FirstFails())

    with caplog.at_level(logging.WARNING, logger="stenographer.lib.delivery.deliverer"):
        assert deliverer.deliver("refined ", original="original ") is True

    assert copy.texts == ["original ", "refined "]
    assert keyboard.chords == 1
    assert deliverer.last_timings.original_copied is False
    assert "deliver: original_copy_failed" in caplog.text


def test_a_raising_original_copy_still_delivers_and_never_logs_the_message(caplog):
    class FirstRaises(RecordingClipboard):
        def __call__(self, text: str) -> bool:
            super().__call__(text)
            if len(self.texts) == 1:
                raise RuntimeError(f"owner quoted {CANARY}")
            return True

    deliverer, copy, keyboard, _restore, _sleeps = _restoring(copy=FirstRaises())

    with caplog.at_level(logging.DEBUG, logger="stenographer.lib.delivery.deliverer"):
        assert deliverer.deliver("refined ", original="original ") is True

    assert copy.texts == ["original ", "refined "]
    assert keyboard.chords == 1
    assert deliverer.last_timings.original_copied is False
    assert "deliver: original_copy_failed" in caplog.text
    assert CANARY not in caplog.text


def test_no_original_is_written_without_one():
    deliverer, copy, _keyboard, _restore, _sleeps = _restoring()

    assert deliverer.deliver("refined ") is True
    assert copy.texts == ["refined "]
    assert deliverer.last_timings.original_copied is None
    assert deliverer.last_timings.original_copy_ms is None


def test_restore_runs_after_a_sent_chord_with_the_configured_delay():
    events: list[str] = []

    class OrderedRestore(RecordingRestore):
        def __call__(self, snapshot: ClipboardSnapshot) -> bool:
            events.append("restore")
            return super().__call__(snapshot)

    deliverer, _copy, _keyboard, restore, sleeps = _restoring(
        restore=OrderedRestore(), events=events
    )

    assert deliverer.deliver("refined ") is True
    assert restore.snapshots == []
    assert deliverer.restore_clipboard() is True

    assert restore.snapshots == [SEED]
    assert sleeps == [0.5]
    assert events[-2:] == ["sleep", "restore"]
    timings = deliverer.last_timings
    assert timings.restored is True
    assert timings.restore_ms is not None
    assert timings.chord_sent is True


def test_restore_runs_once_and_then_has_nothing_left_to_restore():
    deliverer, _copy, _keyboard, restore, sleeps = _restoring()

    deliverer.deliver("refined ")
    assert deliverer.restore_clipboard() is True
    assert deliverer.restore_clipboard() is False

    assert restore.snapshots == [SEED]
    assert sleeps == [0.5]


def test_restore_runs_when_cancelled_after_the_main_copy():
    verdicts = iter([False, False, True])
    deliverer, copy, keyboard, restore, _sleeps = _restoring()

    assert deliverer.deliver("refined ", cancelled=lambda: next(verdicts)) is False
    assert copy.texts == ["refined "]
    assert keyboard.chords == 0
    assert deliverer.restore_clipboard() is True
    assert restore.snapshots == [SEED]


def test_restore_runs_when_the_chord_raises():
    class BrokenKeyboard(RecordingKeyboard):
        def send_chord(self) -> None:
            raise RuntimeError("uinput gone")

    deliverer, _copy, _keyboard, restore, _sleeps = _restoring(keyboard=BrokenKeyboard())

    with pytest.raises(RuntimeError):
        deliverer.deliver("refined ")
    assert deliverer.restore_clipboard() is True
    assert restore.snapshots == [SEED]


def test_restore_runs_when_the_main_copy_fails_after_writing():
    deliverer, _copy, keyboard, restore, _sleeps = _restoring(copy=RecordingClipboard(result=False))

    assert deliverer.deliver("refined ") is False
    assert keyboard.chords == 0
    assert deliverer.restore_clipboard() is True
    assert restore.snapshots == [SEED]


def test_no_snapshot_and_no_restore_when_cancelled_before_any_write():
    events: list[str] = []
    deliverer, copy, _keyboard, restore, sleeps = _restoring(events=events)

    assert deliverer.deliver("refined ", cancelled=lambda: True) is False
    assert deliverer.restore_clipboard() is False
    assert events == []
    assert copy.texts == []
    assert restore.snapshots == []
    assert sleeps == []


def test_a_cancel_during_a_slow_snapshot_never_writes():
    verdicts = iter([False, True])
    deliverer, copy, _keyboard, restore, sleeps = _restoring()

    assert (
        deliverer.deliver("refined ", original="original ", cancelled=lambda: next(verdicts))
        is False
    )
    assert copy.texts == []
    assert deliverer.restore_clipboard() is False
    assert restore.snapshots == []
    assert sleeps == []


def test_no_restore_for_empty_text():
    events: list[str] = []
    deliverer, _copy, _keyboard, restore, sleeps = _restoring(events=events)

    assert deliverer.deliver("", original="original ") is False
    assert deliverer.restore_clipboard() is False
    assert events == []
    assert restore.snapshots == []
    assert sleeps == []


def test_no_restore_when_the_reader_found_nothing_to_keep():
    deliverer, copy, _keyboard, restore, sleeps = _restoring(snapshot=None)

    assert deliverer.deliver("refined ") is True
    assert deliverer.restore_clipboard() is False
    assert copy.texts == ["refined "]
    assert restore.snapshots == []
    assert sleeps == []


def test_a_raising_reader_still_delivers_without_a_restore(caplog):
    restore = RecordingRestore()

    def read() -> ClipboardSnapshot | None:
        raise RuntimeError(f"owner sent {CANARY}")

    keyboard = RecordingKeyboard()
    deliverer = Deliverer(
        keyboard=keyboard,
        copy=RecordingClipboard(),
        read=read,
        restore=restore,
        restore_delay=0.5,
        sleep=lambda _seconds: None,
    )

    with caplog.at_level(logging.DEBUG, logger="stenographer.lib.delivery.deliverer"):
        assert deliverer.deliver("refined ") is True
        assert deliverer.restore_clipboard() is False

    assert keyboard.chords == 1
    assert restore.snapshots == []
    assert "deliver: snapshot_failed" in caplog.text
    assert CANARY not in caplog.text


def test_a_failed_restore_returns_false_and_says_so(caplog):
    deliverer, _copy, _keyboard, _restore, _sleeps = _restoring(
        restore=RecordingRestore(result=False)
    )
    deliverer.deliver("refined ")

    with caplog.at_level(logging.WARNING, logger="stenographer.lib.delivery.deliverer"):
        assert deliverer.restore_clipboard() is False

    assert deliverer.last_timings.restored is False
    assert "deliver: restore_failed" in caplog.text


def test_a_raising_restore_returns_false_without_raising(caplog):
    deliverer, _copy, _keyboard, _restore, _sleeps = _restoring(
        restore=RecordingRestore(error=RuntimeError(f"wl-copy said {CANARY}"))
    )
    deliverer.deliver("refined ")

    with caplog.at_level(logging.DEBUG, logger="stenographer.lib.delivery.deliverer"):
        assert deliverer.restore_clipboard() is False

    assert deliverer.last_timings.restored is False
    assert "deliver: restore_failed" in caplog.text
    assert CANARY not in caplog.text


def test_a_new_delivery_drops_a_snapshot_the_last_one_never_restored():
    reads = iter([lambda: SEED, lambda: 1 / 0])
    restore = RecordingRestore()
    deliverer = Deliverer(
        keyboard=RecordingKeyboard(),
        copy=RecordingClipboard(),
        read=lambda: next(reads)(),
        restore=restore,
        restore_delay=0.0,
        sleep=lambda _seconds: None,
    )

    deliverer.deliver("first ")
    deliverer.deliver("second ")

    assert deliverer.restore_clipboard() is False
    assert restore.snapshots == []
