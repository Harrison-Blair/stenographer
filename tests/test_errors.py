# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for :mod:`stenographer.errors`."""

from __future__ import annotations

import ast
import logging
import sys
from pathlib import Path

import pytest

from stenographer import errors
from stenographer.errors import (
    AudioCaptureError,
    CapabilityError,
    ConfigError,
    StenographerError,
    TranscriptionError,
    degrade_capability,
    fatal,
    notify_failure,
)

EXCEPTION_CLASSES: tuple[type[StenographerError], ...] = (
    StenographerError,
    ConfigError,
    CapabilityError,
    AudioCaptureError,
    TranscriptionError,
)


@pytest.mark.parametrize("cls", EXCEPTION_CLASSES)
def test_exception_is_subclass_of_stenographer_error(cls: type[StenographerError]) -> None:
    assert issubclass(cls, StenographerError)
    assert issubclass(cls, Exception)


@pytest.mark.parametrize("cls", EXCEPTION_CLASSES)
def test_exception_carries_message(cls: type[StenographerError]) -> None:
    with pytest.raises(cls) as exc_info:
        raise cls("boom")
    assert exc_info.value.message == "boom"
    assert exc_info.value.args == ("boom",)


def test_module_logger_name() -> None:
    assert errors.log.name == "stenographer.errors"


def test_notify_failure_logs_at_error(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR, logger="stenographer.errors"):
        notify_failure("transcoder crashed")
    matches = [
        record
        for record in caplog.records
        if record.name == "stenographer.errors"
        and record.levelno == logging.ERROR
        and record.getMessage() == "notify_failure: transcoder crashed"
    ]
    assert matches, (
        f"missing expected ERROR log; got: "
        f"{[(r.levelname, r.getMessage()) for r in caplog.records]}"
    )


def test_fatal_default_code_exits_78(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    exits: list[int] = []
    monkeypatch.setattr(sys, "exit", lambda code: exits.append(code))
    with caplog.at_level(logging.CRITICAL, logger="stenographer.errors"):
        fatal("something broke")
    assert exits == [78]


def test_fatal_custom_code_exits_with_it(monkeypatch: pytest.MonkeyPatch) -> None:
    exits: list[int] = []
    monkeypatch.setattr(sys, "exit", lambda code: exits.append(code))
    fatal("oops", code=2)
    assert exits == [2]


def test_fatal_logs_at_critical(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(sys, "exit", lambda code: None)
    with caplog.at_level(logging.CRITICAL, logger="stenographer.errors"):
        fatal("the end")
    matches = [
        record
        for record in caplog.records
        if record.name == "stenographer.errors"
        and record.levelno == logging.CRITICAL
        and record.getMessage() == "the end"
    ]
    assert matches


def test_degrade_capability_logs_at_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="stenographer.errors"):
        degrade_capability("wtype")
    matches = [
        record
        for record in caplog.records
        if record.name == "stenographer.errors"
        and record.levelno == logging.WARNING
        and record.getMessage() == "degrade: wtype unavailable; continuing without it"
    ]
    assert matches


def test_module_does_not_import_other_stenographer_modules() -> None:
    source = Path(errors.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("stenographer") and alias.name != "stenographer.errors":
                    bad.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith("stenographer") and module != "stenographer.errors":
                bad.append(module)
    assert not bad, f"errors.py must not import: {bad}"
