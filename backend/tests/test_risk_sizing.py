"""test_risk_sizing.py - volatility-adjusted position sizing tests."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.quant.risk_sizing import (
    SizingConfig,
    SizingDiagnostics,
    position_shares,
    position_weight,
    risk_parity_weights,
    sizing_table,
)
from src.quant.sector_rotation import atr, atr_pct, beta_vs_index

from src.core.models import DailyBar


def _bar(d: date, close: float, volume: int = 50_000,
         high=None, low=None, open_=None) -> DailyBar:
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


def _tape(close_start: float, steps: int = 200, volume: int = 50_000) -> list[DailyBar]:
    base = date(2024, 1, 2)
    bars: list[DailyBar] = []
    for i in range(steps):
        close = close_start * (1 + 0.0008 * i)
        bars.append(_bar(base + timedelta(days=i * 2), close, volume))
    return bars


# ---------------------------------------------------------------------------
# Position weight
# ---------------------------------------------------------------------------


class TestPositionWeight:
    def test_basics_produce_a_readable_weight(self) -> None:
        bars = _tape(100.0, steps=200)
        cfg = SizingConfig()
        w = position_weight(100.0, 93.0, bars, cfg)
        assert 0.0 < w < 0.2  # 7% stop, 1% risk budget => ~14% raw before dampeners

    def test_invalid_entry_returns_zero(self) -> None:
        bars = _tape(100.0, steps=200)
        assert position_weight(0.0, 93.0, bars, SizingConfig()) == 0.0
        assert position_weight(100.0, 105.0, bars, SizingConfig()) == 0.0

    def test_empty_bars_returns_zero(self) -> None:
        assert position_weight(100.0, 93.0, [], SizingConfig()) == 0.0

    def test_atr_dampener_shifts_weight_down(self) -> None:
        # Flat low-vol tape: ATR% ~1%.
        base = date(2024, 1, 2)
        calm_bars = [_bar(base + timedelta(days=i * 2), 100.0, high=100.5, low=99.5) for i in range(200)]
        # Flat high-vol tape: ATR% ~8%.
        wild_bars = [_bar(base + timedelta(days=i * 2), 100.0 + 0.5 * i, high=100.0 + 0.5 * i + 8.0, low=100.0 + 0.5 * i - 8.0) for i in range(200)]
        cfg = SizingConfig(target_risk_pct=5.0, atr_target_pct=1.0, atr_dampener=0.5, min_weight_pct=0.1)
        w_calm = position_weight(100.0, 93.0, calm_bars, cfg)
        w_wild = position_weight(100.0, 93.0, wild_bars, cfg)
        assert w_wild < w_calm

    def test_beta_dampener_shifts_weight_down(self) -> None:
        # Index tape with small random walk so returns have variance.
        base = date(2024, 1, 2)
        index_closes: list[float] = [100.0]
        for i in range(1, 200):
            index_closes.append(index_closes[-1] * (1 + 0.002 * (-1 if i % 2 else 1)))
        index_tape = [_bar(base + timedelta(days=i * 2), index_closes[i], high=index_closes[i] * 1.02, low=index_closes[i] * 0.98) for i in range(200)]
        # Stock tape with twice the index's return sensitivity.
        stock_tape: list[DailyBar] = []
        for i, ic in enumerate(index_closes):
            if i == 0:
                stock_close = 100.0
            else:
                index_ret = index_closes[i] / index_closes[i - 1] - 1
                stock_close = stock_tape[-1].close_price * (1 + 2.0 * index_ret)
            news = DailyBar(
                ticker="STOCK",
                trade_date=base + timedelta(days=i * 2),
                open_price=stock_close,
                high_price=stock_close * 1.02,
                low_price=stock_close * 0.98,
                close_price=stock_close,
                volume=50000,
            )
            stock_tape.append(news)
        beta = beta_vs_index(stock_tape, index_tape, window=63)
        assert beta > 1.0  # confirm the tapes actually produce a beta > 1
        cfg = SizingConfig(target_risk_pct=5.0, beta_neutral=1.0, beta_dampener=1.0, min_weight_pct=0.1)
        w_neutral = position_weight(100.0, 93.0, stock_tape, cfg, index_bars=None)
        w_beta = position_weight(100.0, 93.0, stock_tape, cfg, index_bars=index_tape)
        assert w_beta < w_neutral

    def test_concentration_cap_clamps_weight(self) -> None:
        bars = _tape(100.0, steps=200)
        cfg = SizingConfig(target_risk_pct=50.0, max_weight_pct=5.0)
        w = position_weight(100.0, 93.0, bars, cfg)
        assert w <= 0.05

    def test_dust_floor_clamps_weight(self) -> None:
        bars = _tape(100.0, steps=200)
        cfg = SizingConfig(target_risk_pct=0.01, min_weight_pct=2.0)
        w = position_weight(100.0, 99.95, bars, cfg)
        assert w >= 0.02


# ---------------------------------------------------------------------------
# Position shares
# ---------------------------------------------------------------------------


class TestPositionShares:
    def test_returns_whole_shares(self) -> None:
        bars = _tape(100.0, steps=200)
        shares = position_shares(100.0, 93.0, bars, equity=100_000.0, config=SizingConfig())
        assert isinstance(shares, int)
        assert shares >= 0

    def test_zero_on_zero_weight(self) -> None:
        assert position_shares(100.0, 100.0, _tape(100.0, 200), 100_000.0, SizingConfig()) == 0

    def test_scales_with_equity(self) -> None:
        bars = _tape(100.0, steps=200)
        s1 = position_shares(100.0, 93.0, bars, equity=100_000.0, config=SizingConfig())
        s2 = position_shares(100.0, 93.0, bars, equity=200_000.0, config=SizingConfig())
        assert s2 > s1


# ---------------------------------------------------------------------------
# Risk parity normalization
# ---------------------------------------------------------------------------


class TestRiskParityWeights:
    def test_empty_positions_returns_empty(self) -> None:
        assert risk_parity_weights([], 100_000.0, SizingConfig()) == {}

    def test_normalizes_to_the_book(self) -> None:
        bars = _tape(100.0, steps=200)
        candidates = [
            ("A", 100.0, 93.0, bars, None),
            ("B", 50.0, 47.0, bars, None),
        ]
        weights = risk_parity_weights(candidates, 100_000.0, SizingConfig())
        total = sum(weights.values())
        assert total <= 1.0 + 1e-9

    def test_respects_volatility_differences(self) -> None:
        base = date(2024, 1, 2)
        calm = [_bar(base + timedelta(days=i * 2), 100.0, high=100.5, low=99.5) for i in range(200)]
        wild = [_bar(base + timedelta(days=i * 2), 100.0 + 0.5 * i, high=100.0 + 0.5 * i + 8.0, low=100.0 + 0.5 * i - 8.0) for i in range(200)]
        candidates = [
            ("calm", 100.0, 93.0, calm, None),
            ("wild", 100.0, 93.0, wild, None),
        ]
        weights = risk_parity_weights(candidates, 100_000.0, SizingConfig(target_risk_pct=5.0, atr_target_pct=1.0, atr_dampener=0.5, min_weight_pct=0.1))
        # The wild name is more volatile so its normalized weight should be smaller.
        assert weights["calm"] > weights["wild"]


# ---------------------------------------------------------------------------
# Diagnostics table
# ---------------------------------------------------------------------------


class TestSizingTable:
    def test_reports_full_row(self) -> None:
        bars = _tape(100.0, steps=200)
        diag = sizing_table("OGDC", 100.0, 93.0, bars, 100_000.0, SizingConfig())
        assert diag.ticker == "OGDC"
        assert diag.entry == 100.0
        assert diag.stop == 93.0
        assert diag.shares >= 0
        assert diag.raw_weight > 0
        assert diag.final_weight > 0
        assert diag.risk_pkr >= 0

    def test_beta_appears_when_index_supplied(self) -> None:
        stock = _tape(100.0, steps=200)
        index = _tape(100.0, steps=200)
        for i, b in enumerate(stock):
            b.close_price = index[i].close_price * (1 + 0.0016 * i) / (1 + 0.0008 * i)
        diag = sizing_table("A", 100.0, 93.0, stock, 100_000.0, SizingConfig(), index_bars=index)
        assert diag.beta > 1.0
