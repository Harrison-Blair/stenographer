# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the incremental transcription driver."""

from __future__ import annotations

import concurrent.futures
import dataclasses
import threading

import numpy as np

from stenographer.asr.model import WordInfo
from stenographer.asr.streaming import StreamingTranscriber
from stenographer.asr.worker import CancelledError
from stenographer.config import Config
from stenographer.live import _TAIL_CUSHION_SECONDS, IncrementalDriver, _cut_trailing_silence
from stenographer.output.formatter import HeuristicFormatter

SR = 16000


def _words(*tokens: tuple[str, float, float]) -> list[WordInfo]:
    return [
        WordInfo(start=start, end=end, word=word, probability=1.0) for word, start, end in tokens
    ]


def _cfg(**incremental_overrides: object) -> Config:
    cfg = Config.defaults()
    incremental = dataclasses.replace(cfg.incremental, **incremental_overrides)
    return dataclasses.replace(cfg, incremental=incremental)


def _speech(seconds: float) -> np.ndarray:
    return np.full((int(seconds * SR), 1), 0.5, dtype=np.float32)


class _FakeRecorder:
    def __init__(self, windows: list[np.ndarray]) -> None:
        self.windows = windows
        self.snapshot_calls: list[float] = []

    def snapshot(self, start_seconds: float = 0.0) -> np.ndarray:
        self.snapshot_calls.append(start_seconds)
        index = min(len(self.snapshot_calls) - 1, len(self.windows) - 1)
        return self.windows[index]


class _FakeWorker:
    def __init__(self, hypotheses: list[list[WordInfo] | Exception]) -> None:
        self.hypotheses = hypotheses
        self.calls: list[dict[str, object]] = []

    def submit_words(self, samples, *, beam_size=None, cancel_event=None):
        self.calls.append(
            {
                "n_samples": samples.shape[0],
                "beam_size": beam_size,
                "cancel_event": cancel_event,
            }
        )
        future: concurrent.futures.Future = concurrent.futures.Future()
        item = self.hypotheses[min(len(self.calls) - 1, len(self.hypotheses) - 1)]
        if isinstance(item, Exception):
            future.set_exception(item)
        else:
            future.set_result(item)
        return future


def _make_driver(
    windows: list[np.ndarray],
    hypotheses: list[list[WordInfo] | Exception],
    *,
    cfg: Config | None = None,
    previews: list[tuple[str, str]] | None = None,
) -> tuple[IncrementalDriver, _FakeWorker]:
    cfg = cfg or _cfg()
    worker = _FakeWorker(hypotheses)
    driver = IncrementalDriver(
        cfg=cfg,
        recorder=_FakeRecorder(windows),  # type: ignore[arg-type]
        worker=worker,  # type: ignore[arg-type]
        transcriber=StreamingTranscriber(agreement_n=cfg.incremental.agreement_n),
        formatter=HeuristicFormatter(
            cfg.formatting,
            append_trailing_space=cfg.output.append_trailing_space,
        ),
        abort=threading.Event(),
        on_preview=(lambda stable, tail: previews.append((stable, tail)))
        if previews is not None
        else None,
    )
    return driver, worker


def test_partials_publish_stable_and_revisable_tail_then_return_final() -> None:
    previews: list[tuple[str, str]] = []
    driver, _worker = _make_driver(
        [_speech(1.0), _speech(2.0), _speech(2.5)],
        [
            _words((" hello", 0.0, 0.5)),
            _words((" hello", 0.0, 0.5), (" wurld", 0.5, 1.0)),
            _words((" hello", 0.0, 0.5), (" world", 0.5, 1.0)),
            _words(
                (" hello", 0.0, 0.5),
                (" world", 0.5, 1.0),
                (" again", 1.0, 1.5),
            ),
        ],
        previews=previews,
    )

    assert driver._step()
    assert driver._step()
    assert driver._step()
    result = driver._finish(_speech(3.0))

    assert previews[:3] == [
        ("", "Hello"),
        ("Hello", " wurld"),
        ("Hello", " world"),
    ]
    assert previews[-1] == ("Hello world again ", "")
    assert result == "Hello world again "


def test_stable_preview_is_append_only_while_tail_revises() -> None:
    previews: list[tuple[str, str]] = []
    driver, _worker = _make_driver(
        [_speech(1.0)] * 4,
        [
            _words((" one", 0.0, 0.3)),
            _words((" one", 0.0, 0.3), (" too", 0.3, 0.6)),
            _words((" one", 0.0, 0.3), (" two", 0.3, 0.6)),
            _words((" one", 0.0, 0.3), (" two", 0.3, 0.6), (" three", 0.6, 0.9)),
        ],
        previews=previews,
    )
    for _ in range(4):
        assert driver._step()

    stable = [prefix for prefix, _tail in previews]
    assert stable == ["", "One", "One", "One two"]
    assert previews[1][1] == " too"
    assert previews[2][1] == " two"


def test_prequeued_partials_coalesce_into_final_decode() -> None:
    driver, worker = _make_driver(
        [_speech(3.0)],
        [_words((" hi", 0.0, 0.5))],
    )
    driver.signal_partial()
    driver.signal_partial()
    driver.signal_final(_speech(3.0))
    assert driver.run() == "Hi "
    assert len(worker.calls) == 1


