from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from src.core.models import DailyBar
from src.quant.engine import LiquidityQuantEngine

START = date(2026, 1, 5)
VARIED_VOLUMES = [90_000, 110_000, 95_000, 105_000, 100_000]


def tape(n=80, start_price=80.0, step=0.25, volumes=None, ticker="SYS"):
    """A long, gently rising (or falling) tape with the volume variance a z-score needs."""
    vols = volumes or VARIED_VOLUMES
    bars = []
    for i in range(n):
        close = round(start_price + i * step, 2)
        bars.append(
            DailyBar(
                ticker=ticker,
                trade_date=START + timedelta(days=i),
                open_price=close,
                high_price=close + 1,
                low_price=close - 1,
                close_price=close,
                volume=vols[i % len(vols)],
            )
        )
    return bars


def with_sweep(bars, volume=220_000):
    """Undercut the prior 5-session low and reclaim it on 2.2x baseline volume."""
    close = bars[-1].close_price
    bars.append(
        DailyBar(
            ticker=bars[0].ticker,
            trade_date=bars[-1].trade_date + timedelta(days=1),
            open_price=close,
            high_price=close + 0.5,
            low_price=close - 2.5,
            close_price=close,
            volume=volume,
        )
    )
    return bars


def test_pydantic_rejects_corrupt_bar():
    with pytest.raises(ValidationError):
        DailyBar(
            ticker="OGDC",
            trade_date=date(2026, 11, 1),
            open_price=100.0,
            high_price=95.0,
            low_price=98.0,
            close_price=99.0,
            volume=1000,
        )


def test_illiquid_ticker_filtered_out():
    engine = LiquidityQuantEngine(min_avg_volume=50_000)
    assert engine.evaluate_ticker(with_sweep(tape(volumes=[10_000]))) is None


def test_bullish_liquidity_sweep_detected():
    signal = LiquidityQuantEngine().evaluate_ticker(with_sweep(tape()))

    assert signal is not None
    assert signal.side == "BUY"
    assert signal.entry_price == 99.75
    assert signal.stop_loss < signal.entry_price < signal.target_price
    assert "RVOL" in signal.reason and "Trend" in signal.reason


def test_sweep_below_the_trend_average_is_rejected():
    engine = LiquidityQuantEngine()
    falling = with_sweep(tape(start_price=120.0, step=-0.25))
    assert engine.evaluate_ticker(falling) is None


def test_weak_volume_expansion_is_rejected():
    engine = LiquidityQuantEngine()
    assert engine.evaluate_ticker(with_sweep(tape(), volume=120_000)) is None


def test_flat_volume_tape_fails_the_z_score_gate():
    engine = LiquidityQuantEngine()
    flat_volume = with_sweep(tape(volumes=[100_000]), volume=220_000)
    assert engine.evaluate_ticker(flat_volume) is None


def poc_tape(heavy_mid=110.0):
    """Fifteen flat bars at 100 with one heavy print away from the cluster."""
    bars = []
    for i in range(15):
        mid = heavy_mid if i == 7 else 100.0
        bars.append(
            DailyBar(
                ticker="POC",
                trade_date=START + timedelta(days=i),
                open_price=mid,
                high_price=mid + 0.5,
                low_price=mid - 0.5,
                close_price=mid,
                volume=5_000_000 if i == 7 else 100_000,
            )
        )
    return bars


def test_weekly_bias_reads_the_higher_timeframe_regime():
    engine = LiquidityQuantEngine()

    assert engine.weekly_bias(tape()) == "UP"
    assert engine.weekly_bias(tape(start_price=120.0, step=-0.25)) == "DOWN"
    assert engine.weekly_confluence(tape()) is True


def test_weekly_confluence_gate_blocks_a_non_up_week():
    gated = LiquidityQuantEngine(require_weekly_confluence=True)
    assert gated.evaluate_ticker(with_sweep(tape())) is not None

    falling = with_sweep(tape(start_price=120.0, step=-0.25))
    assert gated.evaluate_ticker(falling) is None


def test_volume_poc_sits_on_the_heaviest_node():
    poc = LiquidityQuantEngine().volume_poc(poc_tape())
    assert poc is not None
    assert abs(poc - 110.0) < 0.5  # one 5M print outweighs fourteen 100k prints


def test_poc_confluence_gate_requires_an_entry_on_the_node():
    bars = with_sweep(tape())
    poc = LiquidityQuantEngine().volume_poc(bars[:-1])
    gap_pct = abs((bars[-1].close_price / poc) - 1) * 100

    tight = LiquidityQuantEngine(require_poc_confluence=True, poc_band_pct=gap_pct - 0.25)
    assert tight.evaluate_ticker(bars) is None

    loose = LiquidityQuantEngine(require_poc_confluence=True, poc_band_pct=gap_pct + 0.25)
    assert loose.evaluate_ticker(bars) is not None
