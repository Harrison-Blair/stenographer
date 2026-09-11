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
    assert "reason=clipboard_already_holds_transcript" in messages[0]


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
