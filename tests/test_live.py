# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for :mod:`stenographer.live` (all components faked)."""

from __future__ import annotations

import concurrent.futures
import threading
from unittest.mock import MagicMock, call

import numpy as np

from stenographer.asr.model import WordInfo
from stenographer.asr.streaming import StreamingTranscriber
from stenographer.asr.worker import CancelledError
from stenographer.config import Config
from stenographer.live import _TAIL_CUSHION_SECONDS, LiveStreamer, _cut_trailing_silence
from stenographer.output.formatter import HeuristicFormatter

SR = 16000


def _words(*tokens: tuple[str, float, float]) -> list[WordInfo]:
    return [WordInfo(start=s, end=e, word=w, probability=1.0) for w, s, e in tokens]


def _cfg(**streaming_overrides: object) -> Config:
    import dataclasses

    cfg = Config.defaults()
    cfg = dataclasses.replace(cfg, output=dataclasses.replace(cfg.output, injection_method="paste"))
    streaming = dataclasses.replace(cfg.streaming, **{"enabled": True, **streaming_overrides})
    return dataclasses.replace(cfg, streaming=streaming)


class _FakeRecorder:
    """snapshot() returns scripted windows (clamped to the last one)."""

    def __init__(self, windows: list[np.ndarray]) -> None:
        self.windows = windows
        self.snapshot_calls: list[float] = []

    def snapshot(self, start_seconds: float = 0.0) -> np.ndarray:
        self.snapshot_calls.append(start_seconds)
        i = min(len(self.snapshot_calls) - 1, len(self.windows) - 1)
        return self.windows[i]


class _FakeWorker:
    """submit_words() returns pre-resolved futures with scripted hypotheses."""

    def __init__(self, hypotheses: list[list[WordInfo] | Exception]) -> None:
        self.hypotheses = hypotheses
        self.calls: list[dict] = []

    def submit_words(self, samples, *, beam_size=None, cancel_event=None):
        self.calls.append(
            {"n_samples": samples.shape[0], "beam_size": beam_size, "cancel_event": cancel_event}
        )
        fut: concurrent.futures.Future = concurrent.futures.Future()
        i = min(len(self.calls) - 1, len(self.hypotheses) - 1)
        item = self.hypotheses[i]
        if isinstance(item, Exception):
            fut.set_exception(item)
        else:
            fut.set_result(item)
        return fut


class _FakeInjector:
    """Records paste() deliveries; type_text() must not be used by the live path."""

    def __init__(self, clipboard: MagicMock | None = None) -> None:
        self.typed: list[str] = []
        # The clipboard text actually in place at each paste() — i.e. what the
        # chord really delivers. Reconstructing from this (rather than from
        # copy() calls) is what makes the prefix invariant machine-checkable.
        self.pasted: list[str] = []
        self._clipboard = clipboard

    def type_text(self, text: str, *, raw: bool = False) -> bool:
        assert raw is True  # the live path must never re-prepare deltas
        self.typed.append(text)
        return True

    def paste(self) -> bool:
        assert self._clipboard is not None
        self.pasted.append(self._clipboard.copy.call_args.args[0])
        return True


def _speech(seconds: float) -> np.ndarray:
    """Loud enough that the tail-silence guard keeps everything."""
    n = int(seconds * SR)
    return np.full((n, 1), 0.5, dtype=np.float32)


def _make_streamer(
    windows: list[np.ndarray],
    hypotheses: list[list[WordInfo] | Exception],
    cfg: Config | None = None,
) -> tuple[LiveStreamer, _FakeInjector, _FakeWorker, MagicMock]:
    cfg = cfg or _cfg()
    worker = _FakeWorker(hypotheses)
    clipboard = MagicMock()
    clipboard.copy.return_value = True
    injector = _FakeInjector(clipboard)
    streamer = LiveStreamer(
        cfg=cfg,
        recorder=_FakeRecorder(windows),  # type: ignore[arg-type]
        worker=worker,  # type: ignore[arg-type]
        injector=injector,  # type: ignore[arg-type]
        transcriber=StreamingTranscriber(agreement_n=cfg.streaming.agreement_n),
        formatter=HeuristicFormatter(
            cfg.formatting, append_trailing_space=cfg.output.append_trailing_space
        ),
        clipboard=clipboard,
        caps=MagicMock(has_wl_copy=True),
        abort=threading.Event(),
    )
    return streamer, injector, worker, clipboard


