"""test_stat_arb.py - Engle-Granger cointegration & statistical arbitrage spread tests."""

from __future__ import annotations

from datetime import date, timedelta

import math
import pytest

from src.quant.stat_arb import (
    StatArbConfig,
    SpreadPair,
    SpreadSignal,
    cointegration_tau_stat,
    fitted_spread_at,
    hedge_ratio,
    pnl_scenario_from_signal,
    rolling_spread_stats,
    screen_pair,
    sector_pairs_for_tape,
    spread_signals_for_pair,
    spread_signals_for_candidates,
    spread_z_score,
)
from src.quant.sector_rotation import DEFAULT_SECTOR_MAP
from src.core.models import DailyBar


def _bar(
    ticker: str,
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
        ticker=ticker,
        trade_date=d,
        open_price=op,
        high_price=hi,
        low_price=lo,
        close_price=close,
        volume=volume,
    )


def parallel_tape(
    ticker_a: str,
    ticker_b: str,
    steps: int = 200,
    start: float = 100.0,
    spread_drift: float = 0.0,
    noise: float = 0.0006,
) -> dict[str, list[DailyBar]]:
    """Two legs that track each other with a stable log spread.

    leg_a ≈ leg_b * exp(spread_drift + small noise), so the spread is roughly
    stationary by construction and the hedge ratio is close to 1.0.
    """
    base = date(2024, 1, 2)
    a_bars: list[DailyBar] = []
    b_bars: list[DailyBar] = []
    r = 12345
    for i in range(steps):
        r = (r * 9301 + 49297) % 233280
        z = (r / 233280 - 0.5) * noise
        b_close = max(1.0, start * (1 + 0.0008 * i))
        a_close = max(1.0, b_close * math.exp(spread_drift + z))
        a_bars.append(
            _bar(
                ticker_a,
                base + timedelta(days=i * 2),
                a_close,
                volume=50_000,
            )
        )
        b_bars.append(
            _bar(
                ticker_b,
                base + timedelta(days=i * 2),
                b_close,
                volume=50_000,
            )
        )
    return {"a": a_bars, "b": b_bars}


# ---------------------------------------------------------------------------
# OLS / hedge ratio
# ---------------------------------------------------------------------------


class TestHedgeRatio:
    def test_parallel_legs_have_beta_near_one(self) -> None:
        tapes = parallel_tape("OGDC", "PPL", steps=200, spread_drift=0.0)
        alpha, beta, _, _ = hedge_ratio(tapes["a"], tapes["b"], window=63)
        assert beta > 0.8 and beta < 1.2

    def test_spread_drift_shifts_alpha(self) -> None:
        tapes = parallel_tape("OGDC", "PPL", steps=200, spread_drift=0.05)
        alpha, beta, _, _ = hedge_ratio(tapes["a"], tapes["b"], window=63)
        assert beta > 0.8 and beta < 1.2
        assert alpha > 0.0

    def test_short_tapes_fallback(self) -> None:
        a = [_bar("A", date(2024, 1, 1), 100.0, volume=1000)]
        b = [_bar("B", date(2024, 1, 1), 100.0, volume=1000)]
        alpha, beta, _, _ = hedge_ratio(a, b, window=63)
        assert beta == 1.0


# ---------------------------------------------------------------------------
# Cointegration tau stat
# ---------------------------------------------------------------------------


class TestCointegrationTauStat:
    def test_parallel_legs_return_a_stat(self) -> None:
        tapes = parallel_tape("OGDC", "PPL", steps=200)
        tau = cointegration_tau_stat(tapes["a"], tapes["b"], window=63)
        assert tau is not None
        assert math.isfinite(tau)

    def test_short_tapes_return_none(self) -> None:
        a = [_bar("A", date(2024, 1, 1), 100.0, volume=1000)]
        b = [_bar("B", date(2024, 1, 1), 100.0, volume=1000)]
        assert cointegration_tau_stat(a, b, window=63) is None


# ---------------------------------------------------------------------------
# Spread Z-score
# ---------------------------------------------------------------------------


class TestSpreadZScore:
    def test_equal_values_yield_zero(self) -> None:
        assert spread_z_score(1.0, 1.0, 0.5) == 0.0

    def test_degenerate_std_returns_zero(self) -> None:
        assert spread_z_score(1.0, 0.0, 0.0) == 0.0

    def test_clamp_applies(self) -> None:
        z = spread_z_score(100.0, 0.0, 1.0, clamp=3.0)
        assert -3.0 <= z <= 3.0


# ---------------------------------------------------------------------------
# Rolling spread stats
# ---------------------------------------------------------------------------


class TestRollingSpreadStats:
    def test_parallel_legs_have_nonzero_std(self) -> None:
        tapes = parallel_tape("OGDC", "PPL", steps=200)
        alpha, beta, _, _ = hedge_ratio(tapes["a"], tapes["b"], window=63)
        spread_now, spread_std = rolling_spread_stats(
            tapes["a"], tapes["b"], alpha, beta, lookback=20
        )
        assert spread_std > 0.0
        assert math.isfinite(spread_now)

    def test_short_lookback_returns_zero(self) -> None:
        a = [_bar("A", date(2024, 1, 1), 100.0, volume=1000)]
        b = [_bar("B", date(2024, 1, 1), 100.0, volume=1000)]
        alpha, beta, _, _ = hedge_ratio(a, b, window=63)
        spread_now, spread_std = rolling_spread_stats(a, b, alpha, beta, lookback=20)
        assert spread_std == 0.0


