"""Tests for the six-layer pre-breakout framework primitives."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "scripts"))

from quant_modules import (CONFLUENCE_LAYERS, calc_confluence_score, calc_float_turnover,  # noqa: E402
                           calc_pocket_pivot, calc_time_stop, calc_volume_dryup)


def bar(close: float, volume: float):
    return SimpleNamespace(close_price=close, volume=volume)


def tape(closes: list[float], volumes: list[float]):
    return [bar(c, v) for c, v in zip(closes, volumes)]


def flat_tape(sessions: int = 60, volume: float = 100_000, close: float = 100.0):
    return tape([close] * sessions, [volume] * sessions)


def test_dry_up_band_is_twenty_to_thirty_percent_of_the_fifty_day_average():
    bars = flat_tape(60, volume=100_000)
    for i in range(55, 60):
        bars[i] = bar(100.0, 25_000)  # 25% of the 50d average
    result = calc_volume_dryup(bars)
    assert result["dryUp"] is True
    assert 0.20 <= result["dryUpRatio"] <= 0.30

    outside = flat_tape(60, volume=100_000)
    for i in range(55, 60):
        outside[i] = bar(100.0, 5_000)  # 5%: dead tape, below the band
    assert calc_volume_dryup(outside)["dryUp"] is False
    assert calc_volume_dryup(outside)["contracting"] is True


def test_pocket_pivot_needs_an_up_day_above_two_times_average_volume():
    bars = flat_tape(60, volume=100_000)
    bars[-2] = bar(100.0, 300_000)  # a down day with heavy volume
    bars[-1] = bar(102.0, 250_000)  # up day, 2.5x the 50d average, above the down volume
    pivot = calc_pocket_pivot(bars)
    assert pivot["pocketPivot"] is True
    assert pivot["volumeRatio50"] >= 2.0

    weak = flat_tape(60, volume=100_000)
    weak[-1] = bar(102.0, 120_000)  # up, but nowhere near 2x
    assert calc_pocket_pivot(weak)["pocketPivot"] is False


def test_float_turnover_flags_fifteen_percent_distribution():
    ok = calc_float_turnover(1_000_000, 20_000_000)   # 5% of the float
    assert ok["distributionWarning"] is False
    heavy = calc_float_turnover(3_500_000, 20_000_000)  # 17.5% of the float
    assert heavy["distributionWarning"] is True
    assert heavy["floatTurnoverPct"] == 17.5
    assert calc_float_turnover(None, 20_000_000)["floatTurnoverPct"] is None


def test_confluence_score_counts_satisfied_layers_only():
    assert calc_confluence_score({}) == 0
    assert calc_confluence_score({"macroLiquidity": True, "volumeSetup": True}) == 2
    full = {key: True for key, _label in CONFLUENCE_LAYERS}
    assert calc_confluence_score(full) == 6


def test_time_stop_marks_dead_capital_at_thirty_sessions():
    assert calc_time_stop(12)["sessionsRemaining"] == 18
    assert calc_time_stop(12)["deadCapital"] is False
    spent = calc_time_stop(31)
    assert spent["deadCapital"] is True
    assert spent["sessionsRemaining"] == 0
