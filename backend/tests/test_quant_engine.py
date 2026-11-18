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