def test_abort_returns_none_and_never_finalizes() -> None:
    previews: list[tuple[str, str]] = []
    driver, _worker = _make_driver(
        [_speech(1.0)],
        [_words((" ghost", 0.0, 0.5))],
        previews=previews,
    )
    driver.signal_final(_speech(1.0))
    driver.abort.set()
    driver.signal_abort()
    assert driver.run() is None
    assert previews == []


def test_cancelled_decode_returns_none() -> None:
    driver, _worker = _make_driver([_speech(1.0)], [CancelledError("cancelled")])
    driver.signal_partial()
    assert driver.run() is None


def test_final_decode_failure_still_returns_the_committed_transcript() -> None:
    # The audio since the last interim hypothesis is unrecoverable, but the
    # words already agreed on must not be dropped with it.
    driver, _worker = _make_driver(
        [_speech(1.0)] * 3,
        [
            _words((" hello", 0.0, 0.5)),
            _words((" hello", 0.0, 0.5), (" world", 0.5, 1.0)),
            _words((" hello", 0.0, 0.5), (" world", 0.5, 1.0)),
            RuntimeError("final decode failed"),
        ],
    )
    for _ in range(3):
        assert driver._step()

    assert driver._finish(_speech(1.5)) == "Hello world "


def test_final_decode_failure_with_nothing_committed_returns_empty() -> None:
    driver, _worker = _make_driver([_speech(1.0)], [RuntimeError("final decode failed")])
    assert not driver._finish(_speech(1.0))


def test_cancelled_final_decode_returns_none() -> None:
    driver, _worker = _make_driver([_speech(1.0)], [CancelledError("cancelled")])
    assert driver._finish(_speech(1.0)) is None


def test_interim_failure_is_retried_by_later_partial() -> None:
    driver, _worker = _make_driver(
        [_speech(1.0), _speech(2.0)],
        [
            RuntimeError("temporary"),
            _words((" ok", 0.0, 0.5)),
            _words((" ok", 0.0, 0.5)),
        ],
    )
    assert driver._step()
    assert driver._step()
    assert driver._finish(_speech(2.0)) == "Ok "


def test_interim_beam_override_and_final_full_beam() -> None:
    cfg = _cfg(beam_size=1)
    driver, worker = _make_driver(
        [_speech(1.0)],
        [_words((" a", 0.0, 0.3))],
        cfg=cfg,
    )
    assert driver._step()
    driver._finish(_speech(1.0))
    assert worker.calls[0]["beam_size"] == 1
    assert worker.calls[1]["beam_size"] == cfg.asr.beam_size


def test_interim_null_beam_uses_asr_beam() -> None:
    cfg = _cfg(beam_size=None)
    driver, worker = _make_driver(
        [_speech(1.0)],
        [_words((" a", 0.0, 0.3))],
        cfg=cfg,
    )
    assert driver._step()
    assert worker.calls[0]["beam_size"] == cfg.asr.beam_size


def test_trim_at_sentence_terminal_and_rebase_snapshot() -> None:
    driver, _worker = _make_driver(
        [_speech(2.0), _speech(2.0), _speech(1.0)],
        [
            _words((" done.", 0.0, 1.5)),
            _words((" done.", 0.0, 1.5)),
            _words((" next", 0.2, 0.7)),
        ],
    )
    assert driver._step()
    assert driver._step()
    assert driver._trim_offset == 1.5
    assert driver._step()
    assert driver._recorder.snapshot_calls[-1] == 1.5  # type: ignore[attr-defined]


def test_trim_forced_when_buffer_budget_exceeded() -> None:
    driver, _worker = _make_driver(
        [_speech(6.0)],
        [
            _words((" rambling", 0.0, 4.0)),
            _words((" rambling", 0.0, 4.0)),
        ],
        cfg=_cfg(max_buffer_seconds=5.0),
    )
    assert driver._step()
    assert driver._step()
    assert driver._trim_offset == 4.0


def test_all_silent_interim_window_skips_decode() -> None:
    driver, worker = _make_driver(
        [np.zeros((SR, 1), dtype=np.float32)],
        [_words((" speech", 0.0, 0.5))],
    )
    assert driver._step()
    assert worker.calls == []


def test_cut_trailing_silence_trims_quiet_tail_with_cushion() -> None:
    speech = np.full((SR, 1), 0.5, dtype=np.float32)
    silence = np.zeros((SR, 1), dtype=np.float32)
    out = _cut_trailing_silence(np.concatenate([speech, silence]), SR)
    assert SR <= out.shape[0] <= SR + int(0.3 * SR)


def test_cut_trailing_silence_preserves_quiet_microphone_speech() -> None:
    rng = np.random.default_rng(0)
    speech = np.full((SR, 1), 0.003, dtype=np.float32)
    ambient = rng.normal(0.0, 0.0002, (SR, 1)).astype(np.float32)
    out = _cut_trailing_silence(np.concatenate([speech, ambient]), SR)
    assert out.shape[0] >= SR + int(_TAIL_CUSHION_SECONDS * SR) - int(0.05 * SR)


def test_cut_trailing_silence_keeps_loud_and_short_windows() -> None:
    loud = _speech(1.0)
    short = _speech(0.3)
    assert np.array_equal(_cut_trailing_silence(loud, SR), loud)
    assert np.array_equal(_cut_trailing_silence(short, SR), short)


def test_cut_trailing_silence_all_silent_returns_empty() -> None:
    assert _cut_trailing_silence(np.zeros((SR, 1), dtype=np.float32), SR).shape[0] == 0
