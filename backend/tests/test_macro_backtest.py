"""Coverage for the 5-year macro replay: CAGR, calendar years, drawdowns and gaps."""
from datetime import date, timedelta

import pytest

from src.core.models import DailyBar
from src.quant.backtest import (
    StrategyBacktester,
    StrategyConfig,
    drawdown_episodes,
    year_returns,
    years_between,
)

START = date(2021, 11, 18)
VOLUMES = [90_000, 110_000, 95_000, 105_000, 100_000]


def rising(ticker="AAA", sessions=120, start=80.0, step=0.2):
    bars, price = [], start
    for i in range(sessions):
        price = round(price + step, 2)
        bars.append(
            DailyBar(
                ticker=ticker,
                trade_date=START + timedelta(days=i),
                open_price=round(price - 0.1, 2),
                high_price=round(price + 1, 2),
                low_price=round(price - 1, 2),
                close_price=price,
                volume=VOLUMES[i % 5],
            )
        )
    return bars


def sweep(bars, ticker="AAA", volume=300_000, day_offset=1):
    last = bars[-1]
    close = last.close_price
    bars.append(
        DailyBar(
            ticker=ticker,
            trade_date=last.trade_date + timedelta(days=day_offset),
            open_price=round(close - 1.5, 2),
            high_price=round(close + 0.5, 2),
            low_price=round(close - 2, 2),
            close_price=close,
            volume=volume,
        )
    )
    return bars


def flat_tail(bars, sessions=40, ticker="AAA"):
    price = bars[-1].close_price
    for i in range(sessions):
        bars.append(
            DailyBar(
                ticker=ticker,
                trade_date=bars[-1].trade_date + timedelta(days=1),
                open_price=price,
                high_price=round(price + 0.4, 2),
                low_price=round(price - 0.4, 2),
                close_price=price,
                volume=100_000,
            )
        )
    return bars


def filler(ticker="BBB", sessions=170):
    """A second tape so the session calendar keeps running through a gap."""
    return rising(ticker, sessions, start=50.0, step=0.05)


def macro_config(**overrides):
    base = dict(
        trend_ma_days=50,
        trend_slope_bars=10,
        min_rvol=1.5,
        min_vol_z=1.0,
        atr_stop_mult=2.0,
        hold_horizon=30,
        max_sessions=1260,
    )
    base.update(overrides)
    return StrategyConfig(**base)


def test_five_year_payload_carries_macro_metrics():
    bars = flat_tail(sweep(rising(sessions=120)))
    payload = StrategyBacktester(macro_config()).run({"AAA": bars, "BBB": filler()})

    metrics = payload["metrics"]
    for key in ("cagrPct", "totalReturnPct", "winRatePct", "profitFactor", "maxDrawdownPct", "totalSignals"):
        assert key in metrics
    assert payload["horizonYears"] > 0.3
    assert payload["sessionRange"]["tickers"] == 2
    assert payload["yearlyReturns"], "a multi-year replay must break out calendar years"
    assert sum(row["signals"] for row in payload["yearlyReturns"]) == metrics["totalSignals"]


def test_cagr_is_compound_growth_over_the_replay_window():
    bars = flat_tail(sweep(rising(sessions=120)))
    payload = StrategyBacktester(macro_config()).run({"AAA": bars})
    metrics = payload["metrics"]

    growth = metrics["endingEquity"] / metrics["startingCapital"]
    expected = (growth ** (1 / payload["horizonYears"]) - 1) * 100 if growth > 0 else 0.0
    assert metrics["cagrPct"] == pytest.approx(expected, abs=0.02)
    assert years_between(START, START + timedelta(days=365)) == pytest.approx(1.0, abs=0.01)


def test_drawdown_episodes_track_peak_trough_and_recovery():
    curve = [
        {"date": "2022-01-03", "equity": 100_000.0, "drawdownPct": 0.0},
        {"date": "2022-02-01", "equity": 110_000.0, "drawdownPct": 0.0},
        {"date": "2022-03-01", "equity": 90_000.0, "drawdownPct": -18.18},
        {"date": "2022-04-01", "equity": 95_000.0, "drawdownPct": -13.64},
        {"date": "2022-05-02", "equity": 112_000.0, "drawdownPct": 0.0},
    ]
    episodes, deepest = drawdown_episodes(curve)

    assert len(episodes) == 1
    assert deepest["peakDate"] == "2022-02-01"
    assert deepest["troughDate"] == "2022-03-01"
    assert deepest["recoveryDate"] == "2022-05-02"
    assert deepest["depthPct"] == pytest.approx(-18.18, abs=0.01)
    assert deepest["sessions"] == 3


def test_unrecovered_drawdown_is_reported_without_a_fake_recovery():
    curve = [
        {"date": "2023-01-02", "equity": 100_000.0, "drawdownPct": 0.0},
        {"date": "2023-02-01", "equity": 100_000.0, "drawdownPct": 0.0},
        {"date": "2023-03-01", "equity": 80_000.0, "drawdownPct": -20.0},
    ]
    episodes, deepest = drawdown_episodes(curve)
    assert deepest["recoveryDate"] is None
    assert deepest["depthPct"] == pytest.approx(-20.0)


def test_missing_sessions_are_held_not_fatal():
    """A halted name has no bar; the loop must keep marking and count only real sessions."""
    bars = sweep(rising(sessions=120))
    sweep_day = bars[-1].trade_date
    price = bars[-1].close_price

    # AAA prints nothing for ten sessions after the sweep, then trades normally.
    for offset in range(1, 31):
        if offset <= 10:
            continue
        bars.append(
            DailyBar(
                ticker="AAA",
                trade_date=sweep_day + timedelta(days=offset),
                open_price=price,
                high_price=round(price + 0.4, 2),
                low_price=round(price - 0.4, 2),
                close_price=price,
                volume=100_000,
            )
        )

    payload = StrategyBacktester(macro_config()).run({"AAA": bars, "BBB": filler(sessions=170)})

    trades = payload["trades"]
    assert len(trades) == 1, "the sweep before the gap still produces a signal"
    assert payload["metrics"]["skippedEvaluations"] == 0
    assert trades[0]["barsHeld"] == 20, "only sessions with a real bar count toward the hold"


def test_year_returns_compound_from_carried_equity():
    curve = [
        {"date": "2021-12-31", "equity": 110_000.0, "drawdownPct": 0.0},
        {"date": "2022-06-30", "equity": 99_000.0, "drawdownPct": -10.0},
        {"date": "2022-12-30", "equity": 121_000.0, "drawdownPct": 0.0},
    ]
    rows = year_returns(curve, starting_capital=100_000.0)

    assert [row["year"] for row in rows] == [2021, 2022]
    assert rows[0]["returnPct"] == pytest.approx(10.0)
    assert rows[1]["returnPct"] == pytest.approx(10.0)  # 121/110 - 1
    assert rows[1]["startingEquity"] == pytest.approx(110_000.0)
