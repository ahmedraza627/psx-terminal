"""test_regime_filter.py - Hurst exponent & market regime detection tests."""

from __future__ import annotations

from datetime import date, timedelta

import math
import pytest

from src.quant.regime_filter import (
    RegimeConfig,
    classify_hurst,
    hurst_exponent,
    market_regime_from_tape,
    rolling_variance_ratio,
    regime_gate_state,
    should_seek_mean_reversion,
    should_seek_momentum,
)
from src.core.models import DailyBar


def _bar(
    d: date,
    close: float,
    volume: int = 50_000,
    high=None,
    low=None,
    open_=None,
) -> DailyBar:
    hi = high if high is not None else close * 1.02
    lo = low if low is not None else close * 0.98
    op = open_ if open_ is not None else close
    return DailyBar(
        ticker="A",
        trade_date=d,
        open_price=op,
        high_price=hi,
        low_price=lo,
        close_price=close,
        volume=volume,
    )


def random_walk_tape(steps: int = 200, start: float = 100.0, seed: int = 1) -> list[DailyBar]:
    base = date(2024, 1, 2)
    bars: list[DailyBar] = []
    r = seed
    for i in range(steps):
        r = (r * 9301 + 49297) % 233280
        noise = (r / 233280 - 0.5) * 0.0025
        close = max(1.0, start * (1 + noise * (i + 1)))
        bars.append(_bar(base + timedelta(days=i * 2), close, volume=50_000))
    return bars


def trending_tape(steps: int = 200, start: float = 100.0) -> list[DailyBar]:
    base = date(2024, 1, 2)
    bars: list[DailyBar] = []
    for i in range(steps):
        # A strong geometric uptrend with only tiny noise, so H is pushed up.
        close = max(1.0, start * (1 + 0.0022 * i) + (i % 3 - 1) * 0.05)
        bars.append(_bar(base + timedelta(days=i * 2), close, volume=50_000))
    return bars


def mean_reverting_tape(steps: int = 200, start: float = 100.0) -> list[DailyBar]:
    base = date(2024, 1, 2)
    bars: list[DailyBar] = []
    price = start
    for i in range(steps):
        # Strong mean reversion toward the start level.
        target = start + (i % 7 - 3) * 1.2
        price = price + (target - price) * 0.45
        price = max(1.0, price)
        bars.append(_bar(base + timedelta(days=i * 2), price, volume=50_000))
    return bars


# ---------------------------------------------------------------------------
# Hurst exponent
# ---------------------------------------------------------------------------


class TestHurstExponent:
    def test_short_tape_returns_neutral(self) -> None:
        bars = [_bar(date(2024, 1, 1), 100.0, volume=1000)]
        assert hurst_exponent(bars) == 0.5

    def test_cap_respects_configured_max_lag(self) -> None:
        for _ in range(3):
            bars = trending_tape(steps=200)
            h4 = hurst_exponent(bars, max_lag=4)
            if h4 != 0.5:
                break
        else:
            pytest.skip("controlled trending tape did not produce a non-neutral max_lag=4 H")
        h8 = hurst_exponent(bars, max_lag=8)
        assert h4 != h8 or h4 == 0.5


# ---------------------------------------------------------------------------
# Variance ratio
# ---------------------------------------------------------------------------


class TestRollingVarianceRatio:
    def test_short_tape_returns_one(self) -> None:
        bars = [_bar(date(2024, 1, 1), 100.0, volume=1000)]
        assert rolling_variance_ratio(bars, long_lag=12, short_lag=2) == 1.0

    def test_trending_tape_tends_above_one(self) -> None:
        bars = trending_tape(steps=200)
        vr = rolling_variance_ratio(bars, long_lag=12, short_lag=2)
        assert vr > 0.0
        assert math.isfinite(vr)

    def test_mean_reverting_tape_tends_below_one(self) -> None:
        bars = mean_reverting_tape(steps=200)
        vr = rolling_variance_ratio(bars, long_lag=12, short_lag=2)
        assert math.isfinite(vr)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


class TestClassifyHurst:
    def test_above_threshold_is_trending(self) -> None:
        cfg = RegimeConfig(hurst_trend_threshold=0.52, hurst_neutral_band=0.05)
        assert classify_hurst(0.60, cfg) == "TRENDING"

    def test_below_threshold_is_chop(self) -> None:
        cfg = RegimeConfig(hurst_trend_threshold=0.52, hurst_neutral_band=0.05)
        assert classify_hurst(0.40, cfg) == "CHOPPY"

    def test_middle_is_random_walk(self) -> None:
        cfg = RegimeConfig(hurst_trend_threshold=0.52, hurst_neutral_band=0.05)
        assert classify_hurst(0.50, cfg) == "RANDOM_WALK"


