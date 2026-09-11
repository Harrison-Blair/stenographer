# SPDX-License-Identifier: GPL-3.0-or-later
"""``model download``: the configured model is the one fetched and reported."""

from __future__ import annotations

import argparse
import dataclasses

import pytest

from stenographer.cli.model.download.handler import cmd_model_download
from stenographer.lib.config.models import Config


def test_download_fetches_the_configured_model_and_names_it(monkeypatch, capsys):
    from stenographer.lib.transcribe import download

    requested: list[str] = []
    monkeypatch.setattr(download, "download_model", requested.append)
    defaults = Config.defaults()
    cfg = dataclasses.replace(defaults, asr=dataclasses.replace(defaults.asr, model="small.en"))

    assert cmd_model_download.__wrapped__(argparse.Namespace(), cfg) == 0

    assert requested == ["small.en"]
    assert capsys.readouterr().out == "stenographer: downloaded small.en\n"


def test_a_failed_download_is_not_reported_as_a_success(monkeypatch, capsys):
    from stenographer.lib.transcribe import download

    class UnreachableError(RuntimeError):
        pass

    def fail(model_id):
        raise UnreachableError("no route to host")

    monkeypatch.setattr(download, "download_model", fail)

    with pytest.raises(UnreachableError):
        cmd_model_download.__wrapped__(argparse.Namespace(), Config.defaults())

    assert capsys.readouterr().out == ""
