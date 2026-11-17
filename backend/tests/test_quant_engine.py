from datetime import date, timedelta
import pytest
from pydantic import ValidationError
from src.core.models import DailyBar
from src.quant.engine import LiquidityQuantEngine


def make_bars(closes, base_vol=100_000):
    start = date(2026, 10, 1)
    bars = []
    for i, c in enumerate(closes):
        bars.append(
            DailyBar(
                ticker="SYS",
                trade_date=start + timedelta(days=i),
                open_price=c,
                high_price=c * 1.02,
                low_price=c * 0.98,
                close_price=c,
                volume=base_vol,
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
    engine = LiquidityQuantEngine(lookback_days=5, min_avg_volume=50_000)
    bars = make_bars([100, 101, 102, 100, 101], base_vol=10_000)
    bars.append(
        DailyBar(
            ticker="SYS",
            trade_date=date(2026, 10, 10),
            open_price=99,
            high_price=102,
            low_price=95,
            close_price=101,
            volume=50_000,
        )
    )
    assert engine.evaluate_ticker(bars) is None


def test_bullish_liquidity_sweep_detected():
    engine = LiquidityQuantEngine(lookback_days=5, min_avg_volume=50_000)
    bars = make_bars([100, 101, 100, 102, 101], base_vol=100_000)
    bars.append(
        DailyBar(
            ticker="SYS",
            trade_date=date(2026, 10, 10),
            open_price=100.0,
            high_price=100.5,
            low_price=96.5,
            close_price=99.5,
            volume=200_000,
        )
    )
    signal = engine.evaluate_ticker(bars)
    assert signal is not None
    assert signal.side == "BUY"
    assert signal.entry_price == 99.5
    assert signal.stop_loss < 96.5