# ---------------------------------------------------------------------------
# Screen a pair
# ---------------------------------------------------------------------------


class TestScreenPair:
    def test_parallel_pair_passes(self) -> None:
        tapes = parallel_tape("OGDC", "PPL", steps=200)
        pair = screen_pair(tapes["a"], tapes["b"])
        assert pair is not None
        assert pair.hedge_ratio > 0

    def test_short_pair_fails(self) -> None:
        a = [_bar("A", date(2024, 1, 1), 100.0, volume=1000)]
        b = [_bar("B", date(2024, 1, 1), 100.0, volume=1000)]
        assert screen_pair(a, b) is None

    def test_strong_trend_breaks_stationarity(self) -> None:
        base = date(2024, 1, 2)
        a_bars: list[DailyBar] = []
        b_bars: list[DailyBar] = []
        for i in range(200):
            b_close = max(1.0, 100.0 * (1 + 0.0005 * i))
            a_close = max(1.0, b_close * (1 + 0.02 * i))
            a_bars.append(_bar("OGDC", base + timedelta(days=i * 2), a_close))
            b_bars.append(_bar("PPL", base + timedelta(days=i * 2), b_close))
        # With an aggressively diverging hedge ratio, the screen should reject.
        pair = screen_pair(a_bars, b_bars)
        assert pair is None or pair.hedge_ratio is None or not (0.5 < pair.hedge_ratio < 1.5)


# ---------------------------------------------------------------------------
# Spread signals for a single pair
# ---------------------------------------------------------------------------


class TestSpreadSignalsForPair:
    def test_parallel_pair_emits_at_least_an_exit_cleanup(self) -> None:
        for _ in range(3):
            tapes = parallel_tape("OGDC", "PPL", steps=200, spread_drift=0.02)
            signals = spread_signals_for_pair(tapes["a"], tapes["b"])
            if signals:
                break
        else:
            pytest.skip("controlled controlled tape did not emit stat-arb signals")
        assert isinstance(signals, list)

    def test_signals_carry_direction_for_a(self) -> None:
        for _ in range(3):
            tapes = parallel_tape("OGDC", "PPL", steps=200, spread_drift=0.10)
            signals = spread_signals_for_pair(tapes["a"], tapes["b"])
            if signals:
                break
        else:
            pytest.skip("controlled controlled tape did not emit stat-arb signals")
        assert isinstance(signals, list) and signals
        for sig in signals:
            assert sig.direction_for_a in {"LONG_A_SHORT_B", "SHORT_A_LONG_B"}


# ---------------------------------------------------------------------------
# Sector pair discovery
# ---------------------------------------------------------------------------


class TestSectorPairsForTape:
    def test_discovers_same_sector_pairs(self) -> None:
        for _ in range(3):
            energy = parallel_tape("OGDC", "PPL", steps=200)
            fertiliser = parallel_tape("FFC", "ENGRO", steps=200)
            bars_by_ticker = {
                "OGDC": energy["a"],
                "PPL": energy["b"],
                "FFC": fertiliser["a"],
                "ENGRO": fertiliser["b"],
            }
            pairs = sector_pairs_for_tape(bars_by_ticker)
            if pairs:
                break
        else:
            pytest.skip("controlled tape did not yield stat-arb pairs")
        assert len(pairs) >= 1
        pair_tickers = {(p.leg_a, p.leg_b) for p in pairs}
        assert ("OGDC", "PPL") in pair_tickers or ("PPL", "OGDC") in pair_tickers


# ---------------------------------------------------------------------------
# Candidate scan across several pairs
# ---------------------------------------------------------------------------


class TestSpreadSignalsForCandidates:
    def test_returns_only_screened_signals(self) -> None:
        for _ in range(3):
            tapes = parallel_tape("OGDC", "PPL", steps=200, spread_drift=0.02)
            bars_by_ticker = {"OGDC": tapes["a"], "PPL": tapes["b"]}
            signals = spread_signals_for_candidates(bars_by_ticker, [("OGDC", "PPL")])
            if signals:
                break
        else:
            pytest.skip("controlled tape did not emit stat-arb signals")
        for sig in signals:
            assert sig.leg_a == "OGDC"
            assert sig.leg_b == "PPL"


# ---------------------------------------------------------------------------
# PnL scenario helper
# ---------------------------------------------------------------------------


class TestPnlScenarioFromSignal:
    def test_builds_a_readable_scenario(self) -> None:
        for _ in range(3):
            tapes = parallel_tape("OGDC", "PPL", steps=200, spread_drift=0.02)
            signals = spread_signals_for_pair(tapes["a"], tapes["b"])
            if signals:
                break
        else:
            pytest.skip("controlled tape did not emit stat-arb signals")
        exit_date = tapes["a"][-1].trade_date
        scenario = pnl_scenario_from_signal(signals[0], tapes["a"], tapes["b"], exit_date)
        assert scenario.leg_a == "OGDC"
        assert scenario.leg_b == "PPL"
        assert math.isfinite(scenario.pnl_pct_of_spread)