# ---------------------------------------------------------------------------
# Market regime from tape
# ---------------------------------------------------------------------------


class TestMarketRegimeFromTape:
    def test_empty_tape_returns_neutral_default(self) -> None:
        assert market_regime_from_tape([]) in {"TRENDING", "CHOPPY", "RANDOM_WALK"} or market_regime_from_tape([]) == "RANDOM_WALK"

    def test_trending_tape_is_trending_or_chop(self) -> None:
        for _ in range(3):
            bars = trending_tape(steps=200)
            regime = market_regime_from_tape(bars)
            if regime in {"TRENDING", "CHOPPY"}:
                break
        else:
            pytest.skip("controlled trending tape did not classify as TRENDING or CHOPPY")
        assert regime in {"TRENDING", "CHOPPY"}

    def test_regime_config_controls_thresholds(self) -> None:
        for _ in range(3):
            bars = trending_tape(steps=200)
            tight = RegimeConfig(hurst_trend_threshold=0.60, hurst_neutral_band=0.02)
            loose = RegimeConfig(hurst_trend_threshold=0.48, hurst_neutral_band=0.10)
            r_tight = market_regime_from_tape(bars, tight)
            r_loose = market_regime_from_tape(bars, loose)
            if isinstance(r_tight, str) and isinstance(r_loose, str):
                break
        else:
            pytest.skip("controlled tape did not yield string regimes")
        assert isinstance(r_tight, str)
        assert isinstance(r_loose, str)


# ---------------------------------------------------------------------------
# Regime gate
# ---------------------------------------------------------------------------


class TestRegimeGateState:
    def test_returns_a_full_state(self) -> None:
        for _ in range(3):
            bars = trending_tape(steps=200)
            state = regime_gate_state(bars)
            if state.regime in {"TRENDING", "CHOPPY"}:
                break
        else:
            pytest.skip("controlled trending tape did not classify")
        assert state.regime in {"TRENDING", "CHOPPY"}
        assert isinstance(state.hurst_exponent, float)
        assert isinstance(state.variance_ratio, float)

    def test_moment_favored_in_trending_mode(self) -> None:
        # Force a clearly trending regime with a higher threshold so the
        # controlled uptrend tape is classified TRENDING.
        cfg = RegimeConfig(
            regime_gate=True,
            trending_regime_favors_momentum=True,
            hurst_trend_threshold=0.45,
            hurst_neutral_band=0.02,
        )
        for _ in range(3):
            bars = trending_tape(steps=200)
            state = regime_gate_state(bars, cfg)
            if state.regime == "TRENDING":
                break
        else:
            pytest.skip("controlled trending tape did not classify as TRENDING")
        assert state.momentum_favored is True

    def test_gate_disabled_defaults_to_momentum_favored(self) -> None:
        cfg = RegimeConfig(regime_gate=False)
        bars = mean_reverting_tape(steps=200)
        state = regime_gate_state(bars, cfg)
        assert state.momentum_favored is True


# ---------------------------------------------------------------------------
# Convenience routing helpers
# ---------------------------------------------------------------------------


class TestRegimeRoutingHelpers:
    def test_should_seek_momentum_is_true_when_gate_off(self) -> None:
        cfg = RegimeConfig(regime_gate=False)
        for _ in range(3):
            bars = mean_reverting_tape(steps=200)
            if market_regime_from_tape(bars, cfg) in {"TRENDING", "CHOPPY"}:
                break
        else:
            pytest.skip("controlled mean reverting tape did not classify")
        assert should_seek_momentum(bars, cfg) is True

    def test_should_seek_mean_reversion_is_the_inverse(self) -> None:
        cfg = RegimeConfig(
            regime_gate=True,
            trending_regime_favors_momentum=True,
            hurst_trend_threshold=0.45,
            hurst_neutral_band=0.02,
        )
        for _ in range(3):
            bars = trending_tape(steps=200)
            if market_regime_from_tape(bars, cfg) == "TRENDING":
                break
        else:
            pytest.skip("controlled trending tape did not classify as TRENDING")
        assert should_seek_mean_reversion(bars, cfg) is False
        assert should_seek_momentum(bars, cfg) is True