def test_partials_commit_and_type_deltas_then_final_flushes() -> None:
    streamer, injector, _worker, clipboard = _make_streamer(
        windows=[_speech(1.0), _speech(2.0)],
        hypotheses=[
            _words((" hello", 0.0, 0.5)),
            _words((" hello", 0.0, 0.5), (" world", 0.5, 1.0)),
            _words((" hello", 0.0, 0.5), (" world", 0.5, 1.0), (" again", 1.0, 1.5)),
        ],
    )
    # Drive interim steps directly: run()'s coalescing would collapse
    # pre-queued signals (covered separately below).
    assert streamer._step()
    assert streamer._step()
    typed = streamer._finish(_speech(2.5))
    # Step 2 commits "hello" (agreed across both interim decodes); the final
    # decode + flush commits the rest and appends the trailing space.
    assert injector.pasted == ["Hello", " world again "]
    assert typed == "Hello world again "
    # Each delta was copied as it was pasted; the final re-copy leaves the
    # whole utterance on the clipboard.
    assert clipboard.copy.call_args_list == [
        call("Hello", primary=True),
        call(" world again ", primary=True),
        # The _finish() re-copy must set primary too: the deltas above already
        # clobbered the selection, so leaving it on the last delta would make a
        # middle-click paste a stray word instead of the transcript.
        call("Hello world again ", primary=True),
    ]


def test_prequeued_partials_coalesce_into_the_final() -> None:
    streamer, _injector, worker, _clip = _make_streamer(
        windows=[_speech(3.0)],
        hypotheses=[_words((" hi", 0.0, 0.5))],
    )
    streamer.signal_partial()
    streamer.signal_partial()
    streamer.signal_partial()
    streamer.signal_final(_speech(3.0))
    streamer.run()
    # A queued final wins over pending partials: exactly one decode runs.
    assert len(worker.calls) == 1


def test_abort_stops_typing_and_keeps_typed_text() -> None:
    streamer, injector, _worker, clipboard = _make_streamer(
        windows=[_speech(1.0)],
        hypotheses=[
            _words((" keep", 0.0, 0.5)),
            _words((" keep", 0.0, 0.5), (" going", 0.5, 1.0)),
        ],
    )
    assert streamer._step()
    assert streamer._step()  # commits and types "Keep"
    streamer.abort.set()
    streamer.signal_abort()
    typed = streamer.run()
    # "keep" was committed and pasted before the abort; it is never revised,
    # and nothing further is pasted or copied (no _finish() re-copy).
    assert injector.pasted == ["Keep"]
    assert typed == "Keep"
    assert clipboard.copy.call_args_list == [call("Keep", primary=True)]


def test_abort_wins_over_queued_final() -> None:
    streamer, injector, _worker, _clip = _make_streamer(
        windows=[_speech(1.0)],
        hypotheses=[_words((" ghost", 0.0, 0.5))],
    )
    streamer.signal_final(_speech(1.0))
    streamer.abort.set()
    streamer.signal_abort()
    assert streamer.run() == ""
    assert injector.pasted == []


def test_cancelled_decode_ends_utterance_quietly() -> None:
    streamer, injector, _worker, _clip = _make_streamer(
        windows=[_speech(1.0)],
        hypotheses=[CancelledError("cancelled")],
    )
    streamer.signal_partial()
    assert streamer.run() == ""
    assert injector.pasted == []


def test_failed_decode_is_not_fatal() -> None:
    streamer, injector, _worker, _clip = _make_streamer(
        windows=[_speech(1.0), _speech(2.0)],
        hypotheses=[
            RuntimeError("inference hiccup"),
            _words((" ok", 0.0, 0.5)),
            _words((" ok", 0.0, 0.5)),
        ],
    )
    assert streamer._step()  # decode fails; not fatal
    assert streamer._step()
    typed = streamer._finish(_speech(2.0))
    assert typed == "Ok "
    assert injector.pasted == ["Ok "]


def test_max_chars_stops_typing_without_truncating_delta() -> None:
    import dataclasses

    cfg = _cfg()
    cfg = dataclasses.replace(
        cfg, output=dataclasses.replace(cfg.output, injection_method="text", max_chars=8)
    )
    streamer, injector, _worker, _clip = _make_streamer(
        windows=[_speech(1.0), _speech(2.0)],
        hypotheses=[
            _words((" hello", 0.0, 0.5)),
            _words((" hello", 0.0, 0.5), (" overflowing", 0.5, 1.5)),
            _words((" hello", 0.0, 0.5), (" overflowing", 0.5, 1.5)),
        ],
        cfg=cfg,
    )
    assert streamer._step()
    assert streamer._step()
    typed = streamer._finish(_speech(2.0))
    # "Hello" fits (5 <= 8); " overflowing" would exceed the cap and is
    # dropped whole rather than truncated mid-word.
    assert injector.pasted == ["Hello"]
    assert typed == "Hello"


