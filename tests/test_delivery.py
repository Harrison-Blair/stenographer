# SPDX-License-Identifier: GPL-3.0-or-later
"""Component tests for the final-output delivery boundary."""

from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock

from stenographer.config import Config
from stenographer.output.delivery import TranscriptDelivery


def _make_delivery(
    *,
    mode: str = "type",
    clipboard: bool = True,
    max_chars: int | None = None,
    has_paste_trigger: bool = True,
    has_wl_copy: bool = True,
) -> tuple[TranscriptDelivery, dict[str, MagicMock]]:
    cfg = Config.defaults()
    output = dataclasses.replace(cfg.output, injection_method=mode)
    if max_chars is not None:
        output = dataclasses.replace(output, max_chars=max_chars)
    clipboard_cfg = dataclasses.replace(cfg.clipboard, enabled=clipboard)
    components = {
        "caps": MagicMock(has_paste_trigger=has_paste_trigger, has_wl_copy=has_wl_copy),
        "injector": MagicMock(),
        "clipboard": MagicMock(),
    }
    components["injector"].type_text.return_value = True
    components["injector"].paste.return_value = True
    components["clipboard"].copy.return_value = True
    delivery = TranscriptDelivery(
        output=output,
        clipboard_cfg=clipboard_cfg,
        capabilities=components["caps"],
        injector=components["injector"],
        clipboard=components["clipboard"],
    )
    return delivery, components


def test_empty_text_is_not_delivered() -> None:
    delivery, components = _make_delivery()
    assert delivery.deliver_final("") is False
    components["injector"].type_text.assert_not_called()
    components["clipboard"].copy.assert_not_called()


def test_type_mode_injects_and_copies_full_text() -> None:
    delivery, components = _make_delivery(mode="type", clipboard=True)
    assert delivery.deliver_final("Hello world ")
    components["injector"].type_text.assert_called_once_with("Hello world ", raw=True)
    components["clipboard"].copy.assert_called_once_with("Hello world ", primary=True)
    components["injector"].paste.assert_not_called()


def test_max_chars_caps_typed_text_but_not_copied_text() -> None:
    delivery, components = _make_delivery(mode="type", max_chars=5)
    assert delivery.deliver_final("abcdefgh")
    components["injector"].type_text.assert_called_once_with("abcde", raw=True)
    # The cap bounds what is typed, not what is recoverable.
    components["clipboard"].copy.assert_called_once_with("abcdefgh", primary=True)


def test_disabled_clipboard_skips_recovery_copy() -> None:
    delivery, components = _make_delivery(mode="type", clipboard=False)
    assert delivery.deliver_final("Hello ")
    components["injector"].type_text.assert_called_once_with("Hello ", raw=True)
    components["clipboard"].copy.assert_not_called()


def test_copy_counts_as_delivery_without_paste_trigger() -> None:
    delivery, components = _make_delivery(mode="type", has_paste_trigger=False)
    assert delivery.deliver_final("Hello world ")
    components["injector"].type_text.assert_not_called()
    components["clipboard"].copy.assert_called_once_with("Hello world ", primary=True)


def test_type_mode_returns_false_when_nothing_reaches_the_user() -> None:
    delivery, components = _make_delivery(mode="type", has_paste_trigger=False)
    components["clipboard"].copy.return_value = False
    assert delivery.deliver_final("Hello ") is False


def test_injector_raise_is_logged_and_copy_still_delivers() -> None:
    delivery, components = _make_delivery(mode="type", clipboard=True)
    components["injector"].type_text.side_effect = RuntimeError("wtype blew up")
    assert delivery.deliver_final("Hello ")
    components["clipboard"].copy.assert_called_once_with("Hello ", primary=True)


def test_paste_mode_copies_before_firing_chord() -> None:
    delivery, components = _make_delivery(mode="clipboard_paste")
    calls: list[str] = []
    components["clipboard"].copy.side_effect = lambda *a, **k: calls.append("copy") or True
    components["injector"].paste.side_effect = lambda *a, **k: calls.append("paste") or True

    assert delivery.deliver_final("Hello world ")

    components["clipboard"].copy.assert_called_once_with("Hello world ", primary=True)
    components["injector"].paste.assert_called_once_with()
    assert calls == ["copy", "paste"]


def test_paste_mode_copy_failure_never_fires_chord(monkeypatch) -> None:
    delivery, components = _make_delivery(mode="clipboard_paste")
    components["clipboard"].copy.return_value = False
    notify = MagicMock()
    monkeypatch.setattr("stenographer.output.delivery.notify_failure", notify)

    assert delivery.deliver_final("Hello ") is False

    components["clipboard"].copy.assert_called_once_with("Hello ", primary=True)
    components["injector"].paste.assert_not_called()
    notify.assert_called_once()


def test_paste_mode_without_wl_copy_notifies_and_returns_false(monkeypatch) -> None:
    delivery, components = _make_delivery(mode="clipboard_paste", has_wl_copy=False)
    notify = MagicMock()
    monkeypatch.setattr("stenographer.output.delivery.notify_failure", notify)

    assert delivery.deliver_final("Hello ") is False

    notify.assert_called_once()
    components["clipboard"].copy.assert_not_called()
    components["injector"].paste.assert_not_called()


def test_paste_mode_paste_raise_returns_false() -> None:
    delivery, components = _make_delivery(mode="clipboard_paste")
    components["injector"].paste.side_effect = RuntimeError("paste blew up")
    assert delivery.deliver_final("Hello ") is False
