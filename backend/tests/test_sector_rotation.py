"""test_sector_rotation.py - sector performance tracking & catalyst filtering tests."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.quant.sector_rotation import (
    DEFAULT_SECTOR_MAP,
    SectorStats,
    beta_vs_index,
    atr,
    atr_pct,
    composite_momentum,
    group_by_sector,
    sector_catalyst_scores,
    sector_filtered_leaders,
    sector_momentum_stats,
    sector_of,
    top_n_sectors,
)

from src.core.models import DailyBar


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bar(ticker: str, d: date, close: float, volume: int = 50_000,
         high=None, low=None, open_=None) -> DailyBar:
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


def _tape(close_start: float, steps: int = 200, ticker: str = "AAA",
          volume: int = 50_000) -> list[DailyBar]:
    """A gentle uptrend tape with enough history for 6-month ROC and ATR."""
    base = date(2024, 1, 2)
    bars: list[DailyBar] = []
    for i in range(steps):
        close = close_start * (1 + 0.0008 * i)
        bars.append(_bar(ticker, base + timedelta(days=i * 2), close, volume))
    return bars


# ---------------------------------------------------------------------------
# Sector mapping
# ---------------------------------------------------------------------------


class TestSectorOf:
    def test_known_banking_ticker(self) -> None:
        assert sector_of("UBL") == "Banking"
        assert sector_of("hbl") == "Banking"

    def test_known_energy_ticker(self) -> None:
        assert sector_of("OGDC") == "Energy"

    def test_known_fertilizer_ticker(self) -> None:
        assert sector_of("FFC") == "Fertilizer"

    def test_unknown_defaults_to_other(self) -> None:
        assert sector_of("XYZ") == "OTHER"


class TestGroupBySector:
    def test_groups_known_tickers(self) -> None:
        tickers = ["UBL", "MCB", "OGDC", "FFC", "SYS", "XYZ"]
        grouped = group_by_sector(tickers)
        assert set(grouped["Banking"]) == {"UBL", "MCB"}
        assert set(grouped["Energy"]) == {"OGDC"}
        assert set(grouped["Fertilizer"]) == {"FFC"}
        assert set(grouped["Tech"]) == {"SYS"}
        assert set(grouped["OTHER"]) == {"XYZ"}

    def test_empty_input(self) -> None:
        assert group_by_sector([]) == {}


# ---------------------------------------------------------------------------
# Volatility helpers
# ---------------------------------------------------------------------------


class TestATR:
    def test_flat_tape_returns_small_atr(self) -> None:
        bars = _tape(close_start=100.0, steps=200)
        a = atr(bars, period=14)
        assert a is not None
        assert 0.0 < a < 5.0

    def test_two_bars_returns_range(self) -> None:
        bars = [
            _bar("A", date(2024, 1, 1), 100.0, 1000),
            _bar("A", date(2024, 1, 2), 100.0, 1000, high=105.0, low=95.0),
        ]
        assert atr(bars, period=14) is not None
        assert atr(bars, period=14) > 0


class TestATRPercent:
    def test_typical_tape_is_low_single_digits(self) -> None:
        bars = _tape(close_start=100.0, steps=200)
        pct = atr_pct(bars, period=14)
        assert 0.0 < pct < 15.0

    def test_short_tape_returns_zero(self) -> None:
        assert atr_pct([_bar("A", date(2024, 1, 1), 100.0, 1000)]) == 0.0


# ---------------------------------------------------------------------------
# Beta
# ---------------------------------------------------------------------------


class TestBetaVsIndex:
    def test_identical_tapes_give_beta_one(self) -> None:
        tape = _tape(100.0, steps=200)
        assert beta_vs_index(tape, tape, window=63) == 1.0

    def test_stock_twice_as_volatile_as_index(self) -> None:
        index_tape = _tape(100.0, steps=200, volume=50_000)
        stock_tape = _tape(100.0, steps=200, volume=50_000)
        # Make the stock move twice as much as the index on each step.
        for i, b in enumerate(stock_tape):
            b.close_price = index_tape[i].close_price * (1 + 0.0016 * i) / (
                1 + 0.0008 * i
            )
        beta = beta_vs_index(stock_tape, index_tape, window=63)
        assert beta > 1.0

    def test_short_tapes_fallback_to_one(self) -> None:
        assert beta_vs_index(
            [_bar("A", date(2024, 1, 1), 100.0, 1000)],
            [_bar("I", date(2024, 1, 1), 100.0, 1000)],
            window=63,
        ) == 1.0


# ---------------------------------------------------------------------------
# Composite momentum (mirrors momentum_rotation.composite_momentum)
# ---------------------------------------------------------------------------


class TestCompositeMomentum:
    def test_uptrend_scores_positive(self) -> None:
        bars = _tape(close_start=100.0, steps=200)
        score = composite_momentum(bars, session_index=len(bars) - 1)
        assert score > 0.0

    def test_falling_tape_scores_negative(self) -> None:
        bars = _tape(close_start=200.0, steps=200)
        for b in bars:
            b.close_price = 200.0 / (1 + 0.0008 * (len(bars) - 1 - (
                date(2024, 1, 2) + timedelta(days=0)
            ).toordinal() // 2))
        # simpler: just regress the closes
        for i, b in enumerate(bars):
            b.close_price = 200.0 * (1 - 0.0008 * i)
        score = composite_momentum(bars, session_index=len(bars) - 1)
        assert score < 0.0


# ---------------------------------------------------------------------------
# Sector momentum stats
# ---------------------------------------------------------------------------


class TestSectorMomentumStats:
    def test_two_sectors_score(self) -> None:
        energy_tape = _tape(100.0, steps=200, ticker="OGDC")
        banking_tape = _tape(100.0, steps=200, ticker="UBL")
        bars_by_ticker = {"OGDC": energy_tape, "UBL": banking_tape}
        stats = sector_momentum_stats(bars_by_ticker)
        assert "Energy" in stats
        assert "Banking" in stats
        assert stats["Energy"].members == 1
        assert stats["Banking"].members == 1

    def test_unmeasurable_ticker_scores_zero_momentum(self) -> None:
        short_tape = [_bar("XYZ", date(2024, 1, 1), 100.0, 1000)]
        stats = sector_momentum_stats({"XYZ": short_tape})
        assert stats["OTHER"].momentum == 0.0
        assert stats["OTHER"].members == 1


# ---------------------------------------------------------------------------
# Sector catalyst scores
# ---------------------------------------------------------------------------


class TestSectorCatalystScores:
    def test_calm_sector_scores_near_zero(self) -> None:
        tape = _tape(100.0, steps=200, volume=50_000)
        scores = sector_catalyst_scores({"OGDC": tape})
        assert abs(scores["Energy"]) < 5.0

    def test_spike_on_last_bar_raises_score(self) -> None:
        tape = _tape(100.0, steps=200, volume=50_000)
        tape[-1].volume = 500_000  # 10x the norm
        scores = sector_catalyst_scores({"OGDC": tape}, window_sessions=10)
        assert scores["Energy"] > 0.0


# ---------------------------------------------------------------------------
# Top-N sectors
# ---------------------------------------------------------------------------


class TestTopNSectors:
    def test_returns_top_two(self) -> None:
        energy_tape = _tape(100.0, steps=200, ticker="OGDC")
        banking_tape = _tape(100.0, steps=200, ticker="UBL")
        # Make energy tape rally harder than banking.
        for i, b in enumerate(energy_tape):
            b.close_price = 100.0 * (1 + 0.002 * i)
        for i, b in enumerate(banking_tape):
            b.close_price = 100.0 * (1 + 0.0005 * i)
        bars_by_ticker = {"OGDC": energy_tape, "UBL": banking_tape}
        top = top_n_sectors(bars_by_ticker, top_n=2)
        assert len(top) == 2
        assert top[0][0] == "Energy"

    def test_include_catalyst_overlay(self) -> None:
        tape_a = _tape(100.0, steps=200, ticker="OGDC")
        tape_b = _tape(100.0, steps=200, ticker="UBL")
        tape_b[-1].volume = 500_000
        bars_by_ticker = {"OGDC": tape_a, "UBL": tape_b}
        top = top_n_sectors(bars_by_ticker, top_n=2, use_catalyst=True)
        assert len(top) == 2
        # Both sectors present; ranking reflects momentum + catalyst overlay.
        sectors = [s for s, _ in top]
        assert "Energy" in sectors and "Banking" in sectors


# ---------------------------------------------------------------------------
# Sector-filtered leaders
# ---------------------------------------------------------------------------


class TestSectorFilteredLeaders:
    def test_in_sector_names_keep_score(self) -> None:
        ranking = [("OGDC", 20.0), ("UBL", 10.0)]
        filtered = sector_filtered_leaders(
            ranking,
            {"OGDC": _tape(100.0, 200, "OGDC"), "UBL": _tape(100.0, 200, "UBL")},
            top_sectors=["Energy"],
            sector_bias_weight=0.5,
        )
        scores = {t: s for t, s in filtered}
        assert scores["OGDC"] == 20.0
        assert scores["UBL"] == pytest.approx(5.0, abs=1e-9)

    def test_sorted_by_adjusted_score(self) -> None:
        ranking = [("UBL", 100.0), ("OGDC", 80.0)]
        filtered = sector_filtered_leaders(
            ranking,
            {"OGDC": _tape(100.0, 200, "OGDC"), "UBL": _tape(100.0, 200, "UBL")},
            top_sectors=["Energy"],
            sector_bias_weight=0.5,
        )
        assert filtered[0][0] == "OGDC"  # re-ranked after discount
        assert filtered[0][1] == pytest.approx(80.0, abs=1e-9)
