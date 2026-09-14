# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure tests for the loading-pulse breath and frame-deadline math.

A breath is drawn for one model at a time and never cut short: joining or
leaving only changes who breathes *next*, and the breath in progress rotates
or ends only at its own trough (``advance`` crossing a full
``LOADING_PULSE_SECONDS``).
"""

from __future__ import annotations

import pytest

from stenographer.lib.contracts.loading_model import LoadingModel
from stenographer.overlay.rendering.constants import LOADING_FRAME_INTERVAL, LOADING_PULSE_SECONDS
from stenographer.overlay.rendering.loading_pulse import LoadingPulse


def test_a_single_model_breathes_from_the_trough_in_its_own_colour() -> None:
    pulse = LoadingPulse()
    assert pulse.set_active(LoadingModel.ASR, True) is True

    assert pulse.start_breathing(10.0) is True

    assert pulse.breathing is True
    assert pulse.breath_model is LoadingModel.ASR
    assert pulse.breath_started_at == 10.0
    assert pulse.elapsed(10.0) == 0.0


def test_two_models_alternate_one_full_breath_each_earliest_first() -> None:
    pulse = LoadingPulse()
    pulse.set_active(LoadingModel.ASR, True)
    pulse.set_active(LoadingModel.REFINE, True)

    pulse.start_breathing(101.0)
    assert pulse.breath_model is LoadingModel.ASR

    pulse.advance(102.99)
    assert pulse.breath_model is LoadingModel.ASR

    pulse.advance(103.0)
    assert pulse.breath_model is LoadingModel.REFINE
    assert pulse.breath_started_at == 103.0

    pulse.advance(105.0)
    assert pulse.breath_model is LoadingModel.ASR


def test_a_model_that_joins_mid_breath_waits_for_the_trough() -> None:
    pulse = LoadingPulse()
    pulse.set_active(LoadingModel.ASR, True)
    pulse.start_breathing(10.0)

    assert pulse.set_active(LoadingModel.REFINE, True) is True
    assert pulse.breath_model is LoadingModel.ASR
    assert pulse.breath_started_at == 10.0
    assert pulse.loading == [LoadingModel.ASR, LoadingModel.REFINE]

    pulse.advance(12.0)

    assert pulse.breath_model is LoadingModel.REFINE
    assert pulse.breath_started_at == 12.0


def test_a_model_that_finishes_mid_breath_completes_its_breath() -> None:
    pulse = LoadingPulse()
    pulse.set_active(LoadingModel.ASR, True)
    pulse.start_breathing(10.0)

    assert pulse.set_active(LoadingModel.ASR, False) is True
    assert pulse.breathing is True
    assert pulse.breath_model is LoadingModel.ASR
    assert pulse.loading == []

    pulse.advance(12.0)

    assert pulse.breathing is False
    assert pulse.next_frame_at is None
    assert pulse.elapsed(12.0) is None
    assert pulse.loading == []


def test_the_survivor_takes_every_breath_once_the_other_finishes() -> None:
    pulse = LoadingPulse()
    pulse.set_active(LoadingModel.ASR, True)
    pulse.set_active(LoadingModel.REFINE, True)
    pulse.start_breathing(0.0)

    pulse.advance(2.0)
    assert pulse.breath_model is LoadingModel.REFINE

    pulse.set_active(LoadingModel.ASR, False)
    pulse.advance(4.0)
    assert pulse.breath_model is LoadingModel.REFINE
    assert pulse.breath_started_at == 4.0

    pulse.advance(6.0)
    assert pulse.breath_model is LoadingModel.REFINE
    assert pulse.breath_started_at == 6.0


def test_the_same_model_finishing_and_rejoining_never_restarts_the_breath() -> None:
    pulse = LoadingPulse()
    pulse.set_active(LoadingModel.ASR, True)
    pulse.start_breathing(10.0)

    pulse.set_active(LoadingModel.ASR, False)
    pulse.set_active(LoadingModel.ASR, True)

    assert pulse.breath_model is LoadingModel.ASR
    assert pulse.breath_started_at == 10.0
    assert pulse.loading == [LoadingModel.ASR]


def test_duplicate_edges_change_nothing() -> None:
    pulse = LoadingPulse()
    assert pulse.set_active(LoadingModel.ASR, False) is False
    assert pulse.set_active(LoadingModel.ASR, True) is True
    assert pulse.set_active(LoadingModel.ASR, True) is False
    assert pulse.loading == [LoadingModel.ASR]


def test_a_due_frame_advances_the_breath_by_exactly_one_period() -> None:
    pulse = LoadingPulse()
    pulse.set_active(LoadingModel.ASR, True)
    pulse.start_breathing(10.0)

    pulse.advance(10.0 + LOADING_PULSE_SECONDS)

    assert pulse.breath_started_at == pytest.approx(10.0 + LOADING_PULSE_SECONDS)
    assert pulse.next_frame_at == pytest.approx(
        10.0 + LOADING_PULSE_SECONDS + LOADING_FRAME_INTERVAL
    )


def test_stop_breathing_keeps_activity_the_next_start_is_a_fresh_trough() -> None:
    pulse = LoadingPulse()
    pulse.set_active(LoadingModel.REFINE, True)
    pulse.set_active(LoadingModel.ASR, True)
    pulse.start_breathing(10.0)
    pulse.advance(12.0)

    pulse.stop_breathing()

    assert pulse.breathing is False
    assert pulse.breath_model is None
    assert pulse.breath_started_at is None
    assert pulse.next_frame_at is None
    assert pulse.loading == [LoadingModel.REFINE, LoadingModel.ASR]

    assert pulse.start_breathing(50.0) is True
    assert pulse.breath_model is LoadingModel.REFINE
    assert pulse.breath_started_at == 50.0
    assert pulse.elapsed(50.0) == 0.0


def test_timeout_and_frame_due_require_breathing_visibility_and_an_armed_deadline() -> None:
    pulse = LoadingPulse()
    assert pulse.timeout(10.0, True) is None
    assert pulse.frame_due(10.0, True) is False

    pulse.set_active(LoadingModel.ASR, True)
    assert pulse.timeout(10.0, True) is None

    pulse.start_breathing(10.0)
    assert pulse.timeout(10.0, False) is None
    assert pulse.timeout(10.0, True) == pytest.approx(LOADING_FRAME_INTERVAL)
    assert pulse.frame_due(10.0, True) is False
    due_at = 10.0 + LOADING_FRAME_INTERVAL
    assert pulse.frame_due(due_at, False) is False
    assert pulse.frame_due(due_at, True) is True


def test_disarm_clears_only_the_frame_deadline() -> None:
    pulse = LoadingPulse()
    pulse.set_active(LoadingModel.ASR, True)
    pulse.start_breathing(50.0)

    pulse.disarm_frames()

    assert pulse.next_frame_at is None
    assert pulse.breathing is True
    assert pulse.breath_started_at == 50.0
    assert pulse.timeout(51.0, True) is None
    assert pulse.frame_due(51.0, True) is False

    pulse.arm(51.0)
    assert pulse.next_frame_at == pytest.approx(51.0 + LOADING_FRAME_INTERVAL)
    assert pulse.elapsed(51.0) == 1.0
