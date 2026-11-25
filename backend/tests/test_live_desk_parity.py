"""The live desk must publish exactly what the backtest engine would replay."""

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "scripts"))

import process_daily_tape as desk  # noqa: E402
from src.core.models import DailyBar  # noqa: E402

START = date(2026, 1, 5)
VARIED_VOLUMES = [90_000, 110_000, 95_000, 105_000, 100_000]


def tape(n=90, start_price=80.0, step=0.25, ticker="SYS"):
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
                volume=VARIED_VOLUMES[i % len(VARIED_VOLUMES)],
            )
        )
    return bars


def with_sweep(bars, volume=220_000):
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


def with_expansion(bars, volume=200_000):
    """Volatility/volume expansion that does not undercut the sweep window."""
    close = round(bars[-1].close_price + 0.25, 2)
    bars.append(
        DailyBar(
            ticker=bars[0].ticker,
            trade_date=bars[-1].trade_date + timedelta(days=1),
            open_price=close,
            high_price=close + 0.75,
            low_price=close - 0.75,
            close_price=close,
            volume=volume,
        )
    )
    return bars


def store(bars):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(desk.EOD_SCHEMA.format("psx_daily_eod"))
    conn.execute(desk.EOD_SCHEMA.format("psx_futures_eod"))
    conn.execute("CREATE TABLE psx_disclosures (trade_date TEXT, ticker TEXT, headline TEXT, disclosure_type TEXT)")
    for bar in bars:
        conn.execute(
            desk.INSERT.format("psx_daily_eod"),
            {
                "trade_date": bar.trade_date.strftime("%d%b%Y"),
                "ticker": bar.ticker,
                "open_price": bar.open_price,
                "high_price": bar.high_price,
                "low_price": bar.low_price,
                "close_price": bar.close_price,
                "volume": bar.volume,
            },
        )
    conn.commit()
    return conn


def desk_calls(bars):
    conn = store(bars)
    cur = conn.cursor()
    session = bars[-1].trade_date.strftime("%d%b%Y")
    rows = cur.execute("SELECT ticker, close_price, low_price FROM psx_daily_eod WHERE trade_date=?",
                       (session,)).fetchall()
    sweeps, leaders, traps, _metrics = desk.analyse(cur, session, bars[-1].trade_date, rows)
    return sweeps, leaders, traps


def test_desk_buy_is_the_engine_signal_with_atr_stop_and_flat_target():
    bars = with_sweep(tape())
    sweeps, _leaders, _traps = desk_calls(bars)

    signal = desk.ENGINE.evaluate_ticker(bars)
    assert signal is not None and signal.side == "BUY"
    assert len(sweeps) == 1
    buy = sweeps[0]

    assert buy["ticker"] == "SYS"
    assert buy["close"] == signal.entry_price
    assert buy["stopLoss"] == max(signal.stop_loss, round(signal.entry_price * 0.85, 2))
    assert buy["target"] == round(signal.entry_price * 1.12, 2)
    assert buy["reason"] == signal.reason


def test_desk_no_longer_publishes_the_flat_seven_percent_stop():
    sweeps, _leaders, _traps = desk_calls(with_sweep(tape()))
    buy = sweeps[0]
    assert buy["stopLoss"] != round(buy["close"] * 0.93, 2)
    assert buy["stopLoss"] < buy["close"]


def test_downtrend_tape_publishes_no_buy_and_no_watch_list():
    sweeps, leaders, _traps = desk_calls(with_sweep(tape(start_price=120.0, step=-0.25)))
    assert sweeps == []
    assert leaders == []


def test_weak_volume_tape_publishes_no_buy():
    sweeps, _leaders, _traps = desk_calls(with_sweep(tape(), volume=120_000))
    assert sweeps == []


def test_gated_name_without_a_sweep_lands_on_the_accumulation_watch_list():
    sweeps, leaders, _traps = desk_calls(with_expansion(tape()))
    assert sweeps == []
    assert len(leaders) == 1
    assert leaders[0]["rvol"] >= desk.MIN_RVOL
    assert leaders[0]["stopLoss"] < leaders[0]["close"] < leaders[0]["target"]