def test_interim_beam_size_used_for_partials_full_beam_for_final() -> None:
    cfg = _cfg(beam_size=1)
    streamer, _injector, worker, _clip = _make_streamer(
        windows=[_speech(1.0)],
        hypotheses=[_words((" a", 0.0, 0.3))],
        cfg=cfg,
    )
    streamer._step()
    streamer._finish(_speech(1.0))
    assert worker.calls[0]["beam_size"] == 1  # streaming.beam_size
    assert worker.calls[1]["beam_size"] == cfg.asr.beam_size  # final flush


def test_streaming_beam_size_null_falls_back_to_asr_beam() -> None:
    cfg = _cfg(beam_size=None)
    streamer, _injector, worker, _clip = _make_streamer(
        windows=[_speech(1.0)],
        hypotheses=[_words((" a", 0.0, 0.3))],
        cfg=cfg,
    )
    streamer._step()
    assert worker.calls[0]["beam_size"] == cfg.asr.beam_size


# -- tail-silence guard --------------------------------------------------------


def test_cut_trailing_silence_trims_quiet_tail() -> None:
    speech = np.full((SR, 1), 0.5, dtype=np.float32)
    silence = np.zeros((SR, 1), dtype=np.float32)
    window = np.concatenate([speech, silence])
    out = _cut_trailing_silence(window, SR)
    # Speech plus the 0.25 s cushion survives; the rest of the second of
    # trailing silence is cut.
    assert SR <= out.shape[0] <= SR + int(0.3 * SR)


def test_cut_trailing_silence_keeps_loud_audio() -> None:
    speech = np.full((SR, 1), 0.5, dtype=np.float32)
    out = _cut_trailing_silence(speech, SR)
    assert out.shape[0] == SR


def test_cut_trailing_silence_all_silent_returns_empty() -> None:
    silence = np.zeros((SR, 1), dtype=np.float32)
    out = _cut_trailing_silence(silence, SR)
    # Every step is dead air (max step RMS < _SILENCE_FLOOR_RMS), so the
    # absolute silence-floor check fires before the self-relative trim gate
    # even runs, returning empty -- same behavior as pre-fix.
    assert out.shape[0] == 0


def test_cut_trailing_silence_preserves_quiet_mic_trailing_speech() -> None:
    # Quiet-mic speech (RMS ~0.003) followed by quiet ambient noise
    # (RMS ~0.0002, NOT exact zero) -- a real ambient floor. >=10 steps
    # (0.5s) of speech, well over 10 steps of trailing "silence".
    rng = np.random.default_rng(0)
    speech = np.full((SR, 1), 0.003, dtype=np.float32)
    ambient = (rng.normal(0.0, 0.0002, (SR, 1))).astype(np.float32)
    window = np.concatenate([speech, ambient])

    # Motivating contrast: the OLD fixed-0.01 gate would treat every step
    # (speech included, since 0.003 < 0.01) as sub-threshold and trim to
    # empty -- shaving/emptying real trailing speech on a quiet mic.
    old_gate_result_len = 0  # every step is < 0.01, so the old loop trims to 0

    out = _cut_trailing_silence(window, SR)

    assert out.shape[0] > old_gate_result_len
    # The trailing speech segment (1s) plus cushion must be kept, not just
    # the ambient-truncated tail.
    assert out.shape[0] >= SR + int(_TAIL_CUSHION_SECONDS * SR) - int(0.05 * SR)


def test_cut_trailing_silence_normal_mic_still_trims_true_silence() -> None:
    # Loud speech (RMS ~0.5) followed by >=10 steps (1s) of true silence.
    speech = np.full((SR, 1), 0.5, dtype=np.float32)
    silence = np.zeros((SR, 1), dtype=np.float32)
    window = np.concatenate([speech, silence])

    out = _cut_trailing_silence(window, SR)

    # Trimmed to roughly speech + cushion, not the full 2s window.
    assert SR <= out.shape[0] <= SR + int(0.3 * SR)


