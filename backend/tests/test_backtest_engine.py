from datetime import date, timedelta

import pytest

from src.core.models import DailyBar
from src.quant.backtest import StrategyBacktester, StrategyConfig

START = date(2026, 1, 5)
VARIED_VOLUMES = [90_000, 110_000, 95_000, 105_000, 100_000]

CONFIG = dict(
    lookback_days=5,
    trend_ma_days=50,
    trend_slope_bars=10,
    trend_reference_bars=1,
    min_rvol=1.5,
    min_vol_z=1.0,
    atr_stop_mult=2.0,
    hold_horizon=4,
    target_pct=12.0,
    max_sessions=250,
)


def tape(ticker="TEST", start_price=80.0, step=0.25, n=80):
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
                volume=VARIED_VOLUMES[i % 5],
            )
        )
    return bars


def sweep_series(candles=(), ticker="TEST", start_price=80.0, step=0.25):
    """Rising tape, then a 5-session low sweep/reclaim, then the supplied follow-through bars."""
    bars = tape(ticker, start_price, step)
    close = bars[-1].close_price
    sweep_day = bars[-1].trade_date + timedelta(days=1)
    bars.append(
        DailyBar(
            ticker=ticker,
            trade_date=sweep_day,
            open_price=close,
            high_price=close + 0.5,
            low_price=close - 2.5,
            close_price=close,
            volume=220_000,
        )
    )
    for i, (high, low, close_price) in enumerate(candles):
        bars.append(
            DailyBar(
                ticker=ticker,
                trade_date=sweep_day + timedelta(days=i + 1),
                open_price=close_price,
                high_price=high,
                low_price=low,
                close_price=close_price,
                volume=150_000,
            )
        )
    return bars


def run(bars, **overrides):
    config = dict(CONFIG)
    config.update(overrides)
    return StrategyBacktester(StrategyConfig(**config)).run({bars[0].ticker: bars})


def test_target_hit_is_a_win_and_equity_grows():
    payload = run(sweep_series([(113.0, 100.0, 112.0)]))

    metrics = payload["metrics"]
    assert metrics["totalSignals"] == 1
    assert metrics["wins"] == 1
    assert metrics["losses"] == 0
    assert metrics["winRatePct"] == 100.0

    trade = payload["trades"][0]
    assert trade["outcome"] == "TARGET HIT"
    assert trade["pnlPct"] == pytest.approx(12.0)
    assert trade["targetPrice"] == pytest.approx(111.72, abs=0.01)
    assert trade["stopLoss"] < trade["entryPrice"]
    assert payload["equityCurve"][0]["equity"] == metrics["startingCapital"]
    assert metrics["totalReturnPct"] > 0


def test_stop_takes_precedence_and_books_a_loss():
    # One bar tags both stop and target: the conservative rule must decide it as a loss.
    payload = run(sweep_series([(113.0, 90.0, 92.0)]))

    trade = payload["trades"][0]
    assert trade["outcome"] == "STOPPED OUT"
    assert trade["pnlPct"] < 0
    assert payload["metrics"]["losses"] == 1
    assert payload["metrics"]["winRatePct"] == 0.0
    assert payload["metrics"]["maxDrawdownPct"] > 0


def test_horizon_exit_closes_a_flat_trade():
    payload = run(sweep_series([(100.25, 99.25, 99.75)] * 6))

    trade = payload["trades"][0]
    assert trade["outcome"] == "TIME EXIT"
    assert trade["barsHeld"] == CONFIG["hold_horizon"]
    assert payload["metrics"]["inPlay"] == 0


def test_open_position_at_end_of_tape_is_in_play():
    payload = run(sweep_series())

    assert payload["trades"][0]["outcome"] == "IN PLAY"
    assert payload["metrics"]["totalSignals"] == 1
    assert payload["metrics"]["wins"] == 0
    assert payload["metrics"]["winRatePct"] == 0.0
    assert payload["metrics"]["inPlay"] == 1


def test_trend_filter_blocks_downtrend_sweeps():
    payload = run(sweep_series([(113.0, 100.0, 112.0)], start_price=120.0, step=-0.25))
    assert payload["metrics"]["totalSignals"] == 0


def test_profit_factor_and_curve_span_every_session():
    winner = sweep_series([(113.0, 100.0, 112.0)], ticker="WINR")
    loser = sweep_series([(101.0, 90.0, 92.0)], ticker="LOSR")

    payload = StrategyBacktester(StrategyConfig(**CONFIG)).run({"WINR": winner, "LOSR": loser})
    metrics = payload["metrics"]

    assert metrics["totalSignals"] == 2
    assert metrics["wins"] == 1 and metrics["losses"] == 1
    assert metrics["profitFactor"] == pytest.approx(
        metrics["grossProfitPct"] / metrics["grossLossPct"], rel=1e-2
    )
    assert len(payload["equityCurve"]) == payload["sessionRange"]["sessions"]
    dates = [point["date"] for point in payload["equityCurve"]]
    assert dates == sorted(dates)


def test_store_without_history_is_rejected():
    with pytest.raises(ValueError):
        StrategyBacktester(StrategyConfig(**CONFIG)).run({})
