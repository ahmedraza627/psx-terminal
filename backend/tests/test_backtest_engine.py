from datetime import date, timedelta

import pytest

from src.core.models import DailyBar
from src.quant.backtest import StrategyBacktester, StrategyConfig, run_backtest


def bars_from(prices, volumes, ticker="TEST", start=date(2026, 1, 5)):
    """prices: list of (high, low, close) tuples, one per session."""
    return [
        DailyBar(
            ticker=ticker,
            trade_date=start + timedelta(days=i),
            open_price=close,
            high_price=high,
            low_price=low,
            close_price=close,
            volume=volumes[i],
        )
        for i, (high, low, close) in enumerate(prices)
    ]


def sweep_then(extra, ticker="TEST"):
    """6 quiet sessions around 100, then a 2x-volume sweep that closes back at 100."""
    quiet = [(102.0, 98.0, 100.0)] * 6
    trigger = (101.0, 96.0, 100.0)
    prices = quiet + [trigger] + extra
    volumes = [100_000] * 6 + [200_000] + [150_000] * len(extra)
    return bars_from(prices, volumes, ticker=ticker)


CFG = StrategyConfig(lookback_days=5, min_avg_volume=50_000, target_pct=12.0, max_stop_pct=7.0,
                     hold_horizon=5, max_sessions=250)


def run(bars):
    return StrategyBacktester(CFG).run({bars[0].ticker: bars})


def test_target_hit_is_a_win_and_equity_grows():
    payload = run(sweep_then([(113.0, 100.0, 112.0)]))

    metrics = payload["metrics"]
    assert metrics["totalSignals"] == 1
    assert metrics["wins"] == 1
    assert metrics["losses"] == 0
    assert metrics["winRatePct"] == 100.0
    assert payload["trades"][0]["outcome"] == "TARGET HIT"
    assert payload["trades"][0]["pnlPct"] == pytest.approx(12.0)
    assert payload["trades"][0]["targetPrice"] == pytest.approx(112.0)
    assert metrics["totalReturnPct"] > 0
    assert payload["equityCurve"][0]["equity"] == CFG.starting_capital


def test_stop_takes_precedence_and_books_a_loss():
    # One bar tags both stop and target: the conservative rule must decide it as a loss.
    payload = run(sweep_then([(113.0, 85.0, 90.0)]))

    trade = payload["trades"][0]
    assert trade["outcome"] == "STOPPED OUT"
    assert trade["stopLoss"] >= 100.0 * (1 - CFG.max_stop_pct / 100) - 1e-9
    assert trade["pnlPct"] < 0
    assert payload["metrics"]["losses"] == 1
    assert payload["metrics"]["winRatePct"] == 0.0
    assert payload["metrics"]["maxDrawdownPct"] > 0


def test_horizon_exit_closes_a_flat_trade():
    payload = run(sweep_then([(101.0, 99.0, 100.0)] * 6))

    trade = payload["trades"][0]
    assert trade["outcome"] == "TIME EXIT"
    assert trade["barsHeld"] == CFG.hold_horizon
    assert payload["metrics"]["inPlay"] == 0


def test_open_position_at_end_of_tape_is_in_play():
    payload = run(sweep_then([]))

    assert payload["trades"][0]["outcome"] == "IN PLAY"
    assert payload["metrics"]["totalSignals"] == 1
    assert payload["metrics"]["wins"] == 0
    assert payload["metrics"]["winRatePct"] == 0.0
    assert payload["metrics"]["inPlay"] == 1


def test_profit_factor_and_curve_span_every_session():
    winner = sweep_then([(113.0, 100.0, 112.0)], ticker="WIN")
    loser = sweep_then([(101.0, 85.0, 88.0)], ticker="LOSE")

    payload = StrategyBacktester(CFG).run({"WIN": winner, "LOSE": loser})
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
        StrategyBacktester(CFG).run({})