def test_cut_trailing_silence_short_window_returned_unchanged() -> None:
    # 0.3s at 16kHz = 6 steps of 50ms -- fewer than the 10-step minimum.
    rng = np.random.default_rng(1)
    n = int(0.3 * SR)
    mixed = np.concatenate(
        [
            np.full((n // 2, 1), 0.5, dtype=np.float32),
            (rng.normal(0.0, 0.0002, (n - n // 2, 1))).astype(np.float32),
        ]
    )

    out = _cut_trailing_silence(mixed, SR)

    assert out.shape[0] == mixed.shape[0]
    assert np.array_equal(out, mixed)


def test_cut_trailing_silence_is_pure() -> None:
    rng = np.random.default_rng(2)
    speech = np.full((SR, 1), 0.003, dtype=np.float32)
    ambient = (rng.normal(0.0, 0.0002, (SR, 1))).astype(np.float32)
    window = np.concatenate([speech, ambient])

    out1 = _cut_trailing_silence(window, SR)
    out2 = _cut_trailing_silence(window, SR)

    assert np.array_equal(out1, out2)


def test_all_silent_window_skips_decode() -> None:
    streamer, injector, worker, _clip = _make_streamer(
        windows=[np.zeros((SR, 1), dtype=np.float32)],
        hypotheses=[_words((" ghost", 0.0, 0.5))],
    )
    assert streamer._step()
    streamer._finish(_speech(1.0))
    # The all-silent interim window is skipped; only the final decode runs.
    assert len(worker.calls) == 1
    assert injector.pasted == ["Ghost "]  # final decode is not silence-gated


# -- trimming + absolute-time bookkeeping (M5) ----------------------------------


def test_trim_fires_at_sentence_terminal_commit() -> None:
    streamer, _injector, _worker, _clip = _make_streamer(
        windows=[_speech(2.0), _speech(2.0), _speech(1.0)],
        hypotheses=[
            _words((" done.", 0.0, 1.5)),
            _words((" done.", 0.0, 1.5)),  # commits "done." -> trim at 1.5s
            _words((" next", 0.2, 0.7)),  # window-local times after the trim
        ],
    )
    assert streamer._step()
    assert streamer._step()
    assert streamer._trim_offset == 1.5
    # The next snapshot is requested from the trim offset.
    assert streamer._step()
    assert streamer._recorder.snapshot_calls[-1] == 1.5  # type: ignore[attr-defined]


def test_no_trim_without_sentence_terminal_under_budget() -> None:
    streamer, _injector, _worker, _clip = _make_streamer(
        windows=[_speech(2.0)],
        hypotheses=[
            _words((" ongoing", 0.0, 1.5)),
            _words((" ongoing", 0.0, 1.5)),
        ],
    )
    assert streamer._step()
    assert streamer._step()
    assert streamer._trim_offset == 0.0


def test_trim_forced_when_window_exceeds_max_buffer() -> None:
    cfg = _cfg(max_buffer_seconds=5.0)
    streamer, _injector, _worker, _clip = _make_streamer(
        windows=[_speech(6.0)],
        hypotheses=[
            _words((" rambling", 0.0, 4.0)),
            _words((" rambling", 0.0, 4.0)),  # no terminal, but window > 5s
        ],
        cfg=cfg,
    )
    assert streamer._step()
    assert streamer._step()
    assert streamer._trim_offset == 4.0


def test_post_trim_commits_carry_absolute_times() -> None:
    streamer, _injector, _worker, _clip = _make_streamer(
        windows=[_speech(2.0), _speech(1.0), _speech(1.0)],
        hypotheses=[
            _words((" first.", 0.0, 1.5)),
            _words((" first.", 0.0, 1.5)),  # commit + trim at 1.5s
            _words((" second", 0.5, 1.0)),  # window-local 0.5 = absolute 2.0
            _words((" second", 0.5, 1.0)),
        ],
    )
    for _ in range(4):
        assert streamer._step()
    committed = streamer._transcriber.committed_words
    assert [w.word for w in committed] == [" first.", " second"]
    assert committed[1].start == 2.0
    assert committed[1].end == 2.5


def test_paragraph_pause_straddling_trim_emits_one_break() -> None:
    # "one." ends at absolute 1.0s and the trim rebases the window there.
    # "two" arrives with window-local start 2.5s = absolute 3.5s: the true
    # gap is 2.5s (>= the 2.0s threshold), but read as window-local it would
    # be only 1.5s (< threshold). Exactly one break proves the formatter saw
    # the absolute timeline across the trim.
    import dataclasses

    cfg = _cfg()
    cfg = dataclasses.replace(
        cfg, formatting=dataclasses.replace(cfg.formatting, paragraph_pause_seconds=2.0)
    )
    streamer, injector, _worker, _clip = _make_streamer(
        windows=[_speech(1.5), _speech(1.5), _speech(4.0)],
        hypotheses=[
            _words((" one.", 0.0, 1.0)),
            _words((" one.", 0.0, 1.0)),  # commit + trim at 1.0s
            _words((" two", 2.5, 3.0)),  # window-local: absolute 3.5-4.0
            _words((" two", 2.5, 3.0)),
        ],
        cfg=cfg,
    )
    for _ in range(4):
        assert streamer._step()
    typed = "".join(injector.pasted)
    assert typed == "One.\n\nTwo"
    assert typed.count("\n\n") == 1


def test_final_flush_after_trims_completes_transcript() -> None:
    streamer, injector, _worker, _clip = _make_streamer(
        windows=[_speech(2.0), _speech(2.0)],
        hypotheses=[
            _words((" first.", 0.0, 1.5)),
            _words((" first.", 0.0, 1.5)),  # commit + trim
            _words((" tail", 0.3, 0.8)),  # final decode, window-local
        ],
    )
    assert streamer._step()
    assert streamer._step()
    typed = streamer._finish(_speech(3.0))
    assert typed == "First. Tail "
    assert "".join(injector.pasted) == typed


# -- paste-based delta output ----------------------------------------------------


def test_emit_uses_paste_not_type_text() -> None:
    """The live path delivers via clipboard.copy() + injector.paste(), never
    via Injector.type_text()."""
    streamer, injector, _worker, clipboard = _make_streamer(
        windows=[_speech(1.0), _speech(2.0)],
        hypotheses=[
            _words((" hello", 0.0, 0.5)),
            _words((" hello", 0.0, 0.5), (" world", 0.5, 1.0)),
        ],
    )
    assert streamer._step()
    assert streamer._step()
    streamer._finish(_speech(2.0))

    assert injector.typed == []  # type_text is never reached
    assert clipboard.copy.called
    assert injector.pasted  # delivery went through the paste chord


def test_delta_pastes_fire_per_committed_word() -> None:
    """Each committed delta is delivered live during the utterance — a
    copy()+paste() pair per delta, not deferred to _finish()."""
    streamer, injector, _worker, clipboard = _make_streamer(
        windows=[_speech(1.0), _speech(2.0), _speech(3.0), _speech(4.0)],
        hypotheses=[
            _words((" one", 0.0, 0.5)),
            _words((" one", 0.0, 0.5)),  # commits "one"
            _words((" one", 0.0, 0.5), (" two", 0.5, 1.0)),
            _words((" one", 0.0, 0.5), (" two", 0.5, 1.0)),  # commits "two"
        ],
    )
    assert streamer._step()
    assert streamer._step()
    # First delta pasted mid-utterance, before any further steps or _finish().
    assert injector.pasted == ["One"]
    assert clipboard.copy.call_args_list == [call("One", primary=True)]

    assert streamer._step()
    assert streamer._step()
    # Second delta fires its own pair, again mid-utterance.
    assert injector.pasted == ["One", " two"]
    assert clipboard.copy.call_args_list == [
        call("One", primary=True),
        call(" two", primary=True),
    ]


def test_finish_recopies_full_transcript() -> None:
    """_finish() still re-copies the complete accumulated transcript at
    utterance end — the independent clipboard fallback."""
    streamer, _injector, _worker, clipboard = _make_streamer(
        windows=[_speech(1.0), _speech(2.0)],
        hypotheses=[
            _words((" hello", 0.0, 0.5)),
            _words((" hello", 0.0, 0.5), (" world", 0.5, 1.0)),
            _words((" hello", 0.0, 0.5), (" world", 0.5, 1.0), (" again", 1.0, 1.5)),
        ],
    )
    assert streamer._step()
    assert streamer._step()
    typed = streamer._finish(_speech(2.5))

    assert typed == "Hello world again "
    # The last thing on the clipboard is the whole utterance, so a manual
    # paste after the utterance delivers everything.
    assert clipboard.copy.call_args_list[-1] == call("Hello world again ", primary=True)


def test_failed_copy_skips_paste_and_stops_at_prefix() -> None:
    """Partial-clipboard hazard: copy() returns False when it populated the
    clipboard but not the primary selection, leaving the two selections
    disagreeing. Pasting then would deliver a stale/out-of-order word, so the
    delta must not be pasted — and no later delta may be pasted past that gap,
    or the delivered text stops being a prefix of the final transcript."""
    streamer, injector, _worker, clipboard = _make_streamer(
        windows=[_speech(1.0)] * 6,
        hypotheses=[
            _words((" one", 0.0, 0.5)),
            _words((" one", 0.0, 0.5)),  # commits "one"   -> copy succeeds
            _words((" one", 0.0, 0.5), (" two", 0.5, 1.0)),
            _words((" one", 0.0, 0.5), (" two", 0.5, 1.0)),  # commits "two" -> copy FAILS
            _words((" one", 0.0, 0.5), (" two", 0.5, 1.0), (" three", 1.0, 1.5)),
            _words((" one", 0.0, 0.5), (" two", 0.5, 1.0), (" three", 1.0, 1.5)),  # commits
        ],
    )
    clipboard.copy.side_effect = [True, False, True, True]

    for _ in range(6):
        assert streamer._step()

    # (a) the failed delta is not pasted, and nothing is pasted after it.
    assert injector.pasted == ["One"]

    # (b) the delivered text is still a prefix of the final transcript.
    fresh = HeuristicFormatter(
        streamer._cfg.formatting,
        append_trailing_space=streamer._cfg.output.append_trailing_space,
    )
    full = fresh.format_batch(streamer._transcriber.committed_words)
    delivered = "".join(injector.pasted)
    assert full.startswith(delivered)
    assert delivered == "One"
    # A gap would look like "One three" — delivered past the dropped delta.
    assert "three" not in delivered


# -- prefix-invariant property test (M6) -----------------------------------------


def test_prefix_invariant_paste_mode() -> None:
    """The machine-checkable form of the core invariant, in paste mode: every
    intermediate delivered state is a prefix of the final transcript, and the
    pasted deltas reconstruct exactly the formatted final transcript (no
    duplicated, missing, or reordered words) — across tail revisions,
    punctuation churn, a sentence-boundary trim, and a paragraph-length pause.

    Renamed from test_prefix_invariant_deltas_reconstruct_final_transcript and
    re-seated on the paste seam: the delivered text is now reconstructed from
    the clipboard payload in place at each paste(), not from type_text() args.
    Same script, same assertions."""
    hypotheses = [
        _words((" it", 0.0, 0.3)),
        _words((" it", 0.0, 0.3), (" wors", 0.3, 0.8)),  # commits "it"; noisy tail
        _words((" it", 0.0, 0.3), (" works", 0.3, 0.8)),  # tail revision
        _words((" it", 0.0, 0.3), (" works", 0.3, 0.8), (" now", 0.8, 1.2)),
        _words((" it", 0.0, 0.3), (" works", 0.3, 0.8), (" now.", 0.8, 1.2)),  # punct churn
        _words((" it", 0.0, 0.3), (" works", 0.3, 0.8), (" now.", 0.8, 1.2)),
        # commits "works now." -> sentence-terminal trim at 1.2s; later
        # hypotheses are window-local. 4.0 window-local = 5.2 absolute:
        # a 4.0s pause -> paragraph break.
        _words((" and", 4.0, 4.3)),
        _words((" and", 4.0, 4.3), (" i", 4.3, 4.5)),
        _words((" and", 4.0, 4.3), (" i", 4.3, 4.5)),
        # final decode:
        _words((" and", 4.0, 4.3), (" i", 4.3, 4.5), (" agree", 4.5, 5.0)),
    ]
    import dataclasses

    cfg = _cfg()
    cfg = dataclasses.replace(
        cfg, formatting=dataclasses.replace(cfg.formatting, paragraph_pause_seconds=2.0)
    )
    n_steps = len(hypotheses) - 1
    streamer, injector, _worker, _clip = _make_streamer(
        windows=[_speech(1.5)] * 6 + [_speech(5.0)] * (n_steps - 6),
        hypotheses=hypotheses,
        cfg=cfg,
    )
    for _ in range(n_steps):
        assert streamer._step()
    final_typed = streamer._finish(_speech(7.0))

    # (a) every intermediate delivered concatenation is a prefix of the final.
    concat = ""
    for delta in injector.pasted:
        concat += delta
        assert final_typed.startswith(concat)
    assert concat == final_typed

    # (b) the deltas reconstruct exactly the batch-formatted transcript of
    # the committed words (same formatter rules, fresh state).
    fresh = HeuristicFormatter(
        cfg.formatting, append_trailing_space=cfg.output.append_trailing_space
    )
    expected = fresh.format_batch(streamer._transcriber.committed_words)
    assert final_typed == expected

    # Sanity: the content is what the script says, incl. break + capitals.
    assert final_typed == "It works now.\n\nAnd I agree "


# -- clipboard fallback on delivery failure (FTHR-020) ---------------------------


def _failed_delta_streamer() -> tuple[LiveStreamer, _FakeInjector, MagicMock]:
    """The FTHR-017 forced-failure script: "one two three", where the delta
    carrying " two" fails to copy mid-utterance and latches output off."""
    streamer, injector, _worker, clipboard = _make_streamer(
        windows=[_speech(1.0)] * 6,
        hypotheses=[
            _words((" one", 0.0, 0.5)),
            _words((" one", 0.0, 0.5)),  # commits "one"   -> copy succeeds
            _words((" one", 0.0, 0.5), (" two", 0.5, 1.0)),
            _words((" one", 0.0, 0.5), (" two", 0.5, 1.0)),  # commits "two" -> copy FAILS
            _words((" one", 0.0, 0.5), (" two", 0.5, 1.0), (" three", 1.0, 1.5)),
            _words((" one", 0.0, 0.5), (" two", 0.5, 1.0), (" three", 1.0, 1.5)),  # commits
        ],
    )
    # Only the second copy fails; later copies would succeed if attempted, so
    # nothing but the latch itself can be what stops delivery.
    clipboard.copy.side_effect = [True, False, True, True]
    return streamer, injector, clipboard


def test_finish_copies_full_transcript_after_delivery_failure() -> None:
    """Once the latch engages, `_typed` freezes at the delivered prefix — but
    the clipboard is the independent fallback, so it must carry the WHOLE
    transcript, not the prefix. Otherwise "two three" is neither pasted nor
    recoverable: lost outright."""
    streamer, injector, clipboard = _failed_delta_streamer()

    for _ in range(6):
        assert streamer._step()
    typed = streamer._finish(_speech(2.0))

    # The delivered text still stops at the prefix (that is FTHR-017's latch,
    # and it is correct) ...
    assert typed == "One"
    assert injector.pasted == ["One"]
    # ... but the clipboard now holds everything the user actually said, so
    # the undelivered remainder is recoverable with a manual paste.
    assert clipboard.copy.call_args_list[-1] == call("One two three ", primary=True)


def test_delivery_failure_still_stops_pasting_at_prefix() -> None:
    """Pins FTHR-017's `_delivery_failed` latch against regression by
    FTHR-020: the clipboard change must not cause a delta to be pasted past
    the gap. A `docs:`-labelled commit once deleted this latch with 484/485
    tests still green — a passing suite is not evidence the latch survived."""
    streamer, injector, _clipboard = _failed_delta_streamer()

    for _ in range(6):
        assert streamer._step()
    typed = streamer._finish(_speech(2.0))

    # (a) the failed delta is not pasted, and nothing is pasted after it --
    # not by a later step, and not by _finish().
    assert injector.pasted == ["One"]

    # (b) the delivered text is still a prefix of the final transcript.
    fresh = HeuristicFormatter(
        streamer._cfg.formatting,
        append_trailing_space=streamer._cfg.output.append_trailing_space,
    )
    full = fresh.format_batch(streamer._transcriber.committed_words)
    delivered = "".join(injector.pasted)
    assert full.startswith(delivered)
    assert delivered == "One"
    # A gap would look like "One three" -- delivered past the dropped delta.
    assert "three" not in delivered

    # (c) _typed still means "text actually delivered to the cursor" and is
    # still _finish()'s return value -- the clipboard fallback must not be
    # conflated with the delivered text.
    assert typed == "One"
    assert streamer._typed == "One"


def test_first_delta_failure_still_copies_full_transcript() -> None:
    """The worst case: the FIRST delta fails, so `_typed` stays "" and
    _finish()'s `if self._typed` gate would skip the copy entirely -- the
    utterance vanishing from cursor and clipboard both. A distinct code path
    from the mid-utterance failure (that one has a non-empty `_typed`)."""
    streamer, injector, _worker, clipboard = _make_streamer(
        windows=[_speech(1.0)] * 4,
        hypotheses=[
            _words((" one", 0.0, 0.5)),
            _words((" one", 0.0, 0.5)),  # commits "one" -> copy FAILS on delta #1
            _words((" one", 0.0, 0.5), (" two", 0.5, 1.0)),
            _words((" one", 0.0, 0.5), (" two", 0.5, 1.0)),  # commits "two" -> latched
        ],
    )
    clipboard.copy.side_effect = [False, True, True]

    for _ in range(4):
        assert streamer._step()
    typed = streamer._finish(_speech(2.0))

    # Nothing ever reached the cursor ...
    assert typed == ""
    assert injector.pasted == []
    # ... so the clipboard is the only surviving copy of the utterance. It
    # must hold all of it.
    assert clipboard.copy.call_args_list[-1] == call("One two ", primary=True)


def test_max_chars_clipboard_unchanged() -> None:
    """Pins the max_chars fork: the transcript accumulator must NOT leak into
    the output.max_chars path. A cap is a deliberate, user-configured limit on
    output; the clipboard is output, so it must carry the capped text, not the
    full uncapped transcript. Deliveries all succeed here -- the latch never
    engages -- which is exactly what gates the fallback off."""
    import dataclasses

    cfg = _cfg()
    cfg = dataclasses.replace(
        cfg, output=dataclasses.replace(cfg.output, injection_method="text", max_chars=8)
    )
    streamer, _injector, _worker, clipboard = _make_streamer(
        windows=[_speech(1.0), _speech(2.0)],
        hypotheses=[
            _words((" hello", 0.0, 0.5)),
            _words((" hello", 0.0, 0.5), (" overflowing", 0.5, 1.5)),
            _words((" hello", 0.0, 0.5), (" overflowing", 0.5, 1.5)),
        ],
        cfg=cfg,
    )
    assert streamer._step()
    assert streamer._step()
    typed = streamer._finish(_speech(2.0))

    assert typed == "Hello"
    # The capped text, NOT "Hello overflowing ". Gating the fallback on a
    # `_transcript != _typed` comparison instead of on the latch would fail
    # here -- the condition is true in this case too.
    assert clipboard.copy.call_args_list[-1] == call("Hello", primary=True)


def test_max_chars_latches_and_never_pastes_past_the_gap() -> None:
    """A delta skipped for exceeding output.max_chars latches output off.

    Without the latch a later, shorter delta still fits under the cap and is
    pasted -- delivering text that continues past the skipped delta, so what
    is at the cursor has a hole in the middle and is no longer a prefix of the
    transcript. Cutting the utterance short is the documented behaviour.
    """
    import dataclasses

    cfg = _cfg()
    cfg = dataclasses.replace(cfg, output=dataclasses.replace(cfg.output, max_chars=10))
    streamer, injector, _worker, _clip = _make_streamer(
        windows=[_speech(1.0)], hypotheses=[[]], cfg=cfg
    )
    streamer._emit("12345")  # typed=5, under the cap
    streamer._emit("123456")  # 5+6=11 > 10 -> skipped, latches
    streamer._emit("1")  # 5+1=6 <= 10, but pasting it would skip the gap
    assert injector.pasted == ["12345"]


def test_final_decode_failure_still_flushes_uncommitted_tail() -> None:
    """A failed final decode must not discard the words already agreed on.

    _decode returns no words on failure; feeding that to insert() as an empty
    hypothesis overwrites the transcriber's tail, so flush() returns nothing
    and the user's last words vanish while the success cue plays.
    """
    streamer, _injector, _worker, _clip = _make_streamer(
        windows=[_speech(1.0), _speech(2.0)],
        hypotheses=[
            _words((" hello", 0.0, 0.5)),
            _words((" hello", 0.0, 0.5), (" world", 0.5, 1.0)),
            RuntimeError("ctranslate2 blew up"),
        ],
    )
    assert streamer._step()
    assert streamer._step()  # commits "hello"; "world" is the uncommitted tail
    typed = streamer._finish(_speech(2.5))
    assert "world" in typed, f"tail was discarded on final-decode failure: {typed!r}"


def test_forced_trim_fires_during_agreement_free_stretch() -> None:
    """max_buffer_seconds must bound the window even when nothing commits.

    Gating the trim on a non-empty delta means an agreement-free stretch --
    exactly when the window is growing -- never trims, so re-decode cost grows
    without bound and live typing stalls.
    """
    streamer, _injector, _worker, _clip = _make_streamer(
        # 30s windows are past the 20s default max_buffer_seconds.
        windows=[_speech(3.0), _speech(3.0), _speech(30.0), _speech(30.0)],
        hypotheses=[
            _words((" hello", 0.0, 2.0)),
            _words((" hello", 0.0, 2.0), (" world", 2.0, 2.5)),
            # Now the tail never agrees twice running, so nothing commits.
            _words((" hello", 0.0, 2.0), (" alpha", 2.0, 2.5)),
            _words((" hello", 0.0, 2.0), (" beta", 2.0, 2.5)),
        ],
    )
    assert streamer._step()
    assert streamer._step()  # commits "hello" (ends at 2.0s); window still small
    assert streamer._trim_offset == 0.0
    assert streamer._step()  # agreement-free, window now over budget
    assert streamer._step()  # still agreement-free
    assert streamer._trim_offset == 2.0, "forced trim never fired without a commit"